from __future__ import annotations

from typing import Any

import pytest

import silentfrog.perf_crux as perf_crux
from silentfrog.perf_crux import CruxData, _parse_psi_response, fetch_crux


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def json(self, content_type: Any = None) -> Any:
        return self._body


class _DummySession:
    def __init__(self, status: int = 200, body: Any | None = None, raises: type[Exception] | None = None):
        self._status = status
        self._body = body or {}
        self._raises = raises

    async def __aenter__(self) -> _DummySession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, **_: Any) -> _Resp:
        if self._raises is not None:
            raise self._raises("simulated")
        return _Resp(self._status, self._body)

    async def close(self) -> None:
        return None


def test_parse_psi_response_returns_field_data() -> None:
    body = {
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2200},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},  # CrUX scales CLS *100
            }
        }
    }
    data = _parse_psi_response(body)
    assert data.has_field_data is True
    assert data.lcp_p75_ms == 2200
    assert data.inp_p75_ms == 180
    assert data.cls_p75 == 0.05  # CLS rescaled


def test_parse_psi_response_handles_missing_loading_experience() -> None:
    data = _parse_psi_response({"foo": "bar"})
    assert data.has_field_data is False
    assert "loadingExperience" in data.reason


@pytest.mark.asyncio
async def test_fetch_crux_returns_field_data_on_200(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(perf_crux, "_cache_dir", lambda: tmp_path / "cache")
    body = {
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1500},
                "INTERACTION_TO_NEXT_PAINT": {"percentile": 120},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 3},
            }
        }
    }
    session = _DummySession(status=200, body=body)
    data = await fetch_crux("https://example.com/", session=session)
    assert data.has_field_data is True
    assert data.lcp_p75_ms == 1500


@pytest.mark.asyncio
async def test_fetch_crux_uses_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(perf_crux, "_cache_dir", lambda: tmp_path / "cache")
    session1 = _DummySession(
        status=200,
        body={"loadingExperience": {"metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 1500}}}},
    )
    first = await fetch_crux("https://example.com/", session=session1)
    assert first.has_field_data is True

    # Replace session with one that would fail; cache hit means it's never called.
    session2 = _DummySession(raises=RuntimeError)
    second = await fetch_crux("https://example.com/", session=session2)
    assert second == first


@pytest.mark.asyncio
async def test_fetch_crux_handles_429(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(perf_crux, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession(status=429, body={})
    data = await fetch_crux("https://rate-limited.example/", session=session)
    assert data.has_field_data is False
    assert "rate-limited" in data.reason


@pytest.mark.asyncio
async def test_fetch_crux_handles_network_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(perf_crux, "_cache_dir", lambda: tmp_path / "cache")
    session = _DummySession(raises=ConnectionError)
    data = await fetch_crux("https://flaky.example/", session=session)
    assert data.has_field_data is False
    assert "PSI request failed" in data.reason


@pytest.mark.asyncio
async def test_fetch_crux_rejects_non_http_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(perf_crux, "_cache_dir", lambda: tmp_path / "cache")
    data = await fetch_crux("not-a-url")
    assert data.has_field_data is False
    assert "absolute" in data.reason


def test_crux_data_roundtrips_through_dict() -> None:
    original = CruxData(lcp_p75_ms=1800, inp_p75_ms=200, cls_p75=0.08, has_field_data=True)
    restored = CruxData.from_raw(original.to_dict())
    assert restored == original
