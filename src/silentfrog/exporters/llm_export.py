"""LLM-friendly export (v2.0 V5).

Produces a paste-ready Markdown (+ JSON mirror) bundle of an audit so the
user can hand it to a Claude chat and get a prioritised fix list. The
Markdown opens with a self-describing prompt preamble so the model
understands the file with zero extra context.

- ``export_page_for_llm`` — full single-page detail.
- ``export_crawl_for_llm`` — site rollup (score distribution + issue
  frequency) + per-page detail for the worst-N pages. Compact mode keeps
  only ``warning`` / ``critical`` rows.
- ``write_llm_export`` — writes ``.md`` and/or ``.json``.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PREAMBLE = """# Silentfrog SEO/GEO audit — for AI analysis

You are an expert SEO and GEO (Generative Engine Optimization) consultant.
Read the audit below and tell me, in priority order, the most important
things to fix and why, plus what is already good. Be specific and
actionable: name the page, the issue, and the concrete change.

## How to read this file
- **GEO Score** (0-100): higher is better. It is derived from the check
  list — every `warning` costs points, every `critical` costs more.
- **Status** of a check:
  - `critical` — fix first; materially hurts AI/search visibility.
  - `warning` — should fix.
  - `good` — already correct.
  - `info` — not measured or not applicable; it NEVER counts against the
    score (Silentfrog never penalises an absent optional signal).
