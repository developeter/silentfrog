"""'Connect Google…' modal dialog (v2.0 R3) — the GUI over R2's pure
``integrations/google`` layer (config.py / connect.py / oauth.py /
gsc_client.py). This module adds no new pure logic: it only wires existing,
never-raising R2 entry points to widgets.

Contents: a BYO ``client_secret.json`` file picker, Connect/Disconnect per
account (``gsc`` / ``ga4``), an **editable** combo for the GSC property, a
GA4 property-id field, and a 'Use Google data in audits' checkbox that
starts unchecked (preserves the app's default-OFF invariant). The combo is
editable rather than a plain dropdown because a GSC property string must
match Search Console *exactly* ('sc-domain:example.com' vs
'https://example.com/') — free text that doesn't match fails silently,
producing exactly the "connected but no data" state this dialog exists to
prevent, so picking from ``list_sites()`` is offered but not required.

Threading — deliberately different from ``settings_dialog.py``'s
``_on_semrush_test``/``_on_sov_test``: those marshal a background result
back with ``QMetaObject.invokeMethod(some_label, ...)``, which is a
use-after-free if the modal is closed while the daemon thread is still
running (the label may already be destroyed). That window is ~15s for a
Semrush timeout; ``oauth.run_loopback_flow`` blocks for *minutes* waiting on
a human in a browser, which turns the same latent bug into a likely crash.
That bug is real, pre-existing and out of scope here (roadmap §8) — it is
not fixed and its pattern is not copied.

Instead, every slow call (``connect_account``, ``list_sites``, and the
Test-connection probe — all network/OAuth per R2's own docs) runs on a
daemon thread that writes only into a plain ``_JobHolder`` — a bare Python
object, not a ``QObject`` — and this dialog polls that holder with its own
``QTimer`` every 200ms. The timer is owned by (and dies with) the dialog;
if the dialog is closed mid-flow the orphaned worker thread still finishes,
but it only ever touches the discarded holder, never a Qt widget. This is a
new pattern for this codebase (no existing ``src/`` code polls a
worker-written holder), introduced specifically because the OAuth wait is
too long for the existing daemon-thread + ``invokeMethod`` shape to stay
safe.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from qtpy import QtCore, QtWidgets

from .integrations.google import oauth
from .integrations.google.config import GoogleConfig, load_config, save_config
from .integrations.google.connect import (
    ConnectResult,
    DisconnectResult,
    connect_account,
    disconnect_account,
    load_client_secrets,
)
from .integrations.google.ga4_client import Ga4Client
from .integrations.google.gsc_client import GscClient

_WINDOW_DAYS = 28


class _JobHolder:
    """Plain (non-Qt) box a daemon worker writes its result into. See the
    module docstring for why this replaces ``QMetaObject.invokeMethod``."""

    def __init__(self) -> None:
        self.done = False
        self.result: Any = None


def _start_daemon(target: Callable[..., None], *args: Any) -> None:
    """Seam over ``threading.Thread`` so tests can stub the actual
    threading (mirrors how tests/test_robots_sim_dialog.py stubs
    ``_RobotsFetchWorker.start``) — real code just starts a daemon thread."""
    threading.Thread(target=target, args=args, daemon=True).start()


def _connect_worker(holder: _JobHolder, account: str, secrets: dict[str, Any]) -> None:
    holder.result = GoogleConnectDialog._run_connect(account, secrets)
    holder.done = True


def _list_sites_worker(holder: _JobHolder) -> None:
    holder.result = GoogleConnectDialog._run_list_sites()
    holder.done = True


def _test_worker(holder: _JobHolder, site_url: str, property_id: str) -> None:
    holder.result = GoogleConnectDialog._run_test_connection(site_url, property_id)
    holder.done = True


class GoogleConnectDialog(QtWidgets.QDialog):
    """Modal Google connect dialog launched from Settings → Connect Google."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect Google")
        self.setMinimumSize(480, 360)
        self._active_job: tuple[str, str | None, _JobHolder] | None = None
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._on_poll_timer)
        outer = QtWidgets.QVBoxLayout(self)
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(self._build_secrets_group())
        body_layout.addWidget(self._build_gsc_group())
        body_layout.addWidget(self._build_ga4_group())
        body_layout.addWidget(self._build_status_group())
        body_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._build_button_box())
        self._job_buttons = (
            self.btn_gsc_connect,
            self.btn_gsc_disconnect,
            self.btn_gsc_refresh_sites,
            self.btn_ga4_connect,
            self.btn_ga4_disconnect,
            self.btn_test_connection,
        )
        self._job_handlers: dict[str, Callable[[str | None, Any], None]] = {
            "connect": self._apply_connect_result,
            "list_sites": lambda _meta, result: self._apply_list_sites_result(result),
            "test": lambda _meta, result: self._apply_test_result(result),
        }
        self._initialize_status()
        self._apply_sized_geometry()

    # --- building -----------------------------------------------------
    def _build_secrets_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Client credentials")
        layout = QtWidgets.QHBoxLayout(box)
        self.edit_secrets_path = QtWidgets.QLineEdit()
        self.edit_secrets_path.setPlaceholderText("Path to your client_secret.json (Desktop app type)")
        self.edit_secrets_path.setToolTip(
            "Bring your own OAuth client from a Google Cloud project you control — Silentfrog "
            "never ships credentials. Create a Desktop app OAuth client (not Web application) "
            "and download its client_secret.json."
        )
        layout.addWidget(self.edit_secrets_path, 1)
        self.btn_browse_secrets = QtWidgets.QPushButton("Browse…")
        self.btn_browse_secrets.clicked.connect(self._on_browse_secrets)
        layout.addWidget(self.btn_browse_secrets)
        return box

    def _build_gsc_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Search Console")
        layout = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_gsc_connect = QtWidgets.QPushButton("Connect…")
        self.btn_gsc_connect.clicked.connect(lambda: self._on_connect_clicked("gsc"))
        self.btn_gsc_disconnect = QtWidgets.QPushButton("Disconnect")
        self.btn_gsc_disconnect.clicked.connect(lambda: self._on_disconnect_clicked("gsc"))
        self.lbl_gsc_status = QtWidgets.QLabel("")
        row_layout.addWidget(self.btn_gsc_connect)
        row_layout.addWidget(self.btn_gsc_disconnect)
        row_layout.addWidget(self.lbl_gsc_status)
        row_layout.addStretch(1)
        layout.addWidget(row)
        form = QtWidgets.QFormLayout()
        self.combo_gsc_property = QtWidgets.QComboBox()
        self.combo_gsc_property.setEditable(True)
        self.combo_gsc_property.setToolTip(
            "Must match Search Console exactly, e.g. 'sc-domain:example.com' or "
            "'https://example.com/' — free text that doesn't match fails silently (connected, "
            "no data). Use Refresh to pick from your actual properties."
        )
        self.btn_gsc_refresh_sites = QtWidgets.QPushButton("Refresh")
        self.btn_gsc_refresh_sites.clicked.connect(self._on_refresh_sites_clicked)
        property_row = QtWidgets.QWidget()
        property_row_layout = QtWidgets.QHBoxLayout(property_row)
        property_row_layout.setContentsMargins(0, 0, 0, 0)
        property_row_layout.addWidget(self.combo_gsc_property, 1)
        property_row_layout.addWidget(self.btn_gsc_refresh_sites)
        form.addRow("Property", property_row)
        layout.addLayout(form)
        return box

    def _build_ga4_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Analytics 4")
        layout = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_ga4_connect = QtWidgets.QPushButton("Connect…")
        self.btn_ga4_connect.clicked.connect(lambda: self._on_connect_clicked("ga4"))
        self.btn_ga4_disconnect = QtWidgets.QPushButton("Disconnect")
        self.btn_ga4_disconnect.clicked.connect(lambda: self._on_disconnect_clicked("ga4"))
        self.lbl_ga4_status = QtWidgets.QLabel("")
        row_layout.addWidget(self.btn_ga4_connect)
        row_layout.addWidget(self.btn_ga4_disconnect)
        row_layout.addWidget(self.lbl_ga4_status)
        row_layout.addStretch(1)
        layout.addWidget(row)
        form = QtWidgets.QFormLayout()
        self.edit_ga4_property_id = QtWidgets.QLineEdit()
        self.edit_ga4_property_id.setPlaceholderText("GA4 property id, e.g. 123456789")
        self.edit_ga4_property_id.setToolTip(
            "The numeric GA4 property id (Admin → Property settings). Validated free text "
            "only — no property picker (v2.0 roadmap §8)."
        )
        form.addRow("Property id", self.edit_ga4_property_id)
        layout.addLayout(form)
        return box

    def _build_status_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Use in audits")
        layout = QtWidgets.QVBoxLayout(box)
        self.chk_use_google_data = QtWidgets.QCheckBox("Use Google data in audits")
        self.chk_use_google_data.setToolTip(
            "Off by default. When checked, Search Console and GA4 metrics feed the AI "
            "Visibility 'Real performance' / 'Engagement' checks. Never penalises the GEO "
            "Score either way (§1.5)."
        )
        layout.addWidget(self.chk_use_google_data)
        warning = QtWidgets.QLabel(
            "If your Google Cloud OAuth consent screen is still in Testing, refresh tokens "
            "expire after 7 days and the connection will silently stop returning data. Set "
            "your consent screen to In production in Google Cloud Console to keep it working."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        test_row = QtWidgets.QWidget()
        test_row_layout = QtWidgets.QHBoxLayout(test_row)
        test_row_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_test_connection = QtWidgets.QPushButton("Test connection")
        self.btn_test_connection.setToolTip(
            "Makes a real API call for each connected account — a stored token can look "
            "present and still be dead (see the Testing/7-day note above)."
        )
        self.btn_test_connection.clicked.connect(self._on_test_connection_clicked)
        self.lbl_test_status = QtWidgets.QLabel("")
        test_row_layout.addWidget(self.btn_test_connection)
        test_row_layout.addWidget(self.lbl_test_status)
        test_row_layout.addStretch(1)
        layout.addWidget(test_row)
        disconnect_note = QtWidgets.QLabel(
            "Disconnect removes the token from this app only. To revoke Google's own grant, "
            "visit myaccount.google.com/permissions."
        )
        disconnect_note.setWordWrap(True)
        layout.addWidget(disconnect_note)
        return box

    def _build_button_box(self) -> QtWidgets.QDialogButtonBox:
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    def _apply_sized_geometry(self) -> None:
        """Mirrors CrawlSettingsDialog: size to content but never exceed the
        available screen, so the button row always stays reachable."""
        target = self.sizeHint().expandedTo(self.minimumSize())
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            target.setHeight(min(target.height(), max(self.minimumHeight(), available.height() - 80)))
            target.setWidth(min(target.width(), max(self.minimumWidth(), available.width() - 80)))
        self.resize(target)

    # --- initial state --------------------------------------------------
    def _initialize_status(self) -> None:
        config = load_config()
        self.edit_secrets_path.setText(config.client_secrets_path)
        if config.gsc_site_url:
            self.combo_gsc_property.addItem(config.gsc_site_url)
            self.combo_gsc_property.setCurrentText(config.gsc_site_url)
        self.edit_ga4_property_id.setText(config.ga4_property_id)
        self.chk_use_google_data.setChecked(config.enabled)
        status = self._load_google_status()
        for account, connected in status.items():
            self._sync_account_buttons(account, connected)
            self._set_status(account, "✓ Connected" if connected else "✗ Not connected")

    def _widgets_for(self, account: str) -> tuple[QtWidgets.QLabel, QtWidgets.QPushButton, QtWidgets.QPushButton]:
        if account == "gsc":
            return self.lbl_gsc_status, self.btn_gsc_connect, self.btn_gsc_disconnect
        return self.lbl_ga4_status, self.btn_ga4_connect, self.btn_ga4_disconnect

    def _set_status(self, account: str, text: str) -> None:
        label, _connect_btn, _disconnect_btn = self._widgets_for(account)
        label.setText(text)

    def _sync_account_buttons(self, account: str, connected: bool) -> None:
        # A token existing already means Connect re-runs the flow with a
        # fresh consent — "Reconnect" says that plainly instead of leaving a
        # stale token's failure as a silent measured=False elsewhere.
        _label, connect_btn, disconnect_btn = self._widgets_for(account)
        connect_btn.setText("Reconnect" if connected else "Connect…")
        disconnect_btn.setEnabled(connected)
        if account == "gsc":
            self.btn_gsc_refresh_sites.setEnabled(connected)

    def _set_busy(self, busy: bool) -> None:
        for btn in self._job_buttons:
            btn.setEnabled(not busy)

    # --- static seams (mirrors CrawlSettingsDialog._load_semrush_key) ---
    # Every one of these touches the OS keychain and/or the network via
    # R2's oauth/connect layer. Bare @staticmethod + no captured `self` so
    # tests can monkeypatch the class attribute directly and never hit a
    # real keychain, browser, or network call.
    @staticmethod
    def _load_google_status() -> dict[str, bool]:
        try:
            return {"gsc": oauth.has_token("gsc"), "ga4": oauth.has_token("ga4")}
        except Exception:
            return {"gsc": False, "ga4": False}

    @staticmethod
    def _run_connect(account: str, secrets: dict[str, Any]) -> ConnectResult:
        return connect_account(account, secrets)

    @staticmethod
    def _run_disconnect(account: str) -> DisconnectResult:
        return disconnect_account(account)

    @staticmethod
    def _run_list_sites() -> list[dict[str, str]]:
        """GSC properties for the property combo. ``[]`` on any failure,
        including a missing/broken token — never raises."""
        token = oauth.load_token("gsc")
        if not token:
            return []
        try:
            service = oauth.build_gsc_service(token)
        except Exception:
            return []
        return GscClient(service).list_sites()

    @staticmethod
    def _run_test_connection(site_url: str, property_id: str) -> tuple[bool, str]:
        """Makes one real, lightweight API call per connected account
        instead of just checking token presence — a Testing-mode consent
        screen's refresh token silently stops working after 7 days, and a
        dead token still passes ``has_token``. Tests the dialog's current
        (possibly unsaved) fields, not ``connection.from_env()``'s
        enabled/env gate, so a user can test before opting in."""
        gsc_token = oauth.load_token("gsc")
        ga4_token = oauth.load_token("ga4")
        if not gsc_token and not ga4_token:
            return False, "Not connected."
        end = datetime.now(UTC).date()
        start = end - timedelta(days=_WINDOW_DAYS)
        measured: list[bool] = []
        try:
            if gsc_token and site_url:
                gsc = GscClient(oauth.build_gsc_service(gsc_token))
                metrics = gsc.metrics_for_url(site_url, site_url, start.isoformat(), end.isoformat())
                measured.append(metrics.measured)
            if ga4_token and property_id:
                ga4 = Ga4Client(oauth.build_ga4_service(ga4_token), property_id)
                measured.append(ga4.metrics_for_url("/", start.isoformat(), end.isoformat()).measured)
        except Exception as exc:
            return False, f"Reconnect — {exc}"
        if not measured:
            return False, "Add a GSC property or GA4 property id, then test again."
        if all(measured):
            return True, "Working."
        return False, "Reconnect — Google did not return data (the refresh token may have expired)."

    # --- slots ------------------------------------------------------
    def _on_browse_secrets(self) -> None:
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select client_secret.json", "", "JSON files (*.json)"
        )
        if path:
            self.edit_secrets_path.setText(path)

    def _on_connect_clicked(self, account: str) -> None:
        if self._active_job is not None:
            return
        path = self.edit_secrets_path.text().strip()
        if not path:
            self._set_status(account, "✗ Choose a client_secret.json file first.")
            return
        secrets_result = load_client_secrets(path)
        if not secrets_result.ok:
            self._set_status(account, f"✗ {secrets_result.reason}")
            return
        self._set_status(account, "Connecting… complete the sign-in in your browser.")
        self._set_busy(True)
        holder = _JobHolder()
        self._active_job = ("connect", account, holder)
        _start_daemon(_connect_worker, holder, account, secrets_result.secrets)
        self._poll_timer.start()

    def _on_disconnect_clicked(self, account: str) -> None:
        if self._active_job is not None:
            return
        result = self._run_disconnect(account)
        if result.ok:
            self._set_status(account, "✗ Not connected")
            self._sync_account_buttons(account, False)
            self._clear_property_widget(account)
        else:
            self._set_status(account, f"✗ {result.reason}")

    def _clear_property_widget(self, account: str) -> None:
        """Keep the property widget in sync with what disconnect_account
        just cleared on disk (connect.py's documented clear-on-disconnect
        contract). Without this, accept()'s unconditional widget->config
        write re-persists the stale combo/field text and silently reverts
        the disconnect the moment the dialog is closed with OK."""
        if account == "gsc":
            # clear() alone only empties the item list — an editable
            # combo's line-edit text (set via setCurrentText, never an
            # addItem'd item) survives it, so the text must be reset too.
            self.combo_gsc_property.clear()
            self.combo_gsc_property.setCurrentText("")
        else:
            self.edit_ga4_property_id.clear()

    def _on_refresh_sites_clicked(self) -> None:
        if self._active_job is not None:
            return
        self._set_busy(True)
        holder = _JobHolder()
        self._active_job = ("list_sites", None, holder)
        _start_daemon(_list_sites_worker, holder)
        self._poll_timer.start()

    def _on_test_connection_clicked(self) -> None:
        if self._active_job is not None:
            return
        site_url = self.combo_gsc_property.currentText().strip()
        property_id = self.edit_ga4_property_id.text().strip()
        self.lbl_test_status.setText("Testing…")
        self._set_busy(True)
        holder = _JobHolder()
        self._active_job = ("test", None, holder)
        _start_daemon(_test_worker, holder, site_url, property_id)
        self._poll_timer.start()

    def _on_poll_timer(self) -> None:
        if self._active_job is None:
            self._poll_timer.stop()
            return
        kind, meta, holder = self._active_job
        if not holder.done:
            return
        self._active_job = None
        self._poll_timer.stop()
        self._set_busy(False)
        self._job_handlers[kind](meta, holder.result)

    def _apply_connect_result(self, account: str | None, result: ConnectResult) -> None:
        assert account is not None
        if result.ok:
            self._set_status(account, "✓ Connected")
            self._sync_account_buttons(account, True)
        else:
            self._set_status(account, f"✗ {result.reason}")

    def _apply_list_sites_result(self, sites: list[dict[str, str]]) -> None:
        current = self.combo_gsc_property.currentText().strip()
        self.combo_gsc_property.clear()
        for site in sites:
            self.combo_gsc_property.addItem(site.get("site_url", ""))
        if current:
            self.combo_gsc_property.setCurrentText(current)
        if sites:
            noun = "property" if len(sites) == 1 else "properties"
            self.lbl_gsc_status.setText(f"✓ Connected — {len(sites)} {noun} loaded.")
        else:
            self.lbl_gsc_status.setText("✓ Connected — no properties returned; check account access.")

    def _apply_test_result(self, result: tuple[bool, str]) -> None:
        ok, message = result
        mark = "✓" if ok else "✗"
        self.lbl_test_status.setText(f"{mark} {message}")

    def accept(self) -> None:
        """Persist the dialog's fields as GoogleConfig. Never blocks accept
        — save_config never raises (config.py, R2)."""
        save_config(
            GoogleConfig(
                enabled=self.chk_use_google_data.isChecked(),
                gsc_site_url=self.combo_gsc_property.currentText().strip(),
                ga4_property_id=self.edit_ga4_property_id.text().strip(),
                client_secrets_path=self.edit_secrets_path.text().strip(),
            )
        )
        super().accept()

    def done(self, result: int) -> None:
        """Stop the poll timer and drop the in-flight job reference before
        teardown. The worker thread itself is daemonic and keeps running to
        completion (an OAuth loopback / API call can't be aborted cleanly),
        but it only ever writes into the plain ``_JobHolder`` it closed
        over — nothing reads that holder once ``_active_job`` is cleared
        and the timer is stopped, so a late-arriving result touches no Qt
        object. See the module docstring for why this differs from
        settings_dialog.py's ``_on_semrush_test``."""
        self._poll_timer.stop()
        self._active_job = None
        super().done(result)


__all__ = ["GoogleConnectDialog"]
