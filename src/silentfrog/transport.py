"""Central transport seam for crawler-controlled URL fetches (v2.0 E1/H7).

Every HTTP request silentfrog issues *on behalf of a crawl* — the page
fetch, the link/canonical/hreflang/redirect probes, resource sizing,
discovery files, robots, sitemaps — opens its aiohttp session here. One
chokepoint lets H4 count requests per profile and H7 enforce TLS/SSRF
without revisiting each call site.

Out of scope, governed separately and NOT routed through here: external
SDK/API traffic (Google, Semrush, Brave, PageSpeed Insights) and
updater/bootstrap downloads — those carry their own auth and trust policy.

H7 TLS policy (PR-16): the seam verifies certificates against the certifi
CA bundle at OpenSSL security level >= 2 by default. Verification is
skipped only inside an explicit, off-by-default :func:`insecure_tls`
scope, which logs a visible warning so the insecure posture is never
silent. The scope is read at session-open time and fails *closed* (stays
verified) if it never propagates to a fetch.

H7 SSRF policy (PR-17): the seam connects through a :class:`GuardedConnector`
that vets every resolved/literal address and rejects non-public ones, so a
crawled link cannot reach loopback, intranet, link-local cloud-metadata, or
reserved hosts. The guard is on for every fetch by default and is relaxed
only inside an explicit, off-by-default :func:`allow_private_network` scope
(same read-at-open, fail-closed contract as :func:`insecure_tls`).
"""

from __future__ import annotations

import logging
import ssl as ssl_lib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import aiohttp  # type: ignore[import]  # aiohttp stubs missing
import certifi

from .ssrf import GuardedConnector

logger = logging.getLogger(__name__)


@dataclass
class RequestCounter:
    """Mutable tally of crawler-controlled requests within a scope."""

    count: int = 0


# Bound once at the top of a crawl scope. A ContextVar value is *copied* into
# each task asyncio.gather spawns, so we share one counter object by reference
# (children mutate it) rather than reassigning the var inside a child task,
# which would be invisible to the parent.
_active_counter: ContextVar[RequestCounter | None] = ContextVar("silentfrog_request_counter", default=None)

# Crawl-scoped TLS posture. Default False = verify. A ContextVar (not a flag
# threaded through every fetch) so the standalone probe helpers inherit the
# crawl's choice across asyncio.gather, and so a fetch that runs outside the
# scope fails closed (verified).
_insecure_tls: ContextVar[bool] = ContextVar("silentfrog_insecure_tls", default=False)

# Crawl-scoped SSRF posture. Default False = vet every address (guard on). Same
# ContextVar contract as the TLS posture: probe helpers inherit the crawl's
# choice across asyncio.gather, and a fetch outside any scope fails closed
# (guarded).
_allow_private_network: ContextVar[bool] = ContextVar("silentfrog_allow_private_network", default=False)


@contextmanager
def count_requests() -> Iterator[RequestCounter]:
    """Count crawler-controlled requests issued while the scope is active."""
    counter = RequestCounter()
    token = _active_counter.set(counter)
    try:
        yield counter
    finally:
        _active_counter.reset(token)


@contextmanager
def insecure_tls(*, enabled: bool = True) -> Iterator[None]:
    """Disable TLS verification for crawler fetches in this scope (H7 opt-in).

    Off by default and explicit: a crawl enters this scope only when the
    operator has chosen to trust self-signed / intranet targets. Entering it
    emits a visible warning so the insecure posture is never silent.
    ``enabled=False`` is a no-op, letting callers forward an opt-in flag
    without branching.
    """
    if not enabled:
        yield
        return
    logger.warning(
        "TLS certificate verification is DISABLED for this crawl scope "
        "(insecure opt-in). Use only for trusted self-signed / intranet hosts."
    )
    token = _insecure_tls.set(True)
    try:
        yield
    finally:
        _insecure_tls.reset(token)


@contextmanager
def allow_private_network(*, enabled: bool = True) -> Iterator[None]:
    """Relax the SSRF guard for crawler fetches in this scope (H7 opt-in).

    Off by default and explicit: a crawl enters this scope only when the
    operator has chosen to audit trusted intranet / loopback targets.
    Entering it emits a visible warning so the relaxed posture is never
    silent. ``enabled=False`` is a no-op, letting callers forward an opt-in
    flag without branching.
    """
    if not enabled:
        yield
        return
    logger.warning(
        "SSRF protection is DISABLED for this crawl scope (private-network "
        "opt-in). Crawled links may reach loopback / intranet hosts. Use only "
        "for hosts you control and trust."
    )
    token = _allow_private_network.set(True)
    try:
        yield
    finally:
        _allow_private_network.reset(token)


def secure_ssl_context() -> ssl_lib.SSLContext:
    """Verified TLS context for crawler fetches.

    certifi CA bundle, hostname checking, certificate required, and OpenSSL
    security level >= 2 (rejects weak ciphers, SHA-1 signatures, and RSA/DH
    keys below 2048 bits). This is the default for every crawl fetch.
    """
    ctx = ssl_lib.create_default_context(cafile=certifi.where())
    ctx.set_ciphers("DEFAULT:@SECLEVEL=2")
    return ctx


async def _on_request_start(_session: object, _ctx: object, _params: object) -> None:
    counter = _active_counter.get()
    if counter is not None:
        counter.count += 1


def _counting_trace() -> aiohttp.TraceConfig:
    trace = aiohttp.TraceConfig()
    trace.on_request_start.append(_on_request_start)
    return trace


def open_crawl_session(*, headers: dict[str, str] | None = None) -> aiohttp.ClientSession:
    """Open an instrumented aiohttp session for crawler-controlled fetches.

    TLS is verified against the certifi CA bundle at OpenSSL SECLEVEL>=2.
    Verification is skipped only inside an active :func:`insecure_tls` scope
    (explicit per-crawl opt-in, off by default). The connector vets every
    address for SSRF, rejecting non-public hosts unless an active
    :func:`allow_private_network` scope opts in (also off by default).
    """
    ssl_ctx: ssl_lib.SSLContext | bool = False if _insecure_tls.get() else secure_ssl_context()
    connector = GuardedConnector(ssl=ssl_ctx, allow_private=_allow_private_network.get())
    return aiohttp.ClientSession(headers=headers, connector=connector, trace_configs=[_counting_trace()])


__all__ = [
    "RequestCounter",
    "allow_private_network",
    "count_requests",
    "insecure_tls",
    "open_crawl_session",
    "secure_ssl_context",
]