- Compact exports list only `warning` and `critical` rows.
"""

_COMPACT_STATUSES = {"warning", "critical"}


@dataclass(frozen=True)
class LlmExport:
    markdown: str
    json_data: dict[str, Any]

    @property
    def json_text(self) -> str:
        return json.dumps(self.json_data, indent=2, ensure_ascii=False)


def _checks_for(payload: Any, mode: str) -> list[Any]:
    checks = list(payload.ai_visibility.checks)
    if mode == "full":
        return checks
    return [c for c in checks if (c.status or "").strip().lower() in _COMPACT_STATUSES]


def _meta_value(payload: Any, name: str) -> str:
    for row in payload.meta:
        if len(row) > 1 and str(row[0]).strip().lower() == name:
            return str(row[1]).strip()
    return ""


def _issue_table(checks: Sequence[Any]) -> list[str]:
    if not checks:
        return ["_No warning/critical issues._", ""]
    lines = ["| Status | Area | Check | Detail | Recommendation |", "|---|---|---|---|---|"]
    order = {"critical": 0, "warning": 1, "good": 2, "info": 3}
    for check in sorted(checks, key=lambda c: order.get((c.status or "").lower(), 4)):
        lines.append(
            f"| {check.status} | {check.area} | {check.check} | "
            f"{(check.details or '-').replace('|', '/')} | "
            f"{(check.recommendation or '-').replace('|', '/')} |"
        )
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
        "word_count": getattr(payload.content_quality, "word_count", 0),
    }


def _check_dicts(checks: Sequence[Any]) -> list[dict[str, str]]:
    return [
        {
            "status": c.status,
            "area": c.area,
            "check": c.check,
            "details": c.details or "",
            "recommendation": c.recommendation or "",
        }
        for c in checks
    ]


def _custom_extraction_lines(payload: Any) -> list[str]:
    data = getattr(payload, "custom_extraction", {}) or {}
    if not isinstance(data, dict) or not data:
        return []
    lines = ["### Custom extraction", "", "| Rule | Value |", "|---|---|"]
    lines += [f"| {name} | {str(value).replace('|', '/') or '(no match)'} |" for name, value in data.items()]
    lines.append("")
    return lines


def _lighthouse_lines(payload: Any) -> list[str]:
    data = getattr(payload, "lighthouse", {}) or {}
    if not isinstance(data, dict) or not data.get("measured"):
        return []
    cats = ("performance", "accessibility", "best_practices", "seo")
    scores = ", ".join(f"{name.replace('_', ' ')} {data.get(name, 0)}" for name in cats)
    return ["### Lighthouse (lab)", "", f"- {scores}", ""]


def _rich_results_lines(payload: Any) -> list[str]:
    data = getattr(payload, "rich_results", {}) or {}
    if not isinstance(data, dict) or not data.get("measured"):
        return []
    eligible = ", ".join(str(t) for t in data.get("eligible_types", [])) or "none"
    warnings = data.get("warnings", []) or []
    lines = ["### Rich results", "", f"- Eligible types: {eligible} (source: {data.get('source', 'schema')})"]
    if warnings:
        lines.append(f"- Warnings: {len(warnings)}")
    lines.append("")
    return lines


def _tech_stack_lines(payload: Any) -> list[str]:
    data = getattr(payload, "tech_stack", {}) or {}
    by_category = data.get("by_category") if isinstance(data, dict) else None
    if not isinstance(by_category, dict) or not by_category:
        return []
    lines = ["### Tech stack", ""]
    lines += [f"- {category}: {', '.join(names)}" for category, names in by_category.items() if names]
    lines.append("")
    return lines


def export_page_for_llm(payload: Any, url: str, mode: str = "compact") -> LlmExport:
    metrics = _page_metrics(payload, url)
    checks = _checks_for(payload, mode)
    lines = [
        _PREAMBLE,
        f"## Page: {url}",
        "",
        f"- GEO Score: {metrics['geo_score']}/100 ({metrics['verdict']})",
        f"- Good: {metrics['good']}  Warnings: {metrics['warnings']}  Critical: {metrics['critical']}",
        f"- Title: {metrics['title'] or '(missing)'}",
        f"- Meta description: {metrics['meta_description'] or '(missing)'}",
        f"- Word count: {metrics['word_count']}",
        "",
        *_lighthouse_lines(payload),
        *_rich_results_lines(payload),
        *_tech_stack_lines(payload),
        *_custom_extraction_lines(payload),
        "### Issues",
        *_issue_table(checks),
    ]
    custom = getattr(payload, "custom_extraction", {}) or {}
    json_data = {
        "type": "page",
        "page": metrics,
        "checks": _check_dicts(checks),
        "custom_extraction": dict(custom) if isinstance(custom, dict) else {},
    }
    return LlmExport(markdown="\n".join(lines), json_data=json_data)


def _result_score(result: Any) -> int:
    payload = getattr(result, "payload", None)
    if payload is None:
        return 0
    return payload.ai_visibility.summary.score


def _issue_frequency(results: Sequence[Any]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for result in results:
        payload = getattr(result, "payload", None)
        if payload is None:
            continue
        for check in payload.ai_visibility.checks:
            if (check.status or "").lower() in _COMPACT_STATUSES:
                counter[check.check] += 1
    return counter.most_common(15)


def _score_distribution(results: Sequence[Any]) -> dict[str, Any]:
    scores = [_result_score(r) for r in results if getattr(r, "payload", None) is not None]
    if not scores:
        return {"count": 0}
    return {
        "count": len(scores),
        "min": min(scores),
        "p50": round(statistics.median(scores), 1),
        "max": max(scores),
    }


def _worst_results(results: Sequence[Any], worst_n: int) -> list[Any]:
    measured = [r for r in results if getattr(r, "payload", None) is not None]
    return sorted(measured, key=_result_score)[:worst_n]


def export_crawl_for_llm(results: Sequence[Any], mode: str = "compact", worst_n: int = 50) -> LlmExport:
    distribution = _score_distribution(results)
    frequency = _issue_frequency(results)
    worst = _worst_results(results, worst_n)
    lines = [
        _PREAMBLE,
        "## Site crawl summary",
        "",
        f"- URLs audited: {distribution.get('count', 0)}",
        f"- GEO Score — min {distribution.get('min', 0)}, "
        f"median {distribution.get('p50', 0)}, max {distribution.get('max', 0)}",
        "",
        "### Most common issues",
        *_frequency_table(frequency),
        f"### Worst {len(worst)} pages",
        *_worst_table(worst),
    ]
    lines.extend(_worst_details(worst, mode))
    json_data = {
        "type": "crawl",
        "distribution": distribution,
        "common_issues": [{"check": name, "count": count} for name, count in frequency],
        "worst_pages": [_page_metrics(r.payload, r.url) for r in worst],
    }
    return LlmExport(markdown="\n".join(lines), json_data=json_data)


def _frequency_table(frequency: Sequence[tuple[str, int]]) -> list[str]:
    if not frequency:
        return ["_No recurring issues._", ""]
    lines = ["| Issue | Pages affected |", "|---|---|"]
    lines.extend(f"| {name} | {count} |" for name, count in frequency)
    lines.append("")
    return lines


def _worst_table(worst: Sequence[Any]) -> list[str]:
    if not worst:
        return ["_No measured pages._", ""]
    lines = ["| URL | GEO Score | Top issue |", "|---|---|---|"]
    for result in worst:
        top = result.issue_summary()
        lines.append(f"| {result.url} | {_result_score(result)} | {top} |")
    lines.append("")
    return lines


def _worst_details(worst: Sequence[Any], mode: str) -> list[str]:
    lines: list[str] = ["### Worst page details", ""]
    for result in worst:
        checks = _checks_for(result.payload, mode)
        lines.append(f"#### {result.url} — {_result_score(result)}/100")
        lines.extend(_issue_table(checks))
    return lines


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
