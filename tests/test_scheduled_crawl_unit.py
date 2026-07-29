"""Unit tests for the v3 G9 scheduled-crawl digest + orchestration."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import silentfrog.scheduled_crawl as scheduled_crawl
from silentfrog.audit_issues import IssueCategory, IssueSeverity
from silentfrog.crawl_history import CrawlHistoryIssue, CrawlHistoryRun, CrawlHistoryStore, diff_runs
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.scheduled_crawl import build_digest, run_scheduled_crawl
from silentfrog.site_crawl_types import SiteCrawlConfig, SiteCrawlReport, SiteCrawlResult


def _payload(url: str = "https://example.com/page", *, missing_title: bool = False) -> CrawlPayload:
    title = "" if missing_title else "Example"
    return CrawlPayload.from_raw(
        {
            "meta": [["title", title, str(len(title))], ["description", "Useful description text.", "24"]],
            "headers": [["h1", "Example"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}, "errors": []}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": title, "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {},
            "ai_visibility": {"summary": {"verdict": "Strong"}, "checks": []},
            "performance": {"status": 200, "summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _make_crawl_fn(*, missing_title: bool = False):
    async def _crawl_fn(config: SiteCrawlConfig, timeout: int, store: CrawlStore) -> SiteCrawlReport:
        result = SiteCrawlResult.from_payload("https://example.com/page", _payload(missing_title=missing_title))
        return SiteCrawlReport.from_results([result], discovered_count=1, base_url=config.base_url)

    return _crawl_fn


def _hist_issue(
    issue_id: str,
    severity: IssueSeverity,
    url: str,
    category: IssueCategory = IssueCategory.META,
) -> CrawlHistoryIssue:
    return CrawlHistoryIssue(
        issue_id=issue_id,
        severity=severity,
        category=category,
        url=url,
        reason=f"{issue_id} reason",
        recommendation="Fix it.",
        source=category.value,
        confidence="high",
    )


def _hist_run(run_id: str, issues: list[CrawlHistoryIssue]) -> CrawlHistoryRun:
    return CrawlHistoryRun(
        run_id=run_id,
        created_at="2026-01-01T00:00:00Z",
        scope_key="example.com",
        discovered_count=5,
        crawled_count=5,
        failed_count=1,
        skipped_count=0,
        issues=tuple(issues),
    )


# --- build_digest ------------------------------------------------------------


def test_build_digest_first_run_summarizes_own_issues() -> None:
    run = _hist_run(
        "run-1",
        [
            _hist_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),
            _hist_issue("crawl.http_error", IssueSeverity.CRITICAL, "https://example.com/b", IssueCategory.CRAWL),
        ],
    )

    digest = build_digest(run, None, "https://example.com/")

    assert digest.subject == "History: saved first run for example.com. Future crawls will show a diff."
    assert "Discovered 5, crawled 5, failed 1, skipped 0." in digest.markdown
    assert "Top hints" in digest.markdown
    # Critical outranks warning, so its headline (built from `reason`) leads.
    assert "crawl.http_error reason" in digest.markdown
    assert digest.json_data["counts"]["critical"] == 1
    assert digest.json_data["counts"]["warning"] == 1
    assert digest.json_data["health"] == {"current": run.health_score()}
    assert digest.json_data["previous_run_id"] == ""
    assert digest.json_data["hints"][0]["issue_id"] == "crawl.http_error"


def test_build_digest_with_diff_reports_trend_and_new_worsened_hints() -> None:
    previous = _hist_run(
        "run-1",
        [_hist_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/fixed")],
    )
    current = _hist_run(
        "run-2",
        [_hist_issue("crawl.http_error", IssueSeverity.CRITICAL, "https://example.com/new", IssueCategory.CRAWL)],
    )
    diff = diff_runs(previous, current)

    digest = build_digest(current, diff, "https://example.com/")

    assert "1 new, 1 fixed, 0 worsened, 0 recurring" in digest.subject
    assert diff.trend in digest.markdown
    assert "crawl.http_error reason" in digest.markdown  # from the new issue, not the fixed one
    assert "meta.title_missing reason" not in digest.markdown
    assert digest.json_data["new_count"] == 1
    assert digest.json_data["fixed_count"] == 1
    assert digest.json_data["worsened_count"] == 0
    assert digest.json_data["recurring_count"] == 0
    assert digest.json_data["previous_run_id"] == "run-1"
    assert digest.json_data["health"]["trend"] == diff.trend
    assert digest.json_data["health"]["delta"] == diff.health_delta
    assert digest.json_data["hints"][0]["issue_id"] == "crawl.http_error"


def test_build_digest_diff_falls_back_when_no_new_or_worsened_issues() -> None:
    # Only recurring issues (nothing new/worsened) -> the "fix first" list is
    # empty; the digest must say so instead of crashing on an empty group-by.
    previous = _hist_run(
        "run-1",
        [_hist_issue("links.bad_status", IssueSeverity.WARNING, "https://example.com/x", IssueCategory.LINKS)],
    )
    current = _hist_run(
        "run-2",
        [_hist_issue("links.bad_status", IssueSeverity.WARNING, "https://example.com/x", IssueCategory.LINKS)],
    )
    diff = diff_runs(previous, current)

    digest = build_digest(current, diff, "https://example.com/")

    assert digest.json_data["hints"] == []
    assert "No notable hints." in digest.markdown


# --- run_scheduled_crawl -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_scheduled_crawl_saves_history_and_diffs_on_second_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    config = SiteCrawlConfig.from_text(base_url="https://example.com/")

    report1, run1, diff1 = await run_scheduled_crawl(config, timeout=5, crawl_fn=_make_crawl_fn())
    assert diff1 is None
    assert CrawlHistoryStore().load_runs("example.com") == [run1]

    cli_crawls = tmp_path / "cli_crawls"
    assert len(list(cli_crawls.glob("crawl_*.db"))) == 1

    report2, run2, diff2 = await run_scheduled_crawl(config, timeout=5, crawl_fn=_make_crawl_fn(missing_title=True))
    assert diff2 is not None
    assert len(diff2.new_issues) >= 1
    assert len(list(cli_crawls.glob("crawl_*.db"))) == 2


@pytest.mark.asyncio
async def test_run_scheduled_crawl_prunes_old_dbs_to_retention_cap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    cli_crawls = tmp_path / "cli_crawls"
    cli_crawls.mkdir(parents=True)
    now = time.time()
    for i in range(12):
        dummy = cli_crawls / f"crawl_dummy_{i:02d}.db"
        dummy.write_bytes(b"")
        os.utime(dummy, (now - (100 - i), now - (100 - i)))
    assert len(list(cli_crawls.glob("crawl_*.db"))) == 12

    config = SiteCrawlConfig.from_text(base_url="https://example.com/")
    await run_scheduled_crawl(config, timeout=5, crawl_fn=_make_crawl_fn())

    remaining = list(cli_crawls.glob("crawl_*.db"))
    assert len(remaining) == 10


@pytest.mark.asyncio
async def test_run_scheduled_crawl_closes_store_even_when_crawl_fn_raises(tmp_path: Path, monkeypatch) -> None:
    # Regression guard: a prior version could leave the sqlite store open on a
    # crawl failure. Spy on CrawlStore.close() to prove `finally` always runs.
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    closed = {"count": 0}
    real_close = CrawlStore.close

    def _spy_close(self: CrawlStore) -> None:
        closed["count"] += 1
        real_close(self)

    monkeypatch.setattr(scheduled_crawl.CrawlStore, "close", _spy_close)

    async def _boom(config: SiteCrawlConfig, timeout: int, store: CrawlStore) -> SiteCrawlReport:
        raise RuntimeError("boom")

    config = SiteCrawlConfig.from_text(base_url="https://example.com/")
    with pytest.raises(RuntimeError):
        await run_scheduled_crawl(config, timeout=5, crawl_fn=_boom)

    assert closed["count"] == 1
