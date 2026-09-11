from __future__ import annotations

import json
from dataclasses import fields

import pytest
from hypothesis import given
from hypothesis import strategies as st

from silentfrog.crawl_types import (  # type: ignore[reportMissingImports]
    PAYLOAD_SCHEMA_VERSION,
    CrawlPayload,
    PerformanceMetrics,
)


def _raw_payload() -> dict[str, object]:
    return {
        "meta": [["title", "Example", "7"]],
        "headers": [["h1", "Example"]],
        "images": [["https://example.com/logo.png", "Logo", "", "image/png", "", "", "", "", "", ""]],
        "links": [["https://example.com", "Example", "Internal", "follow", "200", "OK", "Body", "", "com"]],
        "schema": {
            "summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []},
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {"target": "https://example.com", "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": ["https://example.com"], "hops": 0, "final_status": "200", "loop": False},
        "robots": {"*": [("Allow", "/")]},
        "meta_robots": "index, follow",
        "hreflang": [["en", "https://example.com", "200", "Yes", "Yes"]],
        "ai_crawl": [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"]],
        "serp": {
            "title": "Example",
            "description": "Example description",
            "url": "https://example.com",
            "site_name": "Example",
            "favicon": "https://example.com/favicon.ico",
            "breadcrumb": "example.com",
        },
        "serp_audit": {
            "too_long": "No",
            "too_short": "No",
            "px_over": "No",
            "px_under": "No",
            "equals_h1": "No",
            "missing": "No",
            "px_len": "100",
            "char_len": "7",
        },
        "keywords": [{"term": "example", "length": 1, "frequency": 2, "density": 2.5}],
        "content_quality": {"verdict": "Strong", "word_count": 120},
        "ai_visibility": {
            "summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0},
            "checks": [],
        },
        "performance": {"status": 200, "transfer_size": 1024},
        "social": {"open_graph": {"title": "OG title"}, "twitter": {"title": "TW title"}},
        # v2.0 H0: schema version, page URL provenance, AI-Visibility groups.
        "payload_schema_version": 2,
        "requested_url": "https://example.com/req",
        "final_url": "https://example.com/final",
        "discovery": {"llms_txt": {"present": True}},
        "eeat": {"score": 3, "signals": ["author"]},
        "structure": {"headings_ok": True},
        "citation_content": {"quotations": 2},
        "citation_advanced": {"readability": 61.5},
        "seo_basics": {"title_ok": True},
        "render": {"status": "good", "missing_headings": []},
        "perf_vitals": {"lcp_ms": 1800},
        "perf_crux": {"reason": "disabled"},
        "ai_citations": {"measured": False},
        "gsc": {"measured": False},
        "ga4": {"measured": False},
    }


def test_crawl_payload_from_raw_keeps_optional_sections() -> None:
    payload = CrawlPayload.from_raw(_raw_payload())

    assert payload.meta[0][0] == "title"
    assert payload.images[0][0] == "https://example.com/logo.png"
    assert payload.canonical.is_self is True
    assert payload.serp.site_name == "Example"
    assert payload.keywords[0].term == "example"
    assert payload.content_quality.verdict == "Strong"
    assert payload.ai_visibility.summary.verdict == "Strong"
    assert payload.social.open_graph.title == "OG title"


def test_crawl_payload_from_raw_reports_missing_required_keys() -> None:
    raw = _raw_payload()
    raw.pop("meta")
    raw.pop("headers")

    with pytest.raises(ValueError, match=r"Missing crawl keys: headers, meta"):
        CrawlPayload.from_raw(raw)


_H0_GROUPS = (
    "discovery",
    "eeat",
    "structure",
    "citation_content",
    "citation_advanced",
    "seo_basics",
    "render",
    "perf_vitals",
    "perf_crux",
    "ai_citations",
    "gsc",
    "ga4",
)


def test_decode_and_mapping_cover_every_field() -> None:
    # H0 bidirectional drift guard: BOTH halves of (de)serialization must
    # touch every field. _decode_fields keys (from_raw) and to_mapping keys
    # must each equal the dataclass field set, or a new field is silently
    # dropped on the way out OR left unread on the way in.
    field_names = {f.name for f in fields(CrawlPayload)}
    assert set(CrawlPayload._decode_fields(_raw_payload())) == field_names
    payload = CrawlPayload.from_raw(_raw_payload())
    assert set(payload.to_mapping().keys()) == field_names


def test_roundtrip_preserves_all_groups_urls_and_version() -> None:
    raw = _raw_payload()
    payload = CrawlPayload.from_raw(raw)
    # All 12 source groups survive from_raw exactly (not just a subset)...
    for group in _H0_GROUPS:
        assert getattr(payload, group) == raw[group], group
    assert payload.requested_url == "https://example.com/req"
    assert payload.final_url == "https://example.com/final"
    assert payload.payload_schema_version == 2
    # ...and survive a full to_mapping -> from_raw round trip.
    restored = CrawlPayload.from_raw(payload.to_mapping())
    assert restored == payload
    for group in _H0_GROUPS:
        assert getattr(restored, group) == getattr(payload, group), group


def test_new_h0_payload_uses_current_schema_version() -> None:
    payload = CrawlPayload.from_raw(_raw_payload())
    assert payload.payload_schema_version == PAYLOAD_SCHEMA_VERSION == 2


def test_from_raw_absent_schema_version_is_legacy_v1() -> None:
    raw = _raw_payload()
    del raw["payload_schema_version"]  # absent (not None) == a pre-H0 blob
    assert CrawlPayload.from_raw(raw).payload_schema_version == 1


@pytest.mark.parametrize("version", [1, 2])
def test_from_raw_accepts_supported_schema_versions(version: int) -> None:
    raw = _raw_payload()
    raw["payload_schema_version"] = version
    assert CrawlPayload.from_raw(raw).payload_schema_version == version


@pytest.mark.parametrize(
    "bad_version",
    [None, True, False, "2", 2.0, [2], 0, -1],
    ids=["explicit_none", "bool_true", "bool_false", "str", "float", "list", "zero", "negative"],
)
def test_from_raw_rejects_invalid_schema_version(bad_version: object) -> None:
    # Explicit None, booleans, malformed values, and versions < 1 must raise —
    # never silently fall back to legacy v1 (only an ABSENT key does that).
    raw = _raw_payload()
    raw["payload_schema_version"] = bad_version
    with pytest.raises(ValueError):
        CrawlPayload.from_raw(raw)


def test_from_raw_rejects_future_schema_version_as_unsupported() -> None:
    raw = _raw_payload()
    raw["payload_schema_version"] = PAYLOAD_SCHEMA_VERSION + 1
    with pytest.raises(ValueError, match="unsupported payload_schema_version"):
        CrawlPayload.from_raw(raw)


def test_from_raw_legacy_blob_loads_as_version_1_with_empty_groups() -> None:
    # Pre-H0 stored blobs lack the schema version and the new keys; they must
    # load as version 1 with empty groups, not crash, so old history is read.
    raw = _raw_payload()
    for key in ("payload_schema_version", "requested_url", "final_url", *_H0_GROUPS):
        raw.pop(key)
    payload = CrawlPayload.from_raw(raw)
    assert payload.payload_schema_version == 1
    assert payload.requested_url == ""
    assert payload.final_url == ""
    for group in _H0_GROUPS:
        assert getattr(payload, group) == {}, group


def test_content_quality_text_glitches_round_trips_and_defaults_empty() -> None:
    # v3 G15: nested add-only field on ContentQuality (not a top-level
    # CrawlPayload group) — a pre-G15 blob has no "text_glitches" key inside
    # "content_quality" at all, so it must default to {} rather than fail.
    raw = _raw_payload()
    raw["content_quality"] = {
        "verdict": "Strong",
        "word_count": 120,
        "text_glitches": {
            "duplicate_words": 1,
            "doubled_punctuation": 0,
            "space_before_punct": 0,
            "total": 1,
            "samples": ["x"],
        },
    }
    payload = CrawlPayload.from_raw(raw)
    assert payload.content_quality.text_glitches["total"] == 1
    restored = CrawlPayload.from_raw(payload.to_mapping())
    assert restored.content_quality.text_glitches == payload.content_quality.text_glitches

    legacy_payload = CrawlPayload.from_raw(_raw_payload())  # content_quality lacks the key entirely
    assert legacy_payload.content_quality.text_glitches == {}


def test_url_normalization_none_becomes_empty_unicode_preserved() -> None:
    raw = _raw_payload()
    raw["requested_url"] = None  # explicit None value, not an absent key
    raw["final_url"] = "https://例え.テスト/ページ?q=ünïcode"
    payload = CrawlPayload.from_raw(raw)
    assert payload.requested_url == ""  # None -> "", never the string "None"
    assert payload.final_url == "https://例え.テスト/ページ?q=ünïcode"  # unchanged
    assert CrawlPayload.from_raw(payload.to_mapping()).final_url == payload.final_url


# Hypothesis: JSON-safe nested groups + URL edge cases must survive the
# to_mapping -> JSON -> from_raw path the CrawlStore persists through.
_safe_text = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40)
_json_scalar = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-1_000_000, max_value=1_000_000)
    | st.floats(allow_nan=False, allow_infinity=False)
    | _safe_text
)
_json_value = st.recursive(
    _json_scalar,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_safe_text, children, max_size=4),
    max_leaves=15,
)
_json_object = st.dictionaries(_safe_text, _json_value, max_size=4)
_url = st.none() | _safe_text


