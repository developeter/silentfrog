"""SSRF guard for crawler-controlled fetches (v2.0 H7 / PR-17).

A crawl follows URLs it does not control — links, canonical / hreflang
targets, redirect hops, resource and image sources, discovery files and
sitemaps. Any of them can point back at the operator's own network:
loopback services, RFC 1918 / ULA intranet hosts, the 169.254.169.254
link-local cloud-metadata endpoint, or reserved ranges. Fetching those on
the operator's behalf is server-side request forgery.

The guard plugs into the transport seam as the aiohttp connector. It vets
every address aiohttp is about to connect to and hands it only public ones,
so the IP it connects to *is* the IP that was vetted — there is no
re-resolution window for DNS rebinding to flip the target to a private
host. The original hostname is left untouched, so the Host header, TLS SNI,
and certificate verification still use the real hostname (aiohttp connects
to the resolved IP but verifies the cert against ``req.url.raw_host``).
aiohttp resolves through the connector on every redirect hop, so each hop
is vetted too.

Vetting lives in the connector rather than a custom resolver on purpose: a
resolver only sees hostnames that need DNS, but aiohttp short-circuits the
resolver entirely for a URL whose host is already a literal IP
(``connector.py`` ``_resolve_host``). Overriding ``_resolve_host`` vets the
literal-IP path *and* the DNS path through one chokepoint, so a
``http://127.0.0.1/`` or ``http://169.254.169.254/`` link cannot slip past.

Fails closed: when nothing public remains, resolution raises and the fetch
fails like an unreachable host. The ``allow_private`` opt-in (off by
default, set at the seam from ``CrawlOptions``) skips vetting for operators
auditing trusted intranet hosts.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from typing import Any

import aiohttp  # type: ignore[import]
from aiohttp.abc import ResolveResult  # type: ignore[import]


class SsrfBlockedError(OSError):
    """Raised when a crawler fetch resolves only to non-public addresses.

    Subclasses ``OSError`` so aiohttp surfaces it as a connection failure
    that the seam's callers already handle (the target is treated as
    unreachable) instead of crashing the crawl.
    """


def is_public_address(raw: str) -> bool:
    """True only for a globally-routable unicast IP.

    Rejects loopback, RFC 1918 / ULA private, link-local (including the
    169.254.169.254 cloud-metadata endpoint), multicast, reserved, and the
    unspecified address, for both IPv4 and IPv6 — resolving an IPv4-mapped
    IPv6 address to its embedded IPv4 first so ``::ffff:127.0.0.1`` cannot
    smuggle loopback past the check.
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


class GuardedConnector(aiohttp.TCPConnector):
    """aiohttp connector that vets every address before connecting (SSRF guard).

    ``allow_private=True`` forwards aiohttp's resolution verbatim — the
    intranet opt-in, set at the seam from ``CrawlOptions``.
    """

    def __init__(self, *, allow_private: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._allow_private = allow_private

    async def _resolve_host(self, host: str, port: int, traces: Sequence[Any] | None = None) -> list[ResolveResult]:
        # Vet the addresses aiohttp resolved (DNS) *or* short-circuited (a
        # literal-IP host), on this hop and on every redirect, so a public
        # name that rebinds to a private IP and a literal-IP URL are both
        # caught. The kept addresses are exactly what aiohttp connects to.
        resolved = await super()._resolve_host(host, port, traces=traces)
        if self._allow_private:
            return resolved
        vetted = [addr for addr in resolved if is_public_address(addr["host"])]
        if not vetted:
            raise SsrfBlockedError(f"SSRF guard blocked non-public address for host {host!r}")
        return vetted


__all__ = ["GuardedConnector", "SsrfBlockedError", "is_public_address"]
