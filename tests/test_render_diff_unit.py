from __future__ import annotations

from pathlib import Path

import silentfrog.render_diff as render_diff  # type: ignore[reportMissingImports]
from silentfrog.render_diff import (  # type: ignore[reportMissingImports]
    RenderDiff,
    RenderResult,
    build_render_diff_check,
    compute_render_diff,
    render_with_playwright,
)

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_compute_render_diff_identical_html_is_good() -> None:
    html = _read("render_diff_ssr_complete.html")
    diff = compute_render_diff(html, html)
    assert diff.status == "good"
    assert diff.missing_headings == ()
    assert diff.missing_main_text_chars == 0


def test_compute_render_diff_empty_rendered_html_is_critical() -> None:
    diff = compute_render_diff("<html><body><h1>X</h1></body></html>", "")
    assert diff.status == "critical"
    assert "empty" in diff.reason.lower()


def test_compute_render_diff_ssr_missing_h1_is_critical_against_jsr() -> None:
    diff = compute_render_diff(_read("render_diff_ssr_missing_h1.html"), _read("render_diff_jsr_only.html"))
    assert diff.status == "critical"
    assert "RAG Pipelines Explained" in diff.missing_headings or "Architecture" in diff.missing_headings


def test_compute_render_diff_small_text_delta_is_warning() -> None:
    plain = "<html><body><h1>A</h1><p>Short page.</p></body></html>"
    rendered = "<html><body><h1>A</h1><p>Short page.</p>" + ("<p>extra body content.</p>" * 12) + "</body></html>"
    diff = compute_render_diff(plain, rendered)
    assert diff.status == "warning"
    assert diff.missing_main_text_chars > 200


def test_compute_render_diff_complete_ssr_matches_jsr_subset_is_good() -> None:
    plain = _read("render_diff_ssr_complete.html")
    diff = compute_render_diff(plain, plain)
    assert diff.status == "good"


def test_render_with_playwright_returns_none_when_not_installed(monkeypatch) -> None:
    monkeypatch.setattr(render_diff, "sync_playwright", None)
    assert render_with_playwright("https://example.com/") is None


def test_render_with_playwright_returns_result_with_stubbed_runtime(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class _Page:
        def goto(self, url, timeout, wait_until) -> None:
            captured["url"] = url
            captured["wait_until"] = wait_until

        def content(self) -> str:
            return "<html><body><h1>Stubbed</h1></body></html>"

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None:
            captured["closed"] = "yes"

    class _Chromium:
        def launch(self) -> _Browser:
            return _Browser()

    class _Runtime:
        chromium = _Chromium()

        def __enter__(self) -> _Runtime:
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(render_diff, "sync_playwright", lambda: _Runtime())

    result = render_with_playwright("https://example.com/p")

    assert result is not None
    assert result.url == "https://example.com/p"
    assert "Stubbed" in result.rendered_html
    assert captured["url"] == "https://example.com/p"
    assert captured["closed"] == "yes"


def test_build_render_diff_check_none_emits_info_status() -> None:
    check = build_render_diff_check(None)
    assert check.area == "Access"
    assert check.status == "info"
    assert check.key == "access_ssr_parity"
    assert "not measured" in check.details.lower()


def test_build_render_diff_check_critical_status_is_preserved() -> None:
    diff = RenderDiff(status="critical", missing_headings=("H",), missing_main_text_chars=900, missing_links=8)
    check = build_render_diff_check(diff)
    assert check.status == "critical"
    assert "900" in check.details


def test_build_render_diff_check_warning_reason_appended_when_render_failed() -> None:
    diff = RenderDiff(status="warning", reason="Render failed: TimeoutError")
    check = build_render_diff_check(diff)
    assert check.status == "warning"
    assert "TimeoutError" in check.details


def test_render_result_dataclass_preserves_error_field() -> None:
    result = RenderResult(url="https://x/", rendered_html="", error="Boom")
    assert result.error == "Boom"
