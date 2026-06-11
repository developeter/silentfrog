"""Unit tests for the v2.0 V1 fetcher strategy."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from silentfrog.fetchers import (
    FetchOptions,
    FetchRequest,
    FetchResult,
    FetchStrategy,
)
from silentfrog.fetchers.scrapling_backend import (
    ScraplingTlsBackend,
    _to_result,
)


@dataclass
class _StubBackend:
    """Backend that returns a canned result and records calls."""

    name: str
    result: FetchResult
    is_available: bool = True
    calls: int = 0

    def available(self) -> bool:
        return self.is_available

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        return self.result


def _ok(backend: str, status: int = 200) -> FetchResult:
    return FetchResult(body="<html>ok</html>", status=status, final_url="https://e.com/", backend=backend)


def _blocked(backend: str, status: int = 403) -> FetchResult:
    return FetchResult(body="", status=status, final_url="https://e.com/", backend=backend)


@pytest.mark.asyncio
async def test_strategy_returns_base_result_when_not_blocked() -> None:
    base = _StubBackend("aiohttp", _ok("aiohttp"))
    tls = _StubBackend("scrapling-tls", _ok("scrapling-tls"))
    strategy = FetchStrategy(FetchOptions(use_stealth=True), backends=[base, tls])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "aiohttp"
    assert tls.calls == 0  # never escalated — base was fine


@pytest.mark.asyncio
async def test_strategy_does_not_escalate_when_stealth_off() -> None:
    base = _StubBackend("aiohttp", _blocked("aiohttp"))
    tls = _StubBackend("scrapling-tls", _ok("scrapling-tls"))
    strategy = FetchStrategy(FetchOptions(use_stealth=False), backends=[base, tls])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "aiohttp"
    assert result.status == 403
    assert tls.calls == 0  # stealth off → never escalates


@pytest.mark.asyncio
async def test_strategy_escalates_on_block_and_returns_unblocked() -> None:
    base = _StubBackend("aiohttp", _blocked("aiohttp"))
    tls = _StubBackend("scrapling-tls", _ok("scrapling-tls"))
    strategy = FetchStrategy(FetchOptions(use_stealth=True), backends=[base, tls])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "scrapling-tls"
    assert result.status == 200
    assert tls.calls == 1


@pytest.mark.asyncio
async def test_strategy_escalates_through_to_stealth_when_tls_still_blocked() -> None:
    base = _StubBackend("aiohttp", _blocked("aiohttp"))
    tls = _StubBackend("scrapling-tls", _blocked("scrapling-tls"))
    stealth = _StubBackend("scrapling-stealth", _ok("scrapling-stealth"))
    strategy = FetchStrategy(FetchOptions(use_stealth=True), backends=[base, tls, stealth])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "scrapling-stealth"
    assert tls.calls == 1 and stealth.calls == 1


@pytest.mark.asyncio
async def test_strategy_skips_unavailable_backends() -> None:
    base = _StubBackend("aiohttp", _blocked("aiohttp"))
    tls = _StubBackend("scrapling-tls", _ok("scrapling-tls"), is_available=False)
    stealth = _StubBackend("scrapling-stealth", _ok("scrapling-stealth"))
    strategy = FetchStrategy(FetchOptions(use_stealth=True), backends=[base, tls, stealth])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "scrapling-stealth"
    assert tls.calls == 0  # unavailable, skipped


@pytest.mark.asyncio
async def test_strategy_returns_best_seen_when_nothing_unblocks() -> None:
    base = _StubBackend("aiohttp", _blocked("aiohttp", 403))
    tls = _StubBackend("scrapling-tls", _blocked("scrapling-tls", 503))
    strategy = FetchStrategy(FetchOptions(use_stealth=True), backends=[base, tls])
    result = await strategy.fetch(FetchRequest("https://e.com/"))
    # Best seen is the last escalation attempt.
    assert result.backend == "scrapling-tls"
    assert result.status == 503


def test_fetch_result_looks_blocked() -> None:
    assert FetchResult("", 403, "u").looks_blocked()
    assert FetchResult("", 0, "u").looks_blocked()
    assert not FetchResult("ok", 200, "u").looks_blocked()


def test_scrapling_to_result_reads_common_attributes() -> None:
    class _Resp:
        status = 200
        body = "<html>hi</html>"
        url = "https://final.com/"
        headers = {"Content-Type": "text/html"}

    result = _to_result(_Resp(), "scrapling-tls", "https://req.com/")
    assert result.status == 200
    assert "hi" in result.body
    assert result.final_url == "https://final.com/"
    assert result.headers["Content-Type"] == "text/html"


def test_scrapling_to_result_decodes_bytes_body_and_falls_back_url() -> None:
    class _Resp:
        status = 200
        body = b"<html>bytes</html>"
        # no url attribute → falls back to request url

    result = _to_result(_Resp(), "scrapling-tls", "https://req.com/")
    assert "bytes" in result.body
    assert result.final_url == "https://req.com/"


@pytest.mark.asyncio
async def test_scrapling_backend_uses_injected_fetcher() -> None:
    class _Resp:
        status = 200
        body = "<html>injected</html>"
        url = "https://e.com/"

    class _Fetcher:
        @staticmethod
        def get(url: str) -> _Resp:
            return _Resp()

    backend = ScraplingTlsBackend(fetcher=_Fetcher)
    assert backend.available() is True
    result = await backend.fetch(FetchRequest("https://e.com/"))
    assert result.backend == "scrapling-tls"
    assert "injected" in result.body


@pytest.mark.asyncio
async def test_scrapling_backend_degrades_on_exception() -> None:
    class _Boom:
        @staticmethod
        def get(url: str):
            raise RuntimeError("network down")

    backend = ScraplingTlsBackend(fetcher=_Boom)
    result = await backend.fetch(FetchRequest("https://e.com/"))
    assert result.status == 0
    assert "RuntimeError" in result.error
