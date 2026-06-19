"""Unit tests for the crawler-controlled transport seam (v2.0 E1)."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web  # type: ignore[reportMissingImports]

from silentfrog.transport import count_requests, open_crawl_session


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


@pytest.mark.asyncio
async def test_seam_forwards_insecure_posture(ok_server) -> None:
    # ssl=False is preserved verbatim (H7 hardens later); the session still works.
    with count_requests() as counter:
        async with open_crawl_session(ssl=False) as session:
            assert await _hit(session, ok_server) == 200
    assert counter.count == 1
