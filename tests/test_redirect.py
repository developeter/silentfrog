from __future__ import annotations

import http.server
import ipaddress
import pathlib
import socket
import threading
import time

import pandas as pd
import pytest
import requests_mock  # type: ignore[reportMissingImports]
from openpyxl import load_workbook

from silentfrog.redirect import (  # type: ignore[reportMissingImports]
    ISSUE_CHAIN,
    ISSUE_LOOP,
    ISSUE_NOT_CHECKED,
    ISSUE_PRIVATE,
    ISSUE_ROBOTS,
    ISSUE_WRONG_TARGET,
    RedirectCheckOptions,
    RedirectThrottle,
    _comparable_url,
    _load_redirect_frame,
    check_redirects,
)

_OPTIONS = RedirectCheckOptions(timeout=5, max_workers=2, respect_robots=False)
_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the SSRF pre-flight off the network: a literal IP resolves to
    itself (so the loopback test stays honest), any hostname resolves to a
    public address. Without this every mocked example.com host would trigger a
    real DNS lookup on each hop."""

    def fake_getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            host = _PUBLIC_IP
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def _sheet(tmp_path: pathlib.Path, frame: pd.DataFrame, *, header: bool = True, name: str = "input.xlsx"):
    path = tmp_path / name
    frame.to_excel(path, index=False, header=header)
    return path


def _issue(frame: pd.DataFrame, row: int) -> str:
    """The Issue cell as text. Excel reads an empty string back as NaN."""
    value = frame.loc[row, "Issue"]
    return "" if pd.isna(value) else str(value)


def _run(path: pathlib.Path, **kwargs):
    """Run the checker and hand back the report as a DataFrame plus the result."""
    result = check_redirects(path, **kwargs)
    return pd.read_excel(result.output_path), result


def test_check_redirects_marks_a_correct_single_hop(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path, pd.DataFrame([["https://old.example.com/page", "https://new.example.com/page"]]), header=False
    )

    with requests_mock.Mocker() as mock:
        mock.get(
            "https://old.example.com/page",
            status_code=301,
            headers={"Location": "https://new.example.com/page"},
        )
        mock.get("https://new.example.com/page", status_code=200)
        out, result = _run(path, options=_OPTIONS)

    assert out.loc[0, "Redirect Correct"] == "Yes"
    assert out.loc[0, "Status Code"] == 200
    assert out.loc[0, "Redirect Chain Length"] == 1
    assert out.loc[0, "Redirect Chain Statuses"] == "301 -> 200"
    assert result.summary.correct == 1 and result.summary.wrong == 0


def test_extra_column_in_a_headerless_sheet_does_not_shift_the_urls(tmp_path: pathlib.Path) -> None:
    """Regression: pandas was handed two ``names`` for a three-column sheet, so
    it promoted the real Old URL column to the index and every value slid one
    column left — the tool then checked the *new* URLs and compared them to a
    notes column, reporting confidently on URLs nobody asked about."""
    path = _sheet(
        tmp_path,
        pd.DataFrame([["https://old.example.com/a", "https://new.example.com/a", "batch 1"]]),
        header=False,
    )

    frame = _load_redirect_frame(path)

    assert list(frame.columns) == ["Old URL", "New URL"]
    assert frame.loc[0, "Old URL"] == "https://old.example.com/a"
    assert frame.loc[0, "New URL"] == "https://new.example.com/a"


@pytest.mark.parametrize("headers", [("Old Url", "New Url"), ("old_url", "new_url"), ("From", "To")])
def test_header_aliases_are_detected_instead_of_being_read_as_data(
    tmp_path: pathlib.Path, headers: tuple[str, str]
) -> None:
    """Regression: header detection was an exact match on "Old URL"/"New URL",
    so any other spelling fell through to the headerless path and the header
    row itself was fetched as a URL. ``old_url``/``new_url`` matters most — it
    is what Site Crawl's own redirect-map export writes."""
    old, new = headers
    path = _sheet(tmp_path, pd.DataFrame({old: ["https://old.example.com/a"], new: ["https://new.example.com/a"]}))

    frame = _load_redirect_frame(path)

    assert len(frame) == 1
    assert frame.loc[0, "Old URL"] == "https://old.example.com/a"


