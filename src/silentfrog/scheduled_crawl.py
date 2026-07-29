"""Scheduled crawls + alert digest (v3 G9).

A one-shot headless crawl entry point for OS-level schedulers (Windows Task
Scheduler / cron). Per §4.5 supply-chain hygiene (mirroring
``watch_mode.py``'s documented policy), this deliberately does NOT bundle a
scheduler dependency: ``run_scheduled_crawl`` runs exactly one crawl per
invocation and the OS scheduler decides when to invoke it again.

``run_scheduled_crawl`` drives a full site crawl through the same
``crawl_site`` orchestration the GUI uses (store-backed, so "View past
scans" can reopen the run), saves it to crawl history, and returns the
history run + diff. ``build_digest`` turns those into a human/machine
digest — pure, no I/O, so it is trivially testable and reusable by any
future delivery surface.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .audit_issues import IssueSeverity
from .crawl_history import (
    CrawlHistoryDiff,
    CrawlHistoryRun,
    CrawlHistoryStore,
    format_history_status,
    save_report_and_diff,
)
from .crawl_store import CrawlStore
from .hints import Hint, build_hints
from .site_crawl_types import SiteCrawlConfig, SiteCrawlReport
from .site_crawler import crawl_site

_CLI_CRAWLS_SUBDIR = "cli_crawls"
# Mirrors site_crawl_gui.py's _STORED_CRAWL_RETENTION. Duplicated by value
# (not imported) — this module must stay Qt-free and the GUI module is out
# of bounds for this change; keep the two constants in sync by hand.
_RETENTION = 10
_TOP_HINTS_CAP = 8
_APP_DIR = "Silentfrog"

CrawlFn = Callable[[SiteCrawlConfig, int, CrawlStore], Awaitable[SiteCrawlReport]]


@dataclass(frozen=True, slots=True)
class Digest:
    subject: str
    markdown: str
    json_data: dict[str, object]


def build_digest(current_run: CrawlHistoryRun, diff: CrawlHistoryDiff | None, base_url: str) -> Digest:
    """Build the alert digest for one completed scheduled crawl.

    ``diff`` is ``None`` on the very first crawl for a scope (nothing to
    compare against yet) — that digest summarizes the run's own issues
    instead of a delta."""
    subject = format_history_status(current_run, diff)
    if diff is None:
        hints = build_hints(issue.to_audit_issue() for issue in current_run.issues)[:_TOP_HINTS_CAP]
        return Digest(
            subject=subject,
            markdown=_first_run_markdown(current_run, base_url, hints),
            json_data=_first_run_json(current_run, base_url, hints),
        )
    hint_issues = (*diff.new_issues, *diff.worsened_issues)
    hints = build_hints(issue.to_audit_issue() for issue in hint_issues)[:_TOP_HINTS_CAP]
    return Digest(
        subject=subject,
        markdown=_diff_markdown(current_run, diff, base_url, hints),
        json_data=_diff_json(current_run, diff, base_url, hints),
    )


async def run_scheduled_crawl(
    config: SiteCrawlConfig,
    *,
    timeout: int,
    data_dir: Path | str | None = None,
    crawl_fn: CrawlFn | None = None,
    history_store: CrawlHistoryStore | None = None,
) -> tuple[SiteCrawlReport, CrawlHistoryRun, CrawlHistoryDiff | None]:
    """Run one full site crawl, save it to history, and return its digest inputs.

    ``crawl_fn`` is injectable for tests (default wraps ``crawl_site``
    against a fresh on-disk ``CrawlStore``, mirroring ``workers._open_store``
    so a CLI-scheduled run reopens in the GUI exactly like a GUI-run crawl).
    The store is ALWAYS closed, even if the crawl raises, so a failed run
    never leaves a locked sqlite file behind."""
    root = _cli_crawls_dir(data_dir)
    store = CrawlStore(_db_path_for_run(root))
    crawl = crawl_fn or _default_crawl_fn
    try:
        report = await crawl(config, timeout, store)
    finally:
        store.close()
    history = history_store or CrawlHistoryStore()
    run, diff = save_report_and_diff(history, report)
    _prune_cli_crawls(root)
    return report, run, diff


async def _default_crawl_fn(config: SiteCrawlConfig, timeout: int, store: CrawlStore) -> SiteCrawlReport:
    return await crawl_site(config, timeout=timeout, store=store)


# --- digest content builders ------------------------------------------------


def _counts_line(run: CrawlHistoryRun) -> str:
    return (
        f"Discovered {run.discovered_count}, crawled {run.crawled_count}, "
        f"failed {run.failed_count}, skipped {run.skipped_count}."
    )


def _hint_lines(hints: list[Hint]) -> list[str]:
    if not hints:
        return ["- No notable hints."]
    return [f"- {hint.headline()}" for hint in hints]


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _first_run_markdown(run: CrawlHistoryRun, base_url: str, hints: list[Hint]) -> str:
    lines = [
        f"# Silentfrog scheduled crawl — {base_url or run.scope_key}",
        "",
        f"History: saved first run for {run.scope_key}. Future crawls will show a diff.",
        "",
        f"- {_counts_line(run)}",
        f"- Health score: {run.health_score()} (lower is better)",
        "",
        "## Top hints",
        *_hint_lines(hints),
    ]
    return "\n".join(lines)


def _diff_markdown(run: CrawlHistoryRun, diff: CrawlHistoryDiff, base_url: str, hints: list[Hint]) -> str:
    lines = [
        f"# Silentfrog scheduled crawl — {base_url or run.scope_key}",
        "",
        format_history_status(run, diff),
        "",
        f"- {_counts_line(run)}",
        f"- Health score: {diff.current_health_score} (previous {diff.previous_health_score}, "
        f"{_signed(diff.health_delta)}) — {diff.trend}",
        "",
        "## Top hints (new + worsened)",
        *_hint_lines(hints),
    ]
    return "\n".join(lines)


def _base_json(run: CrawlHistoryRun, base_url: str) -> dict[str, object]:
    return {
        "base_url": base_url,
        "scope_key": run.scope_key,
        "run_id": run.run_id,
        "created_at": run.created_at,
        "counts": {
            "discovered": run.discovered_count,
            "crawled": run.crawled_count,
            "failed": run.failed_count,
            "skipped": run.skipped_count,
            "critical": run.severity_count(IssueSeverity.CRITICAL),
            "warning": run.severity_count(IssueSeverity.WARNING),
            "info": run.severity_count(IssueSeverity.INFO),
        },
    }


def _hint_dicts(hints: list[Hint]) -> list[dict[str, object]]:
    return [{"issue_id": hint.issue_id, "headline": hint.headline(), "severity": hint.severity.value} for hint in hints]


def _first_run_json(run: CrawlHistoryRun, base_url: str, hints: list[Hint]) -> dict[str, object]:
    data = _base_json(run, base_url)
    data["health"] = {"current": run.health_score()}
    data["hints"] = _hint_dicts(hints)
    data["previous_run_id"] = ""
    return data


def _diff_json(
    run: CrawlHistoryRun,
    diff: CrawlHistoryDiff,
    base_url: str,
    hints: list[Hint],
) -> dict[str, object]:
    data = _base_json(run, base_url)
    data["health"] = {
        "current": diff.current_health_score,
        "previous": diff.previous_health_score,
        "delta": diff.health_delta,
        "trend": diff.trend,
    }
    data["hints"] = _hint_dicts(hints)
    data["previous_run_id"] = diff.previous_run_id
    data["new_count"] = len(diff.new_issues)
    data["fixed_count"] = len(diff.fixed_issues)
    data["worsened_count"] = len(diff.worsened_issues)
    data["recurring_count"] = len(diff.recurring_issues)
    return data


# --- store path + retention --------------------------------------------------


def _cli_crawls_dir(data_dir: Path | str | None) -> Path:
    root = _data_root(data_dir) / _CLI_CRAWLS_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _data_root(data_dir: Path | str | None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return _platform_data_root()


def _platform_data_root() -> Path:
    # Mirrors crawl_history._platform_data_root() (duplicated rather than
    # imported to keep this module decoupled from crawl_history's internals).
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / _APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / _APP_DIR.lower()


def _db_path_for_run(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    candidate = root / f"crawl_{stamp}.db"
    if not candidate.exists():
        return candidate
    # Same-second collision (rare, e.g. a manual test run) — stay unique
    # rather than silently reopening a previous run's store.
    return root / f"crawl_{stamp}_{uuid.uuid4().hex[:6]}.db"


def _prune_cli_crawls(root: Path, keep: int = _RETENTION) -> None:
    """Keep the ``keep`` newest crawl databases in ``root``; unlink the rest
    (best effort), mirroring site_crawl_gui.py's ``_prune_stored_crawls``."""
    try:
        candidates = sorted(root.glob("crawl_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in candidates[max(0, keep) :]:
        _discard_store(stale)


def _discard_store(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            pass


__all__ = ["CrawlFn", "Digest", "build_digest", "run_scheduled_crawl"]
