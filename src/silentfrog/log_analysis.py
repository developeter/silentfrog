from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .audit_issues import AuditIssue, IssueCategory, IssueEvidence, IssueSeverity, dedupe_issues
from .logs import AI_KINDS, classify_bot

_COMBINED_LOG_RE = re.compile(
    r"^(?P<remote>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "
    r'"(?P<request>[^"]*)" (?P<status>\d{3}|-) (?P<size>\S+)'
    r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?'
)
_BOT_TOKENS = ("googlebot", "adsbot-google", "mediapartners-google", "apis-google")
_WASTE_EXTENSIONS = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)
_WASTE_PATH_PARTS = ("/wp-admin/", "/cart", "/checkout", "/search")


@dataclass(frozen=True, slots=True)
class LogEntry:
    remote_addr: str
    timestamp: str
    method: str
    target: str
    path: str
    status: int
    bytes_sent: int
    referer: str
    user_agent: str

    @property
    def is_googlebot(self) -> bool:
        agent = self.user_agent.lower()
        return any(token in agent for token in _BOT_TOKENS)


@dataclass(frozen=True, slots=True)
class LogFinding:
    finding_id: str
    severity: IssueSeverity
    reason: str
    recommendation: str
    evidence: tuple[IssueEvidence, ...]
    url: str = ""
    count: int = 0


@dataclass(frozen=True, slots=True)
class LogAnalysisConfig:
    site_base_url: str = ""
    important_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LogAnalysisReport:
    entries: tuple[LogEntry, ...]
    findings: tuple[LogFinding, ...]
    googlebot_hits: int
    total_requests: int

    def status_counts(self) -> Counter[int]:
        return Counter(entry.status for entry in self.entries)


def parse_log_line(line: str) -> LogEntry | None:
    match = _COMBINED_LOG_RE.match(line.strip())
    if not match:
        return None
    method, target = _request_parts(match.group("request"))
    return LogEntry(
        remote_addr=match.group("remote"),
        timestamp=match.group("time"),
        method=method,
        target=target,
        path=_target_path(target),
        status=_to_int(match.group("status")),
        bytes_sent=_to_int(match.group("size")),
        referer=_clean_missing(match.group("referer")),
        user_agent=_clean_missing(match.group("agent")),
    )


def parse_log_file(path: Path) -> list[LogEntry]:
    rows: list[LogEntry] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = parse_log_line(line)
        if entry:
            rows.append(entry)
    return rows


def analyse_log_entries(
    entries: Iterable[LogEntry],
    config: LogAnalysisConfig | None = None,
) -> LogAnalysisReport:
    rows = tuple(entries)
    options = config or LogAnalysisConfig()
    findings = _build_findings(rows, options)
    return LogAnalysisReport(
        entries=rows,
        findings=tuple(findings),
        googlebot_hits=sum(1 for entry in rows if entry.is_googlebot),
        total_requests=len(rows),
    )


def analyse_log_file(path: Path, config: LogAnalysisConfig | None = None) -> LogAnalysisReport:
    return analyse_log_entries(parse_log_file(path), config)


def issues_for_log_report(report: LogAnalysisReport) -> list[AuditIssue]:
    return dedupe_issues(_issue_from_finding(finding) for finding in report.findings)


