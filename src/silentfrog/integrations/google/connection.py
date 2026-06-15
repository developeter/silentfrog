"""Google connection — fetch GSC + GA4 metrics for a URL (v2.0 V7).

Holds the two clients + the property identifiers and returns the payload
fragment (``{"gsc": ..., "ga4": ...}``) that enriches a CrawlPayload.
The clients are injectable so the orchestration is unit-tested with
fakes; ``from_env`` builds the real, token-backed connection lazily and
is gated on env so a stock audit never touches Google.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .ga4_client import Ga4Client
from .gsc_client import GscClient
from .types import GscMetrics

_DEFAULT_WINDOW_DAYS = 28


def _date_window(days: int = _DEFAULT_WINDOW_DAYS) -> tuple[str, str]:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


@dataclass
class GoogleConnection:
    gsc: GscClient
    ga4: Ga4Client
    site_url: str = ""
    window_days: int = _DEFAULT_WINDOW_DAYS

    def metrics_for(self, url: str) -> dict[str, Any]:
        start, end = _date_window(self.window_days)
        gsc_metrics = self.gsc.metrics_for_url(self.site_url, url, start, end) if self.site_url else GscMetrics()
        ga4_metrics = self.ga4.metrics_for_url(url, start, end)
        return {"gsc": gsc_metrics.to_dict(), "ga4": ga4_metrics.to_dict()}

    def inspect_rich_results(self, url: str) -> dict[str, Any]:
        """Raw GSC URL Inspection response for ``url`` (v2.0 V14), or
        ``{}`` when no GSC site is connected. Never raises."""
        if not self.site_url:
            return {}
        return self.gsc.inspect_url(self.site_url, url)


def _enabled() -> bool:
    return os.environ.get("SILENTFROG_GOOGLE_ENABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def from_env() -> GoogleConnection | None:
    """Build a token-backed connection from env + keyring, or None when
    the integration isn't enabled/configured. Never raises."""
    if not _enabled():
        return None
    site_url = os.environ.get("SILENTFROG_GSC_SITE_URL", "").strip()
    property_id = os.environ.get("SILENTFROG_GA4_PROPERTY_ID", "").strip()
    try:
        from . import oauth

        gsc_service = None
        ga4_service = None
        gsc_token = oauth.load_token("gsc")
        ga4_token = oauth.load_token("ga4")
        if gsc_token and site_url:
            gsc_service = oauth.build_gsc_service(gsc_token)
        if ga4_token and property_id:
            ga4_service = oauth.build_ga4_service(ga4_token)
    except Exception:
        return None
    if gsc_service is None and ga4_service is None:
        return None
    return GoogleConnection(
        gsc=GscClient(gsc_service),
        ga4=Ga4Client(ga4_service, property_id),
        site_url=site_url,
    )


__all__ = ["GoogleConnection", "from_env"]
