"""Unit tests for v3 M8 JS-rendered link discovery (pure merge, no Chromium)."""

from __future__ import annotations

from silentfrog.crawl_options import CrawlOptions
from silentfrog.seo_crawler import _extract_links, merge_rendered_links

_BASE = "https://spa.example.com/"
_RAW = "<html><body><a href='/home'>Home</a></body></html>"
# A SPA whose nav links exist only after JS hydration.
_RENDERED = (
    "<html><body><a href='/home'>Home</a><a href='/products'>Products</a><a href='/about'>About</a></body></html>"
)


def test_option_off_by_default() -> None:
    assert CrawlOptions.default().render_js is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).render_js is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, render_js=True).render_js is True


def test_merge_adds_js_only_links_without_duplicating() -> None:
    from bs4 import BeautifulSoup

    raw_rows = _extract_links(_BASE, BeautifulSoup(_RAW, "html.parser"))
    merged = merge_rendered_links(_BASE, raw_rows, _RENDERED)
    urls = [row[0] for row in merged]
    # /home appears once (dedup); the two JS-only routes are appended.
    assert urls.count("https://spa.example.com/home") == 1
    assert "https://spa.example.com/products" in urls
    assert "https://spa.example.com/about" in urls
    assert len(merged) == len(raw_rows) + 2


def test_merge_dedups_repeated_rendered_only_links() -> None:
    # Regression: the same JS-only href in header+footer must appear once, not N.
    from bs4 import BeautifulSoup

    raw_rows = _extract_links(_BASE, BeautifulSoup(_RAW, "html.parser"))
    repeated = (
        "<html><body>"
        "<a href='/products'>Nav</a><a href='/products'>Footer</a><a href='/products'>Sidebar</a>"
        "</body></html>"
    )
    merged = merge_rendered_links(_BASE, raw_rows, repeated)
    urls = [row[0] for row in merged]
    assert urls.count("https://spa.example.com/products") == 1


def test_merge_is_noop_without_rendered_html() -> None:
    from bs4 import BeautifulSoup

    raw_rows = _extract_links(_BASE, BeautifulSoup(_RAW, "html.parser"))
    assert merge_rendered_links(_BASE, raw_rows, "") == raw_rows
    assert merge_rendered_links(_BASE, raw_rows, "   ") == raw_rows


def test_merge_preserves_raw_rows_when_render_finds_nothing_new() -> None:
    from bs4 import BeautifulSoup

    raw_rows = _extract_links(_BASE, BeautifulSoup(_RAW, "html.parser"))
    # Rendered DOM identical to raw -> no extra rows, same URLs.
    merged = merge_rendered_links(_BASE, raw_rows, _RAW)
    assert [row[0] for row in merged] == [row[0] for row in raw_rows]
