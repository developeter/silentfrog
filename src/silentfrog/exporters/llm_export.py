"""LLM-friendly export (v2.0 V5, rewritten for PR-C).

Produces a self-contained Markdown (+ JSON mirror) evidence dossier of an
audit so an AI assistant can act on it without asking for more context: every
fact Silentfrog measured, the unified prioritised issue list with evidence,
and an explicit "not measured / feature off" marker for optional signals
(never silently omitted, never presented as a failure — CLAUDE.md §1.5).

- ``export_page_for_llm`` — full single-page dossier (identity, GEO score,
  issues, checks by area, content, links/images, international/structured
  data, performance, AI-crawler access, optional integrations).
- ``export_crawl_for_llm`` — site-wide dossier (crawl summary, hints,
  duplicates, error/redirect pages, common failing checks, discovery facts,
  a full page index) + worst-N pages in page-dossier-compact form.
- ``write_llm_export`` — writes ``.md`` and/or ``.json``.

``mode``: ``"full"`` keeps every check/issue row; ``"compact"`` keeps only
``warning``/``critical`` rows and collapses ``good`` checks to a per-area
count. Both GUI "Export for AI analysis" buttons pass ``mode="full"``; the
CLI/MCP default stays ``"compact"`` for a lighter paste.

Every section builder tolerates missing/empty/odd-shaped data (payloads from
older stores, opt-in groups that are ``{}``) and renders an explicit
placeholder instead of silently dropping the section. Table cells go through
one ``_cell`` escaper; long lists are capped with an explicit ``(+N more)``
marker; the whole markdown document is capped at ~1.5 MB as a final backstop.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..audit_issues import IssueSeverity, issues_for_payload, issues_for_results
from ..content_quality import build_content_quality_rows
from ..hints import build_hints
from ..image_diagnostics import ALT_COL, SIZE_COL, SRC_COL
from ..indexability import build_indexability_rows

_PREAMBLE = """# Silentfrog SEO/GEO audit — for AI analysis

You are a senior technical SEO and GEO (Generative Engine Optimization)
consultant. This file is a self-contained evidence dossier: every fact
Silentfrog's audit measured, plus a unified prioritised issue list with
evidence and recommendations. Read it and produce, in priority order:

1. A prioritised fix list — severity, the exact page/element, the exact
   change to make, why it matters, and the expected impact.
2. Quick wins — small changes with outsized impact.
3. What is already good — call it out explicitly so it doesn't get broken
   by a later change.
4. Open questions — anything you cannot answer from the evidence below;
   ask rather than guess.

Cite the section and evidence you used for each recommendation.

## How to read this file
- **GEO Score** (0-100): higher is better, derived from the check list —
  every `warning` costs points, every `critical` costs more.
- **Status** of a check or issue:
  - `critical` — fix first; materially hurts AI/search visibility.
  - `warning` — should fix.
  - `good` — already correct; don't break it.
  - `info` — not measured or not applicable; it NEVER counts against the
    score (Silentfrog never penalises an absent optional signal — the
    myth rule, CLAUDE.md §1.5).
- An optional signal that was never run (an opt-in integration, a feature
  toggle left off) is marked "Not measured (feature off)" — that is
  neutral, never presented as a failure.
- Compact exports keep only `warning`/`critical` rows in check tables and
  collapse `good` checks to a per-area count.
