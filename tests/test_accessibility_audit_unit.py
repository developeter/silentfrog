"""Unit tests for v3 G4 Stage 1 accessibility audit (axe-core, no Chromium)."""

from __future__ import annotations

from typing import Any

import pytest

from silentfrog.accessibility_audit import (
    collect_accessibility,
    load_axe_source,
    parse_axe_result,
)
from silentfrog.audit_issues import IssueSeverity, _accessibility_issues
from silentfrog.crawl_options import AuditProfile, CrawlOptions, ProfilePolicy
from silentfrog.crawl_types import CrawlPayload
from silentfrog.render_diff import RenderResult

_MINIMAL_RAW: dict[str, Any] = {
    "meta": [],
    "headers": [],
    "images": [],
    "links": [],
    "schema": {},
    "canonical": {},
    "redirect": {},
    "robots": {},
    "meta_robots": "",
    "hreflang": [],
    "ai_crawl": [],
    "serp": {},
    "serp_audit": {},
    "keywords": [],
}


def _payload(accessibility: dict[str, Any] | None = None) -> CrawlPayload:
    raw = dict(_MINIMAL_RAW)
    if accessibility is not None:
        raw = {**raw, "accessibility": accessibility}
    return CrawlPayload.from_raw(raw)


class _FakePool:
    """Records the render call; serves a canned RenderResult (or None)."""

    def __init__(self, result: RenderResult | None = None) -> None:
        self.calls: list[str] = []
        self._result = result

    async def render(self, url: str, **kwargs: Any) -> RenderResult | None:
        self.calls.append(url)
        return self._result


# --- parse_axe_result (pure) -------------------------------------------------


def test_parse_axe_result_happy_path_counts_and_caps_sample_targets() -> None:
    raw = {
        "violations": [
            {
                "id": "color-contrast",
                "impact": "serious",
                "help": "Elements must meet minimum color contrast ratio thresholds",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
                "nodes": [{"target": [f".item-{i}"]} for i in range(6)],
            },
            {
                "id": "region",
                "impact": "moderate",
                "help": "All page content must be contained by landmarks",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/region",
                "nodes": [{"target": [".footer"]}],
            },
        ]
    }
    result = parse_axe_result(raw)
    assert result["measured"] is True
    assert result["counts"] == {"critical": 0, "serious": 1, "moderate": 1, "minor": 0}

    contrast = next(v for v in result["violations"] if v["id"] == "color-contrast")
    assert contrast["nodes"] == 6
    # sample_targets is capped at 5 even though the violation has 6 nodes.
    assert len(contrast["sample_targets"]) == 5
    assert contrast["sample_targets"] == [".item-0", ".item-1", ".item-2", ".item-3", ".item-4"]

    region = next(v for v in result["violations"] if v["id"] == "region")
    assert region["help_url"] == "https://dequeuniversity.com/rules/axe/4.10/region"
    assert region["nodes"] == 1


@pytest.mark.parametrize("garbage", [None, "not a dict", 42, {}, {"violations": "nope"}, {"violations": None}])
def test_parse_axe_result_garbage_degrades_to_empty_dict(garbage: Any) -> None:
    assert parse_axe_result(garbage) == {}


# --- _accessibility_issues (severity mapping) --------------------------------


