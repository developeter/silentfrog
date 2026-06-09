"""Tiny per-URL GEO Score history store (v1.1 N5d).

The existing ``crawl_history.py`` stores Site Crawl-scoped issue
counts under a different metric (``health_score``), so it isn't a
drop-in source for the per-page GEO Score 0–100 sparkline added in
N5c. We keep a tiny JSON file at
``$LOCALAPPDATA/Silentfrog/geo_score_history.json`` (or the XDG
equivalent on POSIX) holding ``{url: [int, int, ...]}``. Each entry
is a rolling FIFO capped at ``_MAX_SCORES`` per URL.

Public surface:

- ``record(url, score)`` appends a score and trims to the rolling cap.
- ``recent(url, limit=10)`` returns the last ``limit`` scores, oldest
  first, ready to feed ``AiVisibilityTab.set_score_history``.

The store NEVER raises — failed reads/writes return an empty result,
so the sparkline degrades gracefully when the data dir is unwritable
or the file is corrupt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_MAX_SCORES = 30
_FILE_NAME = "geo_score_history.json"


def _data_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"


def _store_path() -> Path:
    return _data_dir() / _FILE_NAME


def _read_all() -> dict[str, list[int]]:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[int]] = {}
    for key, values in raw.items():
        if not isinstance(key, str) or not isinstance(values, list):
            continue
        cleaned[key] = [int(v) for v in values if isinstance(v, (int, float))]
    return cleaned


def _write_all(data: dict[str, list[int]]) -> None:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def record(url: str, score: int) -> None:
    """Append ``score`` to ``url``'s rolling history (capped at _MAX_SCORES)."""
    if not url or not isinstance(url, str):
        return
    data = _read_all()
    series = data.get(url, [])
    series.append(int(score))
    if len(series) > _MAX_SCORES:
        series = series[-_MAX_SCORES:]
    data[url] = series
    _write_all(data)


def recent(url: str, limit: int = 10) -> list[int]:
    """Return up to ``limit`` most recent scores for ``url``, oldest first."""
    if not url or not isinstance(url, str):
        return []
    data = _read_all()
    series = data.get(url, [])
    if limit <= 0:
        return list(series)
    return series[-limit:]


def clear() -> None:
    """Drop the whole store (used by tests / a future Settings 'reset' button)."""
    try:
        path = _store_path()
        if path.is_file():
            path.unlink()
    except OSError:
        return


__all__ = ["clear", "record", "recent"]
