"""Unit tests for the v2.0 V2 streaming SQLite crawl store."""

from __future__ import annotations

import sqlite3

import pytest

from silentfrog.crawl_store import CrawlStore, StoredAudit
from silentfrog.crawl_store_schema import SCHEMA_VERSION, schema_version


@pytest.fixture
def store() -> CrawlStore:
    s = CrawlStore(":memory:")
    yield s
    s.close()


def _audit(url: str, score: int = 80, status: str = "200", **kw) -> StoredAudit:
    return StoredAudit(url=url, geo_score=score, http_status=status, **kw)


# H0 source groups carried on CrawlPayload (kept here so this store test is
# self-contained — tests must not import each other).
_H0_GROUPS = (
    "discovery",
    "eeat",
    "structure",
    "citation_content",
    "citation_advanced",
    "seo_basics",
    "render",
    "perf_vitals",
    "perf_crux",
    "ai_citations",
    "gsc",
    "ga4",
)


def _full_payload_raw() -> dict[str, object]:
    """A complete raw payload (all required sections + every H0 group + URLs +
    schema version) for the store persistence round-trip."""
    groups = {name: {name: True, "n": 1} for name in _H0_GROUPS}
    return {
        "meta": [["title", "Example"]],
        "headers": [["h1", "Example"]],
        "images": [],
        "links": [],
        "schema": {
            "summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []},
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {"target": "https://e.com/p", "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": ["https://e.com/p"], "hops": 0, "final_status": "200", "loop": False},
        "robots": {"*": [("Allow", "/")]},
        "meta_robots": "index, follow",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {},
        "serp_audit": {},
        "keywords": [],
        "payload_schema_version": 2,
        "requested_url": "https://e.com/req",
        "final_url": "https://e.com/p",
        **groups,
    }


def test_schema_version_is_set() -> None:
    conn = sqlite3.connect(":memory:")
    from silentfrog.crawl_store_schema import apply_schema

    apply_schema(conn)
    assert schema_version(conn) == SCHEMA_VERSION


def test_apply_schema_adds_frontier_to_legacy_db(tmp_path) -> None:
    # A v1 database (runs + audits, no frontier) gains the frontier table on
    # open via the additive migration, and the version bumps to current.
    from silentfrog.crawl_store_schema import apply_schema

    db = tmp_path / "legacy.db"
    legacy = sqlite3.connect(str(db))
    legacy.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
    legacy.execute("CREATE TABLE audits (insertion_order INTEGER PRIMARY KEY, run_id TEXT, url TEXT)")
    legacy.execute("PRAGMA user_version=1")
    legacy.commit()
    legacy.close()

    conn = sqlite3.connect(str(db))
    apply_schema(conn)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "frontier" in tables
    assert schema_version(conn) == SCHEMA_VERSION == 2
    conn.close()


def test_admit_records_frontier_and_dedups(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    assert store.admit(run_id, "https://e.com/a", "https://e.com/", 1) is True
    assert store.admit(run_id, "https://e.com/a", "https://e.com/", 1) is False  # UNIQUE dedup
    store.flush()
    rows = store._conn.execute(
        "SELECT normalized_url, source_url, depth, state FROM frontier WHERE run_id = ?", (run_id,)
    ).fetchall()
    assert rows == [("https://e.com/a", "https://e.com/", 1, "pending")]


def test_iter_graph_inputs_sources_edges_from_frontier(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "spider")
    store.admit(run_id, "https://e.com/", "", 0)
    store.admit(run_id, "https://e.com/a", "https://e.com/", 1)
    store.save_audit(run_id, _audit("https://e.com/", score=90))
    store.save_audit(run_id, _audit("https://e.com/a", score=70))
    store.flush()
    rows = {url: (source, score) for url, source, score in store.iter_graph_inputs(run_id)}
    assert rows["https://e.com/"] == ("", 90)
    assert rows["https://e.com/a"] == ("https://e.com/", 70)


def test_iter_graph_inputs_edgeless_without_frontier_rows(store: CrawlStore) -> None:
    # A crawl predating the frontier table (audits only) stays edgeless, not empty.
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, _audit("https://e.com/x", score=50))
    store.flush()
    assert store.iter_graph_inputs(run_id) == [("https://e.com/x", "", 50)]


def test_start_run_persists_and_returns_id(store: CrawlStore) -> None:
    run_id = store.start_run(scope="example.com", base_url="https://example.com/", mode="hybrid")
    assert run_id
    assert store.count(run_id) == 0


def test_save_and_iter_lightweight_preserves_order(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    for i in range(5):
        store.save_audit(run_id, _audit(f"https://e.com/{i}", score=90 - i))
    rows = store.iter_lightweight(run_id)
    assert [r.url for r in rows] == [f"https://e.com/{i}" for i in range(5)]
    assert [r.geo_score for r in rows] == [90, 89, 88, 87, 86]


def test_iter_lightweight_paging(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    for i in range(10):
        store.save_audit(run_id, _audit(f"https://e.com/{i}"))
    page = store.iter_lightweight(run_id, offset=3, limit=4)
    assert [r.url for r in page] == [f"https://e.com/{i}" for i in (3, 4, 5, 6)]


def test_load_payload_roundtrips_through_zlib(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    payload = {"meta": [["title", "Hello"]], "ai_visibility": {"summary": {"score": 77}}}
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", payload=payload))
    loaded = store.load_payload(run_id, "https://e.com/p")
    assert loaded == payload


def test_load_payload_none_when_no_blob(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", payload=None))
    assert store.load_payload(run_id, "https://e.com/p") is None


def test_resume_pending_returns_only_unsaved(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, _audit("https://e.com/a"))
    store.save_audit(run_id, _audit("https://e.com/b"))
    pending = store.resume_pending(run_id, ["https://e.com/a", "https://e.com/b", "https://e.com/c", "https://e.com/d"])
    assert pending == ["https://e.com/c", "https://e.com/d"]


def test_insert_or_ignore_dedups_same_url(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, _audit("https://e.com/x", score=80))
    store.save_audit(run_id, _audit("https://e.com/x", score=10))  # duplicate ignored
    store.flush()
    assert store.count(run_id) == 1
    rows = store.iter_lightweight(run_id)
    assert rows[0].geo_score == 80  # first write kept


def test_summary_counts_and_score_stats(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, _audit("https://e.com/a", score=90))
    store.save_audit(run_id, _audit("https://e.com/b", score=70))
    store.save_audit(run_id, _audit("https://e.com/c", score=50))
    store.save_audit(run_id, StoredAudit(url="https://e.com/err", http_status="error"))
    store.save_audit(run_id, StoredAudit(url="https://e.com/skip", http_status="skipped"))
    summary = store.summary(run_id)
    assert summary.total == 5
    assert summary.failed == 1
    assert summary.skipped == 1
    assert summary.score_min == 50
    assert summary.score_max == 90
    assert summary.score_p50 == 70.0


def test_finish_run_sets_status(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, _audit("https://e.com/a"))
    store.finish_run(run_id, "completed")
    row = store._conn.execute("SELECT status, finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row[0] == "completed"
    assert row[1]  # finished_at populated


def test_batched_writes_persist_after_flush(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    # Fewer than the batch threshold — must still be readable after flush.
    for i in range(50):
        store.save_audit(run_id, _audit(f"https://e.com/{i}"))
    store.flush()
    assert store.count(run_id) == 50


def test_scales_to_10k_rows_without_loading_all(store: CrawlStore) -> None:
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    for i in range(10_000):
        store.save_audit(run_id, _audit(f"https://e.com/{i}"))
    store.flush()
    assert store.count(run_id) == 10_000
    # Paged read returns only the page, never the whole table.
    first_page = store.iter_lightweight(run_id, offset=0, limit=100)
    assert len(first_page) == 100
    last_page = store.iter_lightweight(run_id, offset=9_900, limit=100)
    assert len(last_page) == 100
    assert last_page[-1].url == "https://e.com/9999"


def test_two_runs_are_isolated(store: CrawlStore) -> None:
    run_a = store.start_run("a.com", "https://a.com/", "hybrid")
    run_b = store.start_run("b.com", "https://b.com/", "hybrid")
    store.save_audit(run_a, _audit("https://a.com/1"))
    store.save_audit(run_b, _audit("https://b.com/1"))
    store.save_audit(run_b, _audit("https://b.com/2"))
    assert store.count(run_a) == 1
    assert store.count(run_b) == 2


def test_crawl_store_roundtrip_preserves_h0_groups_urls_and_version(store: CrawlStore) -> None:
    # H0: a full CrawlPayload (all 12 AI-Visibility source groups, both URLs,
    # and the schema version) must survive the real compressed-JSON store path
    # save_audit -> load_payload -> from_raw, not just an in-memory round trip.
    from silentfrog.crawl_types import PAYLOAD_SCHEMA_VERSION, CrawlPayload

    payload = CrawlPayload.from_raw(_full_payload_raw())
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, StoredAudit(url=payload.final_url, payload=payload.to_mapping()))
    store.flush()

    loaded = store.load_payload(run_id, payload.final_url)
    assert loaded is not None
    restored = CrawlPayload.from_raw(loaded)
    assert restored == payload
    for group in _H0_GROUPS:
        assert getattr(restored, group) == {group: True, "n": 1}, group
    assert restored.requested_url == "https://e.com/req"
    assert restored.final_url == "https://e.com/p"
    assert restored.payload_schema_version == PAYLOAD_SCHEMA_VERSION == 2


def test_persists_to_disk_and_reopens(tmp_path) -> None:
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "hybrid")
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", payload={"k": "v"}))
    store.finish_run(run_id)
    store.close()
    # Reopen — data survives.
    reopened = CrawlStore(db)
    assert reopened.count(run_id) == 1
    assert reopened.load_payload(run_id, "https://e.com/p") == {"k": "v"}
    reopened.close()
