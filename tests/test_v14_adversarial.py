"""Adversarial validation for v2.0 V14 (Lighthouse + Rich Results).

These cover gaps the green V14 suites miss: cross-subdir cache
isolation, the rich-results fallback path on bad blocks, GSC
inspection nesting crashes, the seo_crawler GSC override / no-network
contract, and the GUI apply-merge path.
"""

from __future__ import annotations

import asyncio

import pytest

from silentfrog import _psi_cache
from silentfrog.crawl_types import CrawlPayload
from silentfrog.integrations.google import lighthouse as lh
from silentfrog.integrations.google.connection import GoogleConnection
from silentfrog.integrations.google.lighthouse import LighthouseScores
from silentfrog.integrations.google.rich_results import derive_from_schema, from_url_inspection
from silentfrog.perf_crux import CruxData


# --- item 11: cross-subdir cache isolation ---------------------------------
def test_crux_cache_does_not_satisfy_lighthouse_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    url = "https://example.com/"
    _psi_cache.write_cache("crux_cache", url, CruxData(lcp_p75_ms=1234, has_field_data=True))
    assert _psi_cache.read_cache("lighthouse_cache", url, LighthouseScores.from_dict) is None


def test_lighthouse_cache_does_not_satisfy_crux_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    url = "https://example.com/"
    _psi_cache.write_cache("lighthouse_cache", url, LighthouseScores(performance=99, measured=True))
    crux = _psi_cache.read_cache("crux_cache", url, CruxData.from_raw)
    assert crux is None


# --- item 8: a network failure must not poison the cache -------------------
def test_network_failure_writes_no_cache_entry(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))

    async def _none(*_a, **_k):
        return None

    monkeypatch.setattr(lh, "_request_psi", _none)
    result = asyncio.run(lh.fetch_lighthouse("https://nocache.example/"))
    assert result.measured is False
    assert not list(tmp_path.rglob("*.json"))


# --- item 9: fallback path tolerates bad blocks ----------------------------
@pytest.mark.parametrize("blocks", [[{"@type": 123}], [None, "x", 5], [{}], "notalist"])
def test_fallback_bad_blocks_never_raises(blocks) -> None:
    report = derive_from_schema({"blocks": blocks})
    assert report.measured is False
    assert report.source == "schema"


def test_eligibility_list_takes_precedence_over_blocks() -> None:
    payload = {
        "eligibility": [{"type": "X", "eligibility": "Eligible", "warnings": []}],
        "blocks": [{"@type": "Organization"}],
    }
    assert derive_from_schema(payload).eligible_types == ("X",)


# --- item 10: GSC inspection nesting variants never crash ------------------
@pytest.mark.parametrize(
    "payload",
    [
        {"inspectionResult": None},
        {"inspectionResult": {"richResultsResult": None}},
        {"inspectionResult": {"richResultsResult": {"detectedItems": "notlist"}}},
        {"inspectionResult": {"richResultsResult": {"detectedItems": [{"richResultType": "X", "items": None}]}}},
        {"inspectionResult": {"richResultsResult": {"detectedItems": [{"richResultType": "X", "items": [None]}]}}},
    ],
)
def test_from_url_inspection_nesting_never_raises(payload) -> None:
    report = from_url_inspection(payload)
    assert report.source == "gsc"


def test_garbage_detected_items_do_not_fabricate_eligible_types() -> None:
    # A list of non-mapping items must never invent eligible types or warnings.
    payload = {"inspectionResult": {"richResultsResult": {"detectedItems": [None, 5, "x"]}}}
    report = from_url_inspection(payload)
    assert report.eligible_types == ()
    assert report.warnings == ()


# --- item 13: seo_crawler GSC override / no-network ------------------------
_SCHEMA = {"eligibility": [{"type": "Product", "eligibility": "Eligible", "warnings": []}]}


def _collect(monkeypatch, connection) -> dict:
    import silentfrog.integrations.google.connection as conn
    from silentfrog import seo_crawler

    monkeypatch.setattr(conn, "from_env", lambda: connection)
    return asyncio.run(seo_crawler._collect_rich_results(_SCHEMA, "https://x.example/"))


def test_collect_rich_results_no_gsc_is_schema_only(monkeypatch) -> None:
    out = _collect(monkeypatch, None)
    assert out["source"] == "schema"
    assert out["eligible_types"] == ["Product"]


def test_collect_rich_results_gsc_measured_overrides(monkeypatch) -> None:
    class _Conn:
        def inspect_rich_results(self, _url):
            return {"inspectionResult": {"richResultsResult": {"detectedItems": [{"richResultType": "Breadcrumbs"}]}}}

    out = _collect(monkeypatch, _Conn())
    assert out["source"] == "gsc"
    assert out["eligible_types"] == ["Breadcrumbs"]


@pytest.mark.parametrize("inspection", [{"inspectionResult": {}}, RuntimeError])
def test_collect_rich_results_gsc_unmeasured_or_raising_keeps_schema(monkeypatch, inspection) -> None:
    class _Conn:
        def inspect_rich_results(self, _url):
            if inspection is RuntimeError:
                raise RuntimeError("boom")
            return inspection

    out = _collect(monkeypatch, _Conn())
    assert out["source"] == "schema"
    assert out["eligible_types"] == ["Product"]


# --- item 13: GscClient.inspect_url null-safety ----------------------------
def test_inspect_url_no_service_returns_empty() -> None:
    from silentfrog.integrations.google.gsc_client import GscClient

    assert GscClient(None).inspect_url("https://site/", "https://site/page") == {}


def test_inspect_rich_results_no_site_returns_empty() -> None:
    conn = GoogleConnection(gsc=object(), ga4=object(), site_url="")  # type: ignore[arg-type]
    assert conn.inspect_rich_results("https://x/") == {}


# --- item 14: GUI apply-merge into the AI Visibility checks ----------------
def _full_payload(url: str) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "Sample", "10"]],
            "headers": [["h1", "Sample"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "errors": []}, "blocks": [], "eligibility": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "", "description": "", "url": url, "site_name": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 400, "thin_content_risk": "Low"},
            "social": {},
        }
    )


def test_apply_lighthouse_merges_into_ai_visibility(qtbot, monkeypatch) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    monkeypatch.setenv("SILENTFROG_PSI_ENABLE", "1")
    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._latest_payload = _full_payload("https://example.com/")
    emitted: list[dict] = []
    win.dataReady.connect(emitted.append)
    win._apply_lighthouse({"performance": 95, "accessibility": 95, "seo": 95, "best_practices": 95, "measured": True})
    assert emitted, "dataReady should fire after a successful Lighthouse apply"
    keys = {c["key"] for c in emitted[0]["ai_visibility"]["checks"]}
    assert "lighthouse_perf_above_90" in keys


def test_apply_lighthouse_with_no_payload_does_not_crash(qtbot) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win._latest_payload = None
    win._apply_lighthouse({"performance": 95, "measured": True})  # must not raise
