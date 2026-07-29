"""Client-ready HTML report (v3 G8).

One self-contained ``.html`` file — inline CSS, zero JS, no external assets,
print-to-PDF friendly (``@media print``) — built from a completed Site Crawl.
This is the consultant-facing deliverable: a single file that can be emailed
or opened directly, unlike the Excel workbook (raw per-URL data) or the
Markdown/JSON LLM export (machine-facing).

``build_site_crawl_html`` is a pure derivation: the report's summary counts,
an already-streamed ``results`` list, and an already-computed ``issues`` list
in, one HTML string out — no I/O beyond the data it is handed. Score/status/
indexability aggregates are derived from ``results`` directly (every field
they need is already on ``SiteCrawlResult``), so the report never re-opens
the run-bound repository for a second SQL pass.

``export_site_crawl_html`` is the only I/O: it streams the crawl exactly
once (H1/H2 — never twice, unlike a naive implementation that streamed for
issues and again for the raw rows), loads scoped crawl history for the trend
section, stamps the current UTC time, and writes the file.

Every crawl-derived string (URLs, titles, issue reasons/recommendations) is
``html.escape()``-d before it reaches the template: a hostile page title
must never inject markup into a report a consultant hands to a client.
"""

from __future__ import annotations

import html
import string
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from .. import __version__
from ..audit_issues import AuditIssue, IssueSeverity, issues_for_results, severity_color_role
from ..crawl_history import CrawlHistoryRun, CrawlHistoryStore
from ..crawl_run_repository import stream_report_results
from ..crawl_trends import TrendPoint, build_trend
from ..hints import Hint, build_hints
from ..site_crawl_types import SiteCrawlReport, SiteCrawlResult
from ..theme import _LIGHT_TOKENS

_TOP_HINTS = 15
_WORST_PAGES = 25
_SCORE_BIN_WIDTH = 20
_SCORE_BIN_LABELS = ("0-19", "20-39", "40-59", "60-79", "80-100")
# Mirrors crawl_run_repository._NO_SCORE_STATUSES: failed/skipped rows carry no
# real GEO score, so they are excluded from every score-based aggregate below.
_NO_SCORE_STATUSES = frozenset({"error", "skipped"})

# Solid hex equivalents of theme.status_brushes' light-theme good/warn/bad RGB
# base colors (theme.py _LIGHT tints :206-209) — a printed report needs flat
# colors, not the translucent overlays a table row uses on screen.
_ROLE_TINTS = {
    "bad": "#d22828",
    "warn": "#f0b400",
    "info": _LIGHT_TOKENS["text2"],
}
_PALETTE = {**_LIGHT_TOKENS, "bad": _ROLE_TINTS["bad"], "warn": _ROLE_TINTS["warn"]}


def build_site_crawl_html(
    report: SiteCrawlReport,
    results: Sequence[SiteCrawlResult],
    issues: Sequence[AuditIssue],
    *,
    generated_at: str,
    history_runs: Sequence[CrawlHistoryRun] = (),
) -> str:
    """Pure derivation: build the full HTML document as one string."""
    hints = build_hints(issues)
    audited_pages = report.crawled_count + report.skipped_count
    total_items = max(1, report.discovered_count)  # matches AuditRecapWidget's convention
    sections = "".join(
        [
            _section_header(report, generated_at),
            _section_executive_summary(issues, audited_pages),
            _section_prioritized_actions(hints, total_items),
            _section_score_distribution(results),
            _section_status_indexability(results),
            _section_worst_pages(results),
            _section_health_trend(history_runs),
            _section_footer(),
        ]
    )
    head = f'<meta charset="utf-8" /><title>{_report_title(report)}</title><style>{_STYLE}</style>'
    body = f'<body><main class="report">{sections}</main></body>'
    return f'<!doctype html><html lang="en"><head>{head}</head>{body}</html>'


