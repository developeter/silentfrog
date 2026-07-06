"""Prioritized hints engine (v3 G1).

Screaming Frog and Ahrefs list raw checks; Sitebulb leads with *hints* — one
row per issue type, ranked by how much it matters, saying what to fix first
and how many pages it touches. Silentfrog already produces rich per-URL
``AuditIssue`` records (severity + why + how-to-fix + evidence); this module
is the thin, pure aggregation that turns that stream into a ranked hint list.

A ``Hint`` groups every issue sharing an ``issue_id`` into a single finding
with a prevalence count and a priority score, so a site crawl surfaces
"Missing meta description — 142 pages — fix first" instead of 142 rows.

Pure + deterministic: no I/O, no Qt. The GUI recap and the LLM export both
render the same ranking.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .audit_issues import AuditIssue, IssueCategory, IssueSeverity, severity_rank

_SAMPLE_URL_CAP = 5

# Severity weight dominates the priority score; prevalence only breaks ties
# within a severity band, so one CRITICAL never sinks below many INFO issues.
_SEVERITY_WEIGHT = {
    IssueSeverity.CRITICAL: 1000.0,
    IssueSeverity.WARNING: 100.0,
    IssueSeverity.INFO: 10.0,
}


@dataclass(frozen=True, slots=True)
class Hint:
    issue_id: str
    category: IssueCategory
    severity: IssueSeverity
    title: str
    recommendation: str
    affected_urls: int
    sample_urls: tuple[str, ...]
    priority: float

    def headline(self, total_items: int = 0) -> str:
        """One-line summary, e.g. 'Missing meta description — 142 pages'."""
        if self.affected_urls <= 1:
            return self.title
        scope = f"{self.affected_urls} pages"
        if total_items > 1:
            scope = f"{self.affected_urls} of {total_items} pages"
        return f"{self.title} — {scope}"


def _priority(severity: IssueSeverity, affected_urls: int) -> float:
    # weight + a bounded prevalence bonus (never enough to cross a severity band).
    return _SEVERITY_WEIGHT[severity] + min(affected_urls, 99)


def build_hints(issues: Iterable[AuditIssue]) -> list[Hint]:
    """Aggregate issues by ``issue_id`` into priority-ranked hints.

    Ordering: highest severity first, then most-affected, then issue_id for a
    stable tie-break. Within a group the strongest severity seen wins (a check
    that is critical on one page and warning on another ranks as critical)."""
    grouped: dict[str, list[AuditIssue]] = {}
    for issue in issues:
        grouped.setdefault(issue.issue_id, []).append(issue)
    hints = [_hint_from_group(issue_id, group) for issue_id, group in grouped.items()]
    hints.sort(key=lambda h: (severity_rank(h.severity), -h.affected_urls, h.issue_id))
    return hints


def _hint_from_group(issue_id: str, group: Sequence[AuditIssue]) -> Hint:
    severity = min((issue.severity for issue in group), key=severity_rank)
    representative = next(issue for issue in group if issue.severity == severity)
    urls = _ordered_unique(issue.url for issue in group if issue.url)
    # A page-scoped single audit has no url; treat it as one affected item.
    affected = len(urls) if urls else 1
    return Hint(
        issue_id=issue_id,
        category=representative.category,
        severity=severity,
        title=representative.reason,
        recommendation=representative.recommendation,
        affected_urls=affected,
        sample_urls=tuple(urls[:_SAMPLE_URL_CAP]),
        priority=_priority(severity, affected),
    )


def _ordered_unique(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


__all__ = ["Hint", "build_hints"]
