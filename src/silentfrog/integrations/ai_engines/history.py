"""Local AI-engine share-of-voice history (v3 G3 Stage 1).

Mirrors ``brand_mentions.tracker``'s history store: one JSON file
(``ai_sov_history.json``) holding ``{host: [point, ...]}``, oldest-first,
capped at 52 points, with same-calendar-day points replaced instead of
appended so a repeated audit in one day cannot fabricate a trend. Never
raises — an unreadable or corrupt file is treated as an empty store.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_FILE_NAME = "ai_sov_history.json"
_MAX_SERIES_POINTS = 52
_SECONDS_PER_DAY = 24 * 60 * 60


def _data_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"


def _clean_engine_stats(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"mentions": 0, "citations": 0, "prompts": 0}
    return {
        "mentions": int(value.get("mentions", 0) or 0),
        "citations": int(value.get("citations", 0) or 0),
        "prompts": int(value.get("prompts", 0) or 0),
    }


def _clean_point(point: dict[str, Any]) -> dict[str, Any]:
    engines_raw = point.get("engines", {})
    engines = (
        {str(name): _clean_engine_stats(stats) for name, stats in engines_raw.items()}
        if isinstance(engines_raw, dict)
        else {}
    )
    return {"ts": int(point.get("ts", 0) or 0), "engines": engines}


def _read_history() -> dict[str, list[dict[str, Any]]]:
    path = _data_dir() / _FILE_NAME
    if not path.is_file():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for host, points in raw.items():
        if isinstance(host, str) and isinstance(points, list):
            cleaned[host] = [_clean_point(point) for point in points if isinstance(point, dict)]
    return cleaned


def _write_history(data: dict[str, list[dict[str, Any]]]) -> None:
    try:
        path = _data_dir() / _FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return


def record_point(
    host: str,
    engines: dict[str, dict[str, int]],
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Append (or same-day replace) a point for ``host``; returns the
    host's full series. ``engines`` is ``{engine_name: {"mentions":
    int, "citations": int, "prompts": int}}``."""
    if not host:
        return []
    ts = int(now if now is not None else time.time())
    data = _read_history()
    series = data.get(host, [])
    if series and series[-1]["ts"] // _SECONDS_PER_DAY == ts // _SECONDS_PER_DAY:
        series = series[:-1]
    point = {"ts": ts, "engines": {name: _clean_engine_stats(stats) for name, stats in engines.items()}}
    series.append(point)
    data[host] = series[-_MAX_SERIES_POINTS:]
    _write_history(data)
    return data[host]


__all__ = ["record_point"]
