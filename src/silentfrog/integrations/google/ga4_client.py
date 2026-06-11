"""Google Analytics 4 client (v2.0 V7).

Wraps the GA4 Data API ``runReport``. Same injectable-service pattern as
the GSC client. Parses the metric rows for a single page path. Never
raises.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .types import Ga4Metrics

# Metric order we request; parsing reads positionally.
_METRICS = ("screenPageViews", "userEngagementDuration", "bounceRate", "conversions")


def _report_body(page_path: str, start_date: str, end_date: str) -> dict[str, Any]:
    return {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": name} for name in _METRICS],
        "dimensionFilter": {
            "filter": {"fieldName": "pagePath", "stringFilter": {"matchType": "EXACT", "value": page_path}}
        },
        "limit": 1,
    }


def _parse_report(response: dict[str, Any]) -> Ga4Metrics:
    rows = response.get("rows", []) if isinstance(response, dict) else []
    if not rows:
        return Ga4Metrics(measured=True)
    values = rows[0].get("metricValues", [])
    nums = [_to_float(v.get("value")) for v in values]
    nums += [0.0] * (len(_METRICS) - len(nums))
    pageviews, engagement, bounce, conversions = nums[0], nums[1], nums[2], nums[3]
    avg_engagement = (engagement / pageviews) if pageviews else 0.0
    return Ga4Metrics(
        pageviews=int(pageviews),
        avg_engagement_seconds=avg_engagement,
        bounce_rate=bounce,
        conversions=int(conversions),
        measured=True,
    )


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class Ga4Client:
    def __init__(self, service: Any | None = None, property_id: str = "") -> None:
        self._service = service
        self._property_id = property_id

    def metrics_for_url(self, page_url: str, start_date: str, end_date: str) -> Ga4Metrics:
        if self._service is None or not self._property_id:
            return Ga4Metrics()
        page_path = urlparse(page_url).path or "/"
        body = _report_body(page_path, start_date, end_date)
        try:
            response = (
                self._service.properties().runReport(property=f"properties/{self._property_id}", body=body).execute()
            )
        except Exception:  # noqa: BLE001 — API failure degrades, never raises
            return Ga4Metrics()
        return _parse_report(response if isinstance(response, dict) else {})


__all__ = ["Ga4Client"]
