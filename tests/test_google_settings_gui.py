"""v2.0 R3 — the Google connect dialog + its Settings launcher row.

Every test here fakes the OAuth/keychain/network seams
(``GoogleConnectDialog._load_google_status`` / ``_run_connect`` /
``_run_disconnect`` / ``_run_list_sites`` / ``_run_test_connection``) so
nothing touches the real OS keychain, a real browser, or the real network —
mirroring how ``tests/test_tech_stack_unit.py`` stubs
``CrawlSettingsDialog._load_semrush_key``. Background work is made
synchronous by stubbing ``google_connect_dialog._start_daemon`` (same
convention as ``tests/test_robots_sim_dialog.py`` stubbing
``_RobotsFetchWorker.start``) instead of waiting on a real thread/timer.
"""

from __future__ import annotations

import json

from qtpy import QtCore, QtWidgets

from silentfrog import google_connect_dialog, settings_dialog
from silentfrog.crawl_options import CrawlOptions
from silentfrog.google_connect_dialog import GoogleConnectDialog
from silentfrog.integrations.google.config import load_config
from silentfrog.integrations.google.connect import ConnectResult, DisconnectResult
from silentfrog.settings_dialog import CrawlSettingsDialog


def _patch_status(monkeypatch, *, gsc: bool = False, ga4: bool = False) -> None:
    """The one seam every GoogleConnectDialog construction must stub —
    without it, __init__ calls the real oauth.has_token (roadmap warning)."""
    monkeypatch.setattr(GoogleConnectDialog, "_load_google_status", staticmethod(lambda: {"gsc": gsc, "ga4": ga4}))


def _write_valid_secrets(tmp_path) -> str:
    path = tmp_path / "client_secret.json"
    path.write_text(json.dumps({"installed": {"client_id": "abc"}}), encoding="utf-8")
    return str(path)


