"""Maintainer-owned Google OAuth *Desktop app* client (v2.0 PR-B).

Paste the id/secret from Google Cloud Console into ``BUILTIN_CLIENT_ID`` /
``BUILTIN_CLIENT_SECRET`` below before tagging a release; the consent
screen must be **In production** (Testing tokens expire after 7 days).
Empty = no built-in app, BYO-only (today's behaviour).

Why an empty/embedded Desktop-app secret is not a leaked credential: per
Google's own OAuth docs and RFC 8252 §8.5, an "installed application"
client secret is explicitly NOT confidential — it only identifies the app
to Google, the same way a public OAuth client id does, and it cannot by
itself grant access to anyone's data. Every sign-in still requires the
end user's own consent in their browser, and the scopes requested here are
read-only (``webmasters.readonly``, ``analytics.readonly``). Data flows
straight from Google to the user's machine; the maintainer never sees
tokens or audit data.
"""

from __future__ import annotations

import os
from typing import Any

BUILTIN_CLIENT_ID = ""
BUILTIN_CLIENT_SECRET = ""

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"
_REDIRECT_URIS = ["http://localhost"]


def _resolved_credentials() -> tuple[str, str]:
    """Env override wins over the pasted-in constants when BOTH env vars
    are set — lets the maintainer test the built-in flow before pasting,
    and CI never needs the real constants populated."""
    env_id = os.environ.get("SILENTFROG_GOOGLE_CLIENT_ID", "").strip()
    env_secret = os.environ.get("SILENTFROG_GOOGLE_CLIENT_SECRET", "").strip()
    if env_id and env_secret:
        return env_id, env_secret
    return BUILTIN_CLIENT_ID, BUILTIN_CLIENT_SECRET


def builtin_client_config() -> dict[str, Any] | None:
    """The ``{"installed": {...}}`` dict shape
    ``InstalledAppFlow.from_client_config`` expects, or ``None`` when no
    built-in client id/secret is available. Never raises."""
    client_id, client_secret = _resolved_credentials()
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "auth_provider_x509_cert_url": _CERT_URL,
            "redirect_uris": _REDIRECT_URIS,
        }
    }


def builtin_client_available() -> bool:
    """Whether this build has a usable built-in Google app. Never raises."""
    return builtin_client_config() is not None


__all__ = ["BUILTIN_CLIENT_ID", "BUILTIN_CLIENT_SECRET", "builtin_client_available", "builtin_client_config"]