def export_site_crawl_html(report: SiteCrawlReport, file_path: Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    # Stream the full crawl exactly once (H1/H2): the same materialized list
    # backs the issues, every aggregate, and the worst-page table, so a large
    # store-backed crawl never decompresses its payloads twice.
    results = list(stream_report_results(report))
    issues = issues_for_results(results)
    document = build_site_crawl_html(
        report,
        results,
        issues,
        generated_at=_utc_now(),
        history_runs=_scoped_history_runs(report),
    )
    file_path.write_text(document, encoding="utf-8")


def _report_title(report: SiteCrawlReport) -> str:
    site = report.base_url or "site crawl"
    return html.escape(f"Silentfrog report — {site}")


def _scoped_history_runs(report: SiteCrawlReport) -> tuple[CrawlHistoryRun, ...]:
    # Mirrors crawl_history._scope_from_report's derivation (a private helper
    # in a module this PR does not touch, so the one-line scope key is
    # duplicated here rather than imported).
    scope = urlparse(report.base_url).netloc.lower() or "unknown"
    return tuple(CrawlHistoryStore().load_runs(scope))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _section(title: str, body_html: str) -> str:
    return f'<section class="report-section"><h2>{html.escape(title)}</h2>{body_html}</section>'


def _section_header(report: SiteCrawlReport, generated_at: str) -> str:
    site = html.escape(report.base_url or "(no base URL)")
    meta = html.escape(f"Generated {generated_at} · Silentfrog {__version__}")
    counts = html.escape(
        f"Discovered {report.discovered_count} · Crawled {report.crawled_count} · "
        f"Skipped {report.skipped_count} · Failed {report.failed_count}"
    )
    return (
        '<header class="report-header">'
        f"<h1>{site}</h1>"
        f'<p class="meta">{meta}</p>'
        f'<p class="counts">{counts}</p>'
        "</header>"
    )


def _section_executive_summary(issues: Sequence[AuditIssue], audited_pages: int) -> str:
    counts = Counter(issue.severity for issue in issues)
    critical = counts.get(IssueSeverity.CRITICAL, 0)
    warning = counts.get(IssueSeverity.WARNING, 0)
    info = counts.get(IssueSeverity.INFO, 0)
    verdict = html.escape(_verdict_sentence(audited_pages, critical, warning))
    stats = "".join(
        [
            _stat_card("Pages audited", audited_pages, ""),
            _stat_card("Critical", critical, "bad"),
            _stat_card("Warning", warning, "warn"),
            _stat_card("Info", info, ""),
        ]
    )
    body = f'<p class="verdict">{verdict}</p><div class="stat-row">{stats}</div>'
    return _section("Executive summary", body)


def _verdict_sentence(audited_pages: int, critical: int, warning: int) -> str:
    if critical:
        return f"{critical} critical issue(s) need immediate attention across {audited_pages} page(s) audited."
    if warning:
        return f"No critical issues; {warning} warning(s) to review across {audited_pages} page(s) audited."
    return f"No critical or warning issues across {audited_pages} page(s) audited — the site is in good shape."


def _stat_card(label: str, value: int, tint: str) -> str:
    css_class = f"stat-card stat-{tint}" if tint else "stat-card"
    return (
        f'<div class="{css_class}"><div class="stat-value">{value}</div>'
        f'<div class="stat-label">{html.escape(label)}</div></div>'
    )


def _section_prioritized_actions(hints: Sequence[Hint], total_items: int) -> str:
    top = hints[:_TOP_HINTS]
    if not top:
        return _section("Prioritized actions", '<p class="muted">No issues found — nothing to prioritize.</p>')
    rows = "".join(_hint_row(hint, total_items) for hint in top)
    return _section("Prioritized actions", f'<div class="hint-list">{rows}</div>')


def _hint_row(hint: Hint, total_items: int) -> str:
    tint = _ROLE_TINTS[severity_color_role(hint.severity)]
    headline = html.escape(hint.headline(total_items))
    recommendation = html.escape(hint.recommendation)
    return (
        f'<div class="hint-row" style="border-left-color: {tint};">'
        f'<div class="hint-headline">{headline}</div>'
        f'<div class="hint-recommendation">{recommendation}</div>'
        "</div>"
    )


def _section_score_distribution(results: Sequence[SiteCrawlResult]) -> str:
    scores = [result.geo_score for result in results if result.status not in _NO_SCORE_STATUSES]
    if not scores:
        return _section("GEO Score distribution", '<p class="muted">No data measured.</p>')
    return _section("GEO Score distribution", _score_bar_chart_svg(_score_bins(scores)))


def _score_bins(scores: Sequence[int]) -> list[tuple[str, int]]:
    counts = [0] * len(_SCORE_BIN_LABELS)
    for score in scores:
        clamped = max(0, min(100, score))
        counts[min(len(_SCORE_BIN_LABELS) - 1, clamped // _SCORE_BIN_WIDTH)] += 1
    return list(zip(_SCORE_BIN_LABELS, counts, strict=True))


def _score_bar_chart_svg(bins: Sequence[tuple[str, int]]) -> str:
    width, height, pad = 640, 220, 32
    plot_h = height - 2 * pad - 24  # reserve room for the axis note + labels
    max_count = max(count for _label, count in bins) or 1
    bar_w = (width - 2 * pad) / len(bins)
    bars = "".join(
        _score_bar(index, label, count, bar_w, plot_h, pad, max_count) for index, (label, count) in enumerate(bins)
    )
    note = html.escape("0-100, higher is better")
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="GEO Score distribution" class="chart">'
        f"{bars}"
        f'<text x="{pad}" y="{height - 6}" class="chart-note">{note}</text>'
        "</svg>"
    )


def _score_bar(index: int, label: str, count: int, bar_w: float, plot_h: int, pad: int, max_count: int) -> str:
    bar_h = (count / max_count) * plot_h
    x = pad + index * bar_w + bar_w * 0.15
    y = pad + plot_h - bar_h
    bar_width = bar_w * 0.7
    center = x + bar_width / 2
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_h:.1f}" class="chart-bar" />'
        f'<text x="{center:.1f}" y="{y - 6:.1f}" text-anchor="middle" class="chart-value">{count}</text>'
        f'<text x="{center:.1f}" y="{pad + plot_h + 16:.1f}" text-anchor="middle" class="chart-label">'
        f"{html.escape(label)}</text>"
    )


