"""Tests for the v1.1 N5a-fix GEO checks enablement badge row."""

from __future__ import annotations

from silentfrog.geo_checks_badge import (
    GROUP_ORDER,
    build_badges,
    evaluate_group,
    render_label,
    render_tooltip,
)
from silentfrog.tabs import AiVisibilityTab


def test_empty_checks_renders_every_group_as_missing() -> None:
    badges = build_badges([])
    assert [b.group for b in badges] == list(GROUP_ORDER)
    assert all(b.state == "missing" for b in badges)
    assert all(b.glyph == "✗" for b in badges)


def test_group_gated_when_every_check_key_is_info() -> None:
    checks = [
        {"key": "perf_lcp", "status": "info"},
        {"key": "perf_inp", "status": "info"},
    ]
    badge = evaluate_group("Lab CWV", checks)
    assert badge.state == "gated"
    assert badge.glyph == "○"


def test_group_measured_when_any_check_key_has_non_info_status() -> None:
    checks = [
        {"key": "perf_lcp", "status": "good"},
        {"key": "perf_inp", "status": "info"},
    ]
    badge = evaluate_group("Lab CWV", checks)
    assert badge.state == "measured"
    assert badge.glyph == "✓"


def test_crux_field_group_independent_from_lab_cwv() -> None:
    checks = [
        {"key": "perf_lcp", "status": "good"},
        {"key": "perf_crux_lcp", "status": "info"},
    ]
    lab = evaluate_group("Lab CWV", checks)
    crux = evaluate_group("CrUX field", checks)
    assert lab.state == "measured"
    assert crux.state == "gated"


def test_ai_citations_group_matches_check_keys() -> None:
    checks = [
        {"key": "ai_citations_brave", "status": "good"},
        {"key": "ai_citations_common_crawl", "status": "info"},
    ]
    assert evaluate_group("AI Citations", checks).state == "measured"
    only_info = [{"key": "ai_citations_brave", "status": "info"}]
    assert evaluate_group("AI Citations", only_info).state == "gated"
    no_keys: list[dict[str, str]] = []
    assert evaluate_group("AI Citations", no_keys).state == "missing"


def test_render_label_mentions_every_group_with_correct_glyph() -> None:
    badges = build_badges([])
    label = render_label(badges)
    for group in GROUP_ORDER:
        assert group in label
    assert label.count("✗") == len(GROUP_ORDER)


def test_render_tooltip_names_enable_instructions() -> None:
    badges = build_badges([])
    tip = render_tooltip(badges)
    assert "SILENTFROG_AI_CITATIONS_ENABLE" in tip
    assert "SILENTFROG_PSI_ENABLE" in tip
    assert "Run SSR parity check" in tip


def test_ai_visibility_tab_badge_label_updates_on_update(qtbot) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    initial_text = tab._badges_label.text()
    # Initial render is "missing" for every group.
    assert "✗" in initial_text
    tab.update(
        {
            "summary": {
                "verdict": "Strong",
                "score": 90,
                "good_count": 1,
                "warning_count": 0,
                "critical_count": 0,
            },
            "checks": [
                {
                    "area": "Performance",
                    "check": "LCP",
                    "status": "good",
                    "details": "",
                    "recommendation": "",
                    "key": "perf_lcp",
                }
            ],
        }
    )
    updated = tab._badges_label.text()
    # Lab CWV is now measured; the ✓ glyph appears in the label.
    assert "✓" in updated


def test_ai_visibility_tab_badge_tooltip_lists_env_vars(qtbot) -> None:
    tab = AiVisibilityTab()
    qtbot.addWidget(tab)
    tab.update({"summary": {"score": 80, "verdict": "Strong"}, "checks": []})
    tip = tab._badges_label.toolTip()
    assert "SILENTFROG_AI_CITATIONS_ENABLE" in tip
    assert "SILENTFROG_PSI_ENABLE" in tip
