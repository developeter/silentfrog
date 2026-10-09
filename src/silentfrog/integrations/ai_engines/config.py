"""AI share-of-voice Settings opt-in — pure, JSON-backed (INT-2).

Until now the only switch was the ``SILENTFROG_AI_SOV_ENABLE`` environment
variable, so ticking nothing in Settings could ever turn the paid sampling on.
This stores the checkbox as a small JSON file under the data dir, with the same
``SILENTFROG_DATA_DIR`` + platform shape as ``semrush/config.py``. The API keys
themselves stay in the OS keychain; nothing secret is written here.

Never raises: a missing or corrupt file degrades to the default (OFF) and a
failed write is dropped.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_SUBDIR = "ai_engines"
_FILENAME = "config.json"


@dataclass(frozen=True, slots=True)
class AiEnginesConfig:
    enabled: bool = False


def _config_path() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / _SUBDIR / _FILENAME


def load_config() -> AiEnginesConfig:
    """The stored opt-in, or the default (OFF) when missing/corrupt."""
    path = _config_path()
    if not path.is_file():
        return AiEnginesConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AiEnginesConfig()
    if not isinstance(raw, dict):
        return AiEnginesConfig()
    return AiEnginesConfig(enabled=raw.get("enabled") is True)


def save_config(config: AiEnginesConfig) -> None:
    """Persist ``config`` as JSON under the data dir. Never raises."""
    try:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(config)), encoding="utf-8")
    except Exception:
        return


__all__ = ["AiEnginesConfig", "load_config", "save_config"]
