from __future__ import annotations

import pytest

from silentfrog.ai_visibility import (  # type: ignore[reportMissingImports]
    AI_VISIBILITY_AREAS,
    ai_visibility_check_tooltip,
    ai_visibility_summary_tooltip,
    build_ai_visibility_checks,
    build_ai_visibility_payload,
    build_ai_visibility_summary,
    normalize_ai_visibility_status,
)
from silentfrog.crawl_types import AiVisibilityCheck, AiVisibilityPayload  # type: ignore[reportMissingImports]


def test_ai_visibility_status_normalization() -> None:
    assert normalize_ai_visibility_status("ok") == "good"
    assert normalize_ai_visibility_status("needs work") == "warning"
    assert normalize_ai_visibility_status("blocked") == "critical"


def test_ai_visibility_tooltips_explain_summary_and_checks() -> None:
    assert "Strong" in ai_visibility_summary_tooltip()
    assert "Weak" in ai_visibility_summary_tooltip()
    assert "robots.txt" in ai_visibility_check_tooltip("access_agents")
    assert "<html lang>" in ai_visibility_check_tooltip("topic_language")


def test_ai_visibility_summary_returns_strong_for_clean_checks() -> None:
    checks = [
        AiVisibilityCheck("Access", "AI agents can fetch the page", "good", "Allowed", "Keep access open", "access"),
        AiVisibilityCheck("Topic clarity", "Primary topic is explicit", "good", "Clear title and H1", "Keep", "topic"),
        AiVisibilityCheck("Answerability", "Intro answers the topic quickly", "warning", "Summary block is missing", "Add one", "answer"),
    ]

    summary = build_ai_visibility_summary(checks)

    assert summary.verdict == "Strong"
    assert summary.good_count == 2
    assert summary.warning_count == 1
    assert summary.critical_count == 0


def test_ai_visibility_summary_returns_needs_work_for_limited_access() -> None:
    checks = [
        AiVisibilityCheck("Access", "Snippet reuse is limited", "warning", "nosnippet found", "Remove nosnippet", "access_snippet"),
        AiVisibilityCheck("Citation readiness", "Structured data is incomplete", "warning", "Missing organization details", "Complete schema", "citation"),
    ]

    summary = build_ai_visibility_summary(checks)

    assert summary.verdict == "Needs work"
    assert summary.warning_count == 2


def test_ai_visibility_summary_returns_weak_for_critical_access() -> None:
    checks = [
        AiVisibilityCheck("Access", "AI crawlers are blocked", "critical", "robots.txt blocks the audited agents", "Open robots.txt access", "access_blocked"),
        AiVisibilityCheck("Topic clarity", "Primary topic is vague", "warning", "Title and H1 are generic", "Clarify the topic", "topic_vague"),
    ]

    summary = build_ai_visibility_summary(checks)

    assert summary.verdict == "Weak"
    assert summary.critical_count == 1


def test_ai_visibility_payload_roundtrip() -> None:
    payload = AiVisibilityPayload.from_raw(
        {
            "summary": {"verdict": "Needs work", "good_count": 1, "warning_count": 2, "critical_count": 0},
            "checks": [
                {
                    "area": "Entity clarity",
                    "check": "Brand naming is consistent",
                    "status": "ok",
                    "details": "Title, schema, and social use the same brand name",
                    "recommendation": "Keep naming aligned",
                    "key": "entity_consistency",
                }
            ],
        }
    )

    assert AI_VISIBILITY_AREAS[0] == "Access"
    assert payload.summary.verdict == "Needs work"
    assert payload.checks[0].status == "good"
    assert payload.to_dict()["checks"][0]["key"] == "entity_consistency"


