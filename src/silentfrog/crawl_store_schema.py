"""SQLite schema for the streaming crawl store (v2.0 V2).

Versioned via ``PRAGMA user_version`` so future milestones can migrate.
Three tables:

- ``runs`` — one row per crawl run.
- ``audits`` — one row per crawled URL. Lightweight columns (status,
  score, indexability, title, issue summary) are duplicated out of the
  payload so the table model + filters never deserialise the blob;
  ``payload_blob`` holds the zlib-compressed JSON of the full
  ``CrawlPayload`` for on-demand detail / export.
- ``frontier`` (v2/H3) — one row per admitted URL, keyed
  ``UNIQUE(run_id, normalized_url)`` so admission dedups atomically via
  ``INSERT OR IGNORE``. ``source_url`` is the page it was discovered from
  (the durable parent → child edge the link graph reads). ``state``
  defaults ``pending``; the ``in_progress``/``completed`` transitions and
  resume requeue land in PR-8/PR-9, not here.

``insertion_order`` is an AUTOINCREMENT primary key — it preserves crawl
order without the O(n²) ``urls.index()`` sort the in-memory list used.

Migrations are additive (new tables via ``CREATE TABLE IF NOT EXISTS``),
so opening a v1 database simply adds ``frontier``; old crawls have no
frontier rows and keep edgeless graphs until re-crawled.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    scope       TEXT NOT NULL,
    base_url    TEXT NOT NULL,
    mode        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running'
)
"""

_AUDITS_TABLE = """
CREATE TABLE IF NOT EXISTS audits (
    insertion_order INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    url             TEXT NOT NULL,
    depth           INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT NOT NULL DEFAULT '',
    http_status     TEXT NOT NULL DEFAULT '',
    geo_score       INTEGER NOT NULL DEFAULT 0,
    indexability    TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    issue_summary   TEXT NOT NULL DEFAULT '',
    payload_blob    BLOB,
    fetched_at      TEXT NOT NULL DEFAULT '',
    UNIQUE(run_id, url)
)
"""

_AUDITS_ORDER_INDEX = "CREATE INDEX IF NOT EXISTS idx_audits_run_order ON audits(run_id, insertion_order)"

_FRONTIER_TABLE = """
CREATE TABLE IF NOT EXISTS frontier (
    run_id          TEXT NOT NULL,
    normalized_url  TEXT NOT NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    depth           INTEGER NOT NULL DEFAULT 0,
    state           TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending', 'in_progress', 'completed', 'failed', 'skipped')),
    UNIQUE(run_id, normalized_url)
)
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create tables + indexes and set the schema version. Idempotent."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(_RUNS_TABLE)
    conn.execute(_AUDITS_TABLE)
    conn.execute(_AUDITS_ORDER_INDEX)
    conn.execute(_FRONTIER_TABLE)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


__all__ = ["SCHEMA_VERSION", "apply_schema", "schema_version"]
