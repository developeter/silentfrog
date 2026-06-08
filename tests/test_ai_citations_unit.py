from __future__ import annotations

from typing import Any

import pytest

import silentfrog.ai_citations as ai_citations
from silentfrog.ai_citations import (
    AiCitationsPayload,
    build_ai_citations_checks,
    fetch_ai_citations,
)


class _Resp:
    def __init__(self, status: int, body: Any = None, text: str = "") -> None:
        self.status = status
        self._body = body
        self._text = text

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self, content_type: Any = None) -> Any:
        return self._body

    async def text(self) -> str:
        return self._text


class _DummySession:
    """Route by URL substring → response factory."""

    def __init__(self, routes: dict[str, _Resp]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    async def __aenter__(self) -> _DummySession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, **_: Any) -> _Resp:
        self.calls.append(url)
        for key, resp in self._routes.items():
            if key in url:
                return resp
        return _Resp(404, body={}, text="")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_fetch_disabled_without_env_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("SILENTFROG_AI_CITATIONS_ENABLE", raising=False)
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    payload = await fetch_ai_citations("https://example.com/")
    assert payload.measured is False
    assert "SILENTFROG_AI_CITATIONS_ENABLE" in payload.reason


@pytest.mark.asyncio
async def test_fetch_rejects_non_http_url(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_AI_CITATIONS_ENABLE", "1")
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    payload = await fetch_ai_citations("not-a-url")
    assert payload.measured is False
    assert "absolute" in payload.reason


@pytest.mark.asyncio
async def test_fetch_brave_indexed_path(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_AI_CITATIONS_ENABLE", "1")
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession(
        {
            "brave.com": _Resp(
                200,
                body={
                    "web": {
                        "results": [
                            {"title": "Example", "url": "https://example.com/page"},
                        ]
                    },
                    "summarizer": {"summary": "example.com is awesome"},
                },
            ),
            "commoncrawl": _Resp(200, text="{}\n{}\n{}"),
        }
    )
    payload = await fetch_ai_citations("https://example.com/page", brave_api_key="key", session=session)
    assert payload.brave_indexed is True
    assert payload.brave_summary_mentions >= 1
    assert payload.common_crawl_references == 3
    assert payload.measured is True


@pytest.mark.asyncio
async def test_fetch_handles_brave_rate_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_AI_CITATIONS_ENABLE", "1")
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession(
        {
            "brave.com": _Resp(429, body={}),
            "commoncrawl": _Resp(200, text=""),
        }
    )
    payload = await fetch_ai_citations("https://example.com/page", brave_api_key="key", session=session)
    assert payload.brave_indexed is False
    assert "rate-limited" in payload.reason


@pytest.mark.asyncio
async def test_fetch_common_crawl_only_when_no_brave_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_AI_CITATIONS_ENABLE", "1")
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession({"commoncrawl": _Resp(200, text="{}\n{}\n")})
    payload = await fetch_ai_citations("https://example.com/page", brave_api_key=None, session=session)
    assert payload.brave_indexed is False
    assert "no API key" in payload.reason
    assert payload.common_crawl_references == 2
    assert payload.measured is True


@pytest.mark.asyncio
async def test_fetch_uses_cache_on_second_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_AI_CITATIONS_ENABLE", "1")
    monkeypatch.setattr(ai_citations, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession({"commoncrawl": _Resp(200, text="{}\n")})
    first = await fetch_ai_citations("https://example.com/", session=session)
    second = await fetch_ai_citations(
        "https://example.com/",
        session=_DummySession({}),  # would 404, but cache hits
    )
    assert first == second


def test_build_checks_routes_to_ai_citations_area() -> None:
    payload = AiCitationsPayload(
        brave_indexed=True,
        brave_summary_mentions=2,
        common_crawl_references=5,
        perplexity_likely_indexed=True,
        measured=True,
    )
    rows = build_ai_citations_checks(payload)
    assert {r.area for r in rows} == {"AI Citations"}
    assert {r.key for r in rows} == {
        "ai_citations_brave",
        "ai_citations_common_crawl",
        "ai_citations_perplexity",
    }
    assert all(r.status == "good" for r in rows)


def test_build_checks_not_measured_returns_info_rows() -> None:
    payload = AiCitationsPayload.empty("disabled")
    rows = build_ai_citations_checks(payload)
    assert all(r.status == "info" for r in rows)
    assert all("not measured" in r.details.lower() for r in rows)


def test_ai_citations_payload_roundtrips_through_dict() -> None:
    payload = AiCitationsPayload(
        brave_indexed=True,
        brave_summary_mentions=1,
        common_crawl_references=2,
        perplexity_likely_indexed=True,
        measured=True,
        reason="",
    )
    restored = AiCitationsPayload.from_raw(payload.to_dict())
    assert restored == payload
