"""Adversarial SSRF corpus for crawler-controlled fetches (v2.0 H7 / PR-17).

The guard must refuse to connect a crawl to the operator's own network no
matter how the private address arrives: a literal-IP link, a hostname that
resolves to a private IP, a DNS-rebinding flip between resolutions, or a
redirect hop to a private host. It must keep connecting to public hosts and
must leave the hostname untouched so TLS/Host/SNI still target the real name.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import aiohttp  # type: ignore[reportMissingImports]
import pytest
from aiohttp import web  # type: ignore[reportMissingImports]

import silentfrog.ssrf as ssrf_mod
from silentfrog import seo_crawler, transport
from silentfrog.crawl_options import CrawlOptions
from silentfrog.ssrf import GuardedConnector, SsrfBlockedError, is_public_address

# Addresses a crawl must never be steered into. Covers IPv4/IPv6 loopback,
# RFC 1918 / ULA private, link-local (incl. the 169.254.169.254 cloud-metadata
# endpoint), the unspecified/broadcast/multicast/reserved ranges, and the
# IPv4-mapped-IPv6 smuggling form of each.
BLOCKED_ADDRESSES = [
    "127.0.0.1",
    "127.0.0.53",
    "0.0.0.0",
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.1.1",
    "169.254.169.254",
    "169.254.0.1",
    "::1",
    "::",
    "fe80::1",
    "fc00::1",
    "fd12:3456:789a::1",
    "::ffff:127.0.0.1",
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "224.0.0.1",
    "239.255.255.250",
    "240.0.0.1",
    "255.255.255.255",
]

# Globally-routable unicast addresses a crawl is allowed to reach.
PUBLIC_ADDRESSES = [
    "1.1.1.1",
    "8.8.8.8",
    "93.184.216.34",
    "2606:4700:4700::1111",
    "2001:4860:4860::8888",
]


class _FakeResolver:
    """Resolver that answers with a fixed address list (no real DNS)."""

    def __init__(self, addrs: list[str]) -> None:
        self._addrs = addrs

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict[str, Any]]:
        return [
            {"hostname": host, "host": addr, "port": port, "family": family, "proto": 0, "flags": 0}
            for addr in self._addrs
        ]

    async def close(self) -> None:
        return None


class _RebindResolver:
    """Public on the first resolution, private on the next — a DNS rebinding flip."""

    def __init__(self) -> None:
        self._calls = 0

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict[str, Any]]:
        self._calls += 1
        addr = "93.184.216.34" if self._calls == 1 else "127.0.0.1"
        return [{"hostname": host, "host": addr, "port": port, "family": family, "proto": 0, "flags": 0}]

    async def close(self) -> None:
        return None


# --- is_public_address: the classification corpus ----------------------------


@pytest.mark.parametrize("addr", BLOCKED_ADDRESSES)
def test_is_public_address_rejects_non_public(addr: str) -> None:
    assert is_public_address(addr) is False


@pytest.mark.parametrize("addr", PUBLIC_ADDRESSES)
def test_is_public_address_allows_public(addr: str) -> None:
    assert is_public_address(addr) is True


def test_is_public_address_rejects_non_ip_strings() -> None:
    # The guard only ever vets resolved/literal IPs; a bare hostname or junk
    # is never a public address.
    assert is_public_address("intranet.example.com") is False
    assert is_public_address("") is False


# --- GuardedConnector: vetting on every resolution ---------------------------


async def _resolve(connector: GuardedConnector, host: str, port: int = 80) -> list[dict[str, Any]]:
    try:
        return await connector._resolve_host(host, port)
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_connector_blocks_literal_private_ip_url() -> None:
    # Regression for the literal-IP gap: aiohttp short-circuits its resolver for
    # a literal-IP host, so a resolver-only guard would never see this. The
    # connector vets the short-circuit path too.
    with pytest.raises(SsrfBlockedError):
        await _resolve(GuardedConnector(), "127.0.0.1")


@pytest.mark.asyncio
async def test_connector_blocks_literal_metadata_ip_url() -> None:
    with pytest.raises(SsrfBlockedError):
        await _resolve(GuardedConnector(), "169.254.169.254")


@pytest.mark.asyncio
async def test_connector_allows_literal_public_ip_url() -> None:
    result = await _resolve(GuardedConnector(), "1.1.1.1")
    assert [addr["host"] for addr in result] == ["1.1.1.1"]


@pytest.mark.asyncio
async def test_connector_blocks_hostname_resolving_to_private() -> None:
    connector = GuardedConnector(resolver=_FakeResolver(["10.0.0.5"]), use_dns_cache=False)
    with pytest.raises(SsrfBlockedError):
        await _resolve(connector, "intranet.evil.test")


@pytest.mark.asyncio
async def test_connector_keeps_public_and_drops_private_when_mixed() -> None:
    # A DNS answer that mixes a public and a private IP must connect only to the
    # public one (and pin to it), never the private one.
    connector = GuardedConnector(resolver=_FakeResolver(["127.0.0.1", "93.184.216.34"]), use_dns_cache=False)
    result = await _resolve(connector, "mixed.evil.test")
    assert [addr["host"] for addr in result] == ["93.184.216.34"]


@pytest.mark.asyncio
async def test_connector_vets_every_resolution_defeating_rebinding() -> None:
    resolver = _RebindResolver()
    connector = GuardedConnector(resolver=resolver, use_dns_cache=False)
    try:
        first = await connector._resolve_host("rebind.evil.test", 80)
        assert all(is_public_address(addr["host"]) for addr in first)
        # The flip to a private IP on the next resolution is blocked: vetting is
        # re-run every time, so there is no resolve-then-connect rebinding window.
        with pytest.raises(SsrfBlockedError):
            await connector._resolve_host("rebind.evil.test", 80)
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_connector_preserves_hostname_and_pins_to_vetted_ip() -> None:
    # The guard filters by resolved IP but never rewrites the hostname, so
    # aiohttp connects to the vetted IP while Host/SNI/cert verification keep
    # using the real hostname.
    connector = GuardedConnector(resolver=_FakeResolver(["93.184.216.34"]), use_dns_cache=False)
    result = await _resolve(connector, "example.test", 443)
    assert result[0]["hostname"] == "example.test"
    assert result[0]["host"] == "93.184.216.34"


@pytest.mark.asyncio
async def test_allow_private_forwards_literal_and_resolved_private() -> None:
    # The intranet opt-in forwards resolution verbatim — literal and resolved
    # private addresses both pass.
    literal = await _resolve(GuardedConnector(allow_private=True), "127.0.0.1")
    assert literal[0]["host"] == "127.0.0.1"
    resolved = await _resolve(
        GuardedConnector(allow_private=True, resolver=_FakeResolver(["10.0.0.5"]), use_dns_cache=False),
        "intranet.local.test",
    )
    assert [addr["host"] for addr in resolved] == ["10.0.0.5"]


# --- End-to-end through the seam: redirects and the production opt-in ---------


@pytest.mark.asyncio
async def test_redirect_to_private_is_blocked_at_the_redirect_hop(aiohttp_server, monkeypatch) -> None:
    # Treat the loopback test server as public so the FIRST hop connects; the
    # real guard still vets the redirect target (an RFC 1918 literal IP).
    real_is_public = ssrf_mod.is_public_address
    monkeypatch.setattr(ssrf_mod, "is_public_address", lambda addr: addr == "127.0.0.1" or real_is_public(addr))

    async def _redirect(_request: web.Request) -> web.Response:
        raise web.HTTPFound("http://10.0.0.1/internal")

    app = web.Application()
    app.router.add_get("/", _redirect)
    server = await aiohttp_server(app)

    async with transport.open_crawl_session() as session:
        with pytest.raises(aiohttp.ClientError) as excinfo:
            async with session.get(str(server.make_url("/"))) as response:
                await response.read()
    assert isinstance(excinfo.value.__cause__, SsrfBlockedError)


@pytest.mark.asyncio
async def test_analyse_translates_allow_private_network_option(monkeypatch) -> None:
    # analyse() must turn CrawlOptions.allow_private_network into the seam's
    # scope so the connector it opens is guarded by default and relaxed only on
    # the explicit opt-in.
    seen: dict[str, bool] = {}

    async def fake_analyse(url: str, timeout: int, options: CrawlOptions) -> str:
        async with transport.open_crawl_session() as session:
            seen["allow_private"] = session.connector._allow_private  # type: ignore[attr-defined]
        return "payload"

    monkeypatch.setattr(seo_crawler, "_analyse", fake_analyse)

    await seo_crawler.analyse("http://example.test/", options=CrawlOptions.default())
    assert seen["allow_private"] is False

    opted_in = dataclasses.replace(CrawlOptions.default(), allow_private_network=True)
    await seo_crawler.analyse("http://example.test/", options=opted_in)
    assert seen["allow_private"] is True
