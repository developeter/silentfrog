"""Alert transports for the scheduled-crawl digest (v3 G9).

Two best-effort, never-raising delivery channels: a webhook POST (aiohttp —
already a base dependency, shape cloned from
``integrations.ai_engines.client._post_json``) and SMTP email (stdlib
``smtplib`` + ``email.message.EmailMessage`` — no new dependency, matching
the repo's no-APScheduler / minimal-deps policy).

Delivery is opt-in twice over: the CLI's ``--digest`` flag is the user's
consent to send anything at all, and each transport additionally requires
its OWN env config — an unconfigured transport is skipped silently, never
attempted.
"""

from __future__ import annotations

import os
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import ClientTimeout

if TYPE_CHECKING:
    from .scheduled_crawl import Digest

_DEFAULT_TIMEOUT_SECONDS = 15
_KEYRING_SERVICE = "silentfrog-smtp"
_DEFAULT_SMTP_PORT = 587

_WEBHOOK_URL_ENV = "SILENTFROG_ALERT_WEBHOOK_URL"
_SMTP_HOST_ENV = "SILENTFROG_SMTP_HOST"
_SMTP_PORT_ENV = "SILENTFROG_SMTP_PORT"
_SMTP_USER_ENV = "SILENTFROG_SMTP_USER"
_SMTP_FROM_ENV = "SILENTFROG_SMTP_FROM"
_SMTP_TO_ENV = "SILENTFROG_SMTP_TO"
_SMTP_PASSWORD_ENV = "SILENTFROG_SMTP_PASSWORD"

SmtpFactory = Callable[[str, int], Any]


def _keyring() -> Any:
    import keyring  # lazy, optional extra

    return keyring


def resolve_smtp_password() -> str:
    """Keyring (``silentfrog-smtp``/``password``) first, env fallback.

    Mirrors the semrush/ai-engines clients' lazy keyring wrapper: keyring is
    optional, so a missing extra degrades straight to the env var."""
    try:
        stored = _keyring().get_password(_KEYRING_SERVICE, "password")
        if stored:
            return str(stored).strip()
    except Exception:
        pass
    return os.environ.get(_SMTP_PASSWORD_ENV, "").strip()


async def send_webhook(
    json_payload: dict[str, Any],
    *,
    url: str,
    session: aiohttp.ClientSession | None = None,
) -> bool:
    """POST ``json_payload`` to ``url`` as JSON. Never raises: any HTTP
    error (>=400), network exception, or blank ``url`` returns ``False``."""
    if not url.strip():
        return False
    owns_session = session is None
    active = session or aiohttp.ClientSession()
    try:
        async with active.post(url, json=json_payload, timeout=ClientTimeout(total=_DEFAULT_TIMEOUT_SECONDS)) as resp:
            return resp.status < 400
    except Exception:
        return False
    finally:
        if owns_session:
            await active.close()


def send_email(subject: str, body: str, *, smtp_factory: SmtpFactory | None = None) -> bool:
    """Send ``subject``/``body`` to the ``;``-separated ``SILENTFROG_SMTP_TO``
    recipients. Never raises. Missing host/from/to returns ``False`` before
    any connection attempt — ``smtp_factory`` is not even referenced, so an
    unconfigured transport never instantiates a real (or fake) SMTP client."""
    host = os.environ.get(_SMTP_HOST_ENV, "").strip()
    sender = os.environ.get(_SMTP_FROM_ENV, "").strip()
    recipients = _split_addresses(os.environ.get(_SMTP_TO_ENV, ""))
    if not host or not sender or not recipients:
        return False
    message = _build_message(subject, body, sender, recipients)
    factory = smtp_factory or smtplib.SMTP
    try:
        _send_via_smtp(factory, host, _smtp_port(), message)
    except Exception:
        return False
    return True


def _send_via_smtp(factory: SmtpFactory, host: str, port: int, message: EmailMessage) -> None:
    with factory(host, port) as server:
        _start_tls(server)
        _login(server)
        server.send_message(message)


def _start_tls(server: Any) -> None:
    # Best-effort: a local/relay-only SMTP server may not support STARTTLS.
    try:
        server.starttls()
    except Exception:
        pass


def _login(server: Any) -> None:
    user = os.environ.get(_SMTP_USER_ENV, "").strip()
    password = resolve_smtp_password()
    if user and password:
        server.login(user, password)


def _build_message(subject: str, body: str, sender: str, recipients: list[str]) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    return message


def _split_addresses(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(";") if item.strip()]


def _smtp_port() -> int:
    raw = os.environ.get(_SMTP_PORT_ENV, "").strip()
    try:
        return int(raw) if raw else _DEFAULT_SMTP_PORT
    except ValueError:
        return _DEFAULT_SMTP_PORT


def _webhook_configured() -> str:
    return os.environ.get(_WEBHOOK_URL_ENV, "").strip()


def _email_configured() -> bool:
    host = os.environ.get(_SMTP_HOST_ENV, "").strip()
    sender = os.environ.get(_SMTP_FROM_ENV, "").strip()
    recipients = _split_addresses(os.environ.get(_SMTP_TO_ENV, ""))
    return bool(host and sender and recipients)


async def deliver_digest(digest: Digest) -> dict[str, bool]:
    """Attempt each transport that has its OWN env config present, returning
    a per-transport outcome. Called only when the caller already decided to
    send (the CLI's ``--digest`` flag) — an unconfigured transport is simply
    absent from the result, not attempted."""
    results: dict[str, bool] = {}
    webhook_url = _webhook_configured()
    if webhook_url:
        results["webhook"] = await send_webhook(digest.json_data, url=webhook_url)
    if _email_configured():
        results["email"] = send_email(digest.subject, digest.markdown)
    return results


__all__ = [
    "SmtpFactory",
    "deliver_digest",
    "resolve_smtp_password",
    "send_email",
    "send_webhook",
]
