"""Unit tests for the run-bound CrawlRunRepository seam (v2.0 H1)."""

from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from silentfrog.crawl_run_repository import (
    CrawlRowQuery,
    CrawlRunRef,
    InMemoryCrawlRunRepository,
    hydrate_payloads,
)
from silentfrog.crawl_store import CrawlStore, StoredAudit
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlResult


def _payload(url: str = "https://e.com/p") -> CrawlPayload:
    raw: dict[str, Any] = {
        "meta": [["title", "Example"]],
        "headers": [],
        "images": [],
        "links": [],
        "schema": {
            "summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []},
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {},
        "redirect": {},
        "robots": {},
        "meta_robots": "index, follow",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {},
        "serp_audit": {},
        "keywords": [],
        "final_url": url,
        "discovery": {"llms_txt": {"present": True}},
    }
    return CrawlPayload.from_raw(raw)


def _seeded_store(tmp_path: Path, url: str) -> tuple[Path, str]:
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, StoredAudit(url=url, payload=_payload(url).to_mapping()))
    store.finish_run(run_id)
    store.close()
    return db, run_id


def test_sqlite_repository_loads_stored_payload(tmp_path: Path) -> None:
    url = "https://e.com/p"
    db, run_id = _seeded_store(tmp_path, url)
    with CrawlRunRef(db, run_id).open() as repo:
        loaded = repo.load_payload(url)
    assert loaded == _payload(url)
    assert loaded is not None and loaded.discovery == {"llms_txt": {"present": True}}


def test_sqlite_repository_returns_none_for_missing_url(tmp_path: Path) -> None:
    db, run_id = _seeded_store(tmp_path, "https://e.com/p")
    with CrawlRunRef(db, run_id).open() as repo:
        assert repo.load_payload("https://e.com/absent") is None


def test_in_memory_repository_returns_result_payload() -> None:
    url = "https://e.com/p"
    result = SiteCrawlResult.from_payload(url, _payload(url))
    repo = InMemoryCrawlRunRepository([result])
    assert repo.load_payload(url) == _payload(url)
    assert repo.load_payload("https://e.com/absent") is None


def test_missing_database_is_not_created_on_read(tmp_path: Path) -> None:
    # Adversarial: opening a ref to a non-existent DB and reading must NOT
    # create (or migrate) a database — it must degrade to None.
    missing = tmp_path / "does_not_exist.db"
    with CrawlRunRef(missing, "run-x").open() as repo:
        assert repo.load_payload("https://e.com/p") is None
    assert not missing.exists()


def test_missing_run_returns_none(tmp_path: Path) -> None:
    db, _real_run = _seeded_store(tmp_path, "https://e.com/p")
    with CrawlRunRef(db, "no-such-run").open() as repo:
        assert repo.load_payload("https://e.com/p") is None


def test_warns_on_expected_but_missing_payload(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # A crawled (non-error) row whose payload blob is absent/corrupt is an
    # integrity problem: load_payload returns None and warns with run id + url.
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, StoredAudit(url="https://e.com/p", http_status="200", payload=None))
    store.finish_run(run_id)
    store.close()
    with caplog.at_level(logging.WARNING, logger="silentfrog.crawl_run_repository"):
        with CrawlRunRef(db, run_id).open() as repo:
            assert repo.load_payload("https://e.com/p") is None
    assert run_id in caplog.text
    assert "https://e.com/p" in caplog.text


def test_does_not_warn_for_failed_row_without_payload(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    # A failed/skipped row legitimately carries no payload — no warning.
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, StoredAudit(url="https://e.com/err", http_status="error", payload=None))
    store.finish_run(run_id)
    store.close()
    with caplog.at_level(logging.WARNING, logger="silentfrog.crawl_run_repository"):
        with CrawlRunRef(db, run_id).open() as repo:
            assert repo.load_payload("https://e.com/err") is None
    assert "missing or corrupt" not in caplog.text


def test_crawl_run_ref_is_frozen() -> None:
    ref = CrawlRunRef(Path("x.db"), "run-1")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.run_id = "other"  # type: ignore[misc]


def test_crawl_run_ref_shared_across_threads_each_opens_own_repo(tmp_path: Path) -> None:
    # The ref is an immutable value safe to share across threads; each thread
    # opens its OWN repository (its own SQLite connection) — no shared handle.
    url = "https://e.com/p"
    db, run_id = _seeded_store(tmp_path, url)
    ref = CrawlRunRef(db, run_id)
    loaded: dict[int, CrawlPayload | None] = {}

    def worker(index: int) -> None:
        with ref.open() as repo:
            loaded[index] = repo.load_payload(url)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert set(loaded) == {0, 1, 2, 3}
    assert all(payload == _payload(url) for payload in loaded.values())


def test_hydrate_payloads_reloads_stripped_via_repository(tmp_path: Path) -> None:
    url = "https://e.com/p"
    db, run_id = _seeded_store(tmp_path, url)
    stripped = dataclasses.replace(SiteCrawlResult.from_payload(url, _payload(url)), payload=None)
    with CrawlRunRef(db, run_id).open() as repo:
        out = hydrate_payloads([stripped], repo)
    assert out[0].payload == _payload(url)


