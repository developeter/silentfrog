"""Unit tests for the v2.0 V4 render pool (fake browser — no Chromium)."""

from __future__ import annotations

import asyncio

import pytest

from silentfrog.render_pool import RenderPool


class _FakePage:
    def __init__(self, html: str) -> None:
        self._html = html

    def goto(self, url: str, timeout: int = 0, wait_until: str = "") -> None:
        self._url = url

    def content(self) -> str:
        return self._html

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, html_for) -> None:
        self._html_for = html_for
        self.pages_created = 0
        self.closed = False
        self.user_agents: list[str] = []

    def new_page(self, user_agent: str = "") -> _FakePage:
        self.pages_created += 1
        self.user_agents.append(user_agent)
        return _FakePage(self._html_for())

    def close(self) -> None:
        self.closed = True


class _FakeManager:
    def __init__(self) -> None:
        self.launch_count = 0
        self.stopped = False
        self.browsers: list[_FakeBrowser] = []
        self._current_url = "x"

    def launch(self) -> _FakeBrowser:
        self.launch_count += 1
        browser = _FakeBrowser(lambda: f"<html>{self._current_url}</html>")
        self.browsers.append(browser)
        return browser

    def stop(self) -> None:
        self.stopped = True


@pytest.mark.asyncio
async def test_render_returns_rendered_html() -> None:
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    result = await pool.render("https://e.com/a")
    assert "<html>" in result.rendered_html
    assert result.error == ""
    pool.close()


@pytest.mark.asyncio
async def test_pool_reuses_one_browser_across_pages() -> None:
    manager = _FakeManager()
    pool = RenderPool(max_pages_per_browser=100, browser_factory=lambda: manager)
    for i in range(5):
        await pool.render(f"https://e.com/{i}")
    # One browser launched, reused for all 5 pages.
    assert manager.launch_count == 1
    assert manager.browsers[0].pages_created == 5
    pool.close()


@pytest.mark.asyncio
async def test_pool_recycles_browser_every_n_pages() -> None:
    manager = _FakeManager()
    pool = RenderPool(max_pages_per_browser=2, browser_factory=lambda: manager)
    for i in range(5):
        await pool.render(f"https://e.com/{i}")
    # 5 pages, recycle every 2 -> launches: initial + after page 2 + after
    # page 4 = 3 browsers.
    assert manager.launch_count == 3
    pool.close()


@pytest.mark.asyncio
async def test_close_stops_the_manager() -> None:
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    await pool.render("https://e.com/a")
    pool.close()
    assert manager.stopped is True


@pytest.mark.asyncio
async def test_render_degrades_when_page_raises() -> None:
    class _BoomBrowser:
        def new_page(self):
            raise RuntimeError("launch failed")

        def close(self):
            pass

    class _BoomManager:
        def launch(self):
            return _BoomBrowser()

        def stop(self):
            pass

    pool = RenderPool(browser_factory=_BoomManager)
    result = await pool.render("https://e.com/a")
    assert result.rendered_html == ""
    assert "RuntimeError" in result.error
    pool.close()


@pytest.mark.asyncio
async def test_launch_failure_resolves_renders_with_error_instead_of_hanging() -> None:
    # V10 regression: a failed browser launch used to kill the worker thread,
    # leaving every queued future unresolved forever.
    class _NoChromiumManager:
        def launch(self):
            raise RuntimeError("Executable doesn't exist; run playwright install")

        def stop(self):
            pass

    pool = RenderPool(browser_factory=_NoChromiumManager)
    result = await asyncio.wait_for(pool.render("https://e.com/a"), timeout=5)
    assert result.rendered_html == ""
    assert result.error.startswith("Browser launch failed:")
    assert "RuntimeError" in result.error
    pool.close()


@pytest.mark.asyncio
async def test_render_passes_the_requested_user_agent_to_the_page() -> None:
    # v2.0 V10: per-bot renders override the UA; the default path leaves it "".
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    await pool.render("https://e.com/a", user_agent="Mozilla/5.0 (compatible; GPTBot/1.2)")
    await pool.render("https://e.com/b")
    assert manager.browsers[0].user_agents == ["Mozilla/5.0 (compatible; GPTBot/1.2)", ""]
    pool.close()


@pytest.mark.asyncio
async def test_concurrent_renders_all_resolve() -> None:
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    results = await asyncio.gather(*[pool.render(f"https://e.com/{i}") for i in range(10)])
    assert len(results) == 10
    assert all("<html>" in r.rendered_html for r in results)
    pool.close()