def test_ai_visibility_analyzer_builds_expected_checks() -> None:
    payload = build_ai_visibility_payload(
        {
            "ai_crawl": [
                ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"],
                ["Googlebot", "googlebot", "Yes", "-", "nosnippet", "Limited", "Google search controls: nosnippet"],
            ],
            "meta": [["title", "Lago Not Only White Sofa", "24"]],
            "headers": [["h1", "Lago Not Only White Sofa"]],
            "meta_robots": "index, follow, nosnippet",
            "content_quality": {
                "language": "English (en-US)",
                "word_count": 420,
                "paragraph_count": 6,
                "substantial_paragraph_count": 4,
                "average_words_per_paragraph": 24.5,
                "title_present": True,
                "meta_description_present": True,
                "h1_count": 1,
                "h2_h6_count": 3,
                "title_h1_alignment": "Aligned",
                "intro_paragraph": "Present",
                "thin_content_risk": "Low",
                "heading_structure": "Good",
                "verdict": "Strong",
            },
            "schema": {
                "summary": {"total": 2, "by_syntax": {"json-ld": 2}, "by_type": {"Product": 1, "Organization": 1}, "errors": []},
                "eligibility": [
                    {"type": "Product", "detected": True, "count": 1, "eligibility": "Eligible", "missing_fields": [], "warnings": []},
                    {"type": "Organization", "detected": True, "count": 1, "eligibility": "Eligible", "missing_fields": [], "warnings": []},
                ],
                "blocks": [],
                "fallback_raw": [],
            },
            "canonical": {"target": "https://example.com/sofa", "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": ["https://example.com/sofa"], "hops": 0, "final_status": "200", "loop": False},
            "social": {
                "open_graph": {
                    "title": "Lago Not Only White Sofa",
                    "description": "White designer sofa with suspended lines.",
                    "image": "https://example.com/og.jpg",
                    "site_name": "Lago",
                    "url": "https://example.com/sofa",
                    "card": "",
                    "issues": [],
                },
                "twitter": {
                    "title": "Lago Not Only White Sofa",
                    "description": "White designer sofa with suspended lines.",
                    "image": "https://example.com/tw.jpg",
                    "site_name": "Lago",
                    "url": "https://example.com/sofa",
                    "card": "summary_large_image",
                    "issues": [],
                },
            },
        }
    )

    checks = {item.key: item for item in payload.checks}
    assert payload.summary.verdict == "Needs work"
    assert checks["access_controls"].status == "warning"
    assert checks["topic_alignment"].status == "good"
    assert checks["citation_schema"].status == "good"
    assert checks["entity_naming"].status == "good"


