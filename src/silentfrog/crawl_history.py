from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .audit_issues import AuditIssue, IssueCategory, IssueSeverity, issues_for_site_report, severity_rank
from .site_crawl_types import SiteCrawlReport

_DATA_DIR_ENV = "SILENTFROG_DATA_DIR"
_APP_DIR = "Silentfrog"
_HISTORY_DIR = "crawl_history"
_HISTORY_VERSION = 1


@dataclass(frozen=True, slots=True)
class CrawlHistoryIssue:
    issue_id: str
    severity: IssueSeverity
    category: IssueCategory
    url: str
    reason: str
    recommendation: str
    source: str
    confidence: str

    @classmethod
    def from_audit_issue(cls, issue: AuditIssue) -> "CrawlHistoryIssue":
        return cls(
            issue_id=issue.issue_id,
            severity=issue.severity,
            category=issue.category,
            url=issue.url,
            reason=issue.reason,
            recommendation=issue.recommendation,
            source=issue.source,
            confidence=issue.confidence,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CrawlHistoryIssue":
        return cls(
            issue_id=str(value.get("issue_id", "")),
            severity=IssueSeverity(str(value.get("severity", IssueSeverity.INFO.value))),
            category=IssueCategory(str(value.get("category", IssueCategory.CRAWL.value))),
            url=str(value.get("url", "")),
            reason=str(value.get("reason", "")),
            recommendation=str(value.get("recommendation", "")),
            source=str(value.get("source", "")),
            confidence=str(value.get("confidence", "high")),
        )

    def key(self) -> tuple[str, str]:
        return self.issue_id, self.url

    def to_dict(self) -> dict[str, str]:
        return {
            "issue_id": self.issue_id,
            "severity": self.severity.value,
            "category": self.category.value,
            "url": self.url,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class CrawlHistoryRun:
    run_id: str
    created_at: str
    scope_key: str
    discovered_count: int
    crawled_count: int
    failed_count: int
    skipped_count: int
    issues: tuple[CrawlHistoryIssue, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CrawlHistoryRun":
        issues = tuple(
            CrawlHistoryIssue.from_dict(item)
            for item in value.get("issues", [])
            if isinstance(item, dict)
        )
        return cls(
            run_id=str(value.get("run_id", "")),
            created_at=str(value.get("created_at", "")),
            scope_key=str(value.get("scope_key", "")),
            discovered_count=_to_int(value.get("discovered_count")),
            crawled_count=_to_int(value.get("crawled_count")),
            failed_count=_to_int(value.get("failed_count")),
            skipped_count=_to_int(value.get("skipped_count")),
            issues=issues,
        )

    def severity_count(self, severity: IssueSeverity) -> int:
        return sum(1 for issue in self.issues if issue.severity == severity)

    def health_score(self) -> int:
        weights = {
            IssueSeverity.CRITICAL: 5,
            IssueSeverity.WARNING: 2,
            IssueSeverity.INFO: 1,
        }
        return sum(weights[issue.severity] for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _HISTORY_VERSION,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "scope_key": self.scope_key,
            "discovered_count": self.discovered_count,
            "crawled_count": self.crawled_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "critical_count": self.severity_count(IssueSeverity.CRITICAL),
            "warning_count": self.severity_count(IssueSeverity.WARNING),
            "info_count": self.severity_count(IssueSeverity.INFO),
            "health_score": self.health_score(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True, slots=True)
class CrawlHistoryDiff:
    previous_run_id: str
    current_run_id: str
    new_issues: tuple[CrawlHistoryIssue, ...]
    fixed_issues: tuple[CrawlHistoryIssue, ...]
    recurring_issues: tuple[CrawlHistoryIssue, ...]
    worsened_issues: tuple[CrawlHistoryIssue, ...]
    previous_health_score: int
    current_health_score: int

    @property
    def health_delta(self) -> int:
        return self.current_health_score - self.previous_health_score

    @property
    def trend(self) -> str:
        if self.health_delta < 0:
            return "improved"
        if self.health_delta > 0:
            return "regressed"
        return "unchanged"


class CrawlHistoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or crawl_history_dir()

    def save_run(self, run: CrawlHistoryRun) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{_safe_filename(run.run_id)}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_runs(self, scope_key: str | None = None) -> list[CrawlHistoryRun]:
        if not self.root.exists():
            return []
        runs = [_load_run(path) for path in self.root.glob("*.json")]
        filtered = [run for run in runs if run and _scope_matches(run, scope_key)]
        return sorted(filtered, key=lambda run: run.created_at)

    def latest_run(self, scope_key: str) -> CrawlHistoryRun | None:
        runs = self.load_runs(scope_key)
        return runs[-1] if runs else None


def build_history_run(
    report: SiteCrawlReport,
    *,
    created_at: str | None = None,
    scope_key: str | None = None,
) -> CrawlHistoryRun:
    timestamp = created_at or _utc_timestamp()
    scope = scope_key or _scope_from_report(report)
    issues = tuple(CrawlHistoryIssue.from_audit_issue(issue) for issue in issues_for_site_report(report))
    return CrawlHistoryRun(
        run_id=f"{_safe_filename(scope)}_{_safe_filename(timestamp)}",
        created_at=timestamp,
        scope_key=scope,
        discovered_count=report.discovered_count,
        crawled_count=report.crawled_count,
        failed_count=report.failed_count,
        skipped_count=report.skipped_count,
        issues=issues,
    )


def diff_runs(previous: CrawlHistoryRun, current: CrawlHistoryRun) -> CrawlHistoryDiff:
    previous_by_key = {issue.key(): issue for issue in previous.issues}
    current_by_key = {issue.key(): issue for issue in current.issues}
    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)
    shared_keys = previous_keys & current_keys
    return CrawlHistoryDiff(
        previous_run_id=previous.run_id,
        current_run_id=current.run_id,
        new_issues=_issues_for_keys(current_by_key, current_keys - previous_keys),
        fixed_issues=_issues_for_keys(previous_by_key, previous_keys - current_keys),
        recurring_issues=_issues_for_keys(current_by_key, shared_keys),
        worsened_issues=_worsened_issues(previous_by_key, current_by_key, shared_keys),
        previous_health_score=previous.health_score(),
        current_health_score=current.health_score(),
    )


def save_report_and_diff(
    store: CrawlHistoryStore,
    report: SiteCrawlReport,
) -> tuple[CrawlHistoryRun, CrawlHistoryDiff | None]:
    current = build_history_run(report)
    previous = store.latest_run(current.scope_key)
    store.save_run(current)
    return current, diff_runs(previous, current) if previous else None


def format_history_status(run: CrawlHistoryRun, diff: CrawlHistoryDiff | None) -> str:
    if diff is None:
        return f"History: saved first run for {run.scope_key}. Future crawls will show a diff."
    return (
        "History: "
        f"{len(diff.new_issues)} new, "
        f"{len(diff.fixed_issues)} fixed, "
        f"{len(diff.worsened_issues)} worsened, "
        f"{len(diff.recurring_issues)} recurring. "
        f"Health {diff.trend} ({_signed(diff.health_delta)})."
    )


def crawl_history_dir() -> Path:
    override = os.environ.get(_DATA_DIR_ENV)
    if override:
        return Path(override) / _HISTORY_DIR
    return _platform_data_root() / _HISTORY_DIR


def _load_run(path: Path) -> CrawlHistoryRun | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return CrawlHistoryRun.from_dict(raw) if isinstance(raw, dict) else None


def _scope_from_report(report: SiteCrawlReport) -> str:
    for result in report.results:
        host = urlparse(result.url).netloc.lower()
        if host:
            return host
    return "unknown"


def _scope_matches(run: CrawlHistoryRun, scope_key: str | None) -> bool:
    return scope_key is None or run.scope_key == scope_key


def _issues_for_keys(
    issues: dict[tuple[str, str], CrawlHistoryIssue],
    keys: Iterable[tuple[str, str]],
) -> tuple[CrawlHistoryIssue, ...]:
    return tuple(issues[key] for key in sorted(keys))


def _worsened_issues(
    previous: dict[tuple[str, str], CrawlHistoryIssue],
    current: dict[tuple[str, str], CrawlHistoryIssue],
    keys: Iterable[tuple[str, str]],
) -> tuple[CrawlHistoryIssue, ...]:
    worsened = [
        current[key]
        for key in keys
        if severity_rank(current[key].severity) < severity_rank(previous[key].severity)
    ]
    return tuple(sorted(worsened, key=lambda issue: issue.key()))


def _platform_data_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / _APP_DIR
    if os.sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / _APP_DIR.lower()


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part) or "run"


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "CrawlHistoryDiff",
    "CrawlHistoryIssue",
    "CrawlHistoryRun",
    "CrawlHistoryStore",
    "build_history_run",
    "crawl_history_dir",
    "diff_runs",
    "format_history_status",
    "save_report_and_diff",
]