# --- launcher row in settings_dialog.py -------------------------------
def test_google_launcher_disabled_without_extra_shows_pip_hint(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(settings_dialog, "_google_available", lambda: False)
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.btn_google_connect.isEnabled() is False
    assert "pip install silentfrog[google]" in dialog.btn_google_connect.toolTip()


def test_google_launcher_enabled_with_extra_present(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(settings_dialog, "_google_available", lambda: True)
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    assert dialog.btn_google_connect.isEnabled() is True
    assert "pip install" not in dialog.btn_google_connect.toolTip()


def test_google_launcher_opens_connect_dialog(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(settings_dialog, "_google_available", lambda: True)
    opened: dict[str, object] = {}

    class _FakeDialog:
        def __init__(self, parent=None) -> None:
            opened["parent"] = parent

        def exec(self) -> int:
            opened["exec"] = True
            return 0

    monkeypatch.setattr("silentfrog.google_connect_dialog.GoogleConnectDialog", _FakeDialog)
    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.btn_google_connect, QtCore.Qt.MouseButton.LeftButton)

    assert opened.get("exec") is True
    assert opened.get("parent") is dialog


# --- layout + defaults --------------------------------------------------
def test_google_connect_dialog_layout_guard(qtbot, monkeypatch) -> None:
    """Mirrors tests/test_audit_profile_settings.py's B1 guard: a
    QScrollArea exists, the dialog fits on screen, and the button box is
    parented outside the scroll area (a sibling of it, not inside)."""
    _patch_status(monkeypatch)
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    assert dialog.findChild(QtWidgets.QScrollArea) is not None
    screen = dialog.screen() or QtWidgets.QApplication.primaryScreen()
    assert dialog.height() <= screen.availableGeometry().height()
    button_box = dialog.findChild(QtWidgets.QDialogButtonBox)
    assert button_box is not None
    assert button_box.parentWidget() is dialog


def test_use_google_data_checkbox_defaults_unchecked(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    _patch_status(monkeypatch)
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    assert dialog.chk_use_google_data.isChecked() is False


def test_gsc_property_combo_is_editable(qtbot, monkeypatch) -> None:
    # Free text must be accepted (roadmap: exact-match GSC property strings
    # like 'sc-domain:example.com' vs 'https://example.com/').
    _patch_status(monkeypatch)
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    assert dialog.combo_gsc_property.isEditable() is True


def test_dialog_text_carries_the_required_copy(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch)
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    all_labels = " ".join(w.text() for w in dialog.findChildren(QtWidgets.QLabel))
    assert "In production" in all_labels
    assert "7 days" in all_labels
    assert "myaccount.google.com/permissions" in all_labels
    assert dialog.btn_test_connection.text() == "Test connection"


# --- accept persists GoogleConfig ---------------------------------------
def test_accept_writes_a_google_config(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    _patch_status(monkeypatch)
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    secrets_path = str(tmp_path / "client_secret.json")
    dialog.edit_secrets_path.setText(secrets_path)
    dialog.combo_gsc_property.setCurrentText("sc-domain:example.com")
    dialog.edit_ga4_property_id.setText("123456789")
    dialog.chk_use_google_data.setChecked(True)

    dialog.accept()

    config = load_config()
    assert config.enabled is True
    assert config.gsc_site_url == "sc-domain:example.com"
    assert config.ga4_property_id == "123456789"
    assert config.client_secrets_path == secrets_path


# --- connect / disconnect wiring -----------------------------------------
def test_connect_success_updates_status_and_flips_button_to_reconnect(qtbot, monkeypatch, tmp_path) -> None:
    _patch_status(monkeypatch)
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: target(*args))
    monkeypatch.setattr(
        GoogleConnectDialog, "_run_connect", staticmethod(lambda account, secrets: ConnectResult(ok=True))
    )
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)
    dialog.edit_secrets_path.setText(_write_valid_secrets(tmp_path))

    qtbot.mouseClick(dialog.btn_gsc_connect, QtCore.Qt.MouseButton.LeftButton)
    dialog._on_poll_timer()  # the stubbed worker already finished; process it like the next tick would

    assert dialog.lbl_gsc_status.text() == "✓ Connected"
    assert dialog.btn_gsc_connect.text() == "Reconnect"
    assert dialog._active_job is None
    assert dialog._poll_timer.isActive() is False


def test_connect_failure_surfaces_the_typed_reason_not_a_traceback(qtbot, monkeypatch, tmp_path) -> None:
    _patch_status(monkeypatch)
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: target(*args))
    reason = "Google OAuth libraries are not installed. Run `pip install silentfrog[google]`."
    monkeypatch.setattr(
        GoogleConnectDialog,
        "_run_connect",
        staticmethod(lambda account, secrets: ConnectResult(ok=False, reason=reason)),
    )
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)
    dialog.edit_secrets_path.setText(_write_valid_secrets(tmp_path))

    qtbot.mouseClick(dialog.btn_ga4_connect, QtCore.Qt.MouseButton.LeftButton)
    dialog._on_poll_timer()

    assert dialog.lbl_ga4_status.text() == f"✗ {reason}"
    assert dialog.btn_ga4_connect.text() == "Connect…"  # never flips to Reconnect on failure


def test_connect_click_without_a_secrets_path_never_starts_a_job(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch)
    started: list[object] = []
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: started.append(target))
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.btn_gsc_connect, QtCore.Qt.MouseButton.LeftButton)

    assert started == []
    assert dialog._active_job is None
    assert "client_secret.json" in dialog.lbl_gsc_status.text()


def test_disconnect_success_reverts_status_and_button(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch, gsc=True)
    monkeypatch.setattr(GoogleConnectDialog, "_run_disconnect", staticmethod(lambda account: DisconnectResult(ok=True)))
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)
    assert dialog.btn_gsc_connect.text() == "Reconnect"  # sanity: starts connected

    qtbot.mouseClick(dialog.btn_gsc_disconnect, QtCore.Qt.MouseButton.LeftButton)

    assert dialog.lbl_gsc_status.text() == "✗ Not connected"
    assert dialog.btn_gsc_connect.text() == "Connect…"