def test_performance_metrics_roundtrip_keeps_heaviest_and_third_party() -> None:
    # perf-payload-roundtrip: a LIVE audit's heaviest_resources/third_party_hosts
    # lists must survive persistence (to_mapping -> from_raw) so a reopened past
    # scan's PerformanceTab still has its two detail tables.
    raw = {
        "status": 200,
        "transfer_size": 2048,
        "heaviest_resources": [
            {"url": "https://example.com/a.js", "bytes": 900, "type": "js", "third_party": False},
            {"url": "https://cdn.example.net/b.png", "bytes": 500, "type": "img", "third_party": True},
        ],
        "third_party_hosts": [
            {"host": "cdn.example.net", "bytes": 500, "count": 1, "types": ["img"]},
        ],
    }
    metrics = PerformanceMetrics.from_raw(raw)
    assert metrics.heaviest_resources == raw["heaviest_resources"]
    assert metrics.third_party_hosts == raw["third_party_hosts"]

    restored = PerformanceMetrics.from_raw(metrics.to_dict())
    assert restored == metrics
    assert restored.heaviest_resources == raw["heaviest_resources"]
    assert restored.third_party_hosts == raw["third_party_hosts"]

    # JSON round trip too, mirroring how CrawlStore persists the payload.
    blob = json.dumps(metrics.to_dict()).encode("utf-8")
    from_json = PerformanceMetrics.from_raw(json.loads(blob.decode("utf-8")))
    assert from_json == metrics


def test_performance_metrics_old_blob_without_new_keys_loads_empty_lists() -> None:
    # OLD persisted blobs predate heaviest_resources/third_party_hosts: absence
    # must decode as [], never raise.
    old_blob = {"status": 200, "transfer_size": 1024}
    metrics = PerformanceMetrics.from_raw(old_blob)
    assert metrics.heaviest_resources == []
    assert metrics.third_party_hosts == []


@given(group=_json_object, requested=_url, final=_url)
def test_property_json_roundtrip_groups_and_urls(
    group: dict[str, object], requested: str | None, final: str | None
) -> None:
    raw = _raw_payload()
    raw["discovery"] = group
    raw["requested_url"] = requested
    raw["final_url"] = final
    payload = CrawlPayload.from_raw(raw)
    # Mirror CrawlStore persistence exactly: to_mapping -> JSON bytes -> from_raw.
    blob = json.dumps(payload.to_mapping(), ensure_ascii=False).encode("utf-8")
    restored = CrawlPayload.from_raw(json.loads(blob.decode("utf-8")))
    assert restored == payload
    assert payload.requested_url == ("" if requested is None else requested)
    assert payload.final_url == ("" if final is None else final)
