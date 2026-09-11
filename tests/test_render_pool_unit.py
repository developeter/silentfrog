"""Unit tests for the v2.0 V4 render pool (fake browser — no Chromium)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from silentfrog.render_pool import (
    RenderPool,
    active_render_pool,
    render_pool_scope_async,
)


class _FakePage:
    def __init__(self, html: str, evaluate_result: Any = None, evaluate_raises: bool = False) -> None:
        self._html = html
        self.injected_scripts: list[str] = []
        self.evaluated: list[str] = []
        self._evaluate_result = evaluate_result
        self._evaluate_raises = evaluate_raises

    def goto(self, url: str, timeout: int = 0, wait_until: str = "") -> None:
        self._url = url

    def content(self) -> str:
        return self._html

    # v3 G4: recorders mirroring Playwright's real API surface.
    def add_script_tag(self, content: str = "") -> None:
        self.injected_scripts.append(content)

    def evaluate(self, expression: str) -> Any:
        self.evaluated.append(expression)
        if self._evaluate_raises:
            raise RuntimeError("evaluate failed")
        return self._evaluate_result

    def close(self) -> None:
        pass


class _FakeBrowser:
    def __init__(self, html_for, evaluate_result: Any = None, evaluate_raises: bool = False) -> None:
        self._html_for = html_for
        self.pages_created = 0
        self.closed = False
        self.user_agents: list[str] = []
        self.pages: list[_FakePage] = []
        self._evaluate_result = evaluate_result
        self._evaluate_raises = evaluate_raises

    def new_page(self, user_agent: str = "") -> _FakePage:
        self.pages_created += 1
        self.user_agents.append(user_agent)
        page = _FakePage(self._html_for(), evaluate_result=self._evaluate_result, evaluate_raises=self._evaluate_raises)
        self.pages.append(page)
        return page

    def close(self) -> None:
        self.closed = True


class _FakeManager:
    def __init__(self, evaluate_result: Any = None, evaluate_raises: bool = False) -> None:
        self.launch_count = 0
        self.stopped = False
        self.browsers: list[_FakeBrowser] = []
        self._current_url = "x"
        self._evaluate_result = evaluate_result
        self._evaluate_raises = evaluate_raises

    def launch(self) -> _FakeBrowser:
        self.launch_count += 1
        browser = _FakeBrowser(
            lambda: f"<html>{self._current_url}</html>",
            evaluate_result=self._evaluate_result,
            evaluate_raises=self._evaluate_raises,
        )
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
async def test_worker_retries_after_a_failed_launch_instead_of_failing_forever() -> None:
    # render-pool repair: every worker launches at once on a crawl's first
    # render, so a transient launch failure under that contention is normal.
    # A worker that kept its dead browser failed EVERY later job it dequeued
    # for the rest of the crawl; the pre-pool direct call relaunched per page
    # and lost exactly one page to the same failure.
    class _FlakyManager:
        def __init__(self) -> None:
            self.launch_count = 0
            self.stopped = False

        def launch(self) -> _FakeBrowser:
            self.launch_count += 1
            if self.launch_count == 1:
                raise RuntimeError("Target page, context or browser has been closed")
            return _FakeBrowser(lambda: "<html>retried</html>")

        def stop(self) -> None:
            self.stopped = True

    manager = _FlakyManager()
    pool = RenderPool(browser_factory=lambda: manager)
    first = await asyncio.wait_for(pool.render("https://e.com/a"), timeout=5)
    second = await asyncio.wait_for(pool.render("https://e.com/b"), timeout=5)
    assert first.error.startswith("Browser launch failed:")
    assert second.error == ""
    assert "retried" in second.rendered_html
    pool.close()


@pytest.mark.asyncio
async def test_worker_retries_the_browser_factory_itself_after_it_failed() -> None:
    # Same repair one level up: when the factory (not the launch) is what
    # raised, the worker has no manager to relaunch from and must rebuild it.
    calls: list[int] = []

    def factory() -> _FakeManager:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("playwright install missing")
        return _FakeManager()

    pool = RenderPool(browser_factory=factory)
    first = await asyncio.wait_for(pool.render("https://e.com/a"), timeout=5)
    second = await asyncio.wait_for(pool.render("https://e.com/b"), timeout=5)
    assert first.error.startswith("Browser launch failed:")
    assert second.error == ""
    assert "<html>" in second.rendered_html
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


# --- v3 G4: inject_js / evaluate_js (axe-core accessibility scan) -----------


@pytest.mark.asyncio
async def test_render_injects_and_evaluates_script_when_requested() -> None:
    manager = _FakeManager(evaluate_result={"violations": []})
    pool = RenderPool(browser_factory=lambda: manager)
    result = await pool.render("https://e.com/a", inject_js="window.axe = {}", evaluate_js="axe.run()")
    assert result.script_result == {"violations": []}
    page = manager.browsers[0].pages[0]
    assert page.injected_scripts == ["window.axe = {}"]
    assert page.evaluated == ["axe.run()"]
    pool.close()


@pytest.mark.asyncio
async def test_render_evaluate_failure_leaves_script_result_none_and_html_intact() -> None:
    # A script failure must never fail the render (error stays "").
    manager = _FakeManager(evaluate_raises=True)
    pool = RenderPool(browser_factory=lambda: manager)
    result = await pool.render("https://e.com/a", inject_js="window.axe = {}", evaluate_js="axe.run()")
    assert result.script_result is None
    assert result.error == ""
    assert "<html>" in result.rendered_html
    pool.close()


@pytest.mark.asyncio
async def test_render_without_script_args_leaves_page_untouched() -> None:
    # Existing (no-script) render path stays exactly as before.
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    result = await pool.render("https://e.com/a")
    assert result.script_result is None
    page = manager.browsers[0].pages[0]
    assert page.injected_scripts == []
    assert page.evaluated == []
    pool.close()


# --- render-pool track: crawl-scoped pool (render_js / ssr_parity reuse) ----


def test_active_render_pool_is_none_outside_any_scope() -> None:
    # Single-page audits call analyse() with no enclosing render_pool_scope();
    # the fallback-to-direct-call path in seo_crawler._render_page depends on
    # this returning None.
    assert active_render_pool() is None


@pytest.mark.asyncio
async def test_render_pool_scope_reuses_one_browser_across_pages() -> None:
    manager = _FakeManager()
    async with render_pool_scope_async(browser_factory=lambda: manager) as pool:
        for i in range(4):
            await pool.render(f"https://e.com/{i}")
    # One Chromium launch served all 4 pages of the crawl — the exact cost
    # the crawl-scoped pool exists to flatten (one launch per page before).
    assert manager.launch_count == 1
    assert manager.browsers[0].pages_created == 4


def test_playwright_available_follows_render_diffs_own_gate(monkeypatch) -> None:
    # The crawl-side gate must never disagree with the direct-call path's own
    # gate: render_diff.sync_playwright is the exact symbol that module's
    # tests patch to simulate the optional extra being absent, so
    # playwright_available() reads it rather than probing the import again.
    from silentfrog import render_diff, render_pool

    monkeypatch.setattr(render_diff, "sync_playwright", None)
    assert render_pool.playwright_available() is False
    monkeypatch.setattr(render_diff, "sync_playwright", object())
    assert render_pool.playwright_available() is True


# --- render-pool repair: size the pool to the crawl's own concurrency -------
#
# One worker thread == one browser == every render serialised, regardless of
# how many pages a crawl fetches in parallel. That made a render-enabled
# crawl SLOWER than the pre-pool direct-call path (measured ~3.8x at the
# default concurrency=4). ``workers=`` must actually put N browsers to work,
# not just accept the kwarg.


def test_pool_launches_one_browser_per_worker_thread() -> None:
    lock = threading.Lock()
    managers: list[_FakeManager] = []

    def factory() -> _FakeManager:
        manager = _FakeManager()
        with lock:
            managers.append(manager)
        return manager

    pool = RenderPool(browser_factory=factory, workers=3)

    async def render_three() -> None:
        await asyncio.gather(*(pool.render(f"https://e.com/{i}") for i in range(3)))

    asyncio.run(render_three())
    try:
        # Each worker thread calls the factory once for its own browser —
        # 3 workers must mean 3 independently launched browsers, not 3
        # requests queued behind a single serial worker.
        assert len(managers) == 3
        assert all(manager.launch_count == 1 for manager in managers)
    finally:
        pool.close()
    # close() sends one sentinel per worker and joins every thread — no
    # worker (and so no browser) is left running.
    assert all(manager.stopped for manager in managers)


@pytest.mark.asyncio
async def test_pool_defaults_to_a_single_worker_when_unspecified() -> None:
    # Backward compatibility: every pre-existing caller (and test) that never
    # passed ``workers=`` must keep getting exactly the one-worker pool it
    # always got.
    manager = _FakeManager()
    pool = RenderPool(browser_factory=lambda: manager)
    await asyncio.gather(*(pool.render(f"https://e.com/{i}") for i in range(4)))
    assert manager.launch_count == 1
    pool.close()


# --- render-pool repair: async scope closes off the event loop -------------


@pytest.mark.asyncio
async def test_render_pool_scope_async_activates_and_restores_pool() -> None:
    assert active_render_pool() is None
    async with render_pool_scope_async(browser_factory=_FakeManager) as pool:
        assert active_render_pool() is pool
    assert active_render_pool() is None


@pytest.mark.asyncio
async def test_render_pool_scope_async_closes_the_pool_without_raising() -> None:
    # Regression guard: the ContextVar reset must happen on the calling
    # task's own context, not inside the asyncio.to_thread(pool.close) call
    # — resetting a Token from a copied context raises ValueError. This
    # exercises the full scope (activate, render, close) end to end.
    manager = _FakeManager()
    async with render_pool_scope_async(browser_factory=lambda: manager, workers=2) as pool:
        await asyncio.gather(pool.render("https://e.com/a"), pool.render("https://e.com/b"))
    assert manager.stopped is True
    assert active_render_pool() is None


@pytest.mark.asyncio
async def test_render_pool_scope_async_closes_the_pool_on_error() -> None:
    manager = _FakeManager()
    with pytest.raises(RuntimeError, match="crawl blew up"):
        async with render_pool_scope_async(browser_factory=lambda: manager) as pool:
            await pool.render("https://e.com/a")
            raise RuntimeError("crawl blew up")
    assert manager.stopped is True
    assert active_render_pool() is None
