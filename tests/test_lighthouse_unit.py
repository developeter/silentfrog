"""Unit tests for v2.0 V14 Lighthouse (PSI) score parsing + fetch."""

from __future__ import annotations

import asyncio

from silentfrog.integrations.google import lighthouse as lh
from silentfrog.integrations.google.lighthouse import LighthouseScores, fetch_lighthouse
from silentfrog.workers import run_lighthouse


def test_run_lighthouse_routes_unmeasured_to_on_error(monkeypatch) -> None:
    """Regression: a PSI failure (e.g. anonymous-quota HTTP 429) used to reach
    on_success as an unmeasured dict — the GUI repainted with nothing and the
    user saw a silent no-op instead of the warning dialog."""

    async def _unmeasured(url: str, api_key: str = "") -> LighthouseScores:
        return LighthouseScores(measured=False)

    monkeypatch.setattr("silentfrog.integrations.google.lighthouse.fetch_lighthouse", _unmeasured)
    outcomes: list[tuple[str, str]] = []
    thread = run_lighthouse(
        "https://example.com",
        "",
        on_success=lambda data: outcomes.append(("success", str(data))),
        on_error=lambda message: outcomes.append(("error", message)),
    )
    thread.join(timeout=10)
    assert [kind for kind, _ in outcomes] == ["error"]
    assert "SILENTFROG_PSI_API_KEY" in outcomes[0][1]


def test_parse_full_lighthouse_result() -> None:
    raw = {
        "lighthouseResult": {
            "fetchTime": "2026-06-15T10:00:00Z",
            "categories": {
                "performance": {"score": 0.92},
                "accessibility": {"score": 0.81},
                "best-practices": {"score": 1.0},
                "seo": {"score": 0.5},
            },
        }
    }
    scores = lh._parse_lighthouse(raw)
    assert scores.measured
    assert scores.performance == 92
    assert scores.accessibility == 81
    assert scores.best_practices == 100
    assert scores.seo == 50
    assert scores.pwa == 0  # absent in Lighthouse 12 -> 0, never a crash
    assert scores.fetched_at == "2026-06-15T10:00:00Z"


def test_parse_missing_or_null_categories_does_not_crash() -> None:
    assert lh._parse_lighthouse({}).measured is False
    assert lh._parse_lighthouse({"lighthouseResult": {}}).measured is False
    # categories block present but empty -> measured, all zero
    assert lh._parse_lighthouse({"lighthouseResult": {"categories": {}}}).measured is True
    null_score = {"lighthouseResult": {"categories": {"performance": {"score": None}}}}
    assert lh._parse_lighthouse(null_score).performance == 0
    assert lh._parse_lighthouse("garbage").measured is False


def test_roundtrip_through_dict() -> None:
    scores = LighthouseScores(
        performance=92, accessibility=81, best_practices=100, seo=50, pwa=0, fetched_at="x", measured=True
    )
    assert LighthouseScores.from_dict(scores.to_dict()) == scores
    assert LighthouseScores.from_dict("garbage").measured is False
    assert LighthouseScores.from_dict({"performance": "notnum"}).performance == 0


def test_fetch_rejects_non_http() -> None:
    assert asyncio.run(fetch_lighthouse("not-a-url")).measured is False


def test_fetch_returns_cache_hit_without_network(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog import _psi_cache

    cached = LighthouseScores(performance=88, measured=True, fetched_at="cached")
    _psi_cache.write_cache("lighthouse_cache", "https://example.com/", cached)

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("network must not be called on a cache hit")

    monkeypatch.setattr(lh, "_request_psi", _boom)
    result = asyncio.run(fetch_lighthouse("https://example.com/"))
    assert result.measured and result.performance == 88


def test_fetch_network_failure_returns_unmeasured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))

    async def _none(*args, **kwargs):  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(lh, "_request_psi", _none)
    assert asyncio.run(fetch_lighthouse("https://example.com/x")).measured is False


def test_request_params_repeats_categories_and_omits_empty_key() -> None:
    params = lh._request_params("https://example.com/", "")
    assert ("category", "performance") in params
    assert ("category", "seo") in params
    assert ("strategy", "mobile") in params
    assert all(name != "key" for name, _ in params)
    with_key = lh._request_params("https://example.com/", "abc")
    assert ("key", "abc") in with_key
