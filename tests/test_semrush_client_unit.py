"""Unit tests for the v2.0 V17 Semrush client (stubbed, no real network)."""

from __future__ import annotations

from typing import Any

import pytest

from silentfrog.integrations.semrush.client import (
    _parse_csv,
    fetch_domain_overview,
)
from silentfrog.integrations.semrush.client import (
    test_connection as run_test_connection,  # aliased: pytest would collect a `test_` name
)

_DOMAIN_RANKS_BODY = (
    "Database;Domain;Rank;Organic Keywords;Organic Traffic;Organic Cost;Adwords Keywords;Adwords Traffic;Adwords Cost\n"
    "us;example.com;42;1500;52000;12000;30;800;500"
)
_BACKLINKS_BODY = "Authority Score;Total Backlinks;Referring Domains\n55;120000;3400"


class _Resp:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def text(self) -> str:
        return self._body


class _DummySession:
    """Returns successive bodies per GET call (domain_ranks, then backlinks)."""

    def __init__(
        self,
        bodies: list[str] | None = None,
        status: int = 200,
        raises: type[Exception] | None = None,
    ) -> None:
        self._bodies = list(bodies or [])
        self._status = status
        self._raises = raises
        self.calls = 0

    async def __aenter__(self) -> _DummySession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def get(self, url: str, **_: Any) -> _Resp:
        if self._raises is not None:
            raise self._raises("simulated")
        self.calls += 1
        body = self._bodies.pop(0) if self._bodies else ""
        return _Resp(self._status, body)

    async def close(self) -> None:
        return None


# --- _parse_csv ------------------------------------------------------------


def test_parse_csv_happy_path() -> None:
    rows = _parse_csv("a;b;c\n1;2;3")
    assert rows == [{"a": "1", "b": "2", "c": "3"}]


def test_parse_csv_ragged_row_pads_missing_cells() -> None:
    rows = _parse_csv("a;b;c\n1;2")
    assert rows == [{"a": "1", "b": "2", "c": ""}]


def test_parse_csv_error_line_returns_empty() -> None:
    assert _parse_csv("ERROR :: API key invalid") == []


def test_parse_csv_empty_returns_empty() -> None:
    assert _parse_csv("") == []
    assert _parse_csv("headers;only") == []  # only a header, no data row


# --- fetch_domain_overview -------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_domain_overview_parses_metrics(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(bodies=[_DOMAIN_RANKS_BODY, _BACKLINKS_BODY])
    metrics = await fetch_domain_overview("example.com", "KEY", max_calls=100, session=session)
    assert metrics.measured is True
    assert metrics.organic_keywords == 1500
    assert metrics.organic_traffic == 52000
    assert metrics.paid_keywords == 30
    assert metrics.paid_traffic == 800
    assert metrics.domain_authority == 55
    assert metrics.backlinks_total == 120000
    assert metrics.referring_domains == 3400
    assert session.calls == 2


@pytest.mark.asyncio
async def test_fetch_domain_overview_http_error_is_unmeasured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(status=403, bodies=["", ""])
    metrics = await fetch_domain_overview("example.com", "KEY", max_calls=100, session=session)
    assert metrics.measured is False


@pytest.mark.asyncio
async def test_fetch_domain_overview_cache_hit_avoids_second_network_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session1 = _DummySession(bodies=[_DOMAIN_RANKS_BODY, _BACKLINKS_BODY])
    first = await fetch_domain_overview("example.com", "KEY", max_calls=100, session=session1)
    assert first.measured is True

    # A session that would explode if touched proves the cache short-circuits.
    session2 = _DummySession(raises=RuntimeError)
    second = await fetch_domain_overview("example.com", "KEY", max_calls=100, session=session2)
    assert second == first
    assert session2.calls == 0


@pytest.mark.asyncio
async def test_fetch_domain_overview_budget_exhausted_makes_no_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(bodies=[_DOMAIN_RANKS_BODY, _BACKLINKS_BODY])
    metrics = await fetch_domain_overview("example.com", "KEY", max_calls=0, session=session)
    assert metrics.measured is False
    assert session.calls == 0


