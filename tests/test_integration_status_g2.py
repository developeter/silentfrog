"""PR-G2 INT-3: an enabled-but-unmeasured Semrush / Google integration says why
(one info row with the reason, a "gated" badge) instead of vanishing; a stock
audit stays silent."""

from __future__ import annotations

import pytest

from silentfrog import seo_crawler
from silentfrog.ai_visibility import build_ai_visibility_checks, build_ai_visibility_summary
from silentfrog.geo_checks_badge import GROUP_ORDER, evaluate_group, render_label
from silentfrog.integrations.google import connection as google_connection
from silentfrog.integrations.semrush import client as semrush_client

_URL = "https://www.example.com/page"


def _badge(group: str, checks) -> str:
    return evaluate_group(group, [{"key": c.key, "status": c.status} for c in checks]).state


def _semrush_rows(checks):
    return [c for c in checks if c.key.startswith("semrush_")]


def _google_rows(checks):
    return [c for c in checks if c.key.startswith(("gsc_", "ga4_"))]


def test_badge_has_authority_and_google_groups() -> None:
    assert "Authority (Semrush)" in GROUP_ORDER and "Google" in GROUP_ORDER
    label = render_label([evaluate_group(group, []) for group in GROUP_ORDER])
    assert "Authority (Semrush)" in label and "Google" in label


@pytest.mark.asyncio
async def test_stock_audit_collects_nothing_and_shows_no_rows(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SILENTFROG_SEMRUSH_ENABLE", raising=False)
    monkeypatch.delenv("SILENTFROG_GOOGLE_ENABLE", raising=False)
    assert await seo_crawler._collect_semrush(_URL) == {}
    assert await seo_crawler._collect_google_metrics(_URL) == {}
    checks = build_ai_visibility_checks({})
    assert _semrush_rows(checks) == [] and _google_rows(checks) == []


@pytest.mark.asyncio
async def test_semrush_enabled_without_a_key_yields_one_info_row_and_a_gated_badge(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_SEMRUSH_ENABLE", "1")
    monkeypatch.setattr(semrush_client, "resolve_api_key", lambda: "")

    fragment = await seo_crawler._collect_semrush(_URL)

    assert fragment["measured"] is False and fragment["enabled"] is True
    assert "API key" in fragment["reason"]
    checks = build_ai_visibility_checks({"semrush": fragment})
    rows = _semrush_rows(checks)
    assert len(rows) == 1 and rows[0].status == "info"
    assert "API key" in rows[0].details
    assert _badge("Authority (Semrush)", rows) == "gated"
    assert (
        build_ai_visibility_summary(checks).score == build_ai_visibility_summary(build_ai_visibility_checks({})).score
    )


@pytest.mark.asyncio
async def test_semrush_enabled_on_a_non_public_host_says_so(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_SEMRUSH_ENABLE", "1")
    monkeypatch.setattr(semrush_client, "resolve_api_key", lambda: "KEY")
    fragment = await seo_crawler._collect_semrush("http://127.0.0.1:8000/")
    assert fragment["enabled"] is True and "public domain" in fragment["reason"]


@pytest.mark.asyncio
async def test_semrush_api_error_reason_reaches_the_row(monkeypatch, tmp_path) -> None:
    from silentfrog.integrations.semrush.types import SemrushMetrics

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SILENTFROG_SEMRUSH_ENABLE", "1")
    monkeypatch.setattr(semrush_client, "resolve_api_key", lambda: "KEY")

    async def refused(domain, key, max_calls, **_):
        return SemrushMetrics.unavailable("Semrush WRONG KEY - ID PAIR (code 120).")

    monkeypatch.setattr(semrush_client, "fetch_domain_overview", refused)
    fragment = await seo_crawler._collect_semrush(_URL)
    rows = _semrush_rows(build_ai_visibility_checks({"semrush": fragment}))
    assert len(rows) == 1 and "WRONG KEY" in rows[0].details


@pytest.mark.parametrize(("builtin", "expected"), [(False, "no built-in Google app"), (True, "click Connect")])
@pytest.mark.asyncio
async def test_google_enabled_but_not_connected_yields_info_rows_with_the_reason(
    monkeypatch, builtin, expected
) -> None:
    monkeypatch.setattr(google_connection, "_enabled", lambda: True)
    monkeypatch.setattr("silentfrog.integrations.google.oauth.load_token", lambda account: None)
    monkeypatch.setattr("silentfrog.integrations.google.app_client.builtin_client_available", lambda: builtin)

    fragment = await seo_crawler._collect_google_metrics(_URL)

    assert expected in fragment["gsc"]["reason"] and fragment["ga4"]["enabled"] is True
    checks = build_ai_visibility_checks(fragment)
    rows = _google_rows(checks)
    assert {row.status for row in rows} == {"info"} and len(rows) == 2
    assert all(expected in row.details for row in rows)
    assert _badge("Google", rows) == "gated"


@pytest.mark.asyncio
async def test_google_connected_without_a_property_names_the_missing_property(monkeypatch) -> None:
    monkeypatch.setattr(google_connection, "_enabled", lambda: True)
    monkeypatch.setattr("silentfrog.integrations.google.oauth.load_token", lambda account: "token")
    monkeypatch.delenv("SILENTFROG_GSC_SITE_URL", raising=False)
    monkeypatch.delenv("SILENTFROG_GA4_PROPERTY_ID", raising=False)
    from silentfrog.integrations.google.config import GoogleConfig

    monkeypatch.setattr(google_connection, "load_config", lambda: GoogleConfig(enabled=True))

    fragment = await seo_crawler._collect_google_metrics(_URL)

    assert "no Search Console property" in fragment["gsc"]["reason"]


def test_env_var_recommendations_tell_the_user_to_restart_the_app() -> None:
    # INT-11: environment variables are read at start-up, so a recommendation
    # that only says "set X" leaves a running app looking broken.
    from silentfrog.geo_checks_badge import build_badges
    from silentfrog.integrations.google.checks import build_real_performance_checks
    from silentfrog.integrations.google.types import Ga4Metrics, GscMetrics

    for row in build_real_performance_checks(GscMetrics(), Ga4Metrics()):
        assert "restart the app" in row.recommendation
    hints = {badge.group: badge.hint for badge in build_badges([])}
    for group in ("CrUX field", "AI Citations", "AI Share of Voice"):
        assert "restart the app" in hints[group], group
