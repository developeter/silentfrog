"""Unit tests for the v2.0 R2 Google integration config (JSON, no Qt)."""

from __future__ import annotations

from pathlib import Path

import pytest

from silentfrog.integrations.google import config as google_config
from silentfrog.integrations.google.config import GoogleConfig, load_config, save_config


def test_defaults_are_disabled_and_empty() -> None:
    config = GoogleConfig()
    assert config.enabled is False
    assert config.gsc_site_url == ""
    assert config.ga4_property_id == ""
    assert config.client_secrets_path == ""


def test_roundtrip_through_save_and_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    config = GoogleConfig(
        enabled=True,
        gsc_site_url="https://example.com/",
        ga4_property_id="123456",
        client_secrets_path=str(tmp_path / "client_secret.json"),
    )
    save_config(config)
    assert load_config() == config


def test_load_missing_file_returns_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    assert load_config() == GoogleConfig()


def test_load_corrupt_json_returns_defaults_without_raising(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = google_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    assert load_config() == GoogleConfig()


def test_load_non_object_json_returns_defaults_without_raising(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = google_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert load_config() == GoogleConfig()


def test_silentfrog_data_dir_is_respected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    save_config(GoogleConfig(enabled=True))

    expected = tmp_path / "google" / "config.json"
    assert expected.is_file()


def test_save_config_never_raises_on_unwritable_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Point the data dir at a path that is actually a file, so mkdir() fails.
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(blocked))

    save_config(GoogleConfig(enabled=True))  # must not raise