def test_accessibility_issues_severity_mapping_by_impact_tier() -> None:
    accessibility = {
        "measured": True,
        "violations": [
            {
                "id": "image-alt",
                "impact": "critical",
                "help": "Images must have alternate text",
                "help_url": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
                "nodes": 2,
                "sample_targets": ["img.hero"],
            },
            {
                "id": "color-contrast",
                "impact": "serious",
                "help": "Elements must meet minimum color contrast ratio thresholds",
                "help_url": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
                "nodes": 3,
                "sample_targets": ["p.body"],
            },
            {
                "id": "region",
                "impact": "moderate",
                "help": "All page content must be contained by landmarks",
                "help_url": "https://dequeuniversity.com/rules/axe/4.10/region",
                "nodes": 1,
                "sample_targets": [],
            },
            {
                "id": "duplicate-id",
                "impact": "minor",
                "help": "IDs of active elements must be unique",
                "help_url": "https://dequeuniversity.com/rules/axe/4.10/duplicate-id",
                "nodes": 1,
                "sample_targets": [],
            },
        ],
        "counts": {"critical": 1, "serious": 1, "moderate": 1, "minor": 1},
    }
    payload = _payload(accessibility)
    issues = _accessibility_issues("https://example.com/page", payload)
    by_id = {issue.issue_id: issue for issue in issues}

    assert by_id["accessibility.image-alt"].severity == IssueSeverity.CRITICAL
    assert by_id["accessibility.color-contrast"].severity == IssueSeverity.WARNING
    assert by_id["accessibility.region"].severity == IssueSeverity.INFO
    assert by_id["accessibility.duplicate-id"].severity == IssueSeverity.INFO
    assert by_id["accessibility.image-alt"].recommendation == (
        "Fix per https://dequeuniversity.com/rules/axe/4.10/image-alt"
    )
    assert by_id["accessibility.image-alt"].category.value == "accessibility"


def test_accessibility_issues_empty_when_group_absent() -> None:
    # Old blobs / feature off: no "accessibility" group -> no issues.
    payload = _payload(None)
    assert _accessibility_issues("https://example.com/page", payload) == []


# --- collect_accessibility (gating + degradation) ----------------------------


@pytest.mark.asyncio
async def test_collect_accessibility_off_by_default_never_touches_the_pool() -> None:
    pool = _FakePool()
    options = CrawlOptions.default()
    policy = ProfilePolicy.for_profile(AuditProfile.DEEP)
    result = await collect_accessibility("https://example.com", options, policy, pool=pool)
    assert result == {}
    assert pool.calls == []


@pytest.mark.asyncio
async def test_collect_accessibility_flag_on_but_profile_does_not_render() -> None:
    pool = _FakePool()
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, accessibility_audit=True)
    policy = ProfilePolicy.for_profile(AuditProfile.STANDARD)  # render=False
    result = await collect_accessibility("https://example.com", options, policy, pool=pool)
    assert result == {}
    assert pool.calls == []


@pytest.mark.asyncio
async def test_collect_accessibility_happy_path_parses_script_result() -> None:
    canned = {
        "violations": [
            {
                "id": "image-alt",
                "impact": "critical",
                "help": "Images must have alternate text",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
                "nodes": [{"target": [".hero"]}],
            },
        ]
    }
    pool = _FakePool(RenderResult(url="https://example.com", rendered_html="<html></html>", script_result=canned))
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, accessibility_audit=True)
    policy = ProfilePolicy.for_profile(AuditProfile.DEEP)
    result = await collect_accessibility("https://example.com", options, policy, pool=pool)
    assert result["measured"] is True
    assert result["violations"][0]["id"] == "image-alt"
    assert pool.calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_collect_accessibility_degrades_when_script_result_missing() -> None:
    pool = _FakePool(RenderResult(url="https://example.com", rendered_html="<html></html>"))
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, accessibility_audit=True)
    policy = ProfilePolicy.for_profile(AuditProfile.DEEP)
    result = await collect_accessibility("https://example.com", options, policy, pool=pool)
    assert result == {}


@pytest.mark.asyncio
async def test_collect_accessibility_degrades_on_render_error() -> None:
    pool = _FakePool(RenderResult(url="https://example.com", rendered_html="", error="Timeout"))
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, accessibility_audit=True)
    policy = ProfilePolicy.for_profile(AuditProfile.DEEP)
    result = await collect_accessibility("https://example.com", options, policy, pool=pool)
    assert result == {}


# --- load_axe_source ----------------------------------------------------------


def test_load_axe_source_reads_the_vendored_file() -> None:
    source = load_axe_source()
    assert source
    assert "axe" in source.lower()
