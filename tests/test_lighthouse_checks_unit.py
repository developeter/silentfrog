"""Unit tests for v2.0 V14 Lighthouse + rich-result AI Visibility checks.

Focus on the §1.5 invariant: absent/unmeasured signals are ``info`` and
never warn; only genuine measured defects warn.
"""

from __future__ import annotations

from silentfrog.integrations.google.checks import build_lighthouse_checks, build_rich_results_checks
from silentfrog.integrations.google.lighthouse import LighthouseScores
from silentfrog.integrations.google.rich_results import RichResultsReport


def test_unmeasured_lighthouse_is_info_only() -> None:
    checks = build_lighthouse_checks(LighthouseScores())
    assert len(checks) == 1
    assert checks[0].status == "info"
    assert checks[0].area == "Performance"
    assert all(c.status != "warning" for c in checks)


def test_low_lighthouse_score_warns_high_is_good() -> None:
    low = LighthouseScores(performance=40, accessibility=95, seo=92, best_practices=88, measured=True, fetched_at="t")
    by_key = {c.key: c for c in build_lighthouse_checks(low)}
    assert by_key["lighthouse_perf_above_90"].status == "warning"
    assert by_key["lighthouse_a11y_above_90"].status == "good"
    assert by_key["lighthouse_seo_above_90"].status == "good"
    assert by_key["lighthouse_freshness"].status == "info"
    assert all(c.area == "Performance" for c in by_key.values())


def test_unmeasured_rich_results_is_info() -> None:
    checks = build_rich_results_checks(RichResultsReport())
    assert len(checks) == 1
    assert checks[0].status == "info"
    assert checks[0].area == "Citation readiness"


def test_rich_results_eligible_good_warnings_warn() -> None:
    report = RichResultsReport(eligible_types=("Product",), warnings=("bad markup",), source="schema", measured=True)
    by_key = {c.key: c for c in build_rich_results_checks(report)}
    assert by_key["rich_results_eligible"].status == "good"
    assert by_key["rich_results_warning_count"].status == "warning"
    assert all(c.area == "Citation readiness" for c in by_key.values())


def test_rich_results_no_eligible_no_warnings() -> None:
    report = RichResultsReport(ineligible_types=("Article",), source="schema", measured=True)
    by_key = {c.key: c for c in build_rich_results_checks(report)}
    # measured but nothing eligible yet -> info, never a penalty (§1.5)
    assert by_key["rich_results_eligible"].status == "info"
    # no warnings -> good
    assert by_key["rich_results_warning_count"].status == "good"