def test_ai_visibility_analyzer_marks_blocked_access_as_weak() -> None:
    checks = build_ai_visibility_checks(
        {
            "ai_crawl": [
                ["GPTBot", "gptbot", "No", "noai", "-", "Blocked", "Blocked by robots.txt: /private; Nonstandard directives detected: noai"],
                ["Google-Extended", "google-extended", "No", "noai", "-", "Blocked", "Blocked by robots.txt: /private; Nonstandard directives detected: noai"],
            ],
            "meta": [["title", "Generic Page", "12"]],
            "headers": [["h1", "Generic Page"]],
            "meta_robots": "noai",
            "content_quality": {
                "language": "Not declared",
                "word_count": 90,
                "paragraph_count": 1,
                "substantial_paragraph_count": 0,
                "average_words_per_paragraph": 90.0,
                "title_present": True,
                "meta_description_present": False,
                "h1_count": 1,
                "h2_h6_count": 0,
                "title_h1_alignment": "Exact match",
                "intro_paragraph": "Weak or missing",
                "thin_content_risk": "High",
                "heading_structure": "Good",
                "verdict": "Weak",
            },
            "schema": {"summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []}, "eligibility": [], "blocks": [], "fallback_raw": []},
            "canonical": {"target": "https://example.com/private", "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": ["https://example.com/private"], "hops": 0, "final_status": "200", "loop": False},
            "social": {"open_graph": {}, "twitter": {}},
        }
    )

    by_key = {item.key: item for item in checks}
    summary = build_ai_visibility_summary(checks)
    assert by_key["access_agents"].status == "critical"
    assert by_key["topic_depth"].status == "critical"
    assert by_key["citation_schema"].status == "warning"
    assert summary.verdict == "Weak"


_MIN_PAYLOAD = {
    "ai_crawl": [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "-"]],
    "meta": [["title", "Sample", "10"]],
    "headers": [["h1", "Sample"]],
    "meta_robots": "",
    "content_quality": {
        "language": "English (en-US)",
        "word_count": 400,
        "paragraph_count": 4,
        "substantial_paragraph_count": 3,
        "average_words_per_paragraph": 20.0,
        "title_present": True,
        "meta_description_present": True,
        "h1_count": 1,
        "h2_h6_count": 2,
        "title_h1_alignment": "Aligned",
        "intro_paragraph": "Present",
        "thin_content_risk": "Low",
        "heading_structure": "Good",
        "verdict": "Strong",
    },
    "schema": {"summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []}, "eligibility": [], "blocks": [], "fallback_raw": []},
    "canonical": {"target": "https://example.com/", "self": True, "multiple": False, "status": "200"},
    "redirect": {"chain": ["https://example.com/"], "hops": 0, "final_status": "200", "loop": False},
    "social": {"open_graph": {}, "twitter": {}},
}


def _payload_with_discovery(discovery: dict) -> dict:
    return {**_MIN_PAYLOAD, "discovery": discovery}


def test_ai_visibility_emits_four_discovery_checks_in_access_area() -> None:
    checks = build_ai_visibility_checks(_payload_with_discovery({}))
    by_key = {item.key: item for item in checks}
    for key in ("access_llms_txt", "access_llms_full_txt", "access_well_known_ai_json", "access_sitemap"):
        assert key in by_key, f"missing check: {key}"
        assert by_key[key].area == "Access"


def test_ai_visibility_discovery_checks_are_good_when_files_present() -> None:
    discovery = {
        "llms_txt": {"url": "https://example.com/llms.txt", "status": 200, "present": True, "body_excerpt": "# x", "parsed": {"title": "x"}, "source": "fetch"},
        "llms_full_txt": {"url": "https://example.com/llms-full.txt", "status": 200, "present": True, "body_excerpt": "# y", "parsed": {}, "source": "fetch"},
        "well_known_ai_json": {"url": "https://example.com/.well-known/ai.json", "status": 200, "present": True, "body_excerpt": "{}", "parsed": {"policy": "allow"}, "source": "fetch"},
        "sitemap": {"url": "https://example.com/sitemap.xml", "status": 200, "present": True, "body_excerpt": "<urlset/>", "parsed": {"robots_sitemap_count": 1}, "source": "robots-sitemap"},
    }
    checks = build_ai_visibility_checks(_payload_with_discovery(discovery))
    by_key = {item.key: item for item in checks}
    for key in ("access_llms_txt", "access_llms_full_txt", "access_well_known_ai_json", "access_sitemap"):
        assert by_key[key].status == "good"


@pytest.mark.parametrize(
    "myth_key",
    ["access_llms_txt", "access_llms_full_txt", "access_well_known_ai_json", "access_sitemap"],
)
def test_ai_visibility_myth_flagged_checks_never_warn_when_absent(myth_key: str) -> None:
    # §1.5 of docs/geo_roadmap.md: absence of myth-flagged signals routes
    # to "info" (which _STATUS_ALIASES maps to "good"), never warning or critical.
    checks = build_ai_visibility_checks(_payload_with_discovery({}))
    check = next(item for item in checks if item.key == myth_key)
    assert check.status not in {"warning", "critical"}


@pytest.mark.parametrize(
    "myth_key",
    ["access_llms_txt", "access_llms_full_txt", "access_well_known_ai_json", "access_sitemap"],
)
def test_ai_visibility_myth_tooltips_carry_google_disclaimer(myth_key: str) -> None:
    # §7 risk register: tooltip rewording must NOT drift away from the
    # Google-myth disclaimer. Every myth-flagged tooltip names Google.
    tooltip = ai_visibility_check_tooltip(myth_key)
    assert "Google" in tooltip
    assert any(token in tooltip for token in ("not required", "NOT required", "Google-not-required", "AI Optimization Guide"))


def test_ai_visibility_areas_include_eeat() -> None:
    # M2 adds "E-E-A-T" as the sixth area.
    assert "E-E-A-T" in AI_VISIBILITY_AREAS
    assert AI_VISIBILITY_AREAS.index("E-E-A-T") == 5


def test_ai_visibility_emits_eeat_and_structure_rows() -> None:
    checks = build_ai_visibility_checks(_payload_with_discovery({}))
    keys = {item.key for item in checks}
    for key in (
        "eeat_author_byline", "eeat_publish_date", "eeat_update_freshness",
        "eeat_author_bio", "eeat_external_citations",
        "structure_semantic_html", "structure_internal_links", "citation_images_alt",
    ):
        assert key in keys, f"missing M2 check: {key}"


def test_eeat_rows_alone_do_not_trigger_weak_verdict() -> None:
    # E-E-A-T warnings should never push the summary to Weak — only
    # Access criticals do that. Build a payload with only the byline
    # missing and assert verdict stays at most "Needs work".
    checks = build_ai_visibility_checks(_payload_with_discovery({}))
    summary = build_ai_visibility_summary(checks)
    assert summary.verdict in {"Strong", "Needs work"}


@pytest.mark.parametrize(
    "myth_key",
    [
        "structure_semantic_html",
        "structure_internal_links",
        "citation_images_alt",
        "eeat_external_citations",
    ],
)
def test_m2_myth_keys_never_warn_when_absent(myth_key: str) -> None:
    checks = build_ai_visibility_checks(_payload_with_discovery({}))
    item = next(check for check in checks if check.key == myth_key)
    assert item.status not in {"warning", "critical"}


@pytest.mark.parametrize(
    "myth_key",
    [
        "structure_semantic_html",
        "structure_internal_links",
        "citation_images_alt",
        "eeat_external_citations",
    ],
)
def test_m2_myth_tooltips_carry_google_disclaimer(myth_key: str) -> None:
    tooltip = ai_visibility_check_tooltip(myth_key)
    assert "Google" in tooltip
    assert any(token in tooltip for token in ("not required", "NOT required", "AI Optimization Guide", "QUALITY"))
