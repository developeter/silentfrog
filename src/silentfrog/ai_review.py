from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from .audit_issues import (
    AuditIssue,
    IssueCategory,
    IssueEvidence,
    IssueSeverity,
    issues_for_payload,
    issues_for_site_report,
)
from .crawl_types import CrawlPayload
from .site_crawl_types import SiteCrawlReport

_DEFAULT_SECRET_PATH = Path("secrets.local.json")
_PROMPT_ISSUE_LIMIT = 40
_PROMPT_EVIDENCE_LIMIT = 6


@dataclass(frozen=True, slots=True)
class AiProviderConfig:
    provider: str
    api_key: str = field(repr=False)
    model: str = ""
    endpoint: str = ""


@dataclass(frozen=True, slots=True)
class AiReviewEvidence:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class AiReviewInput:
    target: str
    scope: str
    issues: tuple[AuditIssue, ...]
    context: tuple[AiReviewEvidence, ...]


@dataclass(frozen=True, slots=True)
class AiReviewFinding:
    finding_id: str
    severity: IssueSeverity
    area: str
    reason: str
    recommendation: str
    evidence: tuple[AiReviewEvidence, ...]
    confidence: str = "medium"
    url: str = ""


@dataclass(frozen=True, slots=True)
class AiReviewResult:
    provider: str
    model: str
    findings: tuple[AiReviewFinding, ...]
    raw_summary: str = ""


class AiReviewClient(Protocol):
    def review(self, request: AiReviewInput) -> AiReviewResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class StaticAiReviewClient:
    result: AiReviewResult

    def review(self, request: AiReviewInput) -> AiReviewResult:
        return self.result


