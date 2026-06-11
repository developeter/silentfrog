"""Typed contract for the fetcher strategy (v2.0 V1).

A ``FetchBackend`` turns a ``FetchRequest`` into a ``FetchResult``. The
strategy ([strategy.py](strategy.py)) escalates across backends when the
base (aiohttp) result looks blocked by a WAF. Everything here is a
frozen dataclass / Protocol so data crossing module boundaries is typed,
per AGENTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# HTTP statuses that signal a likely WAF / bot block worth escalating
# past (0 = transport failure / TLS reset, the classic stdlib-fingerprint
# symptom).
ESCALATE_STATUSES: frozenset[int] = frozenset({0, 403, 429, 503})


@dataclass(frozen=True)
class FetchRequest:
    url: str
    timeout: int = 15
    headers: dict[str, str] | None = None


@dataclass(frozen=True)
class FetchResult:
    body: str
    status: int
    final_url: str
    headers: dict[str, str] = field(default_factory=dict)
    ttfb_ms: float = 0.0
    total_ms: float = 0.0
    backend: str = ""
    error: str = ""

    def looks_blocked(self, escalate_statuses: frozenset[int] = ESCALATE_STATUSES) -> bool:
        """True when the status suggests a WAF block worth escalating past."""
        return self.status in escalate_statuses


@dataclass(frozen=True)
class FetchOptions:
    """Strategy configuration. Selection is by typed config, never a
    bare boolean threaded through call signatures."""

    use_stealth: bool = False
    escalate_statuses: frozenset[int] = ESCALATE_STATUSES


@runtime_checkable
class FetchBackend(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this backend can run in the current environment."""
        ...

    async def fetch(self, request: FetchRequest) -> FetchResult: ...


__all__ = [
    "ESCALATE_STATUSES",
    "FetchBackend",
    "FetchOptions",
    "FetchRequest",
    "FetchResult",
]