def _build_findings(entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    bot_entries = tuple(entry for entry in entries if entry.is_googlebot)
    ai_entries = _ai_agent_entries(entries)
    findings: list[LogFinding] = []
    findings.extend(_googlebot_presence_findings(bot_entries))
    findings.extend(_blocked_bot_findings(bot_entries, config))
    findings.extend(_redirected_bot_findings(bot_entries, config))
    findings.extend(_crawl_waste_findings(bot_entries, config))
    findings.extend(_orphan_findings(bot_entries, config))
    findings.extend(_missing_important_findings(bot_entries, config))
    findings.extend(_ai_agent_presence_findings(ai_entries))
    findings.extend(_ai_agent_blocked_findings(ai_entries, config))
    findings.extend(_ai_agent_redirected_findings(ai_entries, config))
    return findings


def _googlebot_presence_findings(bot_entries: tuple[LogEntry, ...]) -> list[LogFinding]:
    if bot_entries:
        return []
    return [
        _finding(
            "logs.no_googlebot_activity",
            IssueSeverity.WARNING,
            "No Googlebot activity was found in the imported log sample.",
            "Check that the imported file covers the right date range and production host.",
            [("Googlebot hits", "0")],
        )
    ]


def _blocked_bot_findings(bot_entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    blocked = [entry for entry in bot_entries if entry.status >= 400]
    if not blocked:
        return []
    top = _top_path(blocked)
    return [
        _finding(
            "logs.googlebot_blocked",
            IssueSeverity.CRITICAL,
            "Googlebot received client/server errors while crawling.",
            "Review blocked or failing URLs, server rules, robots handling, and origin stability.",
            _status_evidence(blocked),
            url=_absolute_url(top, config),
            count=len(blocked),
        )
    ]


def _redirected_bot_findings(bot_entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    redirected = [entry for entry in bot_entries if 300 <= entry.status < 400]
    if not redirected:
        return []
    top = _top_path(redirected)
    return [
        _finding(
            "logs.googlebot_redirected",
            IssueSeverity.WARNING,
            "Googlebot spent crawl requests on redirects.",
            "Reduce avoidable redirect chains on important URLs and update internal references where possible.",
            _status_evidence(redirected),
            url=_absolute_url(top, config),
            count=len(redirected),
        )
    ]


def _crawl_waste_findings(bot_entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    wasted = [entry for entry in bot_entries if _is_crawl_waste(entry)]
    if not wasted:
        return []
    top = _top_path(wasted)
    return [
        _finding(
            "logs.crawl_waste",
            IssueSeverity.WARNING,
            "Googlebot spent requests on likely low-value URLs or assets.",
            "Review crawl budget signals, parameter handling, and static asset exposure.",
            [("Waste-like hits", str(len(wasted))), ("Top path", top)],
            url=_absolute_url(top, config),
            count=len(wasted),
        )
    ]


def _orphan_findings(bot_entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    known = _known_path_keys(config)
    if not known:
        return []
    orphan_paths = sorted(_bot_page_keys(bot_entries) - known)
    return (
        [
            _finding(
                "logs.orphan_crawled_urls",
                IssueSeverity.WARNING,
                "Googlebot crawled URLs that are not in the provided known URL set.",
                "Check whether these URLs are orphaned, stale, parameter variants, or missing from the crawl source.",
                [("Orphan URL count", str(len(orphan_paths))), ("Sample", _join_sample(orphan_paths))],
                url=_absolute_url(orphan_paths[0], config),
                count=len(orphan_paths),
            )
        ]
        if orphan_paths
        else []
    )


def _missing_important_findings(bot_entries: tuple[LogEntry, ...], config: LogAnalysisConfig) -> list[LogFinding]:
    known = _known_path_keys(config)
    if not known:
        return []
    missing = sorted(known - _bot_page_keys(bot_entries))
    return (
        [
            _finding(
                "logs.important_urls_not_hit",
                IssueSeverity.WARNING,
                "Important known URLs were not hit by Googlebot in the imported log sample.",
                "Verify the log date range, internal linking, sitemap coverage, and indexability of these URLs.",
                [("Missing URL count", str(len(missing))), ("Sample", _join_sample(missing))],
                url=_absolute_url(missing[0], config),
                count=len(missing),
            )
        ]
        if missing
        else []
    )


def _ai_bot_label(entry: LogEntry) -> str:
    """Return the AI-agent bot label for entry's UA, or "" if it's not one
    of the ai_* kinds (training / assistant / AI-search)."""
    classification = classify_bot(entry.user_agent)
    if classification is None or classification.kind not in AI_KINDS:
        return ""
    return classification.label


def _ai_agent_entries(entries: tuple[LogEntry, ...]) -> tuple[tuple[LogEntry, str], ...]:
    tagged = ((entry, _ai_bot_label(entry)) for entry in entries)
    return tuple(pair for pair in tagged if pair[1])


def _ai_agent_presence_findings(ai_entries: tuple[tuple[LogEntry, str], ...]) -> list[LogFinding]:
    if ai_entries:
        return []
    return [
        _finding(
            "logs.ai_agent_no_activity",
            IssueSeverity.INFO,
            "No AI-agent crawler activity (training, assistant, or AI-search bots) "
            "was found in the imported log sample.",
            "Informational only: AI-agent traffic is not required. Re-check log "
            "coverage and date range if you expected AI crawler hits.",
            [("AI-agent hits", "0")],
        )
    ]


def _ai_agent_blocked_findings(
    ai_entries: tuple[tuple[LogEntry, str], ...], config: LogAnalysisConfig
) -> list[LogFinding]:
    blocked = [(entry, label) for entry, label in ai_entries if entry.status >= 400]
    if not blocked:
        return []
    counts = Counter(label for _, label in blocked)
    top = _top_path(entry for entry, _ in blocked)
    return [
        _finding(
            "logs.ai_agent_blocked",
            IssueSeverity.WARNING,
            "AI-agent crawlers received client/server errors while fetching pages.",
            "Review blocking rules (WAF/CDN/robots), origin stability, and rate limits for AI-agent user agents.",
            [(label, str(count)) for label, count in counts.most_common()],
            url=_absolute_url(top, config),
            count=len(blocked),
        )
    ]


def _ai_agent_redirected_findings(
    ai_entries: tuple[tuple[LogEntry, str], ...], config: LogAnalysisConfig
) -> list[LogFinding]:
    redirected = [(entry, label) for entry, label in ai_entries if 300 <= entry.status < 400]
    if not redirected:
        return []
    counts = Counter(label for _, label in redirected)
    top = _top_path(entry for entry, _ in redirected)
    return [
        _finding(
            "logs.ai_agent_redirected",
            IssueSeverity.WARNING,
            "AI-agent crawlers spent fetches on redirects instead of final content.",
            "Reduce avoidable redirect chains on URLs that AI-agent crawlers fetch.",
            [(label, str(count)) for label, count in counts.most_common()],
            url=_absolute_url(top, config),
            count=len(redirected),
        )
    ]


def _issue_from_finding(finding: LogFinding) -> AuditIssue:
    return AuditIssue(
        issue_id=finding.finding_id,
        category=IssueCategory.LOGS,
        severity=finding.severity,
        source="Log analysis",
        reason=finding.reason,
        recommendation=finding.recommendation,
        evidence=finding.evidence,
        url=finding.url,
        scope="site",
        confidence="medium",
    )


def _finding(
    finding_id: str,
    severity: IssueSeverity,
    reason: str,
    recommendation: str,
    evidence: Iterable[tuple[str, object]],
    *,
    url: str = "",
    count: int = 0,
) -> LogFinding:
    return LogFinding(
        finding_id=finding_id,
        severity=severity,
        reason=reason,
        recommendation=recommendation,
        evidence=tuple(IssueEvidence(str(label), str(value)) for label, value in evidence),
        url=url,
        count=count,
    )


def _request_parts(request: str) -> tuple[str, str]:
    parts = request.split()
    if len(parts) < 2:
        return "", ""
    return parts[0].upper(), parts[1]


def _target_path(target: str) -> str:
    if not target or target == "-":
        return ""
    parsed = urlparse(target)
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


def _known_path_keys(config: LogAnalysisConfig) -> set[str]:
    return {_path_key(_target_path(url)) for url in config.important_urls if _target_path(url)}


def _bot_page_keys(entries: Iterable[LogEntry]) -> set[str]:
    return {_path_key(entry.path) for entry in entries if _is_page_candidate(entry)}


def _is_page_candidate(entry: LogEntry) -> bool:
    return entry.method in {"GET", "HEAD"} and 200 <= entry.status < 300 and not _has_waste_extension(entry.path)


def _is_crawl_waste(entry: LogEntry) -> bool:
    path = entry.path.lower()
    return "?" in path or _has_waste_extension(path) or any(part in path for part in _WASTE_PATH_PARTS)


def _has_waste_extension(path: str) -> bool:
    base = path.split("?", 1)[0].lower()
    return any(base.endswith(extension) for extension in _WASTE_EXTENSIONS)


def _path_key(path: str) -> str:
    parsed = urlparse(path)
    value = parsed.path or "/"
    if value != "/":
        value = value.rstrip("/")
    return value.lower()


def _status_evidence(entries: Iterable[LogEntry]) -> tuple[tuple[str, object], ...]:
    counts = Counter(entry.status for entry in entries)
    return tuple((str(status), count) for status, count in sorted(counts.items()))


def _top_path(entries: Iterable[LogEntry]) -> str:
    counts = Counter(entry.path for entry in entries if entry.path)
    return counts.most_common(1)[0][0] if counts else ""


def _absolute_url(path: str, config: LogAnalysisConfig) -> str:
    if not path or not config.site_base_url:
        return path
    base = urlparse(config.site_base_url)
    if not base.scheme or not base.netloc:
        return path
    return urlunparse((base.scheme, base.netloc, path, "", "", ""))


def _join_sample(values: Iterable[str], limit: int = 3) -> str:
    return ", ".join(list(values)[:limit]) or "-"


def _clean_missing(value: str | None) -> str:
    return "" if value in {None, "-"} else str(value)


def _to_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "LogAnalysisConfig",
    "LogAnalysisReport",
    "LogEntry",
    "LogFinding",
    "analyse_log_entries",
    "analyse_log_file",
    "issues_for_log_report",
    "parse_log_file",
    "parse_log_line",
]