def load_ai_provider_config(
    path: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> AiProviderConfig | None:
    env_source = os.environ if environ is None else environ
    env_config = _config_from_env(env_source)
    if env_config:
        return env_config
    return _config_from_file(path or _DEFAULT_SECRET_PATH)


def build_review_input_from_payload(url: str, payload: CrawlPayload) -> AiReviewInput:
    return AiReviewInput(
        target=url,
        scope="page",
        issues=tuple(issues_for_payload(url, payload)),
        context=_payload_context(url, payload),
    )


def build_review_input_from_site_report(report: SiteCrawlReport) -> AiReviewInput:
    return AiReviewInput(
        target="Site crawl",
        scope="site",
        issues=tuple(issues_for_site_report(report)),
        context=_site_report_context(report),
    )


def build_review_prompt(request: AiReviewInput) -> str:
    payload = {
        "target": request.target,
        "scope": request.scope,
        "context": [_evidence_payload(item) for item in request.context],
        "issues": [_issue_payload(issue) for issue in request.issues[:_PROMPT_ISSUE_LIMIT]],
    }
    return "\n".join(
        [
            "Use only the evidence provided. Do not infer facts that are not in the payload.",
            "Return JSON with a findings array. Each finding needs id, severity, area, reason, recommendation, confidence, and evidence.",
            "Severity must be one of critical, warning, or info. Red/critical is only for blockers or high-confidence damage.",
            json.dumps(payload, ensure_ascii=True, indent=2),
        ]
    )


def parse_ai_review_response(
    text: str,
    *,
    default_url: str = "",
    provider: str = "unknown",
    model: str = "",
) -> AiReviewResult:
    data = json.loads(text)
    if not isinstance(data, Mapping):
        raise ValueError("AI review response must be a JSON object")
    findings = tuple(_finding_from_raw(item, default_url) for item in _mapping_items(data.get("findings", [])))
    return AiReviewResult(
        provider=_text(data.get("provider")) or provider,
        model=_text(data.get("model")) or model,
        findings=findings,
        raw_summary=_text(data.get("summary")),
    )


def run_ai_review(request: AiReviewInput, client: AiReviewClient) -> AiReviewResult:
    return client.review(request)


def issues_for_ai_review(result: AiReviewResult, *, default_scope: str = "page") -> list[AuditIssue]:
    return [
        AuditIssue(
            issue_id=f"ai_review.{_slug(finding.finding_id or finding.area or finding.reason)}",
            category=IssueCategory.AI_GEO,
            severity=finding.severity,
            source="AI-assisted review",
            reason=finding.reason,
            recommendation=finding.recommendation,
            evidence=_finding_evidence(finding, result),
            url=finding.url,
            scope="page" if finding.url else default_scope,
            confidence=finding.confidence,
        )
        for finding in result.findings
    ]


def _config_from_env(environ: Mapping[str, str]) -> AiProviderConfig | None:
    api_key = _text(environ.get("SILENTFROG_AI_API_KEY"))
    if not api_key:
        return None
    return AiProviderConfig(
        provider=_text(environ.get("SILENTFROG_AI_PROVIDER")) or "custom",
        api_key=api_key,
        model=_text(environ.get("SILENTFROG_AI_MODEL")),
        endpoint=_text(environ.get("SILENTFROG_AI_ENDPOINT")),
    )


def _config_from_file(path: Path) -> AiProviderConfig | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = _nested_mapping(raw, "ai")
    api_key = _text(data.get("api_key"))
    if not api_key:
        return None
    return AiProviderConfig(
        provider=_text(data.get("provider")) or "custom",
        api_key=api_key,
        model=_text(data.get("model")),
        endpoint=_text(data.get("endpoint")),
    )


def _payload_context(url: str, payload: CrawlPayload) -> tuple[AiReviewEvidence, ...]:
    checks = tuple(
        AiReviewEvidence(f"AI visibility - {check.area}: {check.check}", f"{check.status}; {check.details}")
        for check in payload.ai_visibility.checks[:8]
    )
    base = (
        AiReviewEvidence("Page URL", url),
        AiReviewEvidence("Title", _meta_value(payload, "title") or "Missing"),
        AiReviewEvidence("Meta description", _meta_value(payload, "description") or "Missing"),
        AiReviewEvidence("Word count", str(payload.content_quality.word_count)),
        AiReviewEvidence("Content verdict", payload.content_quality.verdict or "-"),
        AiReviewEvidence("AI visibility verdict", payload.ai_visibility.summary.verdict or "-"),
    )
    return base + checks


def _site_report_context(report: SiteCrawlReport) -> tuple[AiReviewEvidence, ...]:
    return (
        AiReviewEvidence("Discovered URLs", str(report.discovered_count)),
        AiReviewEvidence("Crawled URLs", str(report.crawled_count)),
        AiReviewEvidence("Failed URLs", str(report.failed_count)),
        AiReviewEvidence("Skipped URLs", str(report.skipped_count)),
        AiReviewEvidence("Crawler warning", report.warning or "-"),
    )


def _issue_payload(issue: AuditIssue) -> dict[str, object]:
    return {
        "id": issue.issue_id,
        "category": issue.category.value,
        "severity": issue.severity.value,
        "url": issue.url,
        "reason": issue.reason,
        "recommendation": issue.recommendation,
        "evidence": [_evidence_payload(item) for item in issue.evidence[:_PROMPT_EVIDENCE_LIMIT]],
    }


def _evidence_payload(item: IssueEvidence | AiReviewEvidence) -> dict[str, str]:
    return {"label": item.label, "value": item.value}


def _finding_from_raw(raw: Mapping[str, Any], default_url: str) -> AiReviewFinding:
    return AiReviewFinding(
        finding_id=_text(raw.get("id") or raw.get("finding_id")),
        severity=_severity(raw.get("severity")),
        area=_text(raw.get("area")) or "AI/GEO",
        reason=_text(raw.get("reason")),
        recommendation=_text(raw.get("recommendation")),
        evidence=_review_evidence(raw.get("evidence")),
        confidence=_confidence(raw.get("confidence")),
        url=_text(raw.get("url")) or default_url,
    )


def _finding_evidence(finding: AiReviewFinding, result: AiReviewResult) -> tuple[IssueEvidence, ...]:
    base = (
        IssueEvidence("Provider", result.provider or "-"),
        IssueEvidence("Model", result.model or "-"),
        IssueEvidence("Area", finding.area or "-"),
        IssueEvidence("Confidence", finding.confidence),
    )
    return base + tuple(IssueEvidence(item.label, item.value) for item in finding.evidence)


def _review_evidence(raw: Any) -> tuple[AiReviewEvidence, ...]:
    return tuple(_review_evidence_item(item) for item in _mapping_items(raw))


def _review_evidence_item(raw: Mapping[str, Any]) -> AiReviewEvidence:
    return AiReviewEvidence(_text(raw.get("label")) or "Evidence", _text(raw.get("value")))


def _mapping_items(raw: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(raw, Mapping):
        return (raw,)
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _nested_mapping(raw: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    value = raw.get(key, raw)
    return value if isinstance(value, Mapping) else {}


def _severity(value: Any) -> IssueSeverity:
    normalized = _text(value).lower()
    if normalized in {"critical", "high", "blocker", "bad"}:
        return IssueSeverity.CRITICAL
    if normalized in {"warning", "warn", "medium", "needs work"}:
        return IssueSeverity.WARNING
    return IssueSeverity.INFO


def _confidence(value: Any) -> str:
    normalized = _text(value).lower()
    return normalized if normalized in {"low", "medium", "high"} else "medium"


def _meta_value(payload: CrawlPayload, name: str) -> str:
    expected = name.lower()
    for row in payload.meta:
        if len(row) > 1 and str(row[0]).strip().lower() == expected:
            return str(row[1]).strip()
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _slug(value: str) -> str:
    slug = "_".join(part for part in value.strip().lower().replace("/", " ").split() if part)
    return slug or "finding"


__all__ = [
    "AiProviderConfig",
    "AiReviewClient",
    "AiReviewEvidence",
    "AiReviewFinding",
    "AiReviewInput",
    "AiReviewResult",
    "StaticAiReviewClient",
    "build_review_input_from_payload",
    "build_review_input_from_site_report",
    "build_review_prompt",
    "issues_for_ai_review",
    "load_ai_provider_config",
    "parse_ai_review_response",
    "run_ai_review",
]