"""

_COMPACT_STATUSES = {"warning", "critical"}
_STATUS_ORDER = {"critical": 0, "warning": 1, "good": 2, "info": 3}
_MAX_MARKDOWN_BYTES = 1_500_000
_OVERSIZED_KB = 200
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_DUP_GROUP_CAP = 25
_DUP_URL_CAP = 10
_DISCOVERY_LABELS = (
    ("llms_txt", "llms.txt"),
    ("llms_full_txt", "llms-full.txt"),
    ("well_known_ai_json", ".well-known/ai.json"),
    ("sitemap", "sitemap.xml"),
)
_INTEGRATION_SECTIONS = (
    ("gsc", "Google Search Console"),
    ("ga4", "Google Analytics 4"),
    ("semrush", "Semrush authority"),
    ("ai_sov", "AI share of voice"),
    ("brand_mentions", "Brand mentions"),
    ("topic_embeddings", "Topic embeddings"),
)


@dataclass(frozen=True)
class LlmExport:
    markdown: str
    json_data: dict[str, Any]

    @property
    def json_text(self) -> str:
        return json.dumps(self.json_data, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Generic rendering helpers (shared by the page and crawl dossiers)
# --------------------------------------------------------------------------


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = [f"| {' | '.join(headers)} |", f"|{'---|' * len(headers)}"]
    lines.extend(f"| {' | '.join(_cell(v) for v in row)} |" for row in rows)
    return lines


def _table_or_empty(headers: Sequence[str], rows: Sequence[Sequence[Any]], empty_text: str) -> list[str]:
    if not rows:
        return [empty_text, ""]
    return [*_md_table(headers, rows), ""]


def _titled_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[Any]], empty_text: str) -> list[str]:
    return [f"### {title}", "", *_table_or_empty(headers, rows, empty_text)]


def _capped(items: Sequence[Any], cap: int) -> tuple[list[Any], int]:
    materialized = list(items)
    return materialized[:cap], max(0, len(materialized) - cap)


def _more_note(remainder: int) -> list[str]:
    return [f"_(+{remainder} more)_", ""] if remainder else []


def _join(values: Iterable[Any]) -> str:
    return ", ".join(str(v) for v in values if str(v).strip()) or "-"


def _join_capped(values: Sequence[Any], cap: int) -> str:
    kept, remainder = _capped(list(values), cap)
    text = _join(kept)
    return f"{text} (+{remainder} more)" if remainder else text


def _dict_rows(data: Mapping[str, Any]) -> list[list[Any]]:
    return [[str(k).replace("_", " ").title(), v] for k, v in data.items() if str(v).strip()]


def _scalar(value: Any) -> str:
    if isinstance(value, Mapping):
        return _join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return _join(value)
    return str(value)


def _kv_lines(data: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in data.items():
        if key == "measured" or value in ("", None, [], {}):
            continue
        label = str(key).replace("_", " ").strip().capitalize()
        lines.append(f"- {label}: {_scalar(value)}")
    return lines


def _group_kv_section(title: str, data: Mapping[str, Any]) -> list[str]:
    if not data:
        return [f"### {title}", "", "- Not measured (feature off).", ""]
    return [f"### {title}", "", *_kv_lines(data), ""]


def _is_measured(data: Any) -> bool:
    return isinstance(data, Mapping) and bool(data.get("measured"))


def _not_measured_lines(title: str, data: Any) -> list[str]:
    """Placeholder section for an unmeasured signal: the recorded reason when
    the feature ran and could not measure, else the plain "feature off"."""
    reason = str(data.get("reason") or "").strip() if isinstance(data, Mapping) else ""
    note = f"- Not measured: {reason}" if reason else "- Not measured (feature off)."
    return [f"### {title}", "", note, ""]


def _row_cell(row: Sequence[Any], index: int) -> str:
    return str(row[index]).strip() if len(row) > index else ""


def _to_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _meta_value(payload: Any, name: str) -> str:
    expected = name.lower()
    for row in payload.meta:
        if len(row) > 1 and str(row[0]).strip().lower() == expected:
            return str(row[1]).strip()
    return ""


def _apply_size_cap(markdown: str) -> str:
    encoded = markdown.encode("utf-8")
    if len(encoded) <= _MAX_MARKDOWN_BYTES:
        return markdown
    truncated = encoded[:_MAX_MARKDOWN_BYTES].decode("utf-8", errors="ignore")
    cut = truncated.rfind("\n")
    body = truncated[:cut] if cut > 0 else truncated
    return body + "\n\n_(truncated: export exceeded the 1.5 MB cap; remaining lists were cut)_\n"


def _visible_checks(checks: Sequence[Any], mode: str) -> list[Any]:
    if mode == "full":
        return list(checks)
    return [c for c in checks if c.status in _COMPACT_STATUSES]


def _filtered_issues(issues: Sequence[Any], mode: str) -> list[Any]:
    if mode == "full":
        return list(issues)
    return [issue for issue in issues if issue.severity != IssueSeverity.INFO]


def _sorted_checks(checks: Sequence[Any]) -> list[Any]:
    return sorted(checks, key=lambda c: _STATUS_ORDER.get(c.status, 4))


def _issue_block(issue: Any) -> list[str]:
    lines = [
        f"- **[{issue.severity.value.upper()}] {issue.category.value}** — {issue.reason}",
        f"  - Recommendation: {issue.recommendation}",
        f"  - Confidence: {issue.confidence}",
    ]
    evidence = list(issue.evidence)[:8]
    if evidence:
        lines.append("  - Evidence: " + "; ".join(f"{e.label}: {e.value}" for e in evidence))
    lines.append("")
    return lines


def _page_metrics(payload: Any, url: str) -> dict[str, Any]:
    summary = payload.ai_visibility.summary
    return {
        "url": url,
        "geo_score": summary.score,
        "verdict": summary.verdict or "-",
        "good": summary.good_count,
        "warnings": summary.warning_count,
        "critical": summary.critical_count,
        "title": _meta_value(payload, "title"),
        "meta_description": _meta_value(payload, "description"),
        "word_count": payload.content_quality.word_count,
    }


# --------------------------------------------------------------------------
# Page dossier — section builders (1..10)
# --------------------------------------------------------------------------


def _robots_directive_lines(robots: Mapping[str, Any]) -> list[str]:
    rows = [[agent, verb, value] for agent, directives in sorted(robots.items()) for verb, value in directives]
    return _titled_table("robots.txt directives", ["Agent", "Directive", "Value"], rows, "- None found.")


def _discovery_row(entry: Any, label: str) -> list[Any]:
    entry = entry if isinstance(entry, Mapping) else {}
    present = "Yes" if entry.get("present") else "No"
    return [label, present, entry.get("status", 0), entry.get("url", "-")]


def _discovery_lines(discovery: Mapping[str, Any]) -> list[str]:
    title = "Discovery files (llms.txt / ai.json / sitemap)"
    if not discovery:
        return [f"### {title}", "", "- Not measured (feature off).", ""]
    rows = [_discovery_row(discovery.get(key), label) for key, label in _DISCOVERY_LABELS]
    return _titled_table(title, ["File", "Present", "Status", "URL"], rows, "- None found.")


_IDENTITY_SKIP_LABELS = {"requested url", "final url"}


def _section_identity(payload: Any, url: str) -> list[str]:
    final_url = payload.final_url or (payload.redirect.chain[-1] if payload.redirect.chain else url)
    lines = [
        "## 1. Page identity",
        "",
        f"- Requested URL: {payload.requested_url or url}",
        f"- Final URL: {final_url}",
        "",
    ]
    index_rows = build_indexability_rows(
        payload.redirect.to_dict(), payload.canonical.to_dict(), payload.meta_robots, payload.robots
    )
    # The requested/final URL rows above already cover build_indexability_rows'
    # first two entries (from the H0-tracked payload fields, not just the
    # redirect chain) — skip them here so the dossier doesn't repeat itself.
    lines.extend(
        f"- {label}: {value}" for label, value in index_rows if label.strip().lower() not in _IDENTITY_SKIP_LABELS
    )
    lines.append("")
    lines.extend(_robots_directive_lines(payload.robots))
    lines.extend(_discovery_lines(payload.discovery))
    return lines


def _area_breakdown(checks: Sequence[Any]) -> list[list[Any]]:
    counts: dict[str, Counter[str]] = {}
    for check in checks:
        counts.setdefault(check.area or "-", Counter())[check.status] += 1
    return [
        [area, c.get("good", 0), c.get("warning", 0), c.get("critical", 0), c.get("info", 0)]
        for area, c in sorted(counts.items())
    ]


def _section_geo_score(payload: Any) -> list[str]:
    summary = payload.ai_visibility.summary
    lines = [
        "## 2. GEO score",
        "",
        f"- GEO Score: {summary.score}/100",
        f"- Verdict: {summary.verdict or '-'}",
        f"- Good: {summary.good_count}  Warning: {summary.warning_count}  Critical: {summary.critical_count}",
        "",
    ]
    breakdown = _area_breakdown(payload.ai_visibility.checks)
    headers = ["Area", "Good", "Warning", "Critical", "Info"]
    lines.extend(_titled_table("Per-area breakdown", headers, breakdown, "- None found."))
    return lines


def _section_issues(url: str, payload: Any, mode: str) -> list[str]:
    issues = _filtered_issues(issues_for_payload(url, payload), mode)
    lines = ["## 3. Prioritised issues", ""]
    if not issues:
        return [*lines, "- None found.", ""]
    for issue in issues:
        lines.extend(_issue_block(issue))
    return lines


def _area_check_block(area: str, checks: Sequence[Any], mode: str) -> list[str]:
    visible = _sorted_checks(_visible_checks(checks, mode))
    good_count = sum(1 for c in checks if c.status == "good")
    lines = [f"### {area}", ""]
    if mode != "full" and good_count:
        lines.append(f"- {good_count} check(s) good (not shown).")
    rows = [[c.status, c.check, c.details or "-", c.recommendation or "-"] for c in visible]
    lines.extend(_table_or_empty(["Status", "Check", "Details", "Recommendation"], rows, "- None found."))
    return lines


def _checks_by_area_lines(checks: Sequence[Any], mode: str) -> list[str]:
    if not checks:
        return ["- None found.", ""]
    by_area: dict[str, list[Any]] = {}
    for check in checks:
        by_area.setdefault(check.area or "-", []).append(check)
    lines: list[str] = []
    for area in sorted(by_area):
        lines.extend(_area_check_block(area, by_area[area], mode))
    return lines


def _section_checks_by_area(payload: Any, mode: str) -> list[str]:
    return ["## 4. AI-visibility checks by area", "", *_checks_by_area_lines(payload.ai_visibility.checks, mode)]


def _meta_title_desc_lines(payload: Any) -> list[str]:
    title = _meta_value(payload, "title")
    description = _meta_value(payload, "description")
    return [
        f"- Title ({len(title)} chars): {title or '(missing)'}",
        f"- Meta description ({len(description)} chars): {description or '(missing)'}",
        f"- Word count: {payload.content_quality.word_count}",
        "",
    ]


def _heading_outline_lines(headers: Sequence[Sequence[str]]) -> list[str]:
    rows = [
        [str(row[0]).upper(), row[1] if len(row) > 1 else ""]
        for row in headers
        if row and str(row[0]).strip().lower() in _HEADING_TAGS
    ]
    return _titled_table("Heading outline (document order)", ["Level", "Text"], rows, "- None found.")


def _text_glitch_lines(glitches: Mapping[str, Any]) -> list[str]:
    if not glitches:
        return ["### Text glitches", "", "- None found.", ""]
    lines = [
        "### Text glitches",
        "",
        f"- Duplicate words: {glitches.get('duplicate_words', 0)}",
        f"- Doubled punctuation: {glitches.get('doubled_punctuation', 0)}",
        f"- Space before punctuation: {glitches.get('space_before_punct', 0)}",
        f"- Total: {glitches.get('total', 0)}",
    ]
    samples = glitches.get("samples") or []
    if samples:
        lines.append(f"- Samples: {_join_capped(samples, 5)}")
    lines.append("")
    return lines


def _keyword_lines(keywords: Sequence[Any]) -> list[str]:
    kept, remainder = _capped(keywords, 20)
    rows = [
        [
            k.term,
            k.frequency,
            f"{k.density:.2f}%",
            "Yes" if k.in_title else "No",
            "Yes" if k.in_description else "No",
            k.heading_count,
        ]
        for k in kept
    ]
    headers = ["Term", "Frequency", "Density", "In title", "In description", "Headings"]
    lines = _titled_table("Top keywords", headers, rows, "- None found.")
    lines.extend(_more_note(remainder))
    return lines


def _section_content(payload: Any) -> list[str]:
    lines = ["## 5. Content", "", *_meta_title_desc_lines(payload)]
    serp_rows = _dict_rows(payload.serp.to_dict())
    lines.extend(_titled_table("SERP preview", ["Field", "Value"], serp_rows, "- None found."))
    serp_audit_rows = _dict_rows(payload.serp_audit.to_dict())
    lines.extend(_titled_table("SERP audit", ["Check", "Value"], serp_audit_rows, "- None found."))
    lines.extend(_heading_outline_lines(payload.headers))
    quality_rows = build_content_quality_rows(payload.content_quality)
    lines.extend(_titled_table("Content quality", ["Check", "Value"], quality_rows, "- None found."))
    lines.extend(_text_glitch_lines(payload.content_quality.text_glitches))
    lines.extend(_keyword_lines(payload.keywords))
    lines.extend(_group_kv_section("Structure", payload.structure))
    lines.extend(_group_kv_section("Citation readiness (content)", payload.citation_content))
    lines.extend(_group_kv_section("Citation readiness (advanced)", payload.citation_advanced))
    lines.extend(_group_kv_section("E-E-A-T", payload.eeat))
    lines.extend(_group_kv_section("SEO basics", payload.seo_basics))
    return lines


def _link_type_counts(links: Sequence[Sequence[str]]) -> list[list[Any]]:
    type_counts = Counter(_row_cell(row, 2) or "-" for row in links)
    nofollow = sum(1 for row in links if "nofollow" in _row_cell(row, 3).lower())
    rows = [[kind, count] for kind, count in sorted(type_counts.items())]
    rows.append(["Nofollow (rel)", nofollow])
    return rows


def _is_broken_link(row: Sequence[str]) -> bool:
    status_text = _row_cell(row, 4)
    note = _row_cell(row, 5)
    return _to_int(status_text) >= 400 or (not status_text and bool(note))


def _broken_links(links: Sequence[Sequence[str]], cap: int = 30) -> tuple[list[list[Any]], int]:
    broken = [row for row in links if _is_broken_link(row)]
    kept, remainder = _capped(broken, cap)
    rows = [_broken_link_row(row) for row in kept]
    return rows, remainder


def _broken_link_row(row: Sequence[str]) -> list[str]:
    status = _row_cell(row, 4) or _row_cell(row, 5) or "-"
    return [_row_cell(row, 0), _row_cell(row, 1) or "-", status]


def _pseudo_link_lines(pseudo_links: Mapping[str, Any]) -> list[str]:
    total = pseudo_links.get("total") if isinstance(pseudo_links, Mapping) else None
    if not isinstance(total, int) or total <= 0:
        return ["### Pseudo-links (uncrawlable)", "", "- None found.", ""]
    counts = pseudo_links.get("counts") if isinstance(pseudo_links.get("counts"), Mapping) else {}
    samples = pseudo_links.get("samples") if isinstance(pseudo_links.get("samples"), list) else []
    lines = ["### Pseudo-links (uncrawlable)", "", f"- Total: {total}"]
    lines.extend(f"- {kind}: {count}" for kind, count in sorted(counts.items()))
    if samples:
        lines.append(f"- Samples: {_join_capped(samples, 5)}")
    lines.append("")
    return lines


def _missing_alt_images(images: Sequence[Sequence[str]], cap: int = 30) -> tuple[list[list[Any]], int]:
    missing = [row for row in images if not _row_cell(row, ALT_COL)]
    kept, remainder = _capped(missing, cap)
    return [[_row_cell(row, SRC_COL)] for row in kept], remainder


def _oversized_images(images: Sequence[Sequence[str]], cap: int = 30) -> tuple[list[list[Any]], int]:
    threshold = _OVERSIZED_KB * 1024
    sized = [(row, _to_int(_row_cell(row, SIZE_COL))) for row in images]
    heavy = sorted((item for item in sized if item[1] > threshold), key=lambda item: -item[1])
    kept, remainder = _capped(heavy, cap)
    return [[_row_cell(row, SRC_COL), f"{size // 1024} KB"] for row, size in kept], remainder


def _section_links_images(payload: Any) -> list[str]:
    lines = ["## 6. Links & images", ""]
    type_rows = _link_type_counts(payload.links)
    lines.extend(_titled_table("Link type breakdown", ["Type", "Count"], type_rows, "- None found."))
    broken, b_remainder = _broken_links(payload.links)
    lines.extend(_titled_table("Broken / erroring links", ["URL", "Anchor", "Status"], broken, "- None found."))
    lines.extend(_more_note(b_remainder))
    lines.extend(_pseudo_link_lines(payload.pseudo_links))
    lines.append(f"- Total images: {len(payload.images)}")
    lines.append("")
    missing, m_remainder = _missing_alt_images(payload.images)
    lines.extend(_titled_table("Images missing alt text", ["Src"], missing, "- None found."))
    lines.extend(_more_note(m_remainder))
    heavy, h_remainder = _oversized_images(payload.images)
    lines.extend(_titled_table(f"Oversized images (> {_OVERSIZED_KB} KB)", ["Src", "Size"], heavy, "- None found."))
    lines.extend(_more_note(h_remainder))
    return lines


def _schema_lines(schema: Any) -> list[str]:
    summary = schema.summary
    if not summary.total and not schema.eligibility:
        return ["### Structured data", "", "- None found.", ""]
    lines = ["### Structured data", "", f"- Total blocks: {summary.total}"]
    if summary.by_type:
        lines.append(f"- Types: {_join(sorted(summary.by_type))}")
    if summary.errors:
        lines.append(f"- Errors: {_join_capped(summary.errors, 10)}")
    lines.append("")
    rows = [
        [e.schema_type, "Yes" if e.detected else "No", e.eligibility, _join(e.missing_fields)]
        for e in schema.eligibility
    ]
    eligibility_headers = ["Type", "Detected", "Eligibility", "Missing fields"]
    lines.extend(_titled_table("Rich-result eligibility", eligibility_headers, rows, "- None found."))
    return lines


def _rich_results_lines(data: Mapping[str, Any]) -> list[str]:
    title = "Rich results (schema-derived)"
    if not _is_measured(data):
        return _not_measured_lines(title, data)
    eligible = data.get("eligible_types") or []
    warnings = data.get("warnings") or []
    lines = [
        f"### {title}",
        "",
        f"- Eligible types: {_join(eligible)}",
        f"- Source: {data.get('source', 'schema')}",
    ]
    if warnings:
        lines.append(f"- Warnings: {len(warnings)}")
    lines.append("")
    return lines


def _social_row(source: str, card: Any) -> list[Any]:
    present = "Yes" if (card.title or card.description or card.image) else "No"
    return [source, present, card.title or "-", card.image or "-", _join(card.issues)]


def _social_lines(social: Any) -> list[str]:
    rows = [_social_row("Open Graph", social.open_graph), _social_row("Twitter", social.twitter)]
    headers = ["Source", "Present", "Title", "Image", "Issues"]
    return _titled_table("Social (Open Graph / Twitter)", headers, rows, "- None found.")


def _section_international_structured(payload: Any) -> list[str]:
    lines = ["## 7. International & structured data", ""]
    hreflang_headers = ["Lang", "Target URL", "Status", "Lang OK", "Returns"]
    lines.extend(_titled_table("Hreflang", hreflang_headers, payload.hreflang, "- None found."))
    lines.extend(_schema_lines(payload.schema))
    lines.extend(_rich_results_lines(payload.rich_results))
    lines.extend(_social_lines(payload.social))
    return lines


def _performance_summary_lines(perf: Any) -> list[str]:
    summary = perf.summary
    return [
        "### Summary",
        "",
        f"- TTFB: {perf.nav_ttfb_ms:.0f} ms",
        f"- Total load: {perf.nav_total_ms:.0f} ms",
        f"- Transfer size: {summary.transfer_size} bytes",
        f"- Total page bytes: {summary.total_page_bytes} bytes",
        f"- Total requests: {summary.total_resource_count}",
        f"- Third-party: {summary.third_party_bytes} bytes ({summary.third_party_count} requests)",
        f"- Verdict: {summary.verdict or '-'}",
        "",
    ]


def _heaviest_resources_lines(resources: Sequence[Mapping[str, Any]]) -> list[str]:
    kept, remainder = _capped(resources, 15)
    rows = [[r.get("url", "-"), r.get("type", "-"), r.get("bytes", 0)] for r in kept]
    lines = _titled_table("Heaviest resources", ["URL", "Type", "Bytes"], rows, "- None found.")
    lines.extend(_more_note(remainder))
    return lines


def _third_party_lines(hosts: Sequence[Mapping[str, Any]]) -> list[str]:
    kept, remainder = _capped(hosts, 15)
    rows = [[h.get("host", "-"), h.get("count", 0), h.get("bytes", 0)] for h in kept]
    lines = _titled_table("Third-party hosts", ["Host", "Requests", "Bytes"], rows, "- None found.")
    lines.extend(_more_note(remainder))
    return lines


def _scripts_lines(scripts: Any) -> list[str]:
    return [
        "### Scripts",
        "",
        f"- Blocking: {scripts.blocking_count} ({scripts.blocking_bytes} bytes)",
        f"- Async/deferred: {scripts.async_count} ({scripts.async_bytes} bytes)",
        "",
    ]


def _lighthouse_lines(data: Mapping[str, Any]) -> list[str]:
    if not _is_measured(data):
        return _not_measured_lines("Lighthouse (lab)", data)
    cats = ("performance", "accessibility", "best_practices", "seo")
    lines = ["### Lighthouse (lab)", ""]
    lines.extend(f"- {name.replace('_', ' ').title()}: {data.get(name, 0)}" for name in cats)
    lines.append("")
    return lines


def _section_performance(payload: Any) -> list[str]:
    lines = ["## 8. Performance", ""]
    lines.extend(_performance_summary_lines(payload.performance))
    lines.extend(_heaviest_resources_lines(payload.performance.heaviest_resources))
    lines.extend(_third_party_lines(payload.performance.third_party_hosts))
    lines.extend(_scripts_lines(payload.performance.scripts))
    lines.extend(_group_kv_section("Core Web Vitals (lab)", payload.perf_vitals))
    lines.extend(_group_kv_section("Core Web Vitals (field / CrUX)", payload.perf_crux))
    lines.extend(_lighthouse_lines(payload.lighthouse))
    return lines


_AI_CRAWL_HEADERS = ["Agent", "Token", "Robots.txt OK", "Nonstandard directive", "Google controls", "Verdict", "Notes"]


def _render_parity_lines(render: Mapping[str, Any]) -> list[str]:
    status = render.get("status") if isinstance(render, Mapping) else None
    if not status or status == "not_measured":
        return _not_measured_lines("SSR / render parity", render)
    lines = ["### SSR / render parity", "", f"- Status: {status}"]
    if render.get("reason"):
        lines.append(f"- Reason: {render['reason']}")
    lines.append(f"- Missing headings: {_join(render.get('missing_headings') or [])}")
    lines.append(f"- Missing main text chars: {render.get('missing_main_text_chars', 0)}")
    lines.append(f"- Missing links: {render.get('missing_links', 0)}")
    lines.append("")
    return lines


def _bot_render_lines(data: Mapping[str, Any]) -> list[str]:
    title = "Per-bot render diffs"
    if not _is_measured(data):
        return _not_measured_lines(title, data)
    bots = data.get("bots") if isinstance(data.get("bots"), Mapping) else {}
    rows = [
        [token, info.get("status", "-"), info.get("missing_links", 0), info.get("reason", "-")]
        for token, info in sorted(bots.items())
    ]
    return _titled_table(title, ["Bot", "Status", "Missing links", "Reason"], rows, "- None found.")


def _section_ai_crawler(payload: Any) -> list[str]:
    lines = ["## 9. AI crawler access", ""]
    lines.extend(_titled_table("Bot access matrix", _AI_CRAWL_HEADERS, payload.ai_crawl, "- None found."))
    lines.extend(_render_parity_lines(payload.render))
    lines.extend(_bot_render_lines(payload.bot_render))
    return lines


def _integration_lines(title: str, data: Mapping[str, Any]) -> list[str]:
    if not _is_measured(data):
        return _not_measured_lines(title, data)
    return [f"### {title}", "", *_kv_lines(data), ""]


def _tech_stack_lines(data: Mapping[str, Any]) -> list[str]:
    by_category = data.get("by_category") if isinstance(data, Mapping) else None
    if not isinstance(by_category, Mapping) or not any(by_category.values()):
        return ["### Tech stack", "", "- Not measured (feature off).", ""]
    lines = ["### Tech stack", ""]
    lines.extend(f"- {category}: {_join(names)}" for category, names in by_category.items() if names)
    lines.append("")
    return lines


def _accessibility_row(violation: Mapping[str, Any]) -> list[Any]:
    return [
        violation.get("id", "-"),
        violation.get("impact", "-"),
        violation.get("nodes", 0),
        violation.get("help", "-"),
    ]


def _accessibility_lines(data: Mapping[str, Any]) -> list[str]:
    title = "Accessibility (axe-core)"
    if not _is_measured(data):
        return _not_measured_lines(title, data)
    violations = data.get("violations") if isinstance(data.get("violations"), list) else []
    counts = data.get("counts") if isinstance(data.get("counts"), Mapping) else {}
    lines = [f"### {title}", ""]
    lines.extend(f"- {impact}: {count}" for impact, count in sorted(counts.items()))
    kept, remainder = _capped(violations, 15)
    rows = [_accessibility_row(v) for v in kept if isinstance(v, Mapping)]
    lines.extend(_titled_table("Top rules", ["Rule", "Impact", "Elements", "Help"], rows, "- None found."))
    lines.extend(_more_note(remainder))
    return lines


def _custom_extraction_lines(data: Mapping[str, str]) -> list[str]:
    if not data:
        return ["### Custom extraction", "", "- None found.", ""]
    rows = [[name, str(value) or "(no match)"] for name, value in data.items()]
    return _titled_table("Custom extraction", ["Rule", "Value"], rows, "- None found.")


def _section_integrations(payload: Any) -> list[str]:
    lines = ["## 10. Optional integrations", ""]
    for attr, title in _INTEGRATION_SECTIONS:
        lines.extend(_integration_lines(title, getattr(payload, attr)))
    lines.extend(_tech_stack_lines(payload.tech_stack))
    lines.extend(_accessibility_lines(payload.accessibility))
    lines.extend(_custom_extraction_lines(payload.custom_extraction))
    return lines


def _page_json(payload: Any, url: str, mode: str) -> dict[str, Any]:
    final_url = payload.final_url or (payload.redirect.chain[-1] if payload.redirect.chain else url)
    return {
        "type": "page",
        "page": _page_metrics(payload, url),
        "issues": [issue.to_dict() for issue in _filtered_issues(issues_for_payload(url, payload), mode)],
        "checks": [c.to_dict() for c in _visible_checks(payload.ai_visibility.checks, mode)],
        "identity": {
            "requested_url": payload.requested_url or url,
            "final_url": final_url,
            "redirect": payload.redirect.to_dict(),
            "canonical": payload.canonical.to_dict(),
            "meta_robots": payload.meta_robots,
            "discovery": dict(payload.discovery),
        },
        "content": {
            "content_quality": payload.content_quality.to_dict(),
            "keywords": [k.to_dict() for k in payload.keywords[:20]],
        },
        "links_images": {
            "link_count": len(payload.links),
            "image_count": len(payload.images),
            "pseudo_links": dict(payload.pseudo_links),
        },
        "structured_data": payload.schema.to_mapping(),
        "social": payload.social.to_dict(),
        "hreflang": [list(row) for row in payload.hreflang],
        "performance": payload.performance.to_dict(),
        "ai_crawl": [list(row) for row in payload.ai_crawl],
        "render": dict(payload.render),
        "bot_render": dict(payload.bot_render),
        "custom_extraction": dict(payload.custom_extraction),
        "tech_stack": dict(payload.tech_stack),
        "accessibility": dict(payload.accessibility),
        "lighthouse": dict(payload.lighthouse),
        "rich_results": dict(payload.rich_results),
        "integrations": {attr: dict(getattr(payload, attr)) for attr, _ in _INTEGRATION_SECTIONS},
    }


def export_page_for_llm(payload: Any, url: str, mode: str = "compact") -> LlmExport:
    lines = [
        _PREAMBLE,
        f"# Page dossier: {url}",
        "",
        *_section_identity(payload, url),
        *_section_geo_score(payload),
        *_section_issues(url, payload, mode),
        *_section_checks_by_area(payload, mode),
        *_section_content(payload),
        *_section_links_images(payload),
        *_section_international_structured(payload),
        *_section_performance(payload),
        *_section_ai_crawler(payload),
        *_section_integrations(payload),
    ]
    markdown = _apply_size_cap("\n".join(lines))
    return LlmExport(markdown=markdown, json_data=_page_json(payload, url, mode))


# --------------------------------------------------------------------------
# Crawl dossier
# --------------------------------------------------------------------------


def _distribution_rows(values: Iterable[Any]) -> list[list[Any]]:
    counts = Counter(v or "-" for v in values)
    return [[k, v] for k, v in counts.most_common()]


def _percentile(sorted_values: Sequence[int], q: float) -> int:
    idx = max(0, min(len(sorted_values) - 1, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def _score_percentile_lines(scores: Sequence[int]) -> list[str]:
    if not scores:
        return ["- GEO Score: not measured (no audited pages).", ""]
    return [
        f"- GEO Score — min {scores[0]}, p25 {_percentile(scores, 0.25)}, "
        f"median {round(statistics.median(scores), 1)}, p75 {_percentile(scores, 0.75)}, max {scores[-1]}",
        "",
    ]


def _crawl_summary_lines(results: Sequence[Any]) -> list[str]:
    total = len(results)
    failed = sum(1 for r in results if r.status == "error")
    skipped = sum(1 for r in results if r.status == "skipped")
    crawled = total - failed - skipped
    lines = [
        "## Crawl summary",
        "",
        f"- URLs audited: {total}",
        f"- Crawled: {crawled}  Failed: {failed}  Skipped: {skipped}",
        "",
    ]
    status_rows = _distribution_rows(r.status for r in results)
    lines.extend(_titled_table("HTTP status distribution", ["Status", "Count"], status_rows, "- None found."))
    index_rows = _distribution_rows(r.indexability for r in results)
    lines.extend(_titled_table("Indexability distribution", ["Verdict", "Count"], index_rows, "- None found."))
    scores = sorted(r.geo_score for r in results if r.payload is not None)
    lines.extend(_score_percentile_lines(scores))
    return lines


def _hints_lines(results: Sequence[Any]) -> list[str]:
    hints = sorted(build_hints(issues_for_results(results)), key=lambda h: -h.priority)
    total = len({r.url for r in results}) or 1
    lines = ["## Site-wide hints", ""]
    if not hints:
        return [*lines, "- None found.", ""]
    for hint in hints:
        lines.append(f"- **[{hint.severity.value.upper()}]** {hint.headline(total)} — {hint.recommendation}")
        if hint.sample_urls:
            lines.append(f"  - Sample URLs: {_join(hint.sample_urls)}")
    lines.append("")
    return lines


def _meta_desc(result: Any) -> str:
    return _meta_value(result.payload, "description") if result.payload else ""


def _duplicate_groups(measured: Sequence[Any], key_fn: Callable[[Any], str]) -> tuple[list[tuple[str, list[str]]], int]:
    buckets: dict[str, list[str]] = {}
    for result in measured:
        key = key_fn(result).strip().lower()
        if not key:
            continue
        buckets.setdefault(key, []).append(result.url)
    groups = sorted(((k, urls) for k, urls in buckets.items() if len(urls) >= 2), key=lambda item: -len(item[1]))
    return _capped(groups, _DUP_GROUP_CAP)


def _duplicate_section_lines(title: str, measured: Sequence[Any], key_fn: Callable[[Any], str]) -> list[str]:
    kept, remainder = _duplicate_groups(measured, key_fn)
    lines = [f"### {title}", ""]
    if not kept:
        return [*lines, "- None found.", ""]
    for key, urls in kept:
        u_kept, u_remainder = _capped(urls, _DUP_URL_CAP)
        entry = f'- "{key}" — {len(urls)} pages: {_join(u_kept)}'
        if u_remainder:
            entry += f" (+{u_remainder} more)"
        lines.append(entry)
    lines.extend(_more_note(remainder))
    return lines


def _duplicate_lines(measured: Sequence[Any]) -> list[str]:
    lines = ["## Duplicate content", ""]
    lines.extend(_duplicate_section_lines("Duplicate titles", measured, lambda r: r.title))
    lines.extend(_duplicate_section_lines("Duplicate meta descriptions", measured, _meta_desc))
    return lines


def _is_redirecting(result: Any) -> bool:
    if result.payload is not None:
        return result.payload.redirect.hops > 0
    return bool(result.final_url) and result.final_url != result.url


def _error_page_lines(results: Sequence[Any]) -> list[str]:
    errors = [r for r in results if r.status == "error" or _to_int(r.status) >= 400]
    redirects = [r for r in results if _is_redirecting(r)]
    e_kept, e_remainder = _capped(errors, 100)
    r_kept, r_remainder = _capped(redirects, 50)
    lines = ["## Error & redirecting pages", ""]
    e_rows = [[r.url, r.status, r.error or "-"] for r in e_kept]
    lines.extend(_titled_table("4xx / 5xx / fetch-error pages", ["URL", "Status", "Error"], e_rows, "- None found."))
    lines.extend(_more_note(e_remainder))
    r_rows = [[r.url, r.redirect_status, r.final_url or "-"] for r in r_kept]
    lines.extend(_titled_table("Redirecting pages", ["URL", "Redirect status", "Final URL"], r_rows, "- None found."))
    lines.extend(_more_note(r_remainder))
    return lines


def _common_issues_json(measured: Sequence[Any]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for result in measured:
        for check in result.payload.ai_visibility.checks:
            if check.status in _COMPACT_STATUSES:
                counter[check.check] += 1
    return [{"check": name, "count": count} for name, count in counter.most_common(25)]


def _common_failing_checks_lines(measured: Sequence[Any]) -> list[str]:
    rows = [[item["check"], item["count"]] for item in _common_issues_json(measured)]
    return _titled_table("Most common failing checks", ["Check", "Pages affected"], rows, "- None found.")


def _site_discovery_lines(measured: Sequence[Any]) -> list[str]:
    discovery = next((r.payload.discovery for r in measured if r.payload.discovery), {})
    return ["## Site-wide discovery", "", *_discovery_lines(discovery)]


def _page_index_lines(results: Sequence[Any]) -> list[str]:
    kept, remainder = _capped(results, 500)
    rows = [[r.url, r.status, r.geo_score, r.title or "-", r.issue_summary()] for r in kept]
    headers = ["URL", "Status", "GEO score", "Title", "Top issue"]
    lines = _titled_table("Page index", headers, rows, "- None found.")
    lines.extend(_more_note(remainder))
    return lines


def _worst_results(results: Sequence[Any], worst_n: int) -> list[Any]:
    measured = [r for r in results if getattr(r, "payload", None) is not None]
    return sorted(measured, key=lambda r: r.geo_score)[:worst_n]


def _worst_page_block(result: Any, mode: str) -> list[str]:
    payload = result.payload
    summary = payload.ai_visibility.summary
    lines = [
        f"#### {result.url}",
        "",
        f"- GEO Score: {summary.score}/100 ({summary.verdict or '-'})",
        f"- Final URL: {payload.final_url or result.final_url or result.url}",
        f"- Canonical: {'self' if payload.canonical.is_self else (payload.canonical.target or 'missing')}",
        f"- Indexability: {result.indexability or '-'}",
        "",
    ]
    issues = _filtered_issues(issues_for_payload(result.url, payload), mode)
    kept, remainder = _capped(issues, 10)
    for issue in kept:
        lines.extend(_issue_block(issue))
    lines.extend(_more_note(remainder))
    lines.extend(_checks_by_area_lines(payload.ai_visibility.checks, mode))
    return lines


def _distribution_json(scores: Sequence[int]) -> dict[str, Any]:
    if not scores:
        return {"count": 0}
    return {
        "count": len(scores),
        "min": scores[0],
        "p25": _percentile(scores, 0.25),
        "p50": round(statistics.median(scores), 1),
        "p75": _percentile(scores, 0.75),
        "max": scores[-1],
    }


def _hint_json(hint: Any) -> dict[str, Any]:
    return {
        "issue_id": hint.issue_id,
        "category": hint.category.value,
        "severity": hint.severity.value,
        "title": hint.title,
        "recommendation": hint.recommendation,
        "affected_urls": hint.affected_urls,
        "sample_urls": list(hint.sample_urls),
    }


def _duplicate_groups_json(measured: Sequence[Any], key_fn: Callable[[Any], str]) -> list[dict[str, Any]]:
    kept, _remainder = _duplicate_groups(measured, key_fn)
    return [{"value": key, "count": len(urls), "urls": urls[:_DUP_URL_CAP]} for key, urls in kept]


def _worst_pages_json(worst: Sequence[Any], mode: str) -> list[dict[str, Any]]:
    entries = []
    for result in worst:
        entry = _page_metrics(result.payload, result.url)
        entry["checks"] = [c.to_dict() for c in _visible_checks(result.payload.ai_visibility.checks, mode)]
        entries.append(entry)
    return entries


def _crawl_json(results: Sequence[Any], measured: Sequence[Any], worst: Sequence[Any], mode: str) -> dict[str, Any]:
    scores = sorted(r.geo_score for r in measured)
    discovery = next((r.payload.discovery for r in measured if r.payload.discovery), {})
    return {
        "type": "crawl",
        "distribution": _distribution_json(scores),
        "common_issues": _common_issues_json(measured),
        "worst_pages": _worst_pages_json(worst, mode),
        "hints": [_hint_json(h) for h in build_hints(issues_for_results(results))],
        "duplicates": {
            "titles": _duplicate_groups_json(measured, lambda r: r.title),
            "descriptions": _duplicate_groups_json(measured, _meta_desc),
        },
        "errors": {
            "http_errors": [r.url for r in results if r.status == "error" or _to_int(r.status) >= 400][:100],
            "redirects": [r.url for r in results if _is_redirecting(r)][:50],
        },
        "discovery": dict(discovery),
        "page_index": [[r.url, r.status, r.geo_score, r.title, r.issue_summary()] for r in list(results)[:500]],
    }


def export_crawl_for_llm(results: Sequence[Any], mode: str = "compact", worst_n: int = 50) -> LlmExport:
    # ``results`` arrive fully hydrated (the caller streams them through the
    # run-bound repository), so every measured page already carries its payload.
    measured = [r for r in results if getattr(r, "payload", None) is not None]
    worst = _worst_results(results, worst_n)
    lines = [
        _PREAMBLE,
        "# Site crawl dossier",
        "",
        *_crawl_summary_lines(results),
        *_hints_lines(results),
        *_duplicate_lines(measured),
        *_error_page_lines(results),
        *_common_failing_checks_lines(measured),
        *_site_discovery_lines(measured),
        *_page_index_lines(results),
        f"## Worst {len(worst)} pages (detailed)",
        "",
    ]
    for result in worst:
        lines.extend(_worst_page_block(result, mode))
    markdown = _apply_size_cap("\n".join(lines))
    json_data = _crawl_json(results, measured, worst, mode)
    return LlmExport(markdown=markdown, json_data=json_data)


def write_llm_export(export: LlmExport, out_path: str | Path, fmt: str = "both") -> list[Path]:
    base = Path(out_path)
    written: list[Path] = []
    if fmt in {"markdown", "both"}:
        md_path = base.with_suffix(".md")
        md_path.write_text(export.markdown, encoding="utf-8")
        written.append(md_path)
    if fmt in {"json", "both"}:
        json_path = base.with_suffix(".json")
        json_path.write_text(export.json_text, encoding="utf-8")
        written.append(json_path)
    return written


__all__ = [
    "LlmExport",
    "export_crawl_for_llm",
    "export_page_for_llm",
    "write_llm_export",
]
