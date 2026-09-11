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
  defaults ``pending``; ``claim_pending``/``mark`` drive the
  ``in_progress``/``completed`` transitions (PR-8a); ``requeue_in_progress``
  resets ``in_progress -> pending`` on resume (PR-9) so an interrupted crawl
  re-runs only its unfinished URLs.

``insertion_order`` is an AUTOINCREMENT primary key — it preserves crawl
order without the O(n²) ``urls.index()`` sort the in-memory list used.

Migrations are additive (new tables via ``CREATE TABLE IF NOT EXISTS``),
so opening a v1 database simply adds ``frontier``; old crawls have no
frontier rows and keep edgeless graphs until re-crawled.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2


class NewerSchemaError(RuntimeError):
    """Raised when an on-disk store's ``PRAGMA user_version`` is newer than
    this build's ``SCHEMA_VERSION`` — a newer version of the app wrote this
    file. Refusing (rather than silently stamping the version backward) keeps
    a newer store from being downgraded and losing whatever that newer schema
    added. ``apply_schema`` closes the refused connection before raising, so
    handlers get a released file, not a locked one."""

    def __init__(self, found: int, expected: int) -> None:
        self.found = found
        self.expected = expected
        super().__init__(
            f"This crawl database was written by a newer version of the app "
            f"(schema {found}, this build supports up to {expected}). "
            "Open it with a newer version of the app instead."
        )


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
    """Create tables + indexes and set the schema version. Idempotent.

    Refuses (:class:`NewerSchemaError`) instead of applying anything when the
    store's existing ``user_version`` is already newer than this build's
    ``SCHEMA_VERSION`` — that store was written by a newer app version, and
    silently stamping ``PRAGMA user_version`` backward would downgrade its
    recorded schema without migrating anything. The file is left byte-for-byte
    untouched, and ``conn`` is closed before the raise: the store behind it is
    unusable to this build, and the raising frames stay alive inside the
    exception's traceback (``CrawlStore.__init__`` holds the connection it
    just opened), so an unclosed handle keeps the ``.db`` locked on Windows
    ([WinError 32]) until a garbage-collection pass."""
    current = schema_version(conn)
    if current > SCHEMA_VERSION:
        conn.close()
        raise NewerSchemaError(current, SCHEMA_VERSION)
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


__all__ = ["SCHEMA_VERSION", "NewerSchemaError", "apply_schema", "schema_version"]
