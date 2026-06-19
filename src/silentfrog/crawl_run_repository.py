"""Run-bound crawl-result repository (v2.0 H1).

A crawl streams its audits into a SQLite store keyed by ``run_id``.
``CrawlRunRef`` is an immutable handle to one such run: it is safe to pass
across threads, and each thread opens its OWN :class:`CrawlRunRepository`
from it (no shared SQLite connection). The repository is the single seam
consumers (GUI detail dialog, recap, history) use to read a run's data — it
is bound to one run, so no method takes a ``run_id``.

The in-memory implementation backs tests and explicitly bounded small
programmatic crawls; production GUI crawls are SQLite-backed.

Payload I/O is explicit here (``load_payload``); there is intentionally no
lazy auto-loading hidden behind ``SiteCrawlResult.payload``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .crawl_store import _decompress
from .crawl_types import CrawlPayload
from .site_crawl_types import SiteCrawlResult

logger = logging.getLogger(__name__)

# Row statuses that legitimately carry no payload (failed / skipped / uncrawled).
# A missing payload for these is expected and must not warn.
_NO_PAYLOAD_STATUSES = frozenset({"", "error", "skipped"})


def _open_readonly(db_path: Path | str) -> sqlite3.Connection | None:
    """Open an EXISTING crawl database read-only.

    Never creates or migrates storage: a missing or unopenable file yields
    ``None`` so reads degrade gracefully instead of fabricating a fresh DB.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _payload_from_blob(blob: bytes | None) -> CrawlPayload | None:
    raw = _decompress(blob)
    if raw is None:
        return None
    try:
        return CrawlPayload.from_raw(raw)
    except (ValueError, TypeError):
        return None


class CrawlRunRepository(Protocol):
    """Run-bound read seam over one crawl's audits.

    Every method operates on the single run the repository was opened for, so
    none takes a ``run_id``. Use as a context manager so the backing handle is
    released on the thread that opened it.
    """

    def load_payload(self, url: str) -> CrawlPayload | None: ...

    def close(self) -> None: ...

    def __enter__(self) -> CrawlRunRepository: ...

    def __exit__(self, *exc: object) -> None: ...


@dataclass(frozen=True)
class CrawlRunRef:
    """Immutable, thread-safe handle to one crawl run.

    Pass this across threads; each thread calls :meth:`open` to obtain its own
    repository (and its own SQLite connection).
    """

    db_path: Path
    run_id: str

    def open(self) -> CrawlRunRepository:
        return SqliteCrawlRunRepository(self.db_path, self.run_id)


class SqliteCrawlRunRepository:
    """SQLite-backed repository: opens an EXISTING database READ-ONLY, bound to
    one run. Never creates or migrates storage on reads — a missing database or
    a missing run simply yields ``None``.

    Not shared across threads: open one per thread from a :class:`CrawlRunRef`.
    """

    def __init__(self, db_path: Path | str, run_id: str) -> None:
        self._conn = _open_readonly(db_path)
        self._run_id = run_id

    def load_payload(self, url: str) -> CrawlPayload | None:
        if self._conn is None:
            return None  # database absent — never created on a read
        try:
            row = self._conn.execute(
                "SELECT payload_blob, http_status FROM audits WHERE run_id = ? AND url = ?",
                (self._run_id, url),
            ).fetchone()
        except sqlite3.Error:
            return None  # not a crawl database / schema absent — degrade, don't crash
        if row is None:
            return None  # URL was not part of this run
        payload = _payload_from_blob(row[0])
        if payload is None and str(row[1]) not in _NO_PAYLOAD_STATUSES:
            logger.warning("crawled payload missing or corrupt for run %s url %s", self._run_id, url)
        return payload

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def __enter__(self) -> SqliteCrawlRunRepository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class InMemoryCrawlRunRepository:
    """In-memory repository for tests and explicitly bounded small programmatic
    crawls — backed by the crawl's results, with no SQLite and no persistence.
    """

    def __init__(self, results: Sequence[SiteCrawlResult]) -> None:
        # Retain only real payloads: a stored ``None`` would be indistinguishable
        # from a missing URL. The sole caller hydrates only when a result's own
        # payload is already None, so dropping these keeps behaviour identical
        # while removing the impossible state.
        self._payloads: dict[str, CrawlPayload] = {r.url: r.payload for r in results if r.payload is not None}

    def load_payload(self, url: str) -> CrawlPayload | None:
        return self._payloads.get(url)

    def close(self) -> None:
        pass

    def __enter__(self) -> InMemoryCrawlRunRepository:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


__all__ = [
    "CrawlRunRef",
    "CrawlRunRepository",
    "InMemoryCrawlRunRepository",
    "SqliteCrawlRunRepository",
]
