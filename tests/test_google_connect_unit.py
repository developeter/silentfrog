"""Unit tests for the v2.0 R2 Google connect/disconnect orchestration
(fake flow + fake keyring, no real network/browser/OS keychain)."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from silentfrog.integrations.google import oauth
from silentfrog.integrations.google.config import GoogleConfig, load_config, save_config
from silentfrog.integrations.google.connect import connect_account, disconnect_account, load_client_secrets


class _FakeKeyring:
    """In-memory stand-in for the ``keyring`` module (get/set/delete_password)."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self._store[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self._store.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self._store.pop((service, account), None)


class _RefusingFlow:
    """Stand-in for InstalledAppFlow whose construction fails, so the real
    run_loopback_flow's error normalisation is what gets exercised."""

    @staticmethod
    def from_client_config(client_config: dict[str, Any], scopes: list[str]) -> _RefusingFlow:
        raise ValueError("the browser window was closed")


# --- load_client_secrets ---------------------------------------------------
def test_load_client_secrets_accepts_desktop_app_client(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"installed": {"client_id": "abc"}}), encoding="utf-8")

    result = load_client_secrets(str(path))

    assert result.ok is True
    assert result.secrets == {"installed": {"client_id": "abc"}}


def test_load_client_secrets_rejects_web_application_client(tmp_path: Path) -> None:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"web": {"client_id": "abc"}}), encoding="utf-8")

    result = load_client_secrets(str(path))

    assert result.ok is False
    assert "Desktop app" in result.reason


def test_load_client_secrets_missing_file_returns_ok_false_without_raising(tmp_path: Path) -> None:
    result = load_client_secrets(str(tmp_path / "does_not_exist.json"))

    assert result.ok is False
    assert result.secrets is None


# --- connect_account ---------------------------------------------------
def test_connect_account_saves_token_via_injected_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(oauth, "save_token", lambda account, token_json: calls.append((account, token_json)))

    def fake_flow(secrets: dict[str, Any], scopes: list[str]) -> str:
        assert secrets == {"installed": {}}
        assert scopes == oauth.GSC_SCOPES
        return "FAKE-TOKEN-JSON"

    result = connect_account("gsc", {"installed": {}}, flow=fake_flow)

    assert result.ok is True
    assert calls == [("gsc", "FAKE-TOKEN-JSON")]


def test_connect_account_missing_extra_returns_pip_install_message(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(oauth, "save_token", lambda account, token_json: calls.append((account, token_json)))

    def missing_extra_flow(secrets: dict[str, Any], scopes: list[str]) -> str:
        raise ModuleNotFoundError("no module named 'google_auth_oauthlib'")

    result = connect_account("gsc", {"installed": {}}, flow=missing_extra_flow)

    assert result.ok is False
    assert "pip install silentfrog[google]" in result.reason
    assert calls == []


def test_connect_account_timeout_writes_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(oauth, "save_token", lambda account, token_json: calls.append((account, token_json)))

    def timing_out_flow(secrets: dict[str, Any], scopes: list[str]) -> str:
        raise TimeoutError("timed out waiting for the browser")

    result = connect_account("ga4", {"installed": {}}, flow=timing_out_flow)

    assert result.ok is False
    assert calls == []


def test_connect_account_reports_a_flow_failure_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The user-facing prefix belongs to connect_account alone: wording it in
    run_loopback_flow too produced 'Google sign-in failed: Google sign-in
    failed: ...'. Exercises the real default flow via a stub oauthlib."""
    monkeypatch.setattr(oauth, "save_token", lambda account, token_json: pytest.fail("no token expected"))
    flow_module = types.ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = _RefusingFlow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib", types.ModuleType("google_auth_oauthlib"))
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)

    result = connect_account("gsc", {"installed": {}})

    assert result.ok is False
    assert result.reason == "Google sign-in failed: the browser window was closed"


def test_connect_account_unknown_account_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(oauth, "save_token", lambda account, token_json: calls.append((account, token_json)))

    result = connect_account("bogus", {"installed": {}}, flow=lambda secrets, scopes: "TOKEN")

    assert result.ok is False
    assert calls == []


# --- disconnect_account --------------------------------------------------
def test_disconnect_account_clears_token_and_config_field(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    fake_keyring = _FakeKeyring()
    monkeypatch.setattr(oauth, "_keyring", lambda: fake_keyring)

    oauth.save_token("gsc", "TOKEN-JSON")
    save_config(GoogleConfig(enabled=True, gsc_site_url="https://example.com/", ga4_property_id="123"))

    result = disconnect_account("gsc")

    assert result.ok is True
    assert oauth.load_token("gsc") is None
    config = load_config()
    assert config.gsc_site_url == ""
    assert config.ga4_property_id == "123"  # unrelated field untouched


def test_disconnect_account_keeps_config_when_keychain_delete_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: a keychain delete that raises (locked vault, backend
    error, permissions) must not be reported as a successful disconnect —
    the token is still live, so the config field must stay put."""
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))

    class _RaisingDeleteKeyring(_FakeKeyring):
        def delete_password(self, service: str, account: str) -> None:
            raise RuntimeError("credential vault is locked")

    fake_keyring = _RaisingDeleteKeyring()
    monkeypatch.setattr(oauth, "_keyring", lambda: fake_keyring)

    oauth.save_token("gsc", "REAL-TOKEN-JSON")
    save_config(GoogleConfig(enabled=True, gsc_site_url="https://example.com/", ga4_property_id="123"))

    result = disconnect_account("gsc")

    assert result.ok is False
    assert oauth.has_token("gsc") is True  # token is still live in the keychain
    config = load_config()
    assert config.gsc_site_url == "https://example.com/"  # not falsely cleared