def test_csv_redirect_map_from_site_crawl_is_accepted(tmp_path: pathlib.Path) -> None:
    """The G13 redirect map is exported as CSV with old_url/new_url headers;
    the checker used to accept Excel only, so the documented hand-off between
    the two features could not actually be walked."""
    path = tmp_path / "silentfrog_redirect_map.csv"
    path.write_text("old_url,new_url\nhttps://old.example.com/a,https://new.example.com/a\n", encoding="utf-8")

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=301, headers={"Location": "https://new.example.com/a"})
        mock.get("https://new.example.com/a", status_code=200)
        out, _ = _run(path, options=_OPTIONS)

    assert out.loc[0, "Redirect Correct"] == "Yes"


def test_blank_cells_are_flagged_not_fetched_as_the_string_nan(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path,
        pd.DataFrame({"Old URL": ["https://old.example.com/a", None], "New URL": ["https://new.example.com/a", "x"]}),
    )

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=200)
        out, _ = _run(path, options=_OPTIONS)

    assert len(out) == 2, "a blank row must stay in the report, not vanish from it"
    assert _issue(out, 1) == "Invalid URL"


@pytest.mark.parametrize(
    ("final_url", "expected_url"),
    [
        ("https://new.example.com/caff%C3%A8", "https://new.example.com/caffè"),
        ("https://NEW.example.com/page", "https://new.example.com/page"),
        ("https://new.example.com/page/", "https://new.example.com/page"),
        ("https://new.example.com:443/page", "https://new.example.com/page"),
    ],
)
def test_comparable_url_ignores_only_cosmetic_differences(final_url: str, expected_url: str) -> None:
    """Regression: the verdict was ``final.rstrip("/") == new.rstrip("/")``, so
    an exactly-correct redirect onto an accented URL (routine on Italian sites)
    reported "No" purely because requests returns it percent-encoded."""
    assert _comparable_url(final_url) == _comparable_url(expected_url)


def test_comparable_url_still_separates_genuinely_different_targets() -> None:
    assert _comparable_url("https://a.example.com/x") != _comparable_url("https://b.example.com/x")
    assert _comparable_url("https://a.example.com/x") != _comparable_url("https://a.example.com/X")


def test_redirect_loop_is_reported_as_a_loop_with_its_chain(tmp_path: pathlib.Path) -> None:
    """Regression: following redirects inside requests turned a loop into a
    bare "Error" with chain length 0 — the one diagnosis a redirect audit
    exists to produce was the one it could not give."""
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://new.example.com/a"]})
    )

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=301, headers={"Location": "https://old.example.com/b"})
        mock.get("https://old.example.com/b", status_code=301, headers={"Location": "https://old.example.com/a"})
        out, result = _run(path, options=_OPTIONS)

    assert _issue(out, 0) == ISSUE_LOOP
    assert out.loc[0, "Redirect Chain URLs"] == "https://old.example.com/a -> https://old.example.com/b"
    assert result.summary.loops == 1


def test_multi_hop_chain_is_flagged_even_when_it_lands_correctly(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://new.example.com/a"]})
    )

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=301, headers={"Location": "https://mid.example.com/a"})
        mock.get("https://mid.example.com/a", status_code=301, headers={"Location": "https://new.example.com/a"})
        mock.get("https://new.example.com/a", status_code=200)
        out, result = _run(path, options=_OPTIONS)

    assert out.loc[0, "Redirect Correct"] == "Yes"
    assert _issue(out, 0) == ISSUE_CHAIN
    assert out.loc[0, "Redirect Chain Length"] == 2
    assert result.summary.chains == 1


