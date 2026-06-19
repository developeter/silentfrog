"""Unit tests for the run-bound CrawlRunRepository seam (v2.0 H1)."""

from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any

import pytest

from silentfrog.crawl_run_repository import CrawlRunRef, InMemoryCrawlRunRepository
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
