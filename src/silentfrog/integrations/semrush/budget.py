"""Date-keyed daily Semrush call budget (v2.0 V17).

The Semrush Analytics API is metered and billed per call, so the client
guards every request against a per-day budget. The counter is persisted
as ``semrush_calls_YYYYMMDD.json`` under the same data dir the disk cache
uses (respecting ``SILENTFROG_DATA_DIR``), so it survives process
restarts and resets automatically each calendar day.

Never raises — a corrupt or unreadable counter file is treated as zero
calls spent, which fails open (the worst case is a few extra calls, not
a crash mid-audit).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_SUBDIR = "semrush_cache"


def _data_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / _SUBDIR


def _counter_path() -> Path:
    today = datetime.now(UTC).strftime("%Y%m%d")
    return _data_dir() / f"semrush_calls_{today}.json"


def _read_count() -> int:
    path = _counter_path()
    if not path.is_file():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return max(int(payload.get("count", 0)), 0)
    except Exception:
        # A corrupt counter fails open as zero spent.
        return 0


def remaining(max_calls: int) -> int:
    """Calls still available today against ``max_calls`` (never negative)."""
    return max(0, int(max_calls) - _read_count())


def record_call() -> None:
    """Increment today's call counter by one. Never raises."""
    try:
        directory = _data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _counter_path().write_text(json.dumps({"count": _read_count() + 1}), encoding="utf-8")
    except Exception:
        return


__all__ = ["record_call", "remaining"]
