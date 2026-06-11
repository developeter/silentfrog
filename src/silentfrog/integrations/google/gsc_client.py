"""Google Search Console client (v2.0 V7).

Wraps the Search Analytics API. The ``service`` (a googleapiclient
resource) is injected so the query-building + response-parsing is fully
unit-tested with a fake; the real service is built lazily by
``oauth.build_gsc_service`` only when the user has connected an account.
Never raises — API failures degrade to unmeasured metrics.
"""

from __future__ import annotations

from typing import Any

from .types import GscMetrics


def _query_body(page_url: str, start_date: str, end_date: str, row_limit: int) -> dict[str, Any]:
    return {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "dimensionFilterGroups": [{"filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]}],
        "rowLimit": row_limit,
    }


def _aggregate_rows(rows: list[dict[str, Any]]) -> GscMetrics:
    if not rows:
        return GscMetrics(measured=True)
    impressions = sum(int(r.get("impressions", 0) or 0) for r in rows)
    clicks = sum(int(r.get("clicks", 0) or 0) for r in rows)
    # CTR / position are best aggregated impression-weighted.
    ctr = (clicks / impressions) if impressions else 0.0
    weighted_pos = sum(float(r.get("position", 0.0) or 0.0) * int(r.get("impressions", 0) or 0) for r in rows)
    position = (weighted_pos / impressions) if impressions else 0.0
    top = sorted(rows, key=lambda r: int(r.get("impressions", 0) or 0), reverse=True)[:5]
    top_queries = tuple(str(r.get("keys", [""])[0]) for r in top if r.get("keys"))
    return GscMetrics(
        impressions=impressions,
        clicks=clicks,
        ctr=ctr,
        position=position,
        top_queries=top_queries,
        measured=True,
    )


class GscClient:
    def __init__(self, service: Any | None = None) -> None:
        self._service = service

    def metrics_for_url(
        self,
        site_url: str,
        page_url: str,
        start_date: str,
        end_date: str,
        row_limit: int = 25,
    ) -> GscMetrics:
        if self._service is None:
            return GscMetrics()
        body = _query_body(page_url, start_date, end_date, row_limit)
        try:
            response = self._service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        except Exception:  # noqa: BLE001 — API failure degrades, never raises
            return GscMetrics()
        rows = response.get("rows", []) if isinstance(response, dict) else []
        return _aggregate_rows(rows)


__all__ = ["GscClient"]