def test_disconnect_failure_keeps_the_account_connected(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch, gsc=True)
    reason = "Could not remove the stored Google credential from the OS keychain."
    monkeypatch.setattr(
        GoogleConnectDialog, "_run_disconnect", staticmethod(lambda account: DisconnectResult(ok=False, reason=reason))
    )
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.btn_gsc_disconnect, QtCore.Qt.MouseButton.LeftButton)

    assert dialog.lbl_gsc_status.text() == f"✗ {reason}"
    assert dialog.btn_gsc_connect.text() == "Reconnect"  # still connected — token wasn't removed


def test_disconnect_then_accept_does_not_revert_the_config_clear(qtbot, monkeypatch, tmp_path) -> None:
    # Regression for the R3 blocker: disconnect_account (connect.py) clears
    # gsc_site_url on disk, but the combo kept showing the stale property
    # text, so the ordinary Disconnect -> OK flow silently re-wrote it back
    # on accept(). The widget must be cleared alongside the status/buttons
    # so accept()'s unconditional widget->config write has nothing stale
    # left to persist.
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    _patch_status(monkeypatch, gsc=True)
    monkeypatch.setattr(GoogleConnectDialog, "_run_disconnect", staticmethod(lambda account: DisconnectResult(ok=True)))
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)
    dialog.combo_gsc_property.setCurrentText("sc-domain:example.com")

    qtbot.mouseClick(dialog.btn_gsc_disconnect, QtCore.Qt.MouseButton.LeftButton)
    assert dialog.combo_gsc_property.currentText() == ""  # stale value must not survive disconnect

    dialog.accept()

    assert load_config().gsc_site_url == ""  # accept() must not revert the disconnect's clear


def test_refresh_sites_populates_the_property_combo_from_site_url_keys(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch, gsc=True)
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: target(*args))
    sites = [
        {"site_url": "sc-domain:example.com", "permission_level": "siteOwner"},
        {"site_url": "https://example.com/", "permission_level": "siteFullUser"},
    ]
    monkeypatch.setattr(GoogleConnectDialog, "_run_list_sites", staticmethod(lambda: sites))
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.btn_gsc_refresh_sites, QtCore.Qt.MouseButton.LeftButton)
    dialog._on_poll_timer()

    items = [dialog.combo_gsc_property.itemText(i) for i in range(dialog.combo_gsc_property.count())]
    assert items == ["sc-domain:example.com", "https://example.com/"]


def test_test_connection_reports_glyph_and_message(qtbot, monkeypatch) -> None:
    _patch_status(monkeypatch, gsc=True)
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: target(*args))
    monkeypatch.setattr(
        GoogleConnectDialog,
        "_run_test_connection",
        staticmethod(lambda site_url, property_id: (False, "Reconnect — boom")),
    )
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.btn_test_connection, QtCore.Qt.MouseButton.LeftButton)
    dialog._on_poll_timer()

    assert dialog.lbl_test_status.text() == "✗ Reconnect — boom"


# --- the threading deviation: closing mid-connect ------------------------
def test_closing_dialog_during_connect_stops_timer_and_discards_late_result(qtbot, monkeypatch, tmp_path) -> None:
    """The specific crash the QTimer+holder design exists to prevent:
    settings_dialog.py's _on_semrush_test calls QMetaObject.invokeMethod on
    a QLabel the dialog may have already destroyed. Here, closing mid-flow
    must stop the timer and drop the job so a late-arriving result from the
    (still-running, daemon) worker thread is never applied."""
    _patch_status(monkeypatch)
    monkeypatch.setattr(google_connect_dialog, "_start_daemon", lambda target, *args: None)  # never actually runs
    dialog = GoogleConnectDialog()
    qtbot.addWidget(dialog)
    dialog.edit_secrets_path.setText(_write_valid_secrets(tmp_path))

    qtbot.mouseClick(dialog.btn_gsc_connect, QtCore.Qt.MouseButton.LeftButton)
    assert dialog._active_job is not None
    assert dialog._poll_timer.isActive() is True
    _kind, _meta, holder = dialog._active_job
    status_while_connecting = dialog.lbl_gsc_status.text()

    dialog.reject()

    assert dialog._active_job is None
    assert dialog._poll_timer.isActive() is False

    # Simulate the orphaned daemon worker finishing late, after the dialog
    # is gone. It only ever writes into this plain holder.
    holder.result = ConnectResult(ok=True)
    holder.done = True
    dialog._on_poll_timer()  # a stray tick, if one ever fired, must be a no-op

    assert dialog._active_job is None
    assert dialog.lbl_gsc_status.text() == status_while_connecting  # never applied


