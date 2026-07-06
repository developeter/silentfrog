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


def _render_with_browser(
    browser: Any, url: str, timeout: int, collect_vitals: bool, user_agent: str = ""
) -> RenderResult:
    try:
        # v2.0 V10: only pass user_agent when set, so pre-V10 fakes (and the
        # default-UA path) keep the zero-kwarg new_page() contract.
        page = browser.new_page(user_agent=user_agent) if user_agent else browser.new_page()
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
    # v2.0 V10: render with this exact user-agent ("" = browser default).
    user_agent: str = ""


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

    async def render(
        self,
        url: str,
        timeout: int = 15,
        collect_vitals: bool = False,
        user_agent: str = "",
    ) -> RenderResult:
        self._ensure_started()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RenderResult] = loop.create_future()
        self._queue.put(_RenderJob(url, timeout, collect_vitals, loop, future, user_agent))
        return await future

    def _run(self) -> None:
        # V10 hardening: a failed launch must never kill the worker thread —
        # queued futures would hang forever. A dead browser resolves every
        # job with an error result instead.
        manager, browser, launch_error = self._start_browser()
        pages_done = 0
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    return
                result = _job_result(browser, job, launch_error)
                job.loop.call_soon_threadsafe(_resolve, job.future, result)
                pages_done += 1
                if browser is None or pages_done < self._max_pages:
                    continue
                _safe_close(browser)
                browser, launch_error = _relaunch(manager)
                pages_done = 0
        finally:
            _safe_close(browser)
            _safe_stop(manager)

    def _start_browser(self) -> tuple[Any, Any, str]:
        try:
            manager = self._factory()
        except Exception as exc:
            return None, None, f"{type(exc).__name__}: {exc}"
        browser, error = _relaunch(manager)
        return manager, browser, error

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


def _relaunch(manager: Any) -> tuple[Any, str]:
    """Launch a browser off *manager*; ``(None, error)`` instead of raising."""
    try:
        return manager.launch(), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _job_result(browser: Any, job: _RenderJob, launch_error: str) -> RenderResult:
    if browser is None:
        return RenderResult(url=job.url, rendered_html="", error=f"Browser launch failed: {launch_error}")
    return _render_with_browser(browser, job.url, job.timeout, job.collect_vitals, job.user_agent)


__all__ = ["BrowserManager", "RenderPool"]
