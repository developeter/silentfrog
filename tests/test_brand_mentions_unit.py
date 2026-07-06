"""Unit tests for v2.0 V20 brand-mention tracking (offline — no HTTP)."""

from __future__ import annotations

import pytest

from silentfrog.brand_mentions import (
    BrandMentionsPayload,
    build_brand_mention_checks,
    derive_brand,
    fetch_brand_mentions,
)
from silentfrog.brand_mentions.tracker import _MAX_SERIES_POINTS, record_point

_DAY = 24 * 60 * 60


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))


def test_derive_brand_prefers_site_name_then_domain_stem() -> None:
    assert derive_brand("https://shop.example.com/p", "Acme Store") == "Acme Store"
    assert derive_brand("https://www.example.com/p") == "Example"
    assert derive_brand("") == ""


def test_record_point_replaces_same_day_and_caps_series() -> None:
    base = 1_750_000_000
    record_point("example.com", 3, 1, now=base)
    series = record_point("example.com", 5, 2, now=base + 60)  # same day -> replace
    assert len(series) == 1
    assert series[0]["brave"] == 5
    for day in range(1, _MAX_SERIES_POINTS + 10):
        series = record_point("example.com", day, 0, now=base + day * _DAY)
    assert len(series) == _MAX_SERIES_POINTS


@pytest.mark.asyncio
async def test_fetch_disabled_by_default_never_touches_network(monkeypatch) -> None:
    monkeypatch.delenv("SILENTFROG_BRAND_MENTIONS_ENABLE", raising=False)
    payload = await fetch_brand_mentions("https://example.com/")
    assert payload.measured is False
    assert "SILENTFROG_BRAND_MENTIONS_ENABLE" in payload.reason


def test_checks_not_emitted_when_unmeasured() -> None:
    assert build_brand_mention_checks(BrandMentionsPayload()) == []


def test_visibility_check_good_on_mentions_info_on_absence() -> None:
    seen = build_brand_mention_checks(
        BrandMentionsPayload(measured=True, brand="Acme", host="acme.com", brave_mentions=4, common_crawl_refs=2)
    )
    assert seen[0].key == "brand_mentions_visibility"
    assert seen[0].status == "good"
    # §1.5 myth rule: zero mentions is informational, never a warning.
    absent = build_brand_mention_checks(
        BrandMentionsPayload(measured=True, brand="Acme", host="acme.com", brave_mentions=0, common_crawl_refs=0)
    )
    assert absent[0].status == "info"


def test_trend_check_warns_only_on_decline_and_needs_two_points() -> None:
    one_point = BrandMentionsPayload(
        measured=True, brand="Acme", host="acme.com", series=[{"ts": 1, "brave": 3, "cc": 1}]
    )
    assert build_brand_mention_checks(one_point)[1].status == "info"
    growing = BrandMentionsPayload(
        measured=True,
        brand="Acme",
        host="acme.com",
        series=[{"ts": 1, "brave": 3, "cc": 1}, {"ts": 2, "brave": 5, "cc": 1}],
    )
    assert build_brand_mention_checks(growing)[1].status == "good"
    declining = BrandMentionsPayload(
        measured=True,
        brand="Acme",
        host="acme.com",
        series=[{"ts": 1, "brave": 5, "cc": 2}, {"ts": 2, "brave": 2, "cc": 1}],
    )
    trend = build_brand_mention_checks(declining)[1]
    assert trend.status == "warning"
    assert "down" in trend.details


def test_payload_round_trips_json_native() -> None:
    payload = BrandMentionsPayload(
        measured=True,
        brand="Acme",
        host="acme.com",
        brave_mentions=4,
        common_crawl_refs=2,
        series=[{"ts": 1, "brave": 4, "cc": 2}],
    )
    assert BrandMentionsPayload.from_raw(payload.to_dict()) == payload


@pytest.mark.asyncio
async def test_fetch_records_series_via_injected_session(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_BRAND_MENTIONS_ENABLE", "1")
    monkeypatch.delenv("SILENTFROG_BRAVE_API_KEY", raising=False)

    class _FakeResponse:
        status = 200

        async def text(self) -> str:
            return '{"url": "a"}\n{"url": "b"}\n'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def get(self, url, **kwargs):
            return _FakeResponse()

    payload = await fetch_brand_mentions("https://example.com/page", session=_FakeSession())
    assert payload.measured is True
    assert payload.brand == "Example"
    assert payload.common_crawl_refs == 2
    assert payload.brave_mentions == 0  # no key -> Brave skipped, CC still measures
    assert len(payload.series) == 1