def test_wrong_target_is_named_as_such(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://new.example.com/a"]})
    )

    with requests_mock.Mocker() as mock:
        mock.get(
            "https://old.example.com/a", status_code=301, headers={"Location": "https://new.example.com/elsewhere"}
        )
        mock.get("https://new.example.com/elsewhere", status_code=200)
        out, _ = _run(path, options=_OPTIONS)

    assert out.loc[0, "Redirect Correct"] == "No"
    assert _issue(out, 0) == ISSUE_WRONG_TARGET


def test_private_addresses_are_blocked_like_every_other_fetch(tmp_path: pathlib.Path) -> None:
    """Regression: the crawler refuses loopback/intranet targets but this tool
    fetched them happily, so a shared redirect sheet could aim it at the
    operator's own network."""
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["http://127.0.0.1:8080/admin"], "New URL": ["https://e.example.com/"]})
    )

    out, result = _run(path, options=_OPTIONS)

    assert _issue(out, 0) == ISSUE_PRIVATE
    assert result.summary.errors == 1


def test_private_addresses_are_reachable_when_explicitly_allowed(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["http://127.0.0.1:8080/a"], "New URL": ["http://127.0.0.1:8080/a"]})
    )

    with requests_mock.Mocker() as mock:
        mock.get("http://127.0.0.1:8080/a", status_code=200)
        out, _ = _run(
            path,
            options=RedirectCheckOptions(timeout=5, max_workers=1, respect_robots=False, allow_private_network=True),
        )

    assert _issue(out, 0) == ""
    assert out.loc[0, "Redirect Correct"] == "Yes"


def test_robots_txt_is_fetched_once_per_host_not_once_per_row(tmp_path: pathlib.Path) -> None:
    """Regression: robots.txt was re-fetched for every row, so a 20k-row
    single-host migration doubled its own traffic."""
    rows = 8
    path = _sheet(
        tmp_path,
        pd.DataFrame(
            {
                "Old URL": [f"https://old.example.com/p{i}" for i in range(rows)],
                "New URL": [f"https://old.example.com/p{i}" for i in range(rows)],
            }
        ),
    )

    with requests_mock.Mocker() as mock:
        robots = mock.get("https://old.example.com/robots.txt", status_code=200, text="User-agent: *\nAllow: /\n")
        for i in range(rows):
            mock.get(f"https://old.example.com/p{i}", status_code=200)
        _run(path, options=RedirectCheckOptions(timeout=5, max_workers=1, respect_robots=True))

    assert robots.call_count == 1


def test_robots_block_is_reported_without_fetching_the_url(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path, pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://new.example.com/a"]})
    )

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/robots.txt", status_code=200, text="User-agent: *\nDisallow: /\n")
        page = mock.get("https://old.example.com/a", status_code=200)
        out, _ = _run(path, options=RedirectCheckOptions(timeout=5, max_workers=1, respect_robots=True))

    assert _issue(out, 0) == ISSUE_ROBOTS
    assert page.call_count == 0


