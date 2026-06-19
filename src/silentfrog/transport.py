"""Central transport seam for crawler-controlled URL fetches (v2.0 E1).

Every HTTP request silentfrog issues *on behalf of a crawl* — the page
fetch, the link/canonical/hreflang/redirect probes, resource sizing,
discovery files, robots, sitemaps — opens its aiohttp session here. One
chokepoint lets H4 count requests per profile and H7 enforce TLS/SSRF
without revisiting each call site.

Out of scope, governed separately and NOT routed through here: external
SDK/API traffic (Google, Semrush, Brave, PageSpeed Insights) and
updater/bootstrap downloads — those carry their own auth and trust policy.

E1 only centralises session construction and adds the request-count hook;
it forwards each caller's current TLS posture verbatim so behaviour is
unchanged. H7 hardens the policy in this one place.
"""

from __future__ import annotations

import ssl as ssl_lib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import aiohttp  # type: ignore[import]  # aiohttp stubs missing


@dataclass
class RequestCounter:
    """Mutable tally of crawler-controlled requests within a scope."""

    count: int = 0


# Bound once at the top of a crawl scope. A ContextVar value is *copied* into
# each task asyncio.gather spawns, so we share one counter object by reference
# (children mutate it) rather than reassigning the var inside a child task,
# which would be invisible to the parent.
_active_counter: ContextVar[RequestCounter | None] = ContextVar("silentfrog_request_counter", default=None)


@contextmanager
def count_requests() -> Iterator[RequestCounter]:
    """Count crawler-controlled requests issued while the scope is active."""
    counter = RequestCounter()
    token = _active_counter.set(counter)
    try:
        yield counter
    finally:
        _active_counter.reset(token)


async def _on_request_start(_session: object, _ctx: object, _params: object) -> None:
    counter = _active_counter.get()
    if counter is not None:
        counter.count += 1


def _counting_trace() -> aiohttp.TraceConfig:
    trace = aiohttp.TraceConfig()
    trace.on_request_start.append(_on_request_start)
    return trace


def open_crawl_session(
    *,
    headers: dict[str, str] | None = None,
    ssl: ssl_lib.SSLContext | bool = True,
) -> aiohttp.ClientSession:
    """Open an instrumented aiohttp session for crawler-controlled fetches.

    ``ssl`` is forwarded verbatim to the connector to preserve the caller's
    current posture: ``True`` is aiohttp's default verified context (the
    historical default for sessions built without an explicit connector),
    ``False`` disables verification, or pass an explicit ``SSLContext``. H7
    will centralise the policy here.
    """
    connector = aiohttp.TCPConnector(ssl=ssl)
    return aiohttp.ClientSession(headers=headers, connector=connector, trace_configs=[_counting_trace()])


__all__ = ["RequestCounter", "count_requests", "open_crawl_session"]
