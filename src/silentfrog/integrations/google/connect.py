"""Google account connect/disconnect — the pure orchestration layer
(v2.0 R2).

Ties together BYO ``client_secret.json`` loading, the injectable OAuth
flow, and token storage so a caller (a future Settings dialog, R3) has one
call to make. No GUI here — that is R3's job. Never raises; failures come
back as typed results instead.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import oauth
from .config import load_config, save_config

_INSTALL_HINT = "pip install silentfrog[google]"
_DESKTOP_APP_HINT = (
    'This client_secret.json is a "Web application" credential. Create '
    'an OAuth client of type "Desktop app" in Google Cloud Console instead.'
)

_SCOPES_BY_ACCOUNT: dict[str, list[str]] = {
    "gsc": oauth.GSC_SCOPES,
    "ga4": oauth.GA4_SCOPES,
}


@dataclass(frozen=True, slots=True)
class ClientSecretsResult:
    ok: bool
    secrets: dict[str, Any] | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ConnectResult:
    ok: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    ok: bool
    reason: str = ""


def load_client_secrets(path: str) -> ClientSecretsResult:
    """Load + sanity-check a BYO ``client_secret.json``. Never raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return ClientSecretsResult(ok=False, reason=f"Could not read '{path}' as a Google client secrets file.")
    if not isinstance(data, dict):
        return ClientSecretsResult(ok=False, reason="Not a valid Google OAuth client secrets file.")
    if "installed" in data:
        return ClientSecretsResult(ok=True, secrets=data)
    if "web" in data:
        return ClientSecretsResult(ok=False, reason=_DESKTOP_APP_HINT)
    return ClientSecretsResult(ok=False, reason="Not a valid Google OAuth client secrets file.")


def connect_account(
    account: str,
    secrets: dict[str, Any],
    *,
    flow: Callable[[dict[str, Any], list[str]], str] = oauth.run_loopback_flow,
) -> ConnectResult:
    """Run the OAuth flow for ``account`` (``"gsc"`` or ``"ga4"``) and
    store the resulting token in the keychain. Never raises."""
    scopes = _SCOPES_BY_ACCOUNT.get(account)
    if scopes is None:
        return ConnectResult(ok=False, reason=f"Unknown account '{account}'.")
    try:
        token_json = flow(secrets, scopes)
    except ModuleNotFoundError:
        return ConnectResult(ok=False, reason=f"Google OAuth libraries are not installed. Run `{_INSTALL_HINT}`.")
    except Exception as exc:
        return ConnectResult(ok=False, reason=f"Google sign-in failed: {exc}")
    oauth.save_token(account, token_json)
    return ConnectResult(ok=True)


def disconnect_account(account: str) -> DisconnectResult:
    """Delete the stored token and clear the matching config field. Never
    raises. If the keychain delete fails (locked vault, backend error,
    permissions) the token can still be live, so the config field is left
    untouched rather than falsely reporting the account as disconnected —
    verified via ``has_token`` rather than trusting ``delete_token``'s own
    result, so this also covers a delete that raised for an already-absent
    token (nothing left to leak)."""
    oauth.delete_token(account)
    if oauth.has_token(account):
        return DisconnectResult(
            ok=False,
            reason="Could not remove the stored Google credential from the OS keychain.",
        )
    config = load_config()
    if account == "gsc":
        save_config(replace(config, gsc_site_url=""))
    elif account == "ga4":
        save_config(replace(config, ga4_property_id=""))
    return DisconnectResult(ok=True)


__all__ = [
    "ClientSecretsResult",
    "ConnectResult",
    "DisconnectResult",
    "connect_account",
    "disconnect_account",
    "load_client_secrets",
]
