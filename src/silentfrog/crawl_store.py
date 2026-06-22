"""Streaming SQLite crawl store (v2.0 V2).

Replaces the in-memory ``list[SiteCrawlResult]`` (which held a full
``CrawlPayload`` per URL and sorted O(n²) at the end) so memory stays
bounded as the crawl grows rather than scaling with URL count. Measured
peak RSS is ~117 MB at 100k URLs vs ~96 MB at 10k — the verified scale
gate; 1M is a post-gate follow-up (method + numbers:
``tools/perf_harness.py`` / ``tools/perf_baseline.json``). Each completed
audit is written immediately, batched for speed; the full payload is
zlib-compressed JSON deserialised only on demand.

Public surface (all typed):

- ``CrawlStore`` — `start_run`, `save_audit`, `admit`, `claim_pending`,
  `mark`, `requeue_in_progress`, `frontier_count`, `flush`, `finish_run`,
  `iter_lightweight`, `iter_graph_inputs`, `load_payload`, `summary`,
  `resume_pending`, `close`.
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
        self._db_path = Path(db_path)
        self._conn = sqlite3.connect(str(db_path))
        apply_schema(self._conn)
        self._pending_writes = 0

    @property
    def db_path(self) -> Path:
        """On-disk location of this run's store. A file-backed path round-trips
        through ``CrawlRunRef``; ``:memory:`` stores cannot be reopened by a
        separate connection (each ``:memory:`` connection is a fresh database)."""
        return self._db_path

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

    def admit(self, run_id: str, normalized_url: str, source_url: str = "", depth: int = 0) -> bool:
        """Atomically record a URL in the frontier (H3). Returns True when
        newly admitted, False when it was already present (UNIQUE dedup).
        Batched with audit writes; the row starts in the default ``pending``
        state. The ``in_progress``/``completed`` transitions are driven by
        ``claim_pending``/``mark`` (PR-8a); resume requeue lands in PR-9."""
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO frontier (run_id, normalized_url, source_url, depth) VALUES (?, ?, ?, ?)",
            (run_id, normalized_url, source_url, depth),
        )
        self._pending_writes += 1
        if self._pending_writes >= _BATCH_SIZE:
            self.flush()
        return cursor.rowcount > 0

    def claim_pending(self, run_id: str, limit: int) -> list[tuple[str, int, str]]:
        """Atomically claim up to ``limit`` ``pending`` frontier rows (PR-8a):
        transition them ``pending -> in_progress`` and return ``(url, depth,
        source_url)`` in admission order. The single crawl producer calls this
        to feed the bounded work queue; ``in_progress`` rows are never returned
        again, so the same URL is never claimed twice within a run."""
        rows = self._conn.execute(
            "SELECT normalized_url, depth, source_url FROM frontier "
            "WHERE run_id = ? AND state = 'pending' ORDER BY rowid LIMIT ?",
            (run_id, limit),
        ).fetchall()
        if not rows:
            return []
        self._set_state(run_id, [str(row[0]) for row in rows], "in_progress")
        return [(str(row[0]), int(row[1]), str(row[2])) for row in rows]

    def mark(self, run_id: str, normalized_url: str, state: str) -> None:
        """Set the terminal frontier ``state`` of one claimed URL (PR-8a)."""
        self._set_state(run_id, [normalized_url], state)

    def requeue_in_progress(self, run_id: str) -> int:
        """Return every claimed-but-unfinished frontier row to ``pending`` (PR-9
        resume). A crawl that was cancelled or crashed leaves rows ``in_progress``;
        an abandoned claim never wrote an audit, so on resume those URLs must be
        re-claimed and re-crawled. ``pending`` and terminal rows are untouched, so
        resume re-runs only unfinished URLs with no duplicates. Returns the count
        requeued. Committed immediately: the requeue must be durable before the
        producer starts claiming."""
        cursor = self._conn.execute(
            "UPDATE frontier SET state = 'pending' WHERE run_id = ? AND state = 'in_progress'",
            (run_id,),
        )
        self._conn.commit()
        return cursor.rowcount

    def frontier_count(self, run_id: str) -> int:
        """Number of URLs admitted to this run's frontier in any state — the cap
        baseline the producer resumes from, so a resumed crawl honors ``max_urls``
        across sessions instead of admitting another ``max_urls`` on top."""
        row = self._conn.execute("SELECT COUNT(*) FROM frontier WHERE run_id = ?", (run_id,)).fetchone()
        return int(row[0]) if row else 0

    def _set_state(self, run_id: str, urls: list[str], state: str) -> None:
        # Parameterised IN-list: only the placeholder COUNT is interpolated,
        # never values, so this stays injection-safe. ``urls`` is bounded by the
        # caller's claim batch (a small constant).
        placeholders = ",".join("?" for _ in urls)
        self._conn.execute(
            f"UPDATE frontier SET state = ? WHERE run_id = ? AND normalized_url IN ({placeholders})",
            (state, run_id, *urls),
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

    def iter_graph_inputs(self, run_id: str) -> list[tuple[str, str, int]]:
        """Link-graph rows: every audited URL with the page it was discovered
        from. Edges come from the frontier table via a LEFT JOIN, so a crawl
        predating the frontier table stays edgeless instead of empty."""
        cursor = self._conn.execute(
            """
            SELECT a.url, COALESCE(f.source_url, ''), a.geo_score
            FROM audits a
            LEFT JOIN frontier f ON f.run_id = a.run_id AND f.normalized_url = a.url
            WHERE a.run_id = ?
            ORDER BY a.insertion_order
            """,
            (run_id,),
        )
        return [(str(row[0]), str(row[1]), int(row[2])) for row in cursor.fetchall()]

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
