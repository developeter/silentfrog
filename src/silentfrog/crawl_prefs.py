"""QSettings persistence for the Crawl-settings opt-in ticks.

Single Page and Site Crawl share one ``crawl/opt_in`` JSON blob so a tick made
in either window is there next time (and in the other window). The Site Crawl
audit profile lives in its own ``crawl/site_profile`` key because Single Page is
always DEEP. The (de)serialisers are Qt-free in ``crawl_options``; this module
is only the storage seam. TLS/SSRF overrides and headers/cookies are never
stored (see ``crawl_options.opt_in_to_dict``).
"""

from __future__ import annotations

import json
import logging

from qtpy import QtCore

from .crawl_options import AuditProfile, CrawlOptions, opt_in_from_dict, opt_in_to_dict

log = logging.getLogger(__name__)

OPT_IN_KEY = "crawl/opt_in"
SITE_PROFILE_KEY = "crawl/site_profile"


def app_settings() -> QtCore.QSettings:
    """Single seam for the app-wide settings store — same shape as
    ``CrawlSettingsDialog._app_settings``. QSettings("Silentfrog", "Silentfrog")
    ignores QSettings.setDefaultFormat, so tests substitute a temp-file store
    here instead of touching the platform-native backend."""
    return QtCore.QSettings("Silentfrog", "Silentfrog")


def installed_extras() -> frozenset[str]:
    """Optional extras importable right now, via the same probes the Settings
    checkboxes use (so a stored tick can never outlive its extra)."""
    from . import settings_dialog

    probes = {
        "playwright": settings_dialog._playwright_available,
        "embeddings": settings_dialog._embeddings_available,
        "stealth": settings_dialog._scrapling_available,
    }
    return frozenset(name for name, probe in probes.items() if probe())


def load_opt_in_options(base: CrawlOptions) -> CrawlOptions:
    """``base`` with the stored opt-in ticks applied; absent or corrupt store
    returns ``base`` unchanged."""
    try:
        raw = app_settings().value(OPT_IN_KEY, "")
        data = json.loads(raw) if isinstance(raw, str) and raw else None
    except (ValueError, TypeError):
        log.warning("Ignoring unreadable stored crawl settings")
        return base
    return opt_in_from_dict(data, base, installed=installed_extras())


def save_opt_in_options(options: CrawlOptions) -> None:
    try:
        app_settings().setValue(OPT_IN_KEY, json.dumps(opt_in_to_dict(options)))
    except (OSError, TypeError, ValueError):
        log.warning("Could not store crawl settings", exc_info=True)


def load_site_profile(default: AuditProfile) -> AuditProfile:
    try:
        raw = app_settings().value(SITE_PROFILE_KEY, "")
    except (OSError, TypeError, ValueError):
        return default
    if not isinstance(raw, str) or not raw:
        return default
    try:
        return AuditProfile(raw)
    except ValueError:
        return default


def save_site_profile(profile: AuditProfile) -> None:
    try:
        app_settings().setValue(SITE_PROFILE_KEY, profile.value)
    except (OSError, TypeError, ValueError):
        log.warning("Could not store the site-crawl profile", exc_info=True)


__all__ = [
    "OPT_IN_KEY",
    "SITE_PROFILE_KEY",
    "app_settings",
    "installed_extras",
    "load_opt_in_options",
    "load_site_profile",
    "save_opt_in_options",
    "save_site_profile",
]
