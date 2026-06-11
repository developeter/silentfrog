"""Google Search Console + GA4 integration (v2.0 V7, optional extra
``silentfrog[google]``). Lazy-imports the google libraries; the data
layer (types, clients, checks, connection) imports nothing heavy."""

from __future__ import annotations

from .checks import build_real_performance_checks
from .connection import GoogleConnection, from_env
from .ga4_client import Ga4Client
from .gsc_client import GscClient
from .types import Ga4Metrics, GscMetrics

__all__ = [
    "Ga4Client",
    "Ga4Metrics",
    "GoogleConnection",
    "GscClient",
    "GscMetrics",
    "build_real_performance_checks",
    "from_env",
]
