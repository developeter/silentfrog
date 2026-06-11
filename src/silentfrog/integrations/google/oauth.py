"""Google OAuth + service builders (v2.0 V7, thin lazy wrappers).

System-browser loopback flow (RFC 8252) — no embedded webview, no
QtWebEngine. Tokens are stored in the OS keychain via ``keyring``. Every
google import is lazy so the install base needs nothing; these wrappers
are exercised manually (real Google round-trip) — the keyring token
store is unit-tested with a fake.
"""

from __future__ import annotations

import json
from typing import Any

GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
_KEYRING_SERVICE = "silentfrog-google"


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


def run_loopback_flow(client_config: dict[str, Any], scopes: list[str]) -> str:
    """Run the system-browser loopback OAuth flow; return token JSON."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # lazy

    flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
    creds = flow.run_local_server(port=0)
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
    "load_token",
    "run_loopback_flow",
    "save_token",
]
