"""Unit tests for the v3 G9 alert transports (webhook + SMTP), stubbed —
no real network, no real SMTP connection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import silentfrog.alert_transport as alert_transport
from silentfrog.alert_transport import deliver_digest, resolve_smtp_password, send_email, send_webhook

_ENV_KEYS = (
    "SILENTFROG_ALERT_WEBHOOK_URL",
    "SILENTFROG_SMTP_HOST",
    "SILENTFROG_SMTP_PORT",
    "SILENTFROG_SMTP_USER",
    "SILENTFROG_SMTP_FROM",
    "SILENTFROG_SMTP_TO",
    "SILENTFROG_SMTP_PASSWORD",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every transport is env-configured; start every test from a fully
    # unconfigured slate so host-machine env vars can never leak in.
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@dataclass
class _StubDigest:
    subject: str = "subject line"
    markdown: str = "body text"
    json_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.json_data is None:
            self.json_data = {"counts": {"crawled": 1}}


# --- send_webhook -------------------------------------------------------------


class _Resp:
    def __init__(self, status: int) -> None:
        self.status = status

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _DummySession:
    """Records every POST so tests can assert zero-network-call contracts."""

    def __init__(self, resp: _Resp | None = None, raises: type[Exception] | None = None) -> None:
        self._resp = resp
        self._raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append((url, kwargs))
        if self._raises is not None:
            raise self._raises("simulated")
        assert self._resp is not None
        return self._resp


@pytest.mark.asyncio
async def test_send_webhook_success_returns_true() -> None:
    session = _DummySession(_Resp(200))

    result = await send_webhook({"a": 1}, url="https://hooks.example.com/x", session=session)

    assert result is True
    assert session.calls[0][0] == "https://hooks.example.com/x"
    assert session.calls[0][1]["json"] == {"a": 1}


@pytest.mark.asyncio
async def test_send_webhook_http_error_returns_false() -> None:
    session = _DummySession(_Resp(500))

    result = await send_webhook({"a": 1}, url="https://hooks.example.com/x", session=session)

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_network_exception_returns_false() -> None:
    session = _DummySession(raises=ConnectionError)

    result = await send_webhook({"a": 1}, url="https://hooks.example.com/x", session=session)

    assert result is False


@pytest.mark.asyncio
async def test_send_webhook_blank_url_returns_false_without_posting() -> None:
    session = _DummySession(_Resp(200))

    result = await send_webhook({"a": 1}, url="   ", session=session)

    assert result is False
    assert session.calls == []


# --- send_email ---------------------------------------------------------------


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent_message: Any = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.login_args = (user, password)

    def send_message(self, message: Any) -> None:
        self.sent_message = message


@pytest.fixture(autouse=True)
def _clear_fake_smtp() -> None:
    _FakeSMTP.instances.clear()


def test_send_email_sends_via_factory_and_logs_in_with_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILENTFROG_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_TO", "a@example.com;b@example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_USER", "bot")
    monkeypatch.setattr(alert_transport, "resolve_smtp_password", lambda: "secret")

    result = send_email("Subject line", "Body text", smtp_factory=_FakeSMTP)

    assert result is True
    instance = _FakeSMTP.instances[-1]
    assert instance.sent_message["Subject"] == "Subject line"
    assert instance.sent_message["To"] == "a@example.com, b@example.com"
    assert instance.started_tls is True
    assert instance.login_args == ("bot", "secret")


def test_send_email_skips_login_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILENTFROG_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_TO", "a@example.com")
    monkeypatch.setattr(alert_transport, "resolve_smtp_password", lambda: "")

    result = send_email("Subject", "Body", smtp_factory=_FakeSMTP)

    assert result is True
    assert _FakeSMTP.instances[-1].login_args is None


def test_send_email_missing_config_returns_false_and_never_instantiates_factory() -> None:
    calls: list[tuple[str, int]] = []

    def _factory(host: str, port: int) -> Any:
        calls.append((host, port))
        raise AssertionError("factory must never be instantiated when unconfigured")

    result = send_email("Subject", "Body", smtp_factory=_factory)

    assert result is False
    assert calls == []


def test_resolve_smtp_password_prefers_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeKeyring:
        def get_password(self, service: str, username: str) -> str:
            assert service == "silentfrog-smtp"
            assert username == "password"
            return "keyring-secret"

    monkeypatch.setattr(alert_transport, "_keyring", lambda: _FakeKeyring())
    monkeypatch.setenv("SILENTFROG_SMTP_PASSWORD", "env-secret")

    assert resolve_smtp_password() == "keyring-secret"


def test_resolve_smtp_password_falls_back_to_env_when_keyring_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> Any:
        raise ModuleNotFoundError("no keyring installed")

    monkeypatch.setattr(alert_transport, "_keyring", _boom)
    monkeypatch.setenv("SILENTFROG_SMTP_PASSWORD", "env-secret")

    assert resolve_smtp_password() == "env-secret"


# --- deliver_digest -------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_digest_calls_only_the_configured_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = _StubDigest()
    monkeypatch.setenv("SILENTFROG_ALERT_WEBHOOK_URL", "https://hook.example.com/x")

    async def _fake_webhook(payload: dict[str, Any], *, url: str, session: Any = None) -> bool:
        assert url == "https://hook.example.com/x"
        assert payload == digest.json_data
        return True

    monkeypatch.setattr(alert_transport, "send_webhook", _fake_webhook)

    results = await deliver_digest(digest)

    assert results == {"webhook": True}


@pytest.mark.asyncio
async def test_deliver_digest_calls_only_configured_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILENTFROG_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_TO", "a@example.com")
    monkeypatch.setattr(alert_transport, "send_email", lambda subject, body, **_: True)

    results = await deliver_digest(_StubDigest())

    assert results == {"email": True}


@pytest.mark.asyncio
async def test_deliver_digest_attempts_both_when_both_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILENTFROG_ALERT_WEBHOOK_URL", "https://hook.example.com/x")
    monkeypatch.setenv("SILENTFROG_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SILENTFROG_SMTP_TO", "a@example.com")

    async def _fake_webhook(*_args: Any, **_kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(alert_transport, "send_webhook", _fake_webhook)
    monkeypatch.setattr(alert_transport, "send_email", lambda subject, body, **_: False)

    results = await deliver_digest(_StubDigest())

    assert results == {"webhook": True, "email": False}


@pytest.mark.asyncio
async def test_deliver_digest_skips_all_transports_when_unconfigured() -> None:
    results = await deliver_digest(_StubDigest())

    assert results == {}
