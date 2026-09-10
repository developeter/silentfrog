"""Google integration config — pure, JSON-backed settings (v2.0 R2).

Stores the Google connect state (enabled flag, GSC site URL, GA4 property
id, BYO ``client_secret.json`` path) as a small JSON file under the data
dir, reusing the exact ``SILENTFROG_DATA_DIR`` + platform-branch shape as
``integrations/semrush/budget.py``.

Deliberately NOT QSettings: this module sits in the pure data layer that
``connection.py`` (and therefore ``silentfrog-cli``/``silentfrog-mcp``)
imports, and QSettings would drag Qt into a layer that must stay usable
without it.

Never raises — a missing or corrupt config file degrades to defaults, and a
failed write is silently dropped (mirrors ``budget.py``'s fail-open style).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

_SUBDIR = "google"
_FILENAME = "config.json"


@dataclass(frozen=True, slots=True)
class GoogleConfig:
    enabled: bool = False
    gsc_site_url: str = ""
    ga4_property_id: str = ""
    client_secrets_path: str = ""


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


def load_config() -> GoogleConfig:
    """Load the stored Google config, or defaults when the file is
    missing, unreadable, corrupt JSON, or not shaped like an object. Never
    raises."""
    path = _config_path()
    if not path.is_file():
        return GoogleConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return GoogleConfig()
    if not isinstance(raw, dict):
        return GoogleConfig()
    defaults = GoogleConfig()
    return GoogleConfig(
        enabled=bool(raw.get("enabled", defaults.enabled)),
        gsc_site_url=str(raw.get("gsc_site_url", defaults.gsc_site_url)),
        ga4_property_id=str(raw.get("ga4_property_id", defaults.ga4_property_id)),
        client_secrets_path=str(raw.get("client_secrets_path", defaults.client_secrets_path)),
    )


def save_config(config: GoogleConfig) -> None:
    """Persist ``config`` as JSON under the data dir. Never raises."""
    try:
        directory = _data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        _config_path().write_text(json.dumps(asdict(config)), encoding="utf-8")
    except Exception:
        return


__all__ = ["GoogleConfig", "load_config", "save_config"]
