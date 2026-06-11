"""Concurrent Playwright render pool (v2.0 V4).

``render_diff.render_with_playwright`` launches a fresh Chromium per
URL. At crawl scale with SSR-parity on, that's one browser launch per
page — slow, and memory creeps across runs. This pool keeps a
long-lived browser on a dedicated thread and recycles it every N pages
to bound memory.

Sync Playwright objects are not safe to move across threads, so the
pool owns ONE worker thread that holds the browser; async callers
submit work and await a future resolved from that thread. The browser
factory is injectable, so tests exercise the queue + recycle lifecycle
with a fake — CI never needs real Chromium.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .render_diff import RenderResult, _collect_cdp_vitals

_DEFAULT_MAX_PAGES_PER_BROWSER = 50


class BrowserManager:
    """Owns a Playwright runtime; ``launch`` returns a fresh browser,
    ``stop`` tears the runtime down. Wrapped so the pool can recycle the
    browser without re-importing Playwright."""

    def __init__(self) -> None:
        from playwright.sync_api import sync_playwright  # lazy, optional extra

        self._runtime = sync_playwright().start()

    def launch(self) -> Any:
        return self._runtime.chromium.launch()

    def stop(self) -> None:
        self._runtime.stop()


def _default_browser_factory() -> BrowserManager:
    return BrowserManager()


def _render_with_browser(browser: Any, url: str, timeout: int, collect_vitals: bool) -> RenderResult:
    try:
        page = browser.new_page()
    except Exception as exc:  # pragma: no cover - real browser failures
        return RenderResult(url=url, rendered_html="", error=f"{type(exc).__name__}: {exc}")
    try:
        page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
        vitals_payload = _collect_cdp_vitals(page) if collect_vitals else None
        return RenderResult(url=url, rendered_html=page.content(), vitals_payload=vitals_payload)
    except Exception as exc:  # pragma: no cover - real navigation failures
        return RenderResult(url=url, rendered_html="", error=f"{type(exc).__name__}: {exc}")
    finally:
        _safe_close(page)


def _safe_close(closeable: Any) -> None:
    try:
        closeable.close()
    except Exception:
        pass


@dataclass
class _RenderJob:
    url: str
    timeout: int
    collect_vitals: bool
    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[RenderResult]


def _resolve(future: asyncio.Future[RenderResult], result: RenderResult) -> None:
    if not future.done():
        future.set_result(result)


class RenderPool:
    def __init__(
        self,
        max_pages_per_browser: int = _DEFAULT_MAX_PAGES_PER_BROWSER,
        browser_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._max_pages = max(1, max_pages_per_browser)
        self._factory = browser_factory or _default_browser_factory
        self._queue: queue.Queue[_RenderJob | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    async def render(self, url: str, timeout: int = 15, collect_vitals: bool = False) -> RenderResult:
        self._ensure_started()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RenderResult] = loop.create_future()
        self._queue.put(_RenderJob(url, timeout, collect_vitals, loop, future))
        return await future

    def _run(self) -> None:
        manager = self._factory()
        browser = manager.launch()
        pages_done = 0
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    return
                result = _render_with_browser(browser, job.url, job.timeout, job.collect_vitals)
                job.loop.call_soon_threadsafe(_resolve, job.future, result)
                pages_done += 1
                if pages_done >= self._max_pages:
                    _safe_close(browser)
                    browser = manager.launch()
                    pages_done = 0
        finally:
            _safe_close(browser)
            _safe_stop(manager)

    def close(self) -> None:
        thread = self._thread
        if thread is not None:
            self._queue.put(None)
            thread.join(timeout=10)
            self._thread = None


def _safe_stop(manager: Any) -> None:
    try:
        manager.stop()
    except Exception:
        pass


__all__ = ["BrowserManager", "RenderPool"]
