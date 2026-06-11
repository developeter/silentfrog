"""Unit tests for the v2.0 V7 GSC + GA4 integration (fakes, no creds)."""

from __future__ import annotations

from silentfrog.integrations.google.checks import build_real_performance_checks
from silentfrog.integrations.google.connection import GoogleConnection
from silentfrog.integrations.google.ga4_client import Ga4Client
from silentfrog.integrations.google.gsc_client import GscClient
from silentfrog.integrations.google.types import Ga4Metrics, GscMetrics


# --- fake googleapiclient resource chains -------------------------------
class _FakeExecutable:
    def __init__(self, response) -> None:
        self._response = response

    def execute(self):
        return self._response


class _FakeGscService:
    def __init__(self, response) -> None:
        self._response = response

    def searchanalytics(self):
        return self

    def query(self, siteUrl, body):  # noqa: N803 — mirrors google API kwarg
        return _FakeExecutable(self._response)


class _FakeGa4Service:
    def __init__(self, response) -> None:
        self._response = response

    def properties(self):
        return self

    def runReport(self, property, body):  # noqa: A002, N803 — mirrors google API
        return _FakeExecutable(self._response)


# --- GSC client ----------------------------------------------------------
def test_gsc_unmeasured_without_service() -> None:
    metrics = GscClient(None).metrics_for_url("https://e.com", "https://e.com/p", "2026-01-01", "2026-01-28")
    assert metrics.measured is False


def test_gsc_aggregates_rows() -> None:
    response = {
        "rows": [
            {"keys": ["best widgets"], "impressions": 1000, "clicks": 50, "position": 4.0},
            {"keys": ["widgets"], "impressions": 500, "clicks": 10, "position": 8.0},
        ]
    }
    metrics = GscClient(_FakeGscService(response)).metrics_for_url(
        "https://e.com", "https://e.com/p", "2026-01-01", "2026-01-28"
    )
    assert metrics.measured is True
    assert metrics.impressions == 1500
    assert metrics.clicks == 60
    assert round(metrics.ctr, 3) == 0.04  # 60/1500
    assert metrics.top_queries[0] == "best widgets"  # highest impressions first


def test_gsc_degrades_on_api_error() -> None:
    class _Boom:
        def searchanalytics(self):
            raise RuntimeError("403")

    metrics = GscClient(_Boom()).metrics_for_url("https://e.com", "https://e.com/p", "a", "b")
    assert metrics.measured is False


# --- GA4 client ----------------------------------------------------------
def test_ga4_unmeasured_without_service_or_property() -> None:
    assert Ga4Client(None, "123").metrics_for_url("https://e.com/p", "a", "b").measured is False
    assert Ga4Client(_FakeGa4Service({}), "").metrics_for_url("https://e.com/p", "a", "b").measured is False


def test_ga4_parses_report() -> None:
    response = {"rows": [{"metricValues": [{"value": "200"}, {"value": "9000"}, {"value": "0.45"}, {"value": "3"}]}]}
    metrics = Ga4Client(_FakeGa4Service(response), "123").metrics_for_url("https://e.com/p", "a", "b")
    assert metrics.measured is True
    assert metrics.pageviews == 200
    assert round(metrics.avg_engagement_seconds, 1) == 45.0  # 9000/200
    assert metrics.bounce_rate == 0.45
    assert metrics.conversions == 3


# --- checks --------------------------------------------------------------
def test_checks_unmeasured_render_info_only() -> None:
    checks = build_real_performance_checks(GscMetrics(), Ga4Metrics())
    assert all(c.status == "info" for c in checks)
    keys = {c.key for c in checks}
    assert "gsc_impressions_present" in keys
    assert "ga4_engagement_above_median" in keys


def test_checks_measured_emit_good_and_warning() -> None:
    gsc = GscMetrics(impressions=1000, clicks=50, ctr=0.05, position=6.0, top_queries=("x",), measured=True)
    ga4 = Ga4Metrics(pageviews=100, avg_engagement_seconds=45, bounce_rate=0.8, conversions=2, measured=True)
    checks = build_real_performance_checks(gsc, ga4)
    by_key = {c.key: c for c in checks}
    assert by_key["gsc_ctr_above_average"].status == "good"  # 5% > 2%
    assert by_key["gsc_position_in_top_10"].status == "good"  # pos 6 <= 10
    assert by_key["ga4_bounce_below_threshold"].status == "warning"  # 80% > 70%
    assert by_key["ga4_engagement_above_median"].status == "good"  # 45s >= 30s


def test_checks_route_to_real_performance_and_engagement_areas() -> None:
    gsc = GscMetrics(measured=True)
    ga4 = Ga4Metrics(measured=True)
    areas = {c.area for c in build_real_performance_checks(gsc, ga4)}
    assert areas == {"Real performance", "Engagement"}


# --- connection ----------------------------------------------------------
def test_connection_metrics_for_merges_gsc_and_ga4() -> None:
    gsc_resp = {"rows": [{"keys": ["q"], "impressions": 10, "clicks": 1, "position": 5.0}]}
    ga4_resp = {"rows": [{"metricValues": [{"value": "5"}, {"value": "100"}, {"value": "0.3"}, {"value": "0"}]}]}
    connection = GoogleConnection(
        gsc=GscClient(_FakeGscService(gsc_resp)),
        ga4=Ga4Client(_FakeGa4Service(ga4_resp), "123"),
        site_url="https://e.com",
    )
    merged = connection.metrics_for("https://e.com/p")
    assert merged["gsc"]["measured"] is True
    assert merged["gsc"]["impressions"] == 10
    assert merged["ga4"]["measured"] is True
    assert merged["ga4"]["pageviews"] == 5


# --- types roundtrip -----------------------------------------------------
def test_metrics_roundtrip_through_dict() -> None:
    gsc = GscMetrics(impressions=10, clicks=2, ctr=0.2, position=3.0, top_queries=("a", "b"), measured=True)
    assert GscMetrics.from_dict(gsc.to_dict()) == gsc
    ga4 = Ga4Metrics(pageviews=5, avg_engagement_seconds=12.0, bounce_rate=0.5, conversions=1, measured=True)
    assert Ga4Metrics.from_dict(ga4.to_dict()) == ga4


# --- ai_visibility wiring ------------------------------------------------
def test_ai_visibility_emits_google_checks_when_measured() -> None:
    from silentfrog.ai_visibility import build_ai_visibility_checks

    payload = {
        "meta": [],
        "headers": [],
        "images": [],
        "links": [],
        "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
        "canonical": {},
        "redirect": {},
        "robots": {},
        "meta_robots": "",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {},
        "serp_audit": {},
        "keywords": [],
        "content_quality": {},
        "ai_visibility": {},
        "performance": {},
        "social": {},
        "gsc": {"impressions": 100, "clicks": 5, "ctr": 0.05, "position": 4.0, "measured": True},
        "ga4": {"pageviews": 50, "avg_engagement_seconds": 40, "bounce_rate": 0.4, "conversions": 1, "measured": True},
    }
    checks = build_ai_visibility_checks(payload)
    keys = {c.key for c in checks}
    assert "gsc_impressions_present" in keys
    assert "ga4_bounce_below_threshold" in keys
