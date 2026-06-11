"""Crawl comparison / diff (v2.0 V8).

Compares two ``SiteCrawlReport``s by URL: which pages appeared, which
disappeared, which changed HTTP status, and which GEO Scores moved. Pure
+ typed; the GUI Diff dialog and the LLM export both consume the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .site_crawl_types import SiteCrawlReport, SiteCrawlResult


@dataclass(frozen=True)
class ScoreDelta:
    url: str
    previous: int
    current: int

    @property
    def delta(self) -> int:
        return self.current - self.previous


@dataclass(frozen=True)
class StatusChange:
    url: str
    previous: str
    current: str


@dataclass(frozen=True)
class CrawlDiff:
    new_urls: tuple[str, ...] = field(default_factory=tuple)
    removed_urls: tuple[str, ...] = field(default_factory=tuple)
    status_changes: tuple[StatusChange, ...] = field(default_factory=tuple)
    improved: tuple[ScoreDelta, ...] = field(default_factory=tuple)
    regressed: tuple[ScoreDelta, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not any((self.new_urls, self.removed_urls, self.status_changes, self.improved, self.regressed))

    def to_dict(self) -> dict[str, object]:
        return {
            "new_urls": list(self.new_urls),
            "removed_urls": list(self.removed_urls),
            "status_changes": [
                {"url": c.url, "previous": c.previous, "current": c.current} for c in self.status_changes
            ],
            "improved": [{"url": d.url, "previous": d.previous, "current": d.current} for d in self.improved],
            "regressed": [{"url": d.url, "previous": d.previous, "current": d.current} for d in self.regressed],
        }


def _by_url(results: Sequence[SiteCrawlResult]) -> dict[str, SiteCrawlResult]:
    return {r.url: r for r in results}


def diff_reports(previous: SiteCrawlReport, current: SiteCrawlReport) -> CrawlDiff:
    prev = _by_url(previous.results)
    curr = _by_url(current.results)
    prev_keys = set(prev)
    curr_keys = set(curr)

    new_urls = tuple(sorted(curr_keys - prev_keys))
    removed_urls = tuple(sorted(prev_keys - curr_keys))

    status_changes: list[StatusChange] = []
    improved: list[ScoreDelta] = []
    regressed: list[ScoreDelta] = []
    for url in sorted(prev_keys & curr_keys):
        a, b = prev[url], curr[url]
        if a.status != b.status:
            status_changes.append(StatusChange(url=url, previous=a.status, current=b.status))
        if b.geo_score != a.geo_score:
            delta = ScoreDelta(url=url, previous=a.geo_score, current=b.geo_score)
            (improved if delta.delta > 0 else regressed).append(delta)

    improved.sort(key=lambda d: d.delta, reverse=True)
    regressed.sort(key=lambda d: d.delta)
    return CrawlDiff(
        new_urls=new_urls,
        removed_urls=removed_urls,
        status_changes=tuple(status_changes),
        improved=tuple(improved),
        regressed=tuple(regressed),
    )


def diff_to_markdown(diff: CrawlDiff) -> str:
    if diff.is_empty:
        return "# Crawl diff\n\nNo changes between the two crawls."
    lines = ["# Crawl diff", ""]
    lines += _section("New URLs", diff.new_urls)
    lines += _section("Removed URLs", diff.removed_urls)
    if diff.status_changes:
        lines += ["## Status changes", ""]
        lines += [f"- {c.url}: {c.previous} -> {c.current}" for c in diff.status_changes]
        lines.append("")
    if diff.regressed:
        lines += ["## Regressed (GEO Score down)", ""]
        lines += [f"- {d.url}: {d.previous} -> {d.current} ({d.delta:+d})" for d in diff.regressed]
        lines.append("")
    if diff.improved:
        lines += ["## Improved (GEO Score up)", ""]
        lines += [f"- {d.url}: {d.previous} -> {d.current} ({d.delta:+d})" for d in diff.improved]
        lines.append("")
    return "\n".join(lines)


def _section(title: str, urls: Sequence[str]) -> list[str]:
    if not urls:
        return []
    return [f"## {title}", "", *[f"- {u}" for u in urls], ""]


__all__ = ["CrawlDiff", "ScoreDelta", "StatusChange", "diff_reports", "diff_to_markdown"]