@pytest.mark.asyncio
async def test_fetch_domain_overview_empty_key_is_unmeasured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(bodies=[_DOMAIN_RANKS_BODY, _BACKLINKS_BODY])
    metrics = await fetch_domain_overview("example.com", "", max_calls=100, session=session)
    assert metrics.measured is False
    assert session.calls == 0


# --- test_connection -------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_happy(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(bodies=[_DOMAIN_RANKS_BODY])
    ok, message = await run_test_connection("KEY", session=session)
    assert ok is True
    assert "OK" in message


@pytest.mark.asyncio
async def test_test_connection_error_body(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(bodies=["ERROR :: NOTHING FOUND"])
    ok, message = await run_test_connection("KEY", session=session)
    assert ok is False
    assert message.startswith("ERROR ::")


@pytest.mark.asyncio
async def test_test_connection_network_exception(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _DummySession(raises=ConnectionError)
    ok, _message = await run_test_connection("KEY", session=session)
    assert ok is False


@pytest.mark.asyncio
async def test_test_connection_empty_key() -> None:
    ok, _message = await run_test_connection("")
    assert ok is False


# --- PR-G2: INT-5 / INT-7 / INT-9 -----------------------------------------


def _csv_server_app(web, posts: list[str]):
    """A fake Semrush endpoint that counts real requests and answers slowly
    enough that concurrent callers overlap."""
    import asyncio

    async def handler(request):
        posts.append(request.query.get("type", ""))
        await asyncio.sleep(0.05)
        body = _DOMAIN_RANKS_BODY if request.query.get("type") == "domain_ranks" else _BACKLINKS_BODY
        return web.Response(text=body)

    app = web.Application()
    app.router.add_get("/", handler)
    return app


@pytest.mark.asyncio
async def test_concurrent_overviews_for_one_domain_spend_two_calls(aiohttp_server, monkeypatch, tmp_path) -> None:
    import asyncio

    from aiohttp import web

    from silentfrog.integrations.semrush import client

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    posts: list[str] = []
    server = await aiohttp_server(_csv_server_app(web, posts))
    monkeypatch.setattr(client, "_BASE_URL", str(server.make_url("/")))

    results = await asyncio.gather(*[fetch_domain_overview("example.com", "KEY", max_calls=100) for _ in range(4)])

    assert all(result.measured for result in results)
    assert sorted(posts) == ["backlinks_overview", "domain_ranks"]


@pytest.mark.asyncio
async def test_error_body_with_a_numeric_code_is_reported_by_message(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    body = "ERROR 120 :: WRONG KEY - ID PAIR"
    ok, message = await run_test_connection("KEY", session=_DummySession(bodies=[body]))
    assert ok is False
    assert "WRONG KEY" in message

    metrics = await fetch_domain_overview("example.com", "KEY", 100, session=_DummySession(bodies=[body, body]))
    assert metrics.measured is False and metrics.enabled is True
    assert "WRONG KEY" in metrics.reason
    assert _parse_csv(body) == []


@pytest.mark.asyncio
async def test_connection_test_refuses_once_the_daily_budget_is_spent(monkeypatch, tmp_path) -> None:
    from silentfrog.integrations.semrush.budget import record_call

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    record_call()
    session = _DummySession(bodies=[_DOMAIN_RANKS_BODY])

    ok, message = await run_test_connection("KEY", session=session, max_calls=1)

    assert ok is False and "cap" in message
    assert session.calls == 0
    ok, _ = await run_test_connection("KEY", session=session, max_calls=2)
    assert ok is True and session.calls == 1


@pytest.mark.asyncio
async def test_budget_exhausted_overview_says_why(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    metrics = await fetch_domain_overview("example.com", "KEY", max_calls=1, session=_DummySession())
    assert metrics.measured is False and "cap" in metrics.reason
