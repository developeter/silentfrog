from __future__ import annotations

import json
from pathlib import Path

from silentfrog.ai_review import (  # type: ignore[reportMissingImports]
    AiReviewFinding,
    AiReviewResult,
    StaticAiReviewClient,
    build_review_input_from_payload,
    build_review_input_from_site_report,
    build_review_prompt,
    issues_for_ai_review,
    load_ai_provider_config,
    parse_ai_review_response,
    run_ai_review,
)
from silentfrog.audit_issues import (  # type: ignore[reportMissingImports]
    IssueCategory,
    IssueEvidence,
    IssueSeverity,
)
from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult  # type: ignore[reportMissingImports]


def _payload(url: str = "https://example.com/page") -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "", "0"], ["description", "", "0"]],
            "headers": [],
            "images": [],
            "links": [],
            "schema": {
                "summary": {"total": 0, "by_type": {}, "errors": []},
                "blocks": [],
                "issues": [],
                "eligibility": [],
            },
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": "",
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 80, "h1_count": 0, "verdict": "Weak"},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "good_count": 0,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [
                    {
                        "area": "Answerability",
                        "check": "Direct answer",
                        "status": "warning",
                        "details": "No concise answer near the top.",
                        "recommendation": "Add a direct answer.",
                        "key": "direct_answer",
                    }
                ],
            },
            "performance": {},
            "social": {},
        }
    )


def test_load_ai_provider_config_prefers_local_environment_and_masks_secret() -> None:
    config = load_ai_provider_config(
        environ={
            "SILENTFROG_AI_PROVIDER": "mock",
            "SILENTFROG_AI_API_KEY": "local-secret",
            "SILENTFROG_AI_MODEL": "review-model",
            "SILENTFROG_AI_ENDPOINT": "https://example.test/api",
        }
    )

    assert config is not None
    assert config.provider == "mock"
    assert config.model == "review-model"
    assert config.endpoint == "https://example.test/api"
    assert "local-secret" not in repr(config)


def test_load_ai_provider_config_reads_ignored_local_secret_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_AI_API_KEY", "env-secret")
    secret_file = tmp_path / "secrets.local.json"
    secret_file.write_text(
        json.dumps({"ai": {"provider": "mock", "api_key": "file-secret", "model": "model-a"}}),
        encoding="utf-8",
    )

    config = load_ai_provider_config(path=secret_file, environ={})

    assert config is not None
    assert config.provider == "mock"
    assert config.api_key == "file-secret"
    assert config.model == "model-a"


def test_secrets_policy_tracks_example_only() -> None:
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    example = Path("secrets.example.json").read_text(encoding="utf-8")

    assert "secrets.local.json" in ignore
    assert ".env" in ignore
    assert "replace-with-local-api-key" in example


def test_review_input_and_prompt_are_evidence_bound() -> None:
    request = build_review_input_from_payload("https://example.com/page", _payload())
    prompt = build_review_prompt(request)

    assert request.scope == "page"
    assert any(issue.issue_id == "meta.title_missing" for issue in request.issues)
    assert "Use only the evidence provided" in prompt
    assert "meta.title_missing" in prompt
    assert "No concise answer near the top" in prompt


def test_site_report_review_input_uses_site_scope() -> None:
    failed = SiteCrawlResult.failed("https://example.com/fail", "403")
    report = SiteCrawlReport.from_results([failed], discovered_count=1)
    request = build_review_input_from_site_report(report)

    assert request.scope == "site"
    assert request.target == "Site crawl"
    assert request.context[0].value == "1"
    assert request.issues[0].issue_id == "crawl.fetch_error"


def test_parse_ai_review_response_and_map_to_audit_issue() -> None:
    response = json.dumps(
        {
            "provider": "mock",
            "model": "review-model",
            "summary": "One AI/GEO opportunity.",
            "findings": [
                {
                    "id": "answer_gap",
                    "severity": "warning",
                    "area": "Answerability",
                    "reason": "The page evidence does not show a direct answer.",
                    "recommendation": "Add a concise answer near the top.",
                    "confidence": "medium",
                    "evidence": [{"label": "Intro", "value": "No concise answer near the top."}],
                }
            ],
        }
    )

    result = parse_ai_review_response(response, default_url="https://example.com/page")
    issues = issues_for_ai_review(result)

    assert result.raw_summary == "One AI/GEO opportunity."
    assert issues[0].issue_id == "ai_review.answer_gap"
    assert issues[0].category == IssueCategory.AI_GEO
    assert issues[0].severity == IssueSeverity.WARNING
    assert issues[0].confidence == "medium"
    assert issues[0].evidence[-1] == IssueEvidence("Intro", "No concise answer near the top.")


def test_run_ai_review_uses_mockable_client_boundary() -> None:
    result = AiReviewResult(
        provider="static",
        model="none",
        findings=(
            AiReviewFinding(
                finding_id="client_friendly_summary",
                severity=IssueSeverity.INFO,
                area="Summary",
                reason="The page needs a clearer explanation.",
                recommendation="Rewrite the recap using the collected evidence.",
                evidence=(),
            ),
        ),
    )
    request = build_review_input_from_payload("https://example.com/page", _payload())

    assert run_ai_review(request, StaticAiReviewClient(result)) == result