# --- static seams never raise / never touch real keychain or network ----
def test_load_google_status_never_raises(monkeypatch) -> None:
    def _raise(account: str) -> bool:
        raise RuntimeError("keychain locked")

    monkeypatch.setattr(google_connect_dialog.oauth, "has_token", _raise)

    assert GoogleConnectDialog._load_google_status() == {"gsc": False, "ga4": False}


def test_load_google_status_reports_per_account(monkeypatch) -> None:
    monkeypatch.setattr(google_connect_dialog.oauth, "has_token", lambda account: account == "gsc")

    assert GoogleConnectDialog._load_google_status() == {"gsc": True, "ga4": False}


def test_run_list_sites_empty_without_a_token(monkeypatch) -> None:
    monkeypatch.setattr(google_connect_dialog.oauth, "load_token", lambda account: None)

    assert GoogleConnectDialog._run_list_sites() == []


def test_run_list_sites_empty_when_service_build_raises(monkeypatch) -> None:
    monkeypatch.setattr(google_connect_dialog.oauth, "load_token", lambda account: "TOKEN")

    def _raise(token: str) -> None:
        raise RuntimeError("invalid_grant")

    monkeypatch.setattr(google_connect_dialog.oauth, "build_gsc_service", _raise)

    assert GoogleConnectDialog._run_list_sites() == []


def test_run_test_connection_reports_not_connected_without_any_token(monkeypatch) -> None:
    monkeypatch.setattr(google_connect_dialog.oauth, "load_token", lambda account: None)

    ok, message = GoogleConnectDialog._run_test_connection("sc-domain:example.com", "123")

    assert ok is False
    assert message == "Not connected."


def test_run_test_connection_needs_a_property_value(monkeypatch) -> None:
    monkeypatch.setattr(google_connect_dialog.oauth, "load_token", lambda account: "TOKEN")

    ok, message = GoogleConnectDialog._run_test_connection("", "")

    assert ok is False
    assert "Add a GSC property" in message


def test_run_test_connection_reports_reconnect_when_build_raises(monkeypatch) -> None:
    # This is the case presence-of-token alone would miss: a Testing-mode
    # consent screen's refresh token is dead, but has_token() stays True.
    monkeypatch.setattr(
        google_connect_dialog.oauth, "load_token", lambda account: "TOKEN" if account == "gsc" else None
    )

    def _raise(token: str) -> None:
        raise RuntimeError("invalid_grant")

    monkeypatch.setattr(google_connect_dialog.oauth, "build_gsc_service", _raise)

    ok, message = GoogleConnectDialog._run_test_connection("sc-domain:example.com", "")

    assert ok is False
    assert message.startswith("Reconnect —")
    assert "invalid_grant" in message


def test_run_test_connection_reports_working_when_the_api_call_succeeds(monkeypatch) -> None:
    class _MeasuredMetrics:
        measured = True

    class _FakeGscClient:
        def __init__(self, service) -> None:
            pass

        def metrics_for_url(self, *args, **kwargs) -> _MeasuredMetrics:
            return _MeasuredMetrics()

    monkeypatch.setattr(
        google_connect_dialog.oauth, "load_token", lambda account: "TOKEN" if account == "gsc" else None
    )
    monkeypatch.setattr(google_connect_dialog.oauth, "build_gsc_service", lambda token: object())
    monkeypatch.setattr(google_connect_dialog, "GscClient", _FakeGscClient)

    ok, message = GoogleConnectDialog._run_test_connection("sc-domain:example.com", "")

    assert (ok, message) == (True, "Working.")