def _section_status_indexability(results: Sequence[SiteCrawlResult]) -> str:
    status_counts = _tally(result.status for result in results)
    indexability_counts = _tally(result.indexability for result in results)
    body = (
        '<div class="two-col">'
        f"{_compact_table('HTTP status', status_counts)}"
        f"{_compact_table('Indexability', indexability_counts)}"
        "</div>"
    )
    return _section("HTTP status & indexability", body)


def _tally(values: Iterable[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for value in values:
        key = value.strip() or "-"
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _compact_table(title: str, counts: Sequence[tuple[str, int]]) -> str:
    heading = html.escape(title)
    if not counts:
        return f'<div class="mini-table"><h3>{heading}</h3><p class="muted">No data measured.</p></div>'
    rows = "".join(f"<tr><td>{html.escape(key)}</td><td>{count}</td></tr>" for key, count in counts)
    return (
        f'<div class="mini-table"><h3>{heading}</h3>'
        f"<table><thead><tr><th>{heading}</th><th>Pages</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _section_worst_pages(results: Sequence[SiteCrawlResult]) -> str:
    measured = [result for result in results if result.status not in _NO_SCORE_STATUSES]
    worst = sorted(measured, key=lambda result: result.geo_score)[:_WORST_PAGES]
    if not worst:
        return _section("Worst pages", '<p class="muted">No data measured.</p>')
    rows = "".join(_worst_row(result) for result in worst)
    table = (
        '<table class="worst-table"><thead><tr><th>Page</th><th>GEO Score</th><th>Top issue</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )
    return _section("Worst pages", table)


def _worst_row(result: SiteCrawlResult) -> str:
    # The URL is always shown; the page <title> (untrusted, escaped) is added
    # above it when present so a consultant can scan real page labels rather
    # than a wall of raw URLs.
    url = html.escape(result.url)
    page_cell = url
    if result.title:
        page_cell = f'{html.escape(result.title)}<br /><span class="muted small">{url}</span>'
    reason = html.escape(result.issue_summary())
    return f"<tr><td>{page_cell}</td><td>{result.geo_score}</td><td>{reason}</td></tr>"


def _section_health_trend(history_runs: Sequence[CrawlHistoryRun]) -> str:
    if len(history_runs) < 2:
        return _section("Health trend", '<p class="muted">Trend appears after two crawls of this site.</p>')
    trend = build_trend(history_runs)
    label = html.escape("Health score (weighted issue count — lower is better).")
    chart = _trend_polyline_svg(trend.points)
    return _section("Health trend", f'<p class="muted">{label}</p>{chart}')


def _trend_polyline_svg(points: Sequence[TrendPoint]) -> str:
    width, height, pad = 640, 200, 32
    scores = [point.health_score for point in points]
    max_score = max(scores) or 1
    plot_w, plot_h = width - 2 * pad, height - 2 * pad
    step = plot_w / max(1, len(points) - 1)
    coords = [(pad + index * step, pad + plot_h - (score / max_score) * plot_h) for index, score in enumerate(scores)]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" class="trend-dot" />' for x, y in coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Health score trend" class="chart">'
        f'<polyline points="{path}" class="trend-line" fill="none" />'
        f"{dots}"
        "</svg>"
    )


def _section_footer() -> str:
    return '<footer class="report-footer"><p>Generated by Silentfrog — local-first SEO/GEO auditor.</p></footer>'


# One template (string.Template, because CSS is full of literal braces
# str.format would misparse — the same reason theme.py's QSS template uses
# it) substituted with the exact light-theme tokens (P6) plus the two
# severity-tint hex values, so the report reuses one palette source, never a
# hardcoded duplicate.
_STYLE_TEMPLATE = string.Template("""
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
    background: $bg0; color: $text;
    font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
    font-size: 15px; line-height: 1.5;
}
.report { max-width: 960px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 18px; margin: 0 0 12px; border-bottom: 2px solid $accent; padding-bottom: 6px; }
h3 { font-size: 14px; margin: 0 0 8px; color: $text2; }
p { margin: 0 0 8px; }
.muted { color: $text2; }
.small { font-size: 12px; }
.report-header { margin-bottom: 28px; }
.meta, .counts { color: $text2; font-size: 13px; margin: 2px 0; }
.report-section {
    background: $bg1; border: 1px solid $border; border-radius: 10px;
    padding: 20px 24px; margin-bottom: 20px;
}
.verdict { font-size: 16px; font-weight: 600; margin-bottom: 16px; }
.stat-row { display: flex; flex-wrap: wrap; gap: 12px; }
.stat-card {
    flex: 1 1 120px; background: $bg2; border: 1px solid $border; border-radius: 8px;
    padding: 12px 14px; text-align: center;
}
.stat-value { font-size: 24px; font-weight: 700; }
.stat-label { font-size: 12px; color: $text2; margin-top: 2px; }
.stat-bad .stat-value { color: $bad; }
.stat-warn .stat-value { color: $warn; }
.hint-list { display: flex; flex-direction: column; gap: 10px; }
.hint-row { border-left: 4px solid $border_strong; background: $bg2; border-radius: 6px; padding: 10px 14px; }
.hint-headline { font-weight: 600; margin-bottom: 3px; }
.hint-recommendation { color: $text2; font-size: 13.5px; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid $border; }
th { color: $text2; font-weight: 600; }
.two-col { display: flex; gap: 24px; flex-wrap: wrap; }
.mini-table { flex: 1 1 260px; }
.worst-table td:nth-child(2) { text-align: right; width: 90px; }
.chart { width: 100%; height: auto; max-width: 640px; display: block; }
.chart-bar { fill: $accent; }
.chart-value, .chart-label, .chart-note { fill: $text2; font-size: 11px; }
.trend-line { stroke: $accent; stroke-width: 2; }
.trend-dot { fill: $accent; }
.report-footer { color: $text2; font-size: 12px; text-align: center; margin-top: 24px; }
@media print {
    @page { margin: 16mm; }
    body { background: #ffffff; }
    .report { max-width: none; padding: 0; }
    .report-section { border: 1px solid #ccc; break-inside: avoid; page-break-inside: avoid; }
    tr, .hint-row, .stat-card { break-inside: avoid; page-break-inside: avoid; }
}
""")

_STYLE = _STYLE_TEMPLATE.substitute(_PALETTE)


__all__ = ["build_site_crawl_html", "export_site_crawl_html"]