def test_a_row_that_raises_does_not_lose_the_rest_of_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Regression: an unexpected exception escaped the executor and every
    already-completed row died with it."""
    path = _sheet(
        tmp_path,
        pd.DataFrame(
            {
                "Old URL": ["https://old.example.com/a", "https://old.example.com/boom"],
                "New URL": ["https://new.example.com/a", "https://new.example.com/boom"],
            }
        ),
    )

    def exploding_chain(session, start_url, options, robots):
        if start_url.endswith("boom"):
            raise RuntimeError("kaboom")
        from silentfrog.redirect import RedirectHop, RedirectOutcome

        return RedirectOutcome(200, "https://new.example.com/a", (RedirectHop("https://new.example.com/a", 200),), "")

    monkeypatch.setattr("silentfrog.redirect._follow_chain", exploding_chain)
    out, result = _run(path, options=_OPTIONS)

    assert len(out) == 2
    assert result.summary.total == 2
    assert "Request error" in _issue(out, 1)


def test_cancelling_keeps_the_rows_already_checked(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path,
        pd.DataFrame(
            {
                "Old URL": [f"https://old.example.com/p{i}" for i in range(6)],
                "New URL": [f"https://old.example.com/p{i}" for i in range(6)],
            }
        ),
    )
    cancel = threading.Event()

    def stop_after_first(done: int, total: int, url: str, status: str | int) -> None:
        cancel.set()

    with requests_mock.Mocker() as mock:
        for i in range(6):
            mock.get(f"https://old.example.com/p{i}", status_code=200)
        out, result = _run(
            path,
            options=RedirectCheckOptions(timeout=5, max_workers=1, respect_robots=False),
            progress_callback=stop_after_first,
            cancel_flag=cancel,
        )

    assert result.cancelled is True
    assert 1 <= result.summary.total < 6
    assert result.output_path.exists()
    # Rows the run never reached must SAY so. Left blank they carry an empty
    # status, which is exactly what an unreachable host produces, so a stopped
    # audit would be indistinguishable from a broken site.
    unchecked = [row for row in range(len(out)) if _issue(out, row) == ISSUE_NOT_CHECKED]
    assert len(unchecked) == len(out) - result.summary.total


def test_progress_reports_running_totals(tmp_path: pathlib.Path) -> None:
    path = _sheet(
        tmp_path,
        pd.DataFrame(
            {
                "Old URL": ["https://old.example.com/a", "https://old.example.com/b"],
                "New URL": ["https://old.example.com/a", "https://old.example.com/b"],
            }
        ),
    )
    calls: list[tuple[int, int]] = []

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=200)
        mock.get("https://old.example.com/b", status_code=200)
        _run(
            path,
            options=_OPTIONS,
            progress_callback=lambda done, total, url, status: calls.append((done, total)),
        )

    assert calls == [(1, 2), (2, 2)]


def test_report_is_styled_and_flags_every_row_that_needs_attention(tmp_path: pathlib.Path) -> None:
    """Regression: only a literal 404 was tinted, so 5xx rows and rows that
    landed on the wrong target were indistinguishable from clean ones."""
    path = _sheet(
        tmp_path,
        pd.DataFrame(
            {
                "Old URL": ["https://old.example.com/ok", "https://old.example.com/gone"],
                "New URL": ["https://old.example.com/ok", "https://old.example.com/gone"],
            }
        ),
    )

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/ok", status_code=200)
        mock.get("https://old.example.com/gone", status_code=500)
        _, result = _run(path, options=_OPTIONS)

    workbook = load_workbook(result.output_path)
    try:
        sheet = workbook["Results"]
        assert sheet["A2"].font.name == "Arial"
        assert sheet["A2"].fill.start_color.rgb != "FFFFC7CE", "a clean 200 row must stay untinted"
        assert sheet["A3"].fill.start_color.rgb == "FFFFC7CE"
        assert sheet.freeze_panes == "A2"
    finally:
        workbook.close()


def test_a_locked_report_falls_back_instead_of_losing_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Regression: the workbook write was the last step and had no fallback, so
    "the results file is still open in Excel" threw away the whole run."""
    path = _sheet(
        tmp_path,
        pd.DataFrame({"Old URL": ["https://old.example.com/a"], "New URL": ["https://old.example.com/a"]}),
    )
    from silentfrog import redirect as module

    real_write = module._write_workbook
    blocked = tmp_path / "input_results.xlsx"

    def refuse_locked_target(df, target):
        if target == blocked:
            raise PermissionError(target)
        return real_write(df, target)

    monkeypatch.setattr(module, "_write_workbook", refuse_locked_target)

    with requests_mock.Mocker() as mock:
        mock.get("https://old.example.com/a", status_code=200)
        result = check_redirects(path, options=_OPTIONS)

    assert result.output_path.name == "input_results_1.xlsx"
    assert result.summary.total == 1