def test_hydrate_payloads_passthrough_without_repository() -> None:
    url = "https://e.com/p"
    stripped = dataclasses.replace(SiteCrawlResult.from_payload(url, _payload(url)), payload=None)
    out = hydrate_payloads([stripped], None)
    assert out[0].payload is None


def test_hydrate_payloads_keeps_unrecoverable_none(tmp_path: Path) -> None:
    db, run_id = _seeded_store(tmp_path, "https://e.com/p")  # only /p is stored
    absent = "https://e.com/absent"
    stripped = dataclasses.replace(SiteCrawlResult.from_payload(absent, _payload(absent)), payload=None)
    with CrawlRunRef(db, run_id).open() as repo:
        out = hydrate_payloads([stripped], repo)
    assert out[0].payload is None


# --- PR-10: SQL-backed paging / sorting / filtering for the windowed GUI model ---


def _seed_rows(db: Path, rows: list[tuple[str, str, str, str, int]]) -> str:
    """rows = (url, http_status, indexability, title, geo_score). Lightweight only
    (no payload) — paging/sort/filter operate on the duplicated columns."""
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "list")
    for url, status, indexability, title, score in rows:
        store.save_audit(
            run_id,
            StoredAudit(url=url, http_status=status, indexability=indexability, title=title, geo_score=score),
        )
    store.finish_run(run_id)
    store.close()
    return run_id


def test_page_results_paging_boundaries(tmp_path: Path) -> None:
    rows = [(f"https://e.com/{i}", "200", "Indexable", f"T{i}", 80) for i in range(5)]
    db = tmp_path / "crawl.db"
    run_id = _seed_rows(db, rows)
    with CrawlRunRef(db, run_id).open() as repo:
        q = CrawlRowQuery()
        first = [r.url for r in repo.page_results(q, offset=0, limit=2)]
        middle = [r.url for r in repo.page_results(q, offset=2, limit=2)]
        last = [r.url for r in repo.page_results(q, offset=4, limit=2)]  # partial page
        past_end = repo.page_results(q, offset=5, limit=2)  # beyond the data
    assert first == ["https://e.com/0", "https://e.com/1"]
    assert middle == ["https://e.com/2", "https://e.com/3"]
    assert last == ["https://e.com/4"]
    assert past_end == []


def test_page_results_stable_sort_with_insertion_tiebreak(tmp_path: Path) -> None:
    # Equal sort keys (same status) must keep crawl (insertion) order, so paging
    # is deterministic and never drops or repeats a row across pages.
    rows = [
        ("https://e.com/c", "200", "Indexable", "T", 1),
        ("https://e.com/a", "404", "Not indexable", "T", 2),
        ("https://e.com/b", "200", "Indexable", "T", 3),
    ]
    db = tmp_path / "crawl.db"
    run_id = _seed_rows(db, rows)
    with CrawlRunRef(db, run_id).open() as repo:
        by_status = [r.url for r in repo.page_results(CrawlRowQuery(sort="http_status"), 0, 10)]
        by_url_desc = [r.url for r in repo.page_results(CrawlRowQuery(sort="url", descending=True), 0, 10)]
    # 200 rows first (insertion order c, then b), then 404 (a).
    assert by_status == ["https://e.com/c", "https://e.com/b", "https://e.com/a"]
    assert by_url_desc == ["https://e.com/c", "https://e.com/b", "https://e.com/a"]


def test_filtered_count_and_page_apply_filters(tmp_path: Path) -> None:
    rows = [
        ("https://e.com/ok", "200", "Indexable", "Home", 90),
        ("https://e.com/missing", "404", "Not indexable", "Gone", 0),
        ("https://e.com/blog", "200", "Indexable", "Blog", 70),
    ]
    db = tmp_path / "crawl.db"
    run_id = _seed_rows(db, rows)
    with CrawlRunRef(db, run_id).open() as repo:
        assert repo.filtered_count(CrawlRowQuery()) == 3
        assert repo.filtered_count(CrawlRowQuery(status="200")) == 2
        assert repo.filtered_count(CrawlRowQuery(indexability="Not indexable")) == 1
        assert [r.url for r in repo.page_results(CrawlRowQuery(status="404"), 0, 10)] == ["https://e.com/missing"]
        # search is a case-insensitive substring over url + title
        assert [r.url for r in repo.page_results(CrawlRowQuery(search="BLOG"), 0, 10)] == ["https://e.com/blog"]


def test_large_count_pages_without_loading_all(tmp_path: Path) -> None:
    rows = [(f"https://e.com/{i:05d}", "200", "Indexable", f"T{i}", 80) for i in range(2000)]
    db = tmp_path / "crawl.db"
    run_id = _seed_rows(db, rows)
    with CrawlRunRef(db, run_id).open() as repo:
        assert repo.filtered_count(CrawlRowQuery()) == 2000
        page = repo.page_results(CrawlRowQuery(sort="url"), offset=0, limit=100)
        tail = repo.page_results(CrawlRowQuery(sort="url"), offset=1950, limit=100)
    assert len(page) == 100  # a page, never the whole table
    assert page[0].url == "https://e.com/00000"
    assert len(tail) == 50
    assert tail[-1].url == "https://e.com/01999"
