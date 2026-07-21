"""Accessibility audit via the vendored axe-core engine (v3 G4 Stage 1).

Off by default (Crawl Settings checkbox lands in Stage 2), requires the
``geo-render`` extra (Playwright), and only runs on profiles that render
(H4: DEEP) — same gating shape as ``bot_render`` (v2.0 V10). The axe-core
source is vendored at ``_vendor/axe.min.js`` and is NEVER fetched over the
network at runtime; it is injected into the already-rendered page and run
in-browser via ``RenderPool.render``'s ``inject_js`` / ``evaluate_js``.

``parse_axe_result`` is pure and is what the tests exercise directly; the
async ``collect_accessibility`` is the thin I/O wrapper and degrades to
``{}`` (unmeasured) on any failure — never raises.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Mapping, Sequence
from typing import Any

from .crawl_options import CrawlOptions, ProfilePolicy

AXE_EVALUATE = "axe.run(document, {resultTypes: ['violations']})"

_IMPACT_TIERS = ("critical", "serious", "moderate", "minor")
_MAX_SAMPLE_TARGETS = 5

_axe_source_cache: str | None = None


def load_axe_source() -> str:
    """Read the vendored axe-core bundle once, cached at module level (it's
    ~550KB). Returns ``""`` and stays silent when the resource is missing —
    degrade, never raise."""
    global _axe_source_cache
    if _axe_source_cache is not None:
        return _axe_source_cache
    try:
        source = importlib.resources.files("silentfrog._vendor").joinpath("axe.min.js").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        source = ""
    _axe_source_cache = source
    return source


def _sample_targets(nodes: Sequence[Any]) -> list[str]:
    targets: list[str] = []
    for node in nodes[:_MAX_SAMPLE_TARGETS]:
        if not isinstance(node, Mapping):
            continue
        target = node.get("target")
        if isinstance(target, list) and target:
            targets.append(str(target[0]))
    return targets


def _parsed_violation(item: Mapping[str, Any]) -> dict[str, Any]:
    nodes = item.get("nodes")
    node_list = nodes if isinstance(nodes, list) else []
    return {
        "id": str(item.get("id", "")),
        "impact": str(item.get("impact") or ""),
        "help": str(item.get("help", "")),
        "help_url": str(item.get("helpUrl", "")),
        "nodes": len(node_list),
        "sample_targets": _sample_targets(node_list),
    }


def parse_axe_result(raw: Any) -> dict[str, Any]:
    """Pure, tolerant parser: ``axe.run()`` output -> JSON-native payload.

    Garbage/``None`` -> ``{}`` (unmeasured, never raises)."""
    if not isinstance(raw, Mapping):
        return {}
    violations_raw = raw.get("violations")
    if not isinstance(violations_raw, list):
        return {}
    violations = [_parsed_violation(item) for item in violations_raw if isinstance(item, Mapping)]
    counts = dict.fromkeys(_IMPACT_TIERS, 0)
    for violation in violations:
        impact = violation["impact"]
        if impact in counts:
            counts[impact] += 1
    return {"measured": True, "violations": violations, "counts": counts}


async def collect_accessibility(
    url: str,
    crawl_options: CrawlOptions,
    policy: ProfilePolicy,
    pool: Any = None,
) -> dict[str, Any]:
    """Run axe-core against the rendered page. ``{}`` (unmeasured) when the
    flag is off, the profile does not render, the vendored source is
    missing, or the render/script fails. Never raises."""
    if not crawl_options.accessibility_audit or not policy.render:
        return {}
    source = load_axe_source()
    if not source:
        return {}
    from .bot_render import shared_render_pool

    active_pool = pool if pool is not None else shared_render_pool()
    result = await active_pool.render(url, inject_js=source, evaluate_js=AXE_EVALUATE)
    if result is None or result.error or result.script_result is None:
        return {}
    return parse_axe_result(result.script_result)


__all__ = [
    "AXE_EVALUATE",
    "collect_accessibility",
    "load_axe_source",
    "parse_axe_result",
]
