"""Unit tests for the Semrush "entered my key, connection doesn't work" fix.

Covers the pure JSON config layer (mirrors test_google_config_unit.py) and
the settings-dialog wiring around it (mirrors test_google_settings_gui.py):

- keyring-missing must degrade visibly (disabled field + tooltip, warning
  label on accept) instead of swallowing a typed key (root cause (a));
- the "Use Semrush in audits" checkbox is the one thing that actually gates
  a crawl and defaults unchecked (preserves the default-OFF invariant);
- the enabled flag + daily cap round-trip through SemrushConfig instead of
  the QSettings key seo_crawler.py never read (root cause (c)).

Every dialog test stubs ``CrawlSettingsDialog._load_semrush_key`` /
``_store_semrush_key`` so nothing touches the real OS keychain, mirroring
how ``tests/test_tech_stack_unit.py`` stubs the same seams, and every test
points ``SILENTFROG_DATA_DIR`` at ``tmp_path`` so nothing reads or writes
the developer's real Silentfrog data dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from silentfrog.integrations.semrush import config as semrush_config
from silentfrog.integrations.semrush.config import SemrushConfig, load_config, save_config

# --- pure config layer ----------------------------------------------------


def test_defaults_are_disabled_with_max_calls_100() -> None:
    config = SemrushConfig()
    assert config.enabled is False
    assert config.max_calls == 100


def test_roundtrip_through_save_and_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    config = SemrushConfig(enabled=True, max_calls=250)
    save_config(config)
    assert load_config() == config


def test_load_missing_file_returns_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    assert load_config() == SemrushConfig()


def test_load_corrupt_json_returns_defaults_without_raising(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = semrush_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    assert load_config() == SemrushConfig()


def test_load_non_object_json_returns_defaults_without_raising(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = semrush_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert load_config() == SemrushConfig()


def test_load_invalid_max_calls_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = semrush_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"enabled": true, "max_calls": "not a number"}', encoding="utf-8")

    config = load_config()
    assert config.enabled is True
    assert config.max_calls == 100


def test_load_non_positive_max_calls_falls_back_to_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    path = semrush_config._config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"max_calls": 0}', encoding="utf-8")

    assert load_config().max_calls == 100


def test_silentfrog_data_dir_is_respected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    save_config(SemrushConfig(enabled=True))

    expected = tmp_path / "semrush" / "config.json"
    assert expected.is_file()


def test_save_config_never_raises_on_unwritable_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    blocked = tmp_path / "not_a_dir"
    blocked.write_text("x", encoding="utf-8")
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(blocked))

    save_config(SemrushConfig(enabled=True))  # must not raise


# --- settings dialog: keyring-availability gating -------------------------


def test_semrush_key_field_disabled_without_keyring_shows_pip_hint(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog import settings_dialog
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    monkeypatch.setattr(settings_dialog, "_keyring_available", lambda: False)
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.edit_semrush_key.isEnabled() is False
    assert "pip install silentfrog[semrush]" in dialog.edit_semrush_key.toolTip()


def test_semrush_key_field_enabled_with_keyring_present(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog import settings_dialog
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    monkeypatch.setattr(settings_dialog, "_keyring_available", lambda: True)
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.edit_semrush_key.isEnabled() is True
    assert "pip install" not in dialog.edit_semrush_key.toolTip()


# --- settings dialog: enabled checkbox + config round-trip -----------------


def test_semrush_enabled_checkbox_defaults_unchecked(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.chk_semrush_enabled.isChecked() is False


def test_dialog_initializes_from_stored_config(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    save_config(SemrushConfig(enabled=True, max_calls=42))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.chk_semrush_enabled.isChecked() is True
    assert dialog.spin_semrush_max_calls.value() == 42


def test_accept_writes_a_semrush_config(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(lambda key: True))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.chk_semrush_enabled.setChecked(True)
    dialog.spin_semrush_max_calls.setValue(250)

    dialog.accept()

    config = load_config()
    assert config.enabled is True
    assert config.max_calls == 250


def test_accept_with_key_and_no_keyring_warns_instead_of_swallowing(qtbot, monkeypatch, tmp_path) -> None:
    # Root cause (a): a key typed while keyring is unavailable must never
    # be dropped without a trace, and accept() must never raise. The
    # warning must also be VISIBLE before the dialog closes — a label set
    # right before super().accept() tears the dialog down is invisible to
    # the user, so accept() must also raise a modal (stubbed here, exactly
    # like the established QMessageBox.warning seam in test_log_gui.py /
    # test_site_crawl_gui.py).
    from qtpy import QtWidgets

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    warnings: list[tuple] = []
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(lambda key: False))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.edit_semrush_key.setText("sr-test-key")

    dialog.accept()

    assert dialog.lbl_semrush_test.text().startswith("✗")
    assert "pip install silentfrog[semrush]" in dialog.lbl_semrush_test.text()
    # The warning actually surfaced to the user, not just an invisible label
    # on an already-closed dialog.
    assert len(warnings) == 1
    assert "pip install silentfrog[semrush]" in warnings[0][-1]
    # The enabled flag + cap are still persisted even though the key wasn't.
    assert load_config().max_calls == 100


def test_accept_with_env_key_and_no_keyring_does_not_warn(qtbot, monkeypatch, tmp_path) -> None:
    # Regression guard: on a stock install (no keyring) a user who supplies
    # the key through SILENTFROG_SEMRUSH_API_KEY gets it prefilled into a
    # DISABLED field. Pressing OK must not pop a blocking modal they cannot
    # act on -- and that would be false anyway: nothing was lost, the env
    # key still resolves for every crawl. Only a key the user actually
    # typed (one that differs from the prefill) may warn.
    from qtpy import QtWidgets

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog import settings_dialog
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    warnings: list[tuple] = []
    monkeypatch.setattr(settings_dialog, "_keyring_available", lambda: False)
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: "sr-env-key"))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(lambda key: False))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert dialog.edit_semrush_key.isEnabled() is False
    assert dialog.edit_semrush_key.text() == "sr-env-key"

    dialog.accept()

    assert warnings == []
    assert dialog.lbl_semrush_test.text() == ""


def test_accept_with_key_and_keyring_present_does_not_warn(qtbot, monkeypatch, tmp_path) -> None:
    from qtpy import QtWidgets

    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    stored: list[str] = []
    warnings: list[tuple] = []
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(lambda key: stored.append(key) or True))
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warnings.append(a))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.edit_semrush_key.setText("sr-test-key")

    dialog.accept()

    assert stored == ["sr-test-key"]
    assert dialog.lbl_semrush_test.text() == ""
    assert warnings == []


def test_accept_with_empty_key_clears_the_stored_credential(qtbot, monkeypatch, tmp_path) -> None:
    # Regression guard: HEAD called keyring.set_password unconditionally, so
    # blanking the field and pressing OK cleared a previously stored key.
    # accept() must keep propagating a cleared field, not skip the write
    # for an empty key (the exact inverse of the bug
    # test_google_settings_gui.py:230-252 guards against on the Google side).
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    stored: list[str] = []
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: "sr-existing-key"))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(lambda key: stored.append(key) or True))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert dialog.edit_semrush_key.text() == "sr-existing-key"
    dialog.edit_semrush_key.setText("")

    dialog.accept()

    assert stored == [""]


# --- test-connection status wording ----------------------------------------


def _forbid_store(monkeypatch) -> None:
    """Pin the OK/Cancel contract: ``Test connection`` runs in a daemon
    thread that can outlive the dialog, so a key written from there would
    survive Cancel and stay in the OS keychain forever. The status text
    must stay pure -- only accept() persists."""
    from silentfrog.settings_dialog import CrawlSettingsDialog

    def _must_not_be_called(key: str) -> bool:
        raise AssertionError("Test connection must never write to the keychain")

    monkeypatch.setattr(CrawlSettingsDialog, "_store_semrush_key", staticmethod(_must_not_be_called))


def test_semrush_test_status_success_with_keyring_present(monkeypatch) -> None:
    from silentfrog import settings_dialog
    from silentfrog.settings_dialog import CrawlSettingsDialog

    _forbid_store(monkeypatch)
    monkeypatch.setattr(settings_dialog, "_keyring_available", lambda: True)

    text = CrawlSettingsDialog._semrush_test_status(True, "Connection OK.")
    assert text.startswith("✓")
    assert "not stored yet" in text
    assert "press OK" in text
    assert "OS keychain" in text


def test_semrush_test_status_success_without_keyring(monkeypatch) -> None:
    from silentfrog import settings_dialog
    from silentfrog.settings_dialog import CrawlSettingsDialog

    _forbid_store(monkeypatch)
    monkeypatch.setattr(settings_dialog, "_keyring_available", lambda: False)

    text = CrawlSettingsDialog._semrush_test_status(True, "Connection OK.")
    assert text.startswith("✓")
    assert "pip install silentfrog[semrush]" in text
    assert "cannot be stored" in text


def test_semrush_test_status_failure_passes_message_through_and_never_stores(monkeypatch) -> None:
    from silentfrog.settings_dialog import CrawlSettingsDialog

    _forbid_store(monkeypatch)

    text = CrawlSettingsDialog._semrush_test_status(False, "No API key set.")
    assert text == "✗ No API key set."
