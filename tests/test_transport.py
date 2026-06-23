"""Unit tests for the crawler-controlled transport seam (v2.0 E1/H7)."""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path

import pytest
from aiohttp import web  # type: ignore[reportMissingImports]

import silentfrog
from silentfrog.transport import (
    count_requests,
    insecure_tls,
    open_crawl_session,
    secure_ssl_context,
)


@pytest.fixture
async def ok_server(aiohttp_server):
    """A localhost server that answers GET/HEAD on / with 200."""

    async def _ok(_request):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", _ok)  # allow_head=True also answers HEAD
    server = await aiohttp_server(app)
    return str(server.make_url("/"))


async def _hit(session, url: str) -> int:
    async with session.get(url) as response:
        await response.read()
        return response.status


@pytest.mark.asyncio
async def test_seam_counts_every_request_across_fanout(ok_server) -> None:
    # The per-page probes fan out with asyncio.gather; the counter must see
    # every request even though each runs in its own gathered task.
    with count_requests() as counter:
        async with open_crawl_session() as session:
            statuses = await asyncio.gather(*(_hit(session, ok_server) for _ in range(5)))
    assert statuses == [200, 200, 200, 200, 200]
    assert counter.count == 5


@pytest.mark.asyncio
async def test_seam_counts_only_within_its_scope(ok_server) -> None:
    async with open_crawl_session() as session:
        assert await _hit(session, ok_server) == 200  # no active scope -> not counted
    with count_requests() as counter:
        async with open_crawl_session() as session:
            await _hit(session, ok_server)
    assert counter.count == 1


def test_secure_ssl_context_verifies_against_certifi_at_seclevel_2() -> None:
    # F9/H7 (PR-16): the seam's default context must require + verify certs
    # (no ssl=False default) and load the certifi bundle.
    ctx = secure_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.get_ca_certs(), "certifi CA bundle must be loaded"


@pytest.mark.asyncio
async def test_seam_verifies_tls_by_default() -> None:
    # Reintroducing ssl=False as the seam default would flip _ssl to False.
    async with open_crawl_session() as session:
        ssl_param = session.connector._ssl
    assert isinstance(ssl_param, ssl.SSLContext)
    assert ssl_param.verify_mode == ssl.CERT_REQUIRED
    assert ssl_param.check_hostname is True


@pytest.mark.asyncio
async def test_insecure_tls_is_an_explicit_off_by_default_opt_in(ok_server) -> None:
    # Default posture: a verified context, never False.
    async with open_crawl_session() as default_session:
        assert default_session.connector._ssl is not False
    # Explicit opt-in scope: verification disabled, and fetches still work.
    with count_requests() as counter, insecure_tls():
        async with open_crawl_session() as insecure_session:
            assert insecure_session.connector._ssl is False
            assert await _hit(insecure_session, ok_server) == 200
    assert counter.count == 1
    # Leaving the scope restores verification (the control fails closed).
    async with open_crawl_session() as restored_session:
        assert restored_session.connector._ssl is not False


@pytest.mark.asyncio
async def test_insecure_tls_disabled_flag_is_a_noop() -> None:
    # enabled=False lets a caller forward an opt-in flag without branching;
    # the crawl posture must stay verified.
    with insecure_tls(enabled=False):
        async with open_crawl_session() as session:
            assert session.connector._ssl is not False


def test_no_seclevel_1_downgrade_anywhere_in_crawler_source() -> None:
    # F9 regression guard: SECLEVEL=1 (the old http_client default) re-opens
    # the TLS downgrade hole. The seam pins SECLEVEL=2; nothing may pin it to 1.
    pkg_dir = Path(silentfrog.__file__).resolve().parent
    offenders = sorted(p.name for p in pkg_dir.rglob("*.py") if "SECLEVEL=1" in p.read_text(encoding="utf-8"))
    assert offenders == []
    assert "@SECLEVEL=2" in (pkg_dir / "transport.py").read_text(encoding="utf-8")
