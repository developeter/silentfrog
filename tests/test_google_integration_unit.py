"""Unit tests for the v2.0 V7 GSC + GA4 integration (fakes, no creds)."""

from __future__ import annotations

import pytest

import silentfrog.integrations.google.connection as conn
import silentfrog.integrations.google.oauth as oauth_mod
from silentfrog.integrations.google.checks import build_real_performance_checks
from silentfrog.integrations.google.config import GoogleConfig
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


# --- gsc_client.list_sites (v2.0 R2) -------------------------------------
def test_list_sites_without_service_returns_empty_list() -> None:
    assert GscClient(None).list_sites() == []


def test_list_sites_parses_site_entries() -> None:
    class _FakeSitesService:
        def sites(self):
            return self

        def list(self):
            return self

        def execute(self):
            return {
                "siteEntry": [
                    {"siteUrl": "https://e.com/", "permissionLevel": "siteOwner"},
                    {"permissionLevel": "siteFullUser"},  # missing siteUrl -> dropped
                ]
            }

    sites = GscClient(_FakeSitesService()).list_sites()
    assert sites == [{"site_url": "https://e.com/", "permission_level": "siteOwner"}]


def test_list_sites_degrades_on_api_error() -> None:
    class _Boom:
        def sites(self):
            raise RuntimeError("403")

    assert GscClient(_Boom()).list_sites() == []


# --- connection.from_env matrix (v2.0 R2) --------------------------------
# oauth.load_token/build_gsc_service/build_ga4_service are faked; from_env
# never touches the real network, browser, or OS keychain here.
class _AssertingGa4Service:
    """Records the GA4 property id threaded into runReport by
    ``from_env()`` so the test body can assert on it directly. Asserting
    *inline* here would be swallowed: ``Ga4Client.metrics_for_url`` wraps
    the whole ``runReport(...).execute()`` chain in
    ``except Exception: return Ga4Metrics()``, and ``AssertionError`` is an
    ``Exception`` — a failed assert here would silently degrade to an
    unmeasured result instead of failing the test."""

    def __init__(self, expected_property_id: str) -> None:
        self.expected_property_id = expected_property_id
        self.received_property: str | None = None

    def properties(self):
        return self

    def runReport(self, property, body):  # noqa: A002, N803 — mirrors google API kwarg
        self.received_property = property
        return _FakeExecutable({"rows": []})


def _clear_google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SILENTFROG_GOOGLE_ENABLE", "SILENTFROG_GSC_SITE_URL", "SILENTFROG_GA4_PROPERTY_ID"):
        monkeypatch.delenv(name, raising=False)


def test_from_env_nothing_set_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setattr(conn, "load_config", lambda: GoogleConfig())

    assert conn.from_env() is None


def test_from_env_env_path_is_unchanged_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("SILENTFROG_GOOGLE_ENABLE", "1")
    monkeypatch.setenv("SILENTFROG_GSC_SITE_URL", "https://env.example/")
    monkeypatch.setenv("SILENTFROG_GA4_PROPERTY_ID", "111")
    monkeypatch.setattr(conn, "load_config", lambda: GoogleConfig())
    monkeypatch.setattr(oauth_mod, "load_token", lambda account: "TOKEN")
    monkeypatch.setattr(oauth_mod, "build_gsc_service", lambda token: _FakeGscService({"rows": []}))
    ga4_fake = _AssertingGa4Service("111")
    monkeypatch.setattr(oauth_mod, "build_ga4_service", lambda token: ga4_fake)

    connection = conn.from_env()

    assert connection is not None
    assert connection.site_url == "https://env.example/"
    connection.metrics_for("https://env.example/p")
    # Checked here, not inside runReport: Ga4Client swallows exceptions.
    assert ga4_fake.received_property == "properties/111"


def test_from_env_config_only_path_is_new_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setattr(
        conn,
        "load_config",
        lambda: GoogleConfig(enabled=True, gsc_site_url="https://config.example/", ga4_property_id="222"),
    )
    monkeypatch.setattr(oauth_mod, "load_token", lambda account: "TOKEN")
    monkeypatch.setattr(oauth_mod, "build_gsc_service", lambda token: _FakeGscService({"rows": []}))
    ga4_fake = _AssertingGa4Service("222")
    monkeypatch.setattr(oauth_mod, "build_ga4_service", lambda token: ga4_fake)

    connection = conn.from_env()

    assert connection is not None
    assert connection.site_url == "https://config.example/"
    connection.metrics_for("https://config.example/p")
    # Checked here, not inside runReport: Ga4Client swallows exceptions.
    assert ga4_fake.received_property == "properties/222"


def test_from_env_token_but_empty_site_url_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Documents the trap: a stored token alone does nothing without a
    site URL / property id from either env or config.

    The service builders are also faked (non-raising) here, not left
    un-mocked: from_env()'s whole token+service-building block sits inside
    one ``except Exception: return None``, so with the real (un-mocked)
    builders this test would pass identically -- for the wrong reason --
    even if the ``and site_url`` / ``and property_id`` guards that are
    actually under test were deleted, because the resulting
    ModuleNotFoundError/JSONDecodeError from calling a real builder with an
    invalid token gets caught by that same outer except and also yields
    None. Faking non-raising builders makes a deleted guard build a real
    GoogleConnection instead, which is what actually fails the assertion
    below.
    """
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("SILENTFROG_GOOGLE_ENABLE", "1")
    monkeypatch.setattr(conn, "load_config", lambda: GoogleConfig())
    monkeypatch.setattr(oauth_mod, "load_token", lambda account: "TOKEN")
    monkeypatch.setattr(oauth_mod, "build_gsc_service", lambda token: _FakeGscService({"rows": []}))
    monkeypatch.setattr(oauth_mod, "build_ga4_service", lambda token: _FakeGa4Service({}))

    assert conn.from_env() is None


def test_from_env_env_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("SILENTFROG_GOOGLE_ENABLE", "1")
    monkeypatch.setenv("SILENTFROG_GSC_SITE_URL", "https://env-wins.example/")
    monkeypatch.setenv("SILENTFROG_GA4_PROPERTY_ID", "333")
    monkeypatch.setattr(
        conn,
        "load_config",
        lambda: GoogleConfig(gsc_site_url="https://config-loses.example/", ga4_property_id="999"),
    )
    monkeypatch.setattr(oauth_mod, "load_token", lambda account: "TOKEN")
    monkeypatch.setattr(oauth_mod, "build_gsc_service", lambda token: _FakeGscService({"rows": []}))
    ga4_fake = _AssertingGa4Service("333")
    monkeypatch.setattr(oauth_mod, "build_ga4_service", lambda token: ga4_fake)

    connection = conn.from_env()

    assert connection is not None
    assert connection.site_url == "https://env-wins.example/"
    connection.metrics_for("https://env-wins.example/p")
    # Checked here, not inside runReport: Ga4Client swallows exceptions.
    assert ga4_fake.received_property == "properties/333"


def test_from_env_keyring_raising_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("SILENTFROG_GOOGLE_ENABLE", "1")
    monkeypatch.setenv("SILENTFROG_GSC_SITE_URL", "https://env.example/")
    monkeypatch.setattr(conn, "load_config", lambda: GoogleConfig())

    def _boom(account: str) -> str:
        raise ModuleNotFoundError("no keyring installed")

    monkeypatch.setattr(oauth_mod, "load_token", _boom)

    assert conn.from_env() is None
