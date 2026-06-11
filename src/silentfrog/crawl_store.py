"""Streaming SQLite crawl store (v2.0 V2).

Replaces the in-memory ``list[SiteCrawlResult]`` (which held a full
``CrawlPayload`` per URL and sorted O(n²) at the end) so crawls of up to
~1M URLs stay at flat RAM. Each completed audit is written immediately,
batched for speed; the full payload is zlib-compressed JSON deserialised
only on demand.

Public surface (all typed):

- ``CrawlStore`` — `start_run`, `save_audit`, `flush`, `finish_run`,
  `iter_lightweight`, `load_payload`, `summary`, `resume_pending`,
  `close`.
- ``StoredAudit`` — what the crawler hands to `save_audit`.
- ``LightweightAudit`` / ``RunSummary`` — read-side views (no blob).
"""

from __future__ import annotations

import json
import os
import sqlite3
import statistics
import uuid
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .crawl_store_schema import apply_schema

_BATCH_SIZE = 200


def crawls_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / "crawls"


def new_crawl_db_path() -> Path:
    directory = crawls_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"crawl_{uuid.uuid4().hex}.db"


@dataclass(frozen=True)
class StoredAudit:
    url: str
    depth: int = 0
    discovered_from: str = ""
    http_status: str = ""
    geo_score: int = 0
    indexability: str = ""
    title: str = ""
    issue_summary: str = ""
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class LightweightAudit:
    url: str
    depth: int
    discovered_from: str
    http_status: str
    geo_score: int
    indexability: str
    title: str
    issue_summary: str
    insertion_order: int


@dataclass(frozen=True)
class RunSummary:
    total: int = 0
    failed: int = 0
    skipped: int = 0
    score_min: int = 0
    score_max: int = 0
    score_p50: float = 0.0
    scores: tuple[int, ...] = field(default_factory=tuple)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _compress(payload: dict[str, Any] | None) -> bytes | None:
    if payload is None:
        return None
    return zlib.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _decompress(blob: bytes | None) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except (zlib.error, json.JSONDecodeError, ValueError):
        return None


class CrawlStore:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path))
        apply_schema(self._conn)
        self._pending_writes = 0

    # -- run lifecycle -------------------------------------------------
    def start_run(self, scope: str, base_url: str, mode: str) -> str:
        run_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO runs (run_id, scope, base_url, mode, started_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, scope, base_url, mode, _now_iso()),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        self.flush()
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (_now_iso(), status, run_id),
        )
        self._conn.commit()

    # -- writes --------------------------------------------------------
    def save_audit(self, run_id: str, audit: StoredAudit) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO audits
                (run_id, url, depth, discovered_from, http_status, geo_score,
                 indexability, title, issue_summary, payload_blob, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                audit.url,
                audit.depth,
                audit.discovered_from,
                audit.http_status,
                audit.geo_score,
                audit.indexability,
                audit.title,
                audit.issue_summary,
                _compress(audit.payload),
                _now_iso(),
            ),
        )
        self._pending_writes += 1
        if self._pending_writes >= _BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        if self._pending_writes:
            self._conn.commit()
            self._pending_writes = 0

    # -- reads ---------------------------------------------------------
    def iter_lightweight(self, run_id: str, offset: int = 0, limit: int = 1000) -> list[LightweightAudit]:
        cursor = self._conn.execute(
            """
            SELECT url, depth, discovered_from, http_status, geo_score,
                   indexability, title, issue_summary, insertion_order
            FROM audits WHERE run_id = ?
            ORDER BY insertion_order LIMIT ? OFFSET ?
            """,
            (run_id, limit, offset),
        )
        return [_lightweight_from_row(row) for row in cursor.fetchall()]

    def count(self, run_id: str) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM audits WHERE run_id = ?", (run_id,)).fetchone()
        return int(row[0]) if row else 0

    def load_payload(self, run_id: str, url: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload_blob FROM audits WHERE run_id = ? AND url = ?",
            (run_id, url),
        ).fetchone()
        return _decompress(row[0]) if row else None

    def resume_pending(self, run_id: str, candidate_urls: Iterable[str]) -> list[str]:
        saved = {row[0] for row in self._conn.execute("SELECT url FROM audits WHERE run_id = ?", (run_id,)).fetchall()}
        return [url for url in candidate_urls if url not in saved]

    def summary(self, run_id: str) -> RunSummary:
        self.flush()
        scores = [
            int(row[0])
            for row in self._conn.execute(
                "SELECT geo_score FROM audits WHERE run_id = ? AND http_status NOT IN ('error', 'skipped')",
                (run_id,),
            ).fetchall()
        ]
        failed = self._status_count(run_id, "error")
        skipped = self._status_count(run_id, "skipped")
        total = self.count(run_id)
        if not scores:
            return RunSummary(total=total, failed=failed, skipped=skipped)
        return RunSummary(
            total=total,
            failed=failed,
            skipped=skipped,
            score_min=min(scores),
            score_max=max(scores),
            score_p50=round(statistics.median(scores), 1),
            scores=tuple(scores),
        )

    def _status_count(self, run_id: str, status: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM audits WHERE run_id = ? AND http_status = ?",
            (run_id, status),
        ).fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        self.flush()
        self._conn.close()


def _lightweight_from_row(row: Sequence[Any]) -> LightweightAudit:
    return LightweightAudit(
        url=str(row[0]),
        depth=int(row[1]),
        discovered_from=str(row[2]),
        http_status=str(row[3]),
        geo_score=int(row[4]),
        indexability=str(row[5]),
        title=str(row[6]),
        issue_summary=str(row[7]),
        insertion_order=int(row[8]),
    )


__all__ = [
    "CrawlStore",
    "LightweightAudit",
    "RunSummary",
    "StoredAudit",
    "crawls_dir",
    "new_crawl_db_path",
]
