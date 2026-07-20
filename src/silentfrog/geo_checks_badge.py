"""GEO checks enablement badge (v1.1 N5a-fix).

A single rich-label row that sits at the top of the AI Visibility
tab. It tells the user — at a glance — which v1.1 measurement
groups are actually producing data on the current audit vs which
ones are shipping but gated off.

Status per group:

- ``measured`` (✓ green): at least one check_key from the group is
  present in ``payload.ai_visibility.checks`` AND is non-``info``.
- ``gated`` (○ grey): every check_key from the group is present but
  all are ``info`` — code path exists, user hasn't enabled the
  feature (env var, Settings checkbox, missing API key, …).
- ``missing`` (✗ dim red): no check_key from the group is present
  in the payload (older install, payload truncated).

Groups recognised:

- ``Lab CWV`` — ``perf_lcp``, ``perf_inp``, ``perf_cls``, …
- ``CrUX field`` — ``perf_crux_lcp``, ``perf_crux_inp``,
  ``perf_crux_cls``
- ``SSR parity`` — ``access_ssr_parity``
- ``AI Citations`` — ``ai_citations_brave``,
  ``ai_citations_common_crawl``, ``ai_citations_perplexity``
- ``AI Share of Voice`` — ``sov_openai``, ``sov_perplexity``, ``sov_gemini``,
  ``sov_share``
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

# Group → set of check_keys that belong to it.
_GROUPS: dict[str, tuple[str, ...]] = {
    "Lab CWV": (
        "perf_lcp",
        "perf_inp",
        "perf_cls",
        "perf_fcp",
        "perf_tbt",
        "perf_speed_index",
    ),
    "CrUX field": ("perf_crux_lcp", "perf_crux_inp", "perf_crux_cls"),
    "SSR parity": ("access_ssr_parity",),
    "AI Citations": (
        "ai_citations_brave",
        "ai_citations_common_crawl",
        "ai_citations_perplexity",
    ),
    "AI Share of Voice": (
        "sov_openai",
        "sov_perplexity",
        "sov_gemini",
        "sov_share",
    ),
}

_ENABLEMENT_HINTS: dict[str, str] = {
    "Lab CWV": (
        "Settings → tick 'Run SSR parity check (requires Playwright)'. The same code path "
        "drives the 6 Core Web Vitals lab metrics."
    ),
    "CrUX field": ("Set SILENTFROG_PSI_ENABLE=1; optionally set SILENTFROG_PSI_API_KEY for higher PSI rate."),
    "SSR parity": "Settings → tick 'Run SSR parity check (requires Playwright)'.",
    "AI Citations": ("Set SILENTFROG_AI_CITATIONS_ENABLE=1; for the Brave probe also set SILENTFROG_BRAVE_API_KEY."),
    "AI Share of Voice": (
        "Set SILENTFROG_AI_SOV_ENABLE=1 and add an OpenAI/Perplexity/Gemini key in Settings → "
        "AI share of voice (BYO keys)."
    ),
}

GROUP_ORDER: tuple[str, ...] = ("Lab CWV", "CrUX field", "SSR parity", "AI Citations", "AI Share of Voice")


@dataclass(frozen=True)
class GroupBadge:
    group: str
    state: str  # "measured" | "gated" | "missing"
    glyph: str  # "✓" | "○" | "✗"
    hint: str


def evaluate_group(group: str, checks: Iterable[Mapping[str, Any]]) -> GroupBadge:
    keys = _GROUPS.get(group, ())
    present_keys = []
    measured_keys = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        key = check.get("key") or check.get("check_key") or ""
        if key in keys:
            present_keys.append(key)
            status = (check.get("status") or "").strip().lower()
            if status and status != "info":
                measured_keys.append(key)
    hint = _ENABLEMENT_HINTS.get(group, "")
    if not present_keys:
        return GroupBadge(group=group, state="missing", glyph="✗", hint=hint)
    if not measured_keys:
        return GroupBadge(group=group, state="gated", glyph="○", hint=hint)
    return GroupBadge(group=group, state="measured", glyph="✓", hint=hint)


def build_badges(checks: Iterable[Mapping[str, Any]]) -> list[GroupBadge]:
    materialised = list(checks)
    return [evaluate_group(group, materialised) for group in GROUP_ORDER]


def render_label(badges: list[GroupBadge]) -> str:
    """Return the rich-label HTML for the badge row."""
    color_map = {
        "measured": "#2ecc71",
        "gated": "#9aa0a6",
        "missing": "#e57373",
    }
    bits: list[str] = ["<b>GEO checks:</b>"]
    for badge in badges:
        color = color_map.get(badge.state, "#9aa0a6")
        bits.append(f'<span style="color:{color};">&nbsp; {badge.group} {badge.glyph}</span>')
    return "&nbsp;".join(bits)


def render_tooltip(badges: list[GroupBadge]) -> str:
    lines = ["GEO measurement gates — what's measured vs what's shipping but gated off.", ""]
    for badge in badges:
        state_word = {
            "measured": "measured",
            "gated": "shipping but not enabled",
            "missing": "not present in this payload",
        }.get(badge.state, badge.state)
        lines.append(f"• {badge.group}: {badge.glyph} {state_word}")
        if badge.hint:
            lines.append(f"    Enable: {badge.hint}")
    return "\n".join(lines)


__all__ = [
    "GROUP_ORDER",
    "GroupBadge",
    "build_badges",
    "evaluate_group",
    "render_label",
    "render_tooltip",
]