def test_encoded_delimiters_are_not_treated_as_delimiters() -> None:
    """Regression (adversarial review): normalising with a blind ``unquote``
    made ``/a%2Fb`` compare equal to ``/a/b``, so a redirect landing on the
    wrong resource could be reported as correct."""
    assert _comparable_url("https://x.example.com/a%2Fb") != _comparable_url("https://x.example.com/a/b")
    assert _comparable_url("https://x.example.com/p?a=1%26b=2") != _comparable_url("https://x.example.com/p?a=1&b=2")


def test_a_half_recognised_header_is_refused_instead_of_guessed(tmp_path: pathlib.Path) -> None:
    """A sheet that clearly has a header but names only one of the two columns
    must not fall back to "first two columns" — that reads the header row as
    data and can check entirely the wrong column."""
    path = _sheet(
        tmp_path,
        pd.DataFrame({"Old URL": ["https://old.example.com/a"], "Landing page": ["https://new.example.com/a"]}),
    )

    with pytest.raises(ValueError, match="no new-URL column"):
        _load_redirect_frame(path)


def test_one_connection_serves_many_rows_on_the_same_host(tmp_path: pathlib.Path) -> None:
    """Regression: skipping the landing-page body with ``stream=True`` and
    closing the response left urllib3 unable to pool the socket, so every row
    opened a fresh TCP+TLS connection. On a several-thousand-row single-host
    migration that reads as an attack and the run gets dropped at the edge.

    Runs against a real loopback server: requests_mock never touches a socket,
    so only this can see connection reuse.
    """
    connections: list[int] = []
    handled: list[str] = []
    lock = threading.Lock()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self) -> None:
            with lock:
                connections.append(1)
            super().setup()

        def do_GET(self) -> None:
            with lock:
                handled.append(self.path)
            body = b"<html>" + b"x" * 500 + b"</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        rows = 20
        urls = [f"http://127.0.0.1:{port}/p{index}" for index in range(rows)]
        path = _sheet(tmp_path, pd.DataFrame({"Old URL": urls, "New URL": urls}))
        _, result = _run(
            path,
            options=RedirectCheckOptions(timeout=5, max_workers=1, respect_robots=False, allow_private_network=True),
        )
    finally:
        server.shutdown()
        server.server_close()

    assert len(handled) == rows, "every row must still be checked"
    assert result.summary.correct == rows
    # One worker thread reusing its pooled connection: a couple of connections
    # is normal, one per row is the defect.
    assert len(connections) <= 3, f"expected pooled connections, got {len(connections)} for {rows} rows"


def test_throttle_limits_concurrency_and_can_be_raised_mid_run() -> None:
    """The Threads box must retune a run already in flight, not just the next
    one: a bulk check finds out it is too fast only once the target starts
    refusing it."""
    throttle = RedirectThrottle(parallel=2, max_parallel=8)
    peak = 0
    active = 0
    lock = threading.Lock()
    released = threading.Event()

    def hold() -> None:
        nonlocal peak, active
        with throttle.slot():
            with lock:
                active += 1
                peak = max(peak, active)
            released.wait(2.0)
            with lock:
                active -= 1

    workers = [threading.Thread(target=hold, daemon=True) for _ in range(8)]
    for worker in workers:
        worker.start()
    time.sleep(0.3)
    assert peak <= 2, f"limit of 2 not enforced, saw {peak} concurrent"

    throttle.set_parallel(6)
    time.sleep(0.4)
    raised = peak
    released.set()
    for worker in workers:
        worker.join(3.0)

    assert raised > 2, "raising the limit mid-run must wake threads already queued"
    assert raised <= 6


def test_throttle_delay_is_applied_before_each_request() -> None:
    throttle = RedirectThrottle(parallel=1, delay_ms=120)
    started = time.monotonic()
    throttle.pause_before_request()
    assert time.monotonic() - started >= 0.1

    throttle.set_delay_ms(0)
    started = time.monotonic()
    throttle.pause_before_request()
    assert time.monotonic() - started < 0.05
