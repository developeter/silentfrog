"""PR-G2: Crawl-settings options reach the helpers that fetch outside `analyse`.

D3  the robots.txt tester ("Fetch from URL") uses the dialog's TLS / SSRF scopes,
    user agent and origin headers, and says why a fetch came back empty.
PLUMB-6  "Analyze images" measures with the same posture and headers as the audit.

These tests are deliberately synchronous (a plain threaded HTTP server and
``asyncio.run``): a test-wide ``allow_private_network`` scope would make the
loopback fixture reachable by default and hide the very defect being pinned.
"""

from __future__ import annotations

import asyncio
import dataclasses
import http.server
import threading
from collections.abc import Callable, Iterator
from io import BytesIO

import pytest
from PIL import Image

from silentfrog import robots_sim_dialog
from silentfrog.crawl_options import CrawlOptions
from silentfrog.robots_sim_dialog import RobotsSimDialog, _RobotsFetchWorker
from silentfrog.seo_crawler import analyse_images
from silentfrog.workers import run_image_analysis

_ROBOTS = "User-agent: *\nDisallow: /secret\n"


def _png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class _Handler(http.server.BaseHTTPRequestHandler):
    """Cookie-gated robots.txt and PNG; anything else is a 404."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.server.hits.append((self.path, self.headers.get("Cookie", ""), self.headers.get("User-Agent", "")))
        if self.headers.get("Cookie", "") != "sid=abc":
            self._reply(403, b"forbidden", "text/plain")
        elif self.path == "/robots.txt":
            self._reply(200, _ROBOTS.encode(), "text/plain")
        elif self.path == "/logo.png":
            self._reply(200, _png(7, 5), "image/png")
        else:
            self._reply(404, b"", "text/plain")

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def site() -> Iterator[tuple[str, list[tuple[str, str, str]]]]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.hits = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.hits  # type: ignore[attr-defined]
    finally:
        server.shutdown()
        server.server_close()


def _options(**overrides: object) -> CrawlOptions:
    base = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, cookie_text="sid=abc", user_agent="PlumbBot/1.0")
    return dataclasses.replace(base, **overrides)


def _run_worker(url: str, options: CrawlOptions | None) -> tuple[str, str]:
    worker = _RobotsFetchWorker(url, options=options)
    bodies: list[str] = []
    worker.finished_fetch.connect(bodies.append)
    worker.run()  # synchronously, in this thread: no QThread needed to exercise the fetch
    return bodies[0], worker.outcome


# --- D3: robots.txt tester ------------------------------------------------------


def test_robots_fetch_is_blocked_with_a_reason_under_default_options(site) -> None:
    base, hits = site
    body, outcome = _run_worker(f"{base}/robots.txt", _options())
    assert (body, outcome) == ("", "ssrf")
    assert hits == []
    assert "private-network" in robots_sim_dialog._FETCH_STATUS_TEXT[outcome]


def test_robots_fetch_uses_private_network_scope_ua_and_origin_cookie(site) -> None:
    base, hits = site
    body, outcome = _run_worker(f"{base}/robots.txt", _options(allow_private_network=True))
    assert (body, outcome) == (_ROBOTS, "ok")
    assert hits == [("/robots.txt", "sid=abc", "PlumbBot/1.0")]


def test_robots_fetch_without_the_cookie_reads_as_no_robots_txt(site) -> None:
    base, _hits = site
    opts = dataclasses.replace(_options(allow_private_network=True), extra_headers={})
    assert _run_worker(f"{base}/robots.txt", opts) == ("", "empty")


@pytest.mark.parametrize("with_provider", [True, False])
def test_dialog_fetch_status_comes_from_the_options_provider(qtbot, monkeypatch, site, with_provider) -> None:
    base, _hits = site
    monkeypatch.setattr(_RobotsFetchWorker, "start", lambda self: self.run())
    provider: Callable[[], CrawlOptions] | None = (
        (lambda: _options(allow_private_network=True)) if with_provider else None
    )
    dialog = RobotsSimDialog(options_provider=provider)
    qtbot.addWidget(dialog)
    dialog.edit_target_url.setText(f"{base}/secret/page")

    dialog.btn_fetch.click()

    if with_provider:
        assert dialog.lbl_fetch_status.text() == "Fetched."
        assert "Disallow: /secret" in dialog.txt_robots_body.toPlainText()
    else:
        assert "Allow private-network targets" in dialog.lbl_fetch_status.text()
        assert dialog.txt_robots_body.toPlainText() == ""


def test_settings_dialog_hands_its_live_options_to_the_robots_tester(qtbot, monkeypatch) -> None:
    from silentfrog.settings_dialog import CrawlSettingsDialog

    captured: dict[str, object] = {}

    class _Fake:
        def __init__(self, parent=None, options_provider=None) -> None:
            captured["provider"] = options_provider

        def exec(self) -> int:
            return 0

    monkeypatch.setattr("silentfrog.robots_sim_dialog.RobotsSimDialog", _Fake)
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.chk_allow_private_network.setChecked(True)

    dialog._on_open_robots_sim()

    provider = captured["provider"]
    assert callable(provider) and provider().allow_private_network is True


# --- PLUMB-6: image analysis ------------------------------------------------------


def test_analyse_images_is_blocked_under_default_options(site) -> None:
    base, hits = site
    rows = asyncio.run(analyse_images(base, [["/logo.png"]], timeout=5))
    assert rows[0][0] == "Errore"
    assert hits == []


def test_analyse_images_measures_a_loopback_png_with_the_audit_options(site) -> None:
    base, hits = site
    rows = asyncio.run(analyse_images(base, [["/logo.png"]], timeout=5, options=_options(allow_private_network=True)))
    url, width, height, _size, content_type, _cache = rows[0]
    assert url.endswith("/logo.png")
    assert (width, height, content_type) == ("7", "5", "image/png")
    assert hits[0][1] == "sid=abc"  # the origin still gets the user's cookie


def test_run_image_analysis_threads_the_options_through(site) -> None:
    base, _hits = site
    done: list[list[list[str]]] = []
    errors: list[str] = []
    thread = run_image_analysis(
        base,
        [["/logo.png"]],
        5,
        done.append,
        errors.append,
        options=_options(allow_private_network=True),
    )
    thread.join(timeout=20)
    assert errors == []
    assert done[0][0][1:3] == ["7", "5"]
