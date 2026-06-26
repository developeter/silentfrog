"""Run-bound crawl-result repository (v2.0 H1/H2).

A crawl streams its audits into a SQLite store keyed by ``run_id``.
``CrawlRunRef`` is an immutable handle to one such run: it is safe to pass
across threads, and each thread opens its OWN :class:`CrawlRunRepository`
from it (no shared SQLite connection). The repository is the single seam
consumers (GUI detail dialog, recap, history, diff, exporters, AI review)
use to read a run's data — it is bound to one run, so no method takes a
``run_id``.

Since PR-8b the report carries a ``CrawlRunRef`` instead of a per-URL result
tuple, so consumers stream results through this seam (``stream_results``)
rather than holding the whole crawl in memory. The in-memory implementation
backs tests and explicitly bounded small programmatic crawls; production GUI
crawls are SQLite-backed.

Payload I/O is explicit here (``load_payload``); there is intentionally no
lazy auto-loading hidden behind ``SiteCrawlResult.payload``.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .crawl_store import LightweightAudit, _decompress, _lightweight_from_row
from .crawl_types import CrawlPayload
from .site_crawl_types import SiteCrawlResult

if TYPE_CHECKING:
    from .site_crawl_types import SiteCrawlReport

logger = logging.getLogger(__name__)

# Row statuses that legitimately carry no payload (failed / skipped / uncrawled).
# A missing payload for these is expected and must not warn.
_NO_PAYLOAD_STATUSES = frozenset({"", "error", "skipped"})

_STREAM_BATCH = 500

# Audit columns the windowed GUI model may sort/filter on (PR-10). These are the
# lightweight columns the store duplicates out of the payload, so a page query
# never decompresses a blob. Display columns derived from the payload (words, img
# issues, ...) are not here and fall back to crawl (insertion) order — sorting
# them would require loading every payload, defeating the bounded window.
_SORTABLE_COLUMNS = frozenset({"url", "http_status", "indexability", "title", "geo_score", "issue_summary"})

# Lightweight columns the V19 crawl-level distribution charts may GROUP BY. Kept
# allowlisted so the column name is never interpolated from untrusted input.
_DISTRIBUTION_COLUMNS = frozenset({"http_status", "indexability"})
# Statuses with no real GEO score, excluded from the score distribution. Matches
# ``CrawlStore.summary`` so the chart and the summary agree.
_NO_SCORE_STATUSES = ("error", "skipped")


@dataclass(frozen=True)
class CrawlRowQuery:
    """Filter + sort spec for one windowed page of a run's audited rows.

    All fields optional; the default selects every row in crawl (insertion)
    order. ``sort`` must name a column in :data:`_SORTABLE_COLUMNS` or it falls
    back to insertion order. ``status``/``indexability`` are exact matches (empty
    = no filter); ``search`` is a case-insensitive substring over url + title.
    """

    sort: str = ""
    descending: bool = False
    status: str = ""
    indexability: str = ""
    search: str = ""


def _row_filters(run_id: str, query: CrawlRowQuery) -> tuple[str, list[object]]:
    """Build the parameterised WHERE clause for a row query. Only placeholders
    are interpolated; every value is bound, so this stays injection-safe."""
    clauses = ["run_id = ?"]
    params: list[object] = [run_id]
    if query.status:
        clauses.append("http_status = ?")
        params.append(query.status)
    if query.indexability:
        clauses.append("indexability = ?")
        params.append(query.indexability)
    if query.search:
        clauses.append("(url LIKE ? OR title LIKE ?)")
        like = f"%{query.search}%"
        params.extend([like, like])
    return " AND ".join(clauses), params


def _row_order(query: CrawlRowQuery) -> str:
    # ``insertion_order`` is the stable tiebreak so equal keys keep crawl order;
    # the sort column is allowlisted (never raw input) before interpolation.
    if query.sort not in _SORTABLE_COLUMNS:
        return "insertion_order ASC"
    direction = "DESC" if query.descending else "ASC"
    return f"{query.sort} {direction}, insertion_order ASC"


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


def _result_from_lightweight(light: LightweightAudit) -> SiteCrawlResult:
    """Reconstruct a degraded result when a success row's payload is missing
    (corruption): keep the lightweight columns the store duplicated out of the
    payload so the URL is never silently dropped from a stream."""
    return SiteCrawlResult(
        url=light.url,
        status=light.http_status,
        redirect_status="",
        final_url=light.url,
        title=light.title,
        description_state="",
        canonical_state="",
        indexability=light.indexability,
        hreflang_count=0,
        schema_count=0,
        image_issue_count=0,
        h1_state="",
        word_count=0,
        link_issue_count=0,
        performance_verdict="-",
        ai_visibility_verdict="-",
        geo_score=light.geo_score,
        error=light.issue_summary,
    )


def _result_from_row(light: LightweightAudit, payload: CrawlPayload | None) -> SiteCrawlResult:
    if light.http_status == "error":
        return SiteCrawlResult.failed(light.url, light.issue_summary)
    if light.http_status == "skipped":
        return SiteCrawlResult.skipped(light.url, light.issue_summary)
    if payload is not None:
        return SiteCrawlResult.from_payload(light.url, payload)
    return _result_from_lightweight(light)


class CrawlRunRepository(Protocol):
    """Run-bound read seam over one crawl's audits.

    Every method operates on the single run the repository was opened for, so
    none takes a ``run_id``. Use as a context manager so the backing handle is
    released on the thread that opened it.
    """

    def load_payload(self, url: str) -> CrawlPayload | None: ...

    def iter_lightweight(self, offset: int, limit: int) -> list[LightweightAudit]: ...

    def stream_results(self, batch: int = _STREAM_BATCH) -> Iterator[SiteCrawlResult]: ...

    def count(self) -> int: ...

    def score_values(self) -> list[int]: ...

    def status_distribution(self) -> dict[str, int]: ...

    def indexability_distribution(self) -> dict[str, int]: ...

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
    a missing run simply yields empty reads.

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

    def iter_lightweight(self, offset: int, limit: int) -> list[LightweightAudit]:
        if self._conn is None:
            return []
        try:
            cursor = self._conn.execute(
                """
                SELECT url, depth, discovered_from, http_status, geo_score,
                       indexability, title, issue_summary, insertion_order
                FROM audits WHERE run_id = ?
                ORDER BY insertion_order LIMIT ? OFFSET ?
                """,
                (self._run_id, limit, offset),
            )
        except sqlite3.Error:
            return []
        return [_lightweight_from_row(row) for row in cursor.fetchall()]

    def stream_results(self, batch: int = _STREAM_BATCH) -> Iterator[SiteCrawlResult]:
        """Stream every audited URL as a reconstructed :class:`SiteCrawlResult`,
        a page of rows at a time so memory stays flat at ~1M URLs. Successful
        rows are rebuilt from the (losslessly round-tripped, H0) payload; failed
        and skipped rows carry no payload and rebuild from lightweight columns."""
        offset = 0
        while True:
            rows = self.iter_lightweight(offset, batch)
            if not rows:
                return
            for light in rows:
                payload = None if light.http_status in _NO_PAYLOAD_STATUSES else self.load_payload(light.url)
                yield _result_from_row(light, payload)
            if len(rows) < batch:
                return
            offset += len(rows)

    def count(self) -> int:
        if self._conn is None:
            return 0
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM audits WHERE run_id = ?", (self._run_id,)).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0]) if row else 0

    def score_values(self) -> list[int]:
        """GEO scores of every successfully-audited URL (no payload load), for the
        crawl-level score distribution chart. Failed/skipped rows are excluded."""
        if self._conn is None:
            return []
        placeholders = ", ".join("?" for _ in _NO_SCORE_STATUSES)
        try:
            cursor = self._conn.execute(
                f"SELECT geo_score FROM audits WHERE run_id = ? AND http_status NOT IN ({placeholders})",
                (self._run_id, *_NO_SCORE_STATUSES),
            )
        except sqlite3.Error:
            return []
        return [int(row[0]) for row in cursor.fetchall()]

    def status_distribution(self) -> dict[str, int]:
        """Audited-URL count per HTTP status (read-only GROUP BY, no payloads)."""
        return self._count_by("http_status")

    def indexability_distribution(self) -> dict[str, int]:
        """Audited-URL count per indexability verdict (read-only GROUP BY)."""
        return self._count_by("indexability")

    def _count_by(self, column: str) -> dict[str, int]:
        if self._conn is None or column not in _DISTRIBUTION_COLUMNS:
            return {}
        try:
            cursor = self._conn.execute(
                f"SELECT {column}, COUNT(*) FROM audits WHERE run_id = ? GROUP BY {column}",
                (self._run_id,),
            )
        except sqlite3.Error:
            return {}
        return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

    def filtered_count(self, query: CrawlRowQuery) -> int:
        """Number of rows matching ``query`` — the windowed GUI model's row count
        (PR-10). O(1)-ish in memory: SQL counts, nothing is materialised."""
        if self._conn is None:
            return 0
        where, params = _row_filters(self._run_id, query)
        try:
            row = self._conn.execute(f"SELECT COUNT(*) FROM audits WHERE {where}", params).fetchone()
        except sqlite3.Error:
            return 0
        return int(row[0]) if row else 0

    def page_results(self, query: CrawlRowQuery, offset: int, limit: int) -> list[SiteCrawlResult]:
        """One SQL-sorted/filtered page of fully-rebuilt results (PR-10). Only this
        page's payloads are loaded, so the GUI model holds at most a window in
        memory regardless of crawl size. Failed/skipped rows carry no payload and
        rebuild from the lightweight columns."""
        results: list[SiteCrawlResult] = []
        for light in self._page_lightweight(query, offset, limit):
            payload = None if light.http_status in _NO_PAYLOAD_STATUSES else self.load_payload(light.url)
            results.append(_result_from_row(light, payload))
        return results

    def _page_lightweight(self, query: CrawlRowQuery, offset: int, limit: int) -> list[LightweightAudit]:
        if self._conn is None:
            return []
        where, params = _row_filters(self._run_id, query)
        sql = (
            "SELECT url, depth, discovered_from, http_status, geo_score, indexability, "
            f"title, issue_summary, insertion_order FROM audits WHERE {where} "
            f"ORDER BY {_row_order(query)} LIMIT ? OFFSET ?"
        )
        try:
            cursor = self._conn.execute(sql, [*params, limit, offset])
        except sqlite3.Error:
            return []
        return [_lightweight_from_row(row) for row in cursor.fetchall()]

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
        self._results: tuple[SiteCrawlResult, ...] = tuple(results)
        # Retain only real payloads: a stored ``None`` would be indistinguishable
        # from a missing URL, and ``load_payload`` must not invent one.
        self._payloads: dict[str, CrawlPayload] = {r.url: r.payload for r in self._results if r.payload is not None}

    def load_payload(self, url: str) -> CrawlPayload | None:
        return self._payloads.get(url)

    def iter_lightweight(self, offset: int, limit: int) -> list[LightweightAudit]:
        window = self._results[offset : offset + limit]
        return [_lightweight_from_result(index + offset, result) for index, result in enumerate(window)]

    def stream_results(self, batch: int = _STREAM_BATCH) -> Iterator[SiteCrawlResult]:
        yield from self._results

    def count(self) -> int:
        return len(self._results)

    def score_values(self) -> list[int]:
        return [r.geo_score for r in self._results if r.status not in _NO_SCORE_STATUSES]

    def status_distribution(self) -> dict[str, int]:
        return dict(Counter(r.status for r in self._results))

    def indexability_distribution(self) -> dict[str, int]:
        return dict(Counter(r.indexability for r in self._results))

    def close(self) -> None:
        pass

    def __enter__(self) -> InMemoryCrawlRunRepository:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def _lightweight_from_result(insertion_order: int, result: SiteCrawlResult) -> LightweightAudit:
    return LightweightAudit(
        url=result.url,
        depth=0,
        discovered_from="",
        http_status=result.status,
        geo_score=result.geo_score,
        indexability=result.indexability,
        title=result.title,
        issue_summary=result.issue_summary(),
        insertion_order=insertion_order,
    )


def open_report_repository(report: SiteCrawlReport) -> CrawlRunRepository:
    """Open the run-bound repository a report's data lives in: SQLite when the
    crawl streamed to a store (production), else an in-memory view of the
    report's bounded inline results (tests + small store-less crawls)."""
    if report.run_ref is not None:
        return report.run_ref.open()
    return InMemoryCrawlRunRepository(report.results)


