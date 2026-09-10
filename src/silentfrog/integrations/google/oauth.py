"""Google OAuth + service builders (v2.0 V7, thin lazy wrappers).

System-browser loopback flow (RFC 8252) — no embedded webview, no
QtWebEngine. Tokens are stored in the OS keychain via ``keyring``. Every
google import is lazy so the install base needs nothing; these wrappers
are exercised manually (real Google round-trip) — the keyring token
store is unit-tested with a fake.

Only the path to ``client_secret.json`` is ever persisted (see
``config.GoogleConfig.client_secrets_path``) — never the file's contents.
Verified against the token format actually stored: ``Credentials.to_json()``
(called by ``run_loopback_flow`` below) embeds ``client_id``,
``client_secret``, ``refresh_token``, ``token_uri`` and ``scopes`` in the
token JSON itself, and ``_credentials()`` rebuilds a full ``Credentials``
object from that JSON alone via ``from_authorized_user_info`` — so refresh
never needs the original client secrets file again once a token exists.
"""

from __future__ import annotations

import json
from typing import Any

GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
_KEYRING_SERVICE = "silentfrog-google"
_DEFAULT_TIMEOUT_SECONDS = 180


def _keyring() -> Any:
    import keyring  # lazy, optional extra

    return keyring


def save_token(account: str, token_json: str) -> None:
    try:
        _keyring().set_password(_KEYRING_SERVICE, account, token_json)
    except Exception:
        return


def load_token(account: str) -> str | None:
    try:
        return _keyring().get_password(_KEYRING_SERVICE, account)
    except Exception:
        return None


def has_token(account: str) -> bool:
    """Whether a token is stored for ``account``. Never raises."""
    return load_token(account) is not None


def delete_token(account: str) -> bool:
    """Delete the stored token for ``account``; return whether the
    underlying keyring call succeeded. Never raises."""
    try:
        _keyring().delete_password(_KEYRING_SERVICE, account)
    except Exception:
        return False
    return True


def run_loopback_flow(
    client_config: dict[str, Any],
    scopes: list[str],
    *,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Run the system-browser loopback OAuth flow; return token JSON.

    Raises ``ModuleNotFoundError`` (uncaught, on purpose) when
    ``google-auth-oauthlib`` — the ``silentfrog[google]`` extra — isn't
    installed; ``connect.connect_account`` turns that into a typed,
    user-facing failure. Any other failure during the flow itself (browser
    closed, timeout, firewall block) is normalised into a plain
    ``RuntimeError``, so callers catch one type. The user-facing prefix
    belongs to ``connect.connect_account``, not here — wording it in both
    places produced "Google sign-in failed: Google sign-in failed: …".
    """
    from google_auth_oauthlib.flow import InstalledAppFlow  # lazy

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
        creds = flow.run_local_server(
            host="localhost",
            bind_addr="127.0.0.1",
            port=0,
            timeout_seconds=timeout_seconds,
            prompt="consent",  # forces the consent screen so reconnect can switch account
        )
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    return str(creds.to_json())


def _credentials(token_json: str, scopes: list[str]) -> Any:
    from google.oauth2.credentials import Credentials  # lazy

    return Credentials.from_authorized_user_info(json.loads(token_json), scopes=scopes)


def build_gsc_service(token_json: str) -> Any:
    from googleapiclient.discovery import build  # lazy

    return build("searchconsole", "v1", credentials=_credentials(token_json, GSC_SCOPES), cache_discovery=False)


def build_ga4_service(token_json: str) -> Any:
    from googleapiclient.discovery import build  # lazy

    return build("analyticsdata", "v1beta", credentials=_credentials(token_json, GA4_SCOPES), cache_discovery=False)


__all__ = [
    "GA4_SCOPES",
    "GSC_SCOPES",
    "build_ga4_service",
    "build_gsc_service",
    "delete_token",
    "has_token",
    "load_token",
    "run_loopback_flow",
    "save_token",
]
