"""Concurrent Playwright render pool (v2.0 V4).

``render_diff.render_with_playwright`` launches a fresh Chromium per
URL. At crawl scale with SSR-parity on, that's one browser launch per
page — slow, and memory creeps across runs. This pool keeps long-lived
browsers on dedicated worker threads and recycles each one every N
pages to bound memory.

Sync Playwright objects are not safe to move across threads, so each
worker thread owns exactly one browser; async callers submit work and
await a future resolved from whichever worker thread picks it up. The
pool's thread count (``workers=``) matches the crawl's own concurrency:
a single worker thread would serialise every render regardless of how
many pages a crawl fetches in parallel, which is slower than the
pre-pool direct-call path at any concurrency > 1, so ``site_crawler``
sizes the crawl-scoped pool to ``ctx.concurrency``. The browser factory
is injectable, so tests exercise the queue + recycle lifecycle with a
fake — CI never needs real Chromium.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .render_diff import RenderResult, _collect_cdp_vitals

_DEFAULT_MAX_PAGES_PER_BROWSER = 50


def playwright_available() -> bool:
    """Cheap availability probe used to decide whether the crawl-scoped pool
    is worth handing a render to — mirrors the gate ``bot_render`` already
    uses so a crawl with Playwright absent degrades to the exact same
    "not measured" / ``None`` result the direct ``render_with_playwright``
    call has always produced (a pool launch failure would instead surface as
    a warning, which is a behaviour change we don't want for this case).

    Delegates to ``render_diff``'s own module-level gate rather than a second,
    independent import probe: ``render_diff.sync_playwright`` is exactly the
    symbol its docstring says tests monkeypatch to simulate a missing extra,
    so this can never disagree with the direct-call path's own availability
    check."""
    from . import render_diff

    return render_diff.sync_playwright is not None


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


def _run_page_script(page: Any, inject_js: str, evaluate_js: str) -> Any:
    """v3 G4: optionally inject a script tag then evaluate an expression in
    the rendered page (used to run the vendored axe-core accessibility
    engine). A script failure must never fail the render — this returns
    ``None`` on any error and the caller leaves ``RenderResult.error`` alone,
    since existing consumers treat a populated ``error`` as render failure."""
    if not inject_js and not evaluate_js:
        return None
    try:
        if inject_js:
            page.add_script_tag(content=inject_js)
        if evaluate_js:
            # Playwright's sync API auto-awaits a returned promise.
            return page.evaluate(evaluate_js)
        return None
    except Exception:
        return None


def _render_with_browser(
    browser: Any,
    url: str,
    timeout: int,
    collect_vitals: bool,
    user_agent: str = "",
    inject_js: str = "",
    evaluate_js: str = "",
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
        script_result = _run_page_script(page, inject_js, evaluate_js)
        return RenderResult(
            url=url,
            rendered_html=page.content(),
            vitals_payload=vitals_payload,
            script_result=script_result,
        )
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
    # v3 G4: optional in-page script injection + evaluation (e.g. axe-core).
    inject_js: str = ""
    evaluate_js: str = ""


def _resolve(future: asyncio.Future[RenderResult], result: RenderResult) -> None:
    if not future.done():
        future.set_result(result)


class RenderPool:
    def __init__(
        self,
        max_pages_per_browser: int = _DEFAULT_MAX_PAGES_PER_BROWSER,
        browser_factory: Callable[[], Any] | None = None,
        workers: int = 1,
    ) -> None:
        # render-pool repair: ``workers`` worker threads share one queue, each
        # holding its own browser (module docstring) — sizing this to the
        # crawl's concurrency restores the parallelism a single worker thread
        # took away, while keeping the original win of a browser reused
        # across up to ``max_pages_per_browser`` pages instead of one launch
        # per page.
        self._max_pages = max(1, max_pages_per_browser)
        self._factory = browser_factory or _default_browser_factory
        self._workers = max(1, workers)
        self._queue: queue.Queue[_RenderJob | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._threads:
                return
            for _ in range(self._workers):
                thread = threading.Thread(target=self._run, daemon=True)
                thread.start()
                self._threads.append(thread)

    async def render(
        self,
        url: str,
        timeout: int = 15,
        collect_vitals: bool = False,
        user_agent: str = "",
        inject_js: str = "",
        evaluate_js: str = "",
    ) -> RenderResult:
        self._ensure_started()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[RenderResult] = loop.create_future()
        job = _RenderJob(url, timeout, collect_vitals, loop, future, user_agent, inject_js, evaluate_js)
        self._queue.put(job)
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
                if browser is not None and pages_done < self._max_pages:
                    continue
                # Recycle at the page cap — and retry straight away when this
                # worker has no browser at all. Every worker launches at once
                # on a crawl's first render, so a transient launch failure
                # under that contention is expected; a worker that never
                # retried would fail every job it later dequeued for the rest
                # of the crawl, where the pre-pool direct call relaunched per
                # page and lost exactly one page to the same failure.
                _safe_close(browser)
                manager, browser, launch_error = self._reacquire(manager)
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

    def _reacquire(self, manager: Any) -> tuple[Any, Any, str]:
        """A fresh browser for this worker: relaunch off the manager it
        already has, or build a new manager first when the factory itself
        was what failed."""
        if manager is None:
            return self._start_browser()
        browser, error = _relaunch(manager)
        return manager, browser, error

    def close(self) -> None:
        # One sentinel per worker thread — each thread's ``_run`` loop exits
        # on the first ``None`` it pulls, so N threads need N sentinels.
        threads, self._threads = self._threads, []
        if not threads:
            return
        for _ in threads:
            self._queue.put(None)
        for thread in threads:
            thread.join(timeout=10)


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
    return _render_with_browser(
        browser, job.url, job.timeout, job.collect_vitals, job.user_agent, job.inject_js, job.evaluate_js
    )


# --- crawl-scoped pool (one browser reused by every page of one crawl) -----
#
# render_js / ssr_parity_check used to call render_with_playwright directly,
# launching + tearing down a fresh Chromium per page — same waste this pool
# exists to avoid (see module docstring). This mirrors the
# discovery_files.discovery_scope / crawl_http.robots_fetch_scope idiom
# already used for other crawl-scoped resources: a ContextVar keeps
# analyse()'s signature untouched (existing single-page callers, and every
# test that stubs analyse() with a fixed signature, keep working unchanged),
# and a single-page audit run outside a crawl_site() simply sees no active
# pool and falls back to the direct per-call render.
_active_render_pool: ContextVar[RenderPool | None] = ContextVar("silentfrog_render_pool", default=None)


@asynccontextmanager
async def render_pool_scope_async(
    browser_factory: Callable[[], Any] | None = None, workers: int = 1
) -> AsyncIterator[RenderPool]:
    """Activate one shared ``RenderPool`` for the enclosed crawl.

    Closed on every exit path — normal completion, cancellation, or an
    exception propagating out of the ``async with`` block — so a crawl never
    leaks the pool's worker threads + browsers. ``browser_factory`` is
    exposed only for tests; production crawls always take the real default.
    ``workers`` should match the crawl's own concurrency (module
    docstring); it defaults to 1 so a caller that wants the original
    single-browser pool keeps it.

    The ContextVar set/reset MUST run on the calling task's own context — a
    ``Token`` can only be reset in the exact ``Context`` object that created
    it, so doing it inside ``asyncio.to_thread`` (which runs a *copy* of the
    context) raises ``ValueError``. Only ``pool.close()`` — the slow part, a
    per-worker ``thread.join`` plus each browser's own teardown — is
    offloaded there. Without that offload, a render still in flight when the
    crawl ends blocks the whole event loop for as long as that render plus
    teardown take (up to the 10s join timeout per worker), freezing progress
    callbacks and cancel handling for the whole crawl."""
    pool = RenderPool(browser_factory=browser_factory, workers=workers)
    token = _active_render_pool.set(pool)
    try:
        yield pool
    finally:
        _active_render_pool.reset(token)
        await asyncio.to_thread(pool.close)


def active_render_pool() -> RenderPool | None:
    """The pool activated by an enclosing ``render_pool_scope_async()``,
    or ``None`` when called from a
    single-page audit (no crawl scope) — callers fall back to a direct,
    unpooled render in that case."""
    return _active_render_pool.get()


__all__ = [
    "BrowserManager",
    "RenderPool",
    "active_render_pool",
    "playwright_available",
    "render_pool_scope_async",
]
