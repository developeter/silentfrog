from __future__ import annotations

from pathlib import Path

from silentfrog.audit_issues import IssueCategory, IssueSeverity  # type: ignore[reportMissingImports]
from silentfrog.log_analysis import (  # type: ignore[reportMissingImports]
    LogAnalysisConfig,
    analyse_log_entries,
    analyse_log_file,
    issues_for_log_report,
    parse_log_line,
)
from silentfrog.logs import is_google_crawler

_GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
_USER = "Mozilla/5.0"
_GPTBOT = "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)"


def _line(path: str, status: int, agent: str = _GOOGLEBOT) -> str:
    return f'66.249.66.1 - - [05/May/2026:10:00:00 +0000] "GET {path} HTTP/1.1" {status} 123 "-" "{agent}"'


def test_parse_log_line_reads_common_combined_log_fields() -> None:
    entry = parse_log_line(_line("/design/table/?color=blue", 200))

    assert entry is not None
    assert entry.ip == "66.249.66.1"
    assert entry.method == "GET"
    assert entry.path == "/design/table/"  # query dropped (M6: shared logs.LogEntry)
    assert entry.target == "/design/table/?color=blue"  # query preserved here
    assert entry.status == 200
    assert entry.bytes == 123
    assert is_google_crawler(entry.user_agent) is True


def test_analyse_log_entries_reports_seo_bot_findings() -> None:
    entries = [
        parse_log_line(_line("/design/table/", 200)),
        parse_log_line(_line("/design/private/", 403)),
        parse_log_line(_line("/old-url/", 301)),
        parse_log_line(_line("/assets/app.js", 200)),
        parse_log_line(_line("/orphan/", 200)),
        parse_log_line(_line("/normal-user/", 200, _USER)),
    ]
    config = LogAnalysisConfig(
        site_base_url="https://example.com",
        important_urls=(
            "https://example.com/design/table/",
            "https://example.com/missing-important/",
        ),
    )

    report = analyse_log_entries([entry for entry in entries if entry], config)
    findings = {finding.finding_id: finding for finding in report.findings}

    assert report.total_requests == 6
    assert report.googlebot_hits == 5
    assert findings["logs.googlebot_blocked"].severity == IssueSeverity.CRITICAL
    assert findings["logs.googlebot_blocked"].url == "https://example.com/design/private/"
    assert findings["logs.googlebot_redirected"].severity == IssueSeverity.WARNING
    assert findings["logs.crawl_waste"].count == 1
    assert findings["logs.orphan_crawled_urls"].count == 1
    assert findings["logs.important_urls_not_hit"].url == "https://example.com/missing-important"


def test_analyse_log_entries_flags_ai_agent_blocked() -> None:
    entries = [
        parse_log_line(_line("/blocked-for-ai/", 403, _GPTBOT)),
        parse_log_line(_line("/design/table/", 200)),
    ]

    report = analyse_log_entries([entry for entry in entries if entry])
    findings = {finding.finding_id: finding for finding in report.findings}

    assert "logs.ai_agent_blocked" in findings
    blocked = findings["logs.ai_agent_blocked"]
    assert blocked.severity == IssueSeverity.WARNING
    assert blocked.count == 1
    assert any(evidence.label == "GPTBot" for evidence in blocked.evidence)


def test_analyse_log_entries_flags_ai_agent_redirected() -> None:
    entries = [parse_log_line(_line("/moved-for-ai/", 301, _GPTBOT))]

    report = analyse_log_entries([entry for entry in entries if entry])
    findings = {finding.finding_id: finding for finding in report.findings}

    assert findings["logs.ai_agent_redirected"].severity == IssueSeverity.WARNING
    assert findings["logs.ai_agent_redirected"].count == 1


def test_analyse_log_entries_ai_agent_no_activity_is_info_not_warning() -> None:
    # Sec 1.5 myth rule: absence of a not-required signal is info, never a
    # warning/critical penalty — even though the sibling Googlebot-absence
    # finding (below) is a warning by longstanding precedent.
    entries = [parse_log_line(_line("/page/", 200))]

    report = analyse_log_entries([entry for entry in entries if entry])
    findings = {finding.finding_id: finding for finding in report.findings}

    assert findings["logs.ai_agent_no_activity"].severity == IssueSeverity.INFO


def test_analyse_log_entries_flags_missing_googlebot_activity() -> None:
    entry = parse_log_line(_line("/page/", 200, _USER))

    report = analyse_log_entries([entry for entry in [entry] if entry])

    assert report.googlebot_hits == 0
    assert report.findings[0].finding_id == "logs.no_googlebot_activity"


def test_issues_for_log_report_maps_findings_to_audit_issues() -> None:
    entry = parse_log_line(_line("/blocked/", 500))
    report = analyse_log_entries(
        [entry for entry in [entry] if entry], LogAnalysisConfig(site_base_url="https://example.com")
    )

    issues = issues_for_log_report(report)

    assert issues[0].category == IssueCategory.LOGS
    assert issues[0].source == "Log analysis"
    assert issues[0].url == "https://example.com/blocked/"
    assert issues[0].confidence == "medium"


def test_analyse_log_file_reads_local_file_only(tmp_path: Path) -> None:
    path = tmp_path / "access.log"
    path.write_text("\n".join([_line("/page/", 200), "not a valid access log line"]), encoding="utf-8")

    report = analyse_log_file(path)

    assert report.total_requests == 1
    assert report.googlebot_hits == 1
