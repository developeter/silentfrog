from __future__ import annotations

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
