"""Adversarial tests for v2.0 V17 (Semrush) — budget non-bypass, per-domain
caching, CSV robustness, §1.5, and the stock-audit-no-call guarantee."""

from __future__ import annotations

import asyncio

from silentfrog.integrations.semrush.client import (
    _build_metrics,
    _parse_csv,
    fetch_domain_overview,
)
from silentfrog.integrations.semrush.client import test_connection as run_test_connection
from silentfrog.integrations.semrush.types import SemrushMetrics


class _Resp:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body
        self.status = status

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def text(self) -> str:
        return self._body


class _CountingSession:
    """aiohttp-shaped stub that counts GETs so we can prove the budget is
    never exceeded and the cache prevents repeat network calls."""

    def __init__(self, body: str = "", status: int = 200) -> None:
        self._body = body
        self._status = status
        self.calls = 0

    def get(self, url: str, **_: object) -> _Resp:
        self.calls += 1
        return _Resp(self._body, self._status)

    async def close(self) -> None:
        return None


def test_budget_blocks_when_fewer_than_two_calls_remain(monkeypatch, tmp_path) -> None:
    # A full overview needs 2 metered calls; with only 1 in budget it must
    # make ZERO calls (no partial spend, no overrun).
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _CountingSession(body="Or;Ot\n5;500")
    result = asyncio.run(fetch_domain_overview("example.com", "key", max_calls=1, session=session))
    assert result.measured is False
    assert session.calls == 0


def test_budget_allows_exactly_two_then_exhausts(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.integrations.semrush import budget

    session = _CountingSession(body="Or;Ot;Ad;At\n10;2000;3;40")
    result = asyncio.run(fetch_domain_overview("example.com", "key", max_calls=2, session=session))
    assert result.measured is True
    assert session.calls == 2
    assert budget.remaining(2) == 0
    # A different domain now has no budget left -> no calls at all.
    session2 = _CountingSession(body="Or;Ot\n1;1")
    second = asyncio.run(fetch_domain_overview("other.com", "key", max_calls=2, session=session2))
    assert second.measured is False
    assert session2.calls == 0


def test_same_domain_second_call_served_from_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _CountingSession(body="Or;Ot\n10;2000")
    first = asyncio.run(fetch_domain_overview("example.com", "key", max_calls=100, session=session))
    assert first.measured is True
    after_first = session.calls
    second = asyncio.run(fetch_domain_overview("example.com", "key", max_calls=100, session=session))
    assert second == first
    assert session.calls == after_first  # no new network call


def test_empty_key_makes_no_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    session = _CountingSession(body="Or;Ot\n1;1")
    result = asyncio.run(fetch_domain_overview("example.com", "", max_calls=100, session=session))
    assert result.measured is False
    assert session.calls == 0


def test_parse_csv_edge_cases() -> None:
    assert _parse_csv("") == []
    assert _parse_csv("ERROR :: API key invalid") == []
    assert _parse_csv("a;b;c") == []  # header only -> no data rows
    assert _parse_csv("a;b;c\n1;2") == [{"a": "1", "b": "2", "c": ""}]  # ragged short
    assert _parse_csv("a;b\r\n1;2\r\n") == [{"a": "1", "b": "2"}]  # CRLF + trailing newline
    assert _parse_csv("a;b\n1;2;3") == [{"a": "1", "b": "2"}]  # extra cells ignored


def test_build_metrics_accepts_short_and_display_columns() -> None:
    short = _build_metrics(
        {"Or": "10", "Ot": "2000", "Ad": "3", "At": "40"},
        {"ascore": "55", "total": "900", "domains_num": "120"},
    )
    display = _build_metrics(
        {"Organic Keywords": "10", "Organic Traffic": "2000", "Adwords Keywords": "3", "Adwords Traffic": "40"},
        {"Authority Score": "55", "Total Backlinks": "900", "Referring Domains": "120"},
    )
    assert short == display
    assert short.domain_authority == 55
    assert short.organic_keywords == 10
    assert short.referring_domains == 120


def test_measured_authority_checks_never_warn_or_critical() -> None:
    from silentfrog.integrations.semrush.checks import build_semrush_authority_checks

    weak = SemrushMetrics(measured=True)  # all-zero but measured
    weak_checks = build_semrush_authority_checks(weak)
    assert len(weak_checks) == 6
    for check in weak_checks:
        assert check.status in {"good", "info"}
        assert check.area == "Authority signals"
    strong = SemrushMetrics(
        domain_authority=80,
        organic_keywords=5000,
        organic_traffic=100000,
        backlinks_total=50000,
        referring_domains=3000,
        paid_keywords=200,
        paid_traffic=4000,
        measured=True,
    )
    assert all(check.status == "good" for check in build_semrush_authority_checks(strong))


def test_collect_semrush_skips_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("SILENTFROG_SEMRUSH_ENABLE", raising=False)
    from silentfrog import seo_crawler

    assert asyncio.run(seo_crawler._collect_semrush("https://example.com/page")) == {}


def test_collect_semrush_skips_without_key(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_SEMRUSH_ENABLE", "1")
    from silentfrog import seo_crawler
    from silentfrog.integrations.semrush import client

    monkeypatch.setattr(client, "resolve_api_key", lambda: "")
    assert asyncio.run(seo_crawler._collect_semrush("https://example.com/page")) == {}


def test_registrable_domain_handles_multipart_tld() -> None:
    from silentfrog.seo_crawler import _registrable_domain

    assert _registrable_domain("https://www.sub.example.co.uk/path?x=1") == "example.co.uk"
    assert _registrable_domain("https://example.com") == "example.com"


def test_connection_empty_key_returns_false_without_network() -> None:
    ok, message = asyncio.run(run_test_connection(""))
    assert ok is False
    assert message