def stream_report_results(report: SiteCrawlReport) -> Iterator[SiteCrawlResult]:
    """Stream a report's per-URL results through its run-bound repository so a
    consumer never materialises the whole crawl. The repository is opened for
    the lifetime of the iteration and closed when it is exhausted."""
    with open_report_repository(report) as repo:
        yield from repo.stream_results()


def stream_report_lightweight(report: SiteCrawlReport, batch: int = _STREAM_BATCH) -> Iterator[LightweightAudit]:
    """Stream a report's lightweight per-URL rows (no payload load) for consumers
    that only need status/score/url — e.g. the crawl diff — so a comparison never
    decompresses a payload it does not read."""
    with open_report_repository(report) as repo:
        offset = 0
        while True:
            rows = repo.iter_lightweight(offset, batch)
            if not rows:
                return
            yield from rows
            if len(rows) < batch:
                return
            offset += len(rows)


def hydrate_payloads(
    results: Iterable[SiteCrawlResult], repository: CrawlRunRepository | None
) -> list[SiteCrawlResult]:
    """Return results with any stripped (None) payload reloaded via the run-bound
    repository, so bulk consumers (exports, AI review) see complete data.

    Results that already carry a payload — or that the repository cannot recover —
    pass through unchanged. Without a repository, results pass through as-is.
    """
    if repository is None:
        return list(results)
    hydrated: list[SiteCrawlResult] = []
    for result in results:
        if result.payload is None:
            payload = repository.load_payload(result.url)
            if payload is not None:
                result = replace(result, payload=payload)
        hydrated.append(result)
    return hydrated


__all__ = [
    "CrawlRowQuery",
    "CrawlRunRef",
    "CrawlRunRepository",
    "InMemoryCrawlRunRepository",
    "SqliteCrawlRunRepository",
    "hydrate_payloads",
    "open_report_repository",
    "stream_report_lightweight",
    "stream_report_results",
]
