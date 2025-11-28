from __future__ import annotations

from silentfrog.perf_guides import PerformanceContext, open_source_hints  # type: ignore[reportMissingImports]


def test_open_source_hints_toggle(monkeypatch):
    context = PerformanceContext(
        transfer_size=2_200_000,
        css_count=5,
        js_count=45,
        img_count=12,
        font_count=2,
        nav_total_ms=4_500,
        nav_ttfb_ms=600,
    )

    monkeypatch.delenv("SILENTFROG_PERF_GUIDES", raising=False)
    hints_enabled = open_source_hints(context)
    assert any("HTTP Archive Web Almanac" in hint for hint in hints_enabled)
    assert any("RAIL performance model" in hint for hint in hints_enabled)
    assert any("Web Vitals patterns" in hint for hint in hints_enabled)

    monkeypatch.setenv("SILENTFROG_PERF_GUIDES", "0")
    hints_disabled = open_source_hints(context)
    assert hints_disabled == []
