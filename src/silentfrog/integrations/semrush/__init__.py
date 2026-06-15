"""Semrush authority integration (v2.0 V17, optional extra
``silentfrog[semrush]``). Off by default — a stock audit never touches
Semrush. The data layer (types, checks, budget) imports nothing heavy;
``keyring`` is lazy-imported by the client and degrades to env-only."""

from __future__ import annotations

from .checks import AUTHORITY_AREA, build_semrush_authority_checks
from .client import fetch_domain_overview, resolve_api_key, test_connection
from .types import SemrushMetrics

__all__ = [
    "AUTHORITY_AREA",
    "SemrushMetrics",
    "build_semrush_authority_checks",
    "fetch_domain_overview",
    "resolve_api_key",
    "test_connection",
]
