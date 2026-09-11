"""Semrush integration config — pure, JSON-backed settings (v2.0 gap fix).

Stores the Semrush connect state (enabled flag, daily call cap) as a small
JSON file under the data dir, reusing the exact ``SILENTFROG_DATA_DIR`` +
platform-branch shape as ``integrations/google/config.py`` and
``integrations/semrush/budget.py``.

This closes two real gaps: ``seo_crawler._semrush_enabled`` previously read
only the ``SILENTFROG_SEMRUSH_ENABLE`` env var, so ticking anything in
Settings could never enable a crawl's Semrush calls; and the "Max Semrush
calls per day" spinbox wrote to QSettings while the crawler read
``SILENTFROG_SEMRUSH_MAX_CALLS``, so the spinbox had no effect. Both now
read this config as their non-env fallback.

Deliberately NOT QSettings, for the same reason as the Google config: this
module sits in the pure data layer ``seo_crawler.py`` imports, and QSettings
would drag Qt into a layer that must stay usable without it (headless CLI /
MCP runs).

Never raises — a missing or corrupt config file degrades to defaults, and a
failed write is silently dropped (mirrors ``budget.py``'s and
``google/config.py``'s fail-open style).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_SUBDIR = "semrush"
_FILENAME = "config.json"
_DEFAULT_MAX_CALLS = 100


@dataclass(frozen=True, slots=True)
class SemrushConfig:
    enabled: bool = False
    max_calls: int = _DEFAULT_MAX_CALLS


def _data_dir() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / _SUBDIR


def _config_path() -> Path:
    return _data_dir() / _FILENAME


def _to_max_calls(value: object, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def load_config() -> SemrushConfig:
    """Load the stored Semrush config, or defaults when the file is
    missing, unreadable, corrupt JSON, or not shaped like an object. Never
    raises."""
    path = _config_path()
    if not path.is_file():
        return SemrushConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return SemrushConfig()
    if not isinstance(raw, dict):
        return SemrushConfig()
    defaults = SemrushConfig()
    return SemrushConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        max_calls=_to_max_calls(raw.get("max_calls", defaults.max_calls), defaults.max_calls),
    )


def save_config(config: SemrushConfig) -> None:
    """Persist ``config`` as JSON under the data dir. Never raises."""
    try:
        directory = _data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _config_path().write_text(json.dumps(asdict(config)), encoding="utf-8")
    except Exception:
        return


__all__ = ["SemrushConfig", "load_config", "save_config"]
