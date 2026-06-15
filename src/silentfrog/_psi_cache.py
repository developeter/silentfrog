"""Shared PageSpeed Insights disk-cache helpers (v2.0 V14).

The same ``runPagespeed`` endpoint feeds two consumers — ``perf_crux``
(CrUX field data) and ``integrations.google.lighthouse`` (category
scores). Both cache responses on disk for 24h per URL so a sitemap-level
audit doesn't hammer the API. The cache primitives were originally
private to ``perf_crux``; they live here now so both modules share one
implementation, keyed by a per-consumer subdir.

Generic over the cached type: callers pass ``from_raw`` (a tolerant
parser) and ``to_dict`` so a ``CruxData`` and a ``LighthouseScores``
each round-trip through the same JSON-on-disk plumbing.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h per the plan §N1


def _cache_dir(subdir: str) -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / subdir


def _cache_key(url: str) -> str:
    # Stable, filename-safe.
    safe = (
        url.replace("://", "__")
        .replace("/", "_")
        .replace(":", "_")
        .replace("?", "_")
        .replace("&", "_")
        .replace("=", "_")
    )[:160]
    return safe


def read_cache[T](subdir: str, url: str, from_raw: Callable[[Any], T]) -> T | None:
    path = _cache_dir(subdir) / f"{_cache_key(url)}.json"
    if not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return from_raw(payload)


def write_cache(subdir: str, url: str, data: Any) -> None:
    try:
        directory = _cache_dir(subdir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_cache_key(url)}.json"
        path.write_text(json.dumps(data.to_dict()), encoding="utf-8")
    except Exception:
        # Cache failures are non-fatal; the next call simply re-fetches.
        return


__all__ = ["_CACHE_TTL_SECONDS", "read_cache", "write_cache"]
