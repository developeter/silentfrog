"""'AI review' GUI (PR-D) — the setup + result dialogs for the v3 G7
on-demand AI-assisted page review. Moved out of ``seo_gui.py`` so that
module stays a thin `_on_ai_review` wiring shim; all the provider-picking
and result-rendering logic lives here.

``AiReviewSetupDialog`` lets the user pick a provider (Gemini/OpenAI/
Anthropic/Ollama — see ``ai_review_providers.PROVIDER_CHOICES``), type or
reuse a BYO key, and optionally override the model, before running a
review. Gemini is first in the picker and gets its own "free API key" help
link because it is the easiest zero-cost path when no local Ollama server
is running — the complaint this PR exists to fix.

Threading for the result dialog copies ``google_connect_dialog``'s
``_JobHolder`` + polling ``QTimer`` pattern (see that module's docstring for
the full rationale): ``QMetaObject.invokeMethod`` on a live widget is a
use-after-free if the modal closes while the daemon thread is still
running, and an AI provider call can run long enough (up to the client's
own timeout, tens of seconds) to make that a real risk — the same reasoning
that made the Google OAuth dialog switch away from the
``settings_dialog.py`` ``invokeMethod`` shape. Every slow call here
(``client.review(...)``) runs on a daemon thread that writes only into a
plain ``_JobHolder`` (not a ``QObject``); the dialog polls that holder with
its own ``QTimer`` every 200ms, owned by (and dying with) the dialog. If the
dialog is closed mid-review the orphaned worker thread still finishes, but
it only ever touches the discarded holder, never a Qt widget.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from qtpy import QtCore, QtWidgets

from .ai_review import AiProviderConfig, AiReviewClient, AiReviewInput, AiReviewResult
from .ai_review_providers import DEFAULT_MODELS, PROVIDER_CHOICES, auto_config, provider_remedy
from .audit_issues import IssueSeverity

_GEMINI_HELP_HTML = (
    "Get a free Gemini API key at "
    '<a href="https://aistudio.google.com/apikey">https://aistudio.google.com/apikey</a>'
    " — Google's free tier is enough for page reviews."
)

_KEYRING_SERVICE = "silentfrog-ai-engines"


class AiReviewSetupDialog(QtWidgets.QDialog):
    """Modal provider/key/question picker shown before a review runs."""

    def __init__(self, parent: QtWidgets.QWidget | None, payload_url: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI review")
        self._payload_url = payload_url
        # Set once the FIRST Run hits a key-storage failure (see accept()):
        # that Run stays open so the user can see the warning; a SECOND Run
        # with the same failure proceeds anyway, so a flaky/missing keychain
        # can never trap the user with no way to continue.
        self._store_failed_once = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(f"Review evidence collected for {payload_url}"))
        layout.addLayout(self._build_form())
        layout.addWidget(self.lbl_key_warning)
        layout.addWidget(self.lbl_gemini_help)
        layout.addWidget(QtWidgets.QLabel("Optional question, answered using only this page's collected evidence:"))
        self.question_edit = QtWidgets.QPlainTextEdit()
        layout.addWidget(self.question_edit)
        layout.addWidget(self._build_button_box())
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        self._initialize()

    def _build_form(self) -> QtWidgets.QFormLayout:
        form = QtWidgets.QFormLayout()
        self.combo_provider = QtWidgets.QComboBox()
        for provider, label in PROVIDER_CHOICES:
            self.combo_provider.addItem(label, provider)
        form.addRow("Provider", self.combo_provider)
        self.lbl_key = QtWidgets.QLabel("API key")
        self.edit_key = QtWidgets.QLineEdit()
        self.edit_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow(self.lbl_key, self.edit_key)
        self.edit_model = QtWidgets.QLineEdit()
        form.addRow("Model (optional)", self.edit_model)
        self.lbl_key_warning = QtWidgets.QLabel("")
        self.lbl_key_warning.setWordWrap(True)
        self.lbl_key_warning.hide()
        self.lbl_gemini_help = QtWidgets.QLabel(_GEMINI_HELP_HTML)
        self.lbl_gemini_help.setOpenExternalLinks(True)
        self.lbl_gemini_help.setWordWrap(True)
        return form

    def _build_button_box(self) -> QtWidgets.QDialogButtonBox:
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Run")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        return buttons

    # --- initial state / provider switching ------------------------------
    def _initialize(self) -> None:
        settings = self._app_settings()
        saved_provider = str(settings.value("ai_review/provider", "") or "")
        initial_provider = saved_provider or auto_config().provider
        index = self.combo_provider.findData(initial_provider)
        self.combo_provider.setCurrentIndex(index if index >= 0 else 0)
        saved_model = str(settings.value("ai_review/model", "") or "")
        if saved_model:
            self.edit_model.setText(saved_model)
        self._refresh_for_provider(self._current_provider())

    def _current_provider(self) -> str:
        return str(self.combo_provider.currentData())

    def _on_provider_changed(self, _index: int) -> None:
        self.edit_model.clear()
        self._refresh_for_provider(self._current_provider())

    def _refresh_for_provider(self, provider: str) -> None:
        """Prefill the key from the keychain/env and show/hide the key
        field + Gemini help link for the newly selected provider."""
        is_ollama = provider == "ollama"
        self.edit_key.setText("" if is_ollama else self._load_key(provider))
        self.edit_key.setVisible(not is_ollama)
        self.lbl_key.setVisible(not is_ollama)
        self.lbl_gemini_help.setVisible(provider == "gemini")
        self.edit_model.setPlaceholderText(DEFAULT_MODELS.get(provider, ""))
        self.lbl_key_warning.hide()

    # --- static seams (mirrors CrawlSettingsDialog._load_semrush_key /
    # GoogleConnectDialog's "every keychain/network touch is a bare
    # @staticmethod" convention, so tests can monkeypatch the class
    # attribute directly and never hit a real keychain) -------------------
    @staticmethod
    def _app_settings() -> QtCore.QSettings:
        """Single seam for the app-wide settings store — same shape as
        ``CrawlSettingsDialog._app_settings``; tests substitute a temp-file
        store here instead of touching the platform-native backend."""
        return QtCore.QSettings("Silentfrog", "Silentfrog")

    @staticmethod
    def _load_key(provider: str) -> str:
        from .integrations.ai_engines import resolve_api_key

        try:
            return resolve_api_key(provider)
        except Exception:
            return ""

    @staticmethod
    def _store_key(provider: str, key: str) -> bool:
        try:
            import keyring

            keyring.set_password(_KEYRING_SERVICE, provider, key)
            return True
        except Exception:
            return False

    # --- result -----------------------------------------------------------
    def accept(self) -> None:
        """Persist provider + model to QSettings and a non-empty key to the
        keychain, then close. A key that fails to store is never lost
        silently — it stays in the field and ``config()`` still returns it —
        but the FIRST such failure keeps the dialog OPEN (no
        ``super().accept()``) with a warning telling the user to press Run
        again, so the warning is actually seen instead of flashing past as
        the dialog closes underneath it. A SECOND Run hitting the same
        failure proceeds anyway: persistence failing must never trap the
        user with no way to continue, only warn once."""
        provider = self._current_provider()
        model = self.edit_model.text().strip()
        key = self.edit_key.text().strip()
        if key and not self._store_key(provider, key):
            if not self._store_failed_once:
                self._store_failed_once = True
                self.lbl_key_warning.setText(
                    "Could not store the key in the OS keychain. Press Run again to continue "
                    "anyway — the typed key is still used for this run."
                )
                self.lbl_key_warning.show()
                return
        settings = self._app_settings()
        settings.setValue("ai_review/provider", provider)
        settings.setValue("ai_review/model", model)
        super().accept()

    def config(self) -> AiProviderConfig:
        return AiProviderConfig(
            provider=self._current_provider(),
            api_key=self.edit_key.text().strip(),
            model=self.edit_model.text().strip(),
        )

    def question(self) -> str:
        return self.question_edit.toPlainText()


class _JobHolder:
    """Plain (non-Qt) box a daemon worker writes its result into — copied
    from ``google_connect_dialog._JobHolder``; see this module's docstring
    for why that pattern (not ``QMetaObject.invokeMethod``) is used here."""

    def __init__(self) -> None:
        self.done = False
        self.result: Any = None


def _start_daemon(target: Callable[..., None], *args: Any) -> None:
    """Seam over ``threading.Thread`` so tests can stub the actual
    threading (mirrors ``google_connect_dialog._start_daemon``)."""
    threading.Thread(target=target, args=args, daemon=True).start()


def _review_worker(holder: _JobHolder, client: AiReviewClient, request: AiReviewInput, question: str) -> None:
    """Every concrete ``AiReviewClient`` in this codebase never raises (see
    ``ai_review_providers``'s module docstring), but ``client`` here is a
    Protocol — a caller-supplied stub (tests, or a future client) could
    still raise. Without this guard ``holder.done`` would stay False
    forever and the dialog would spin on "Running AI review..." with no
    error. ``holder.result`` is always set before ``holder.done`` flips, on
    both paths, so a poll never observes done=True with a stale result."""
    try:
        holder.result = client.review(request, question)
    except Exception as exc:  # noqa: BLE001 - a raising client must degrade, never hang the dialog
        config = getattr(client, "config", None)
        provider = getattr(config, "provider", "") or "unknown"
        model = getattr(config, "model", "") or ""
        holder.result = AiReviewResult(provider=provider, model=model, findings=(), raw_summary=f"error: {exc}")
    holder.done = True


_SEVERITY_ORDER = (IssueSeverity.CRITICAL, IssueSeverity.WARNING, IssueSeverity.INFO)
_ERROR_PREFIX = "error:"


def _format_result(result: AiReviewResult) -> str:
    if result.raw_summary.startswith(_ERROR_PREFIX):
        return _format_error(result)
    return _format_findings(result)


def _format_error(result: AiReviewResult) -> str:
    reason = result.raw_summary[len(_ERROR_PREFIX) :].strip()
    remedy = provider_remedy(result.provider)
    return "\n\n".join(["AI review failed", remedy, reason])


def _format_findings(result: AiReviewResult) -> str:
    lines = [result.raw_summary or "(no summary)", ""]
    for severity in _SEVERITY_ORDER:
        lines.extend(_severity_section(result, severity))
    return "\n".join(lines).rstrip()


def _severity_section(result: AiReviewResult, severity: IssueSeverity) -> list[str]:
    group = [finding for finding in result.findings if finding.severity == severity]
    if not group:
        return []
    lines = [f"[{severity.value.upper()}]"]
    for finding in group:
        lines.append(f"{finding.area} — {finding.reason} → {finding.recommendation}")
        lines.extend(f"    {item.label}: {item.value}" for item in finding.evidence)
    lines.append("")
    return lines


class AiReviewResultDialog(QtWidgets.QDialog):
    """Runs ``client.review(request, question)`` on a daemon thread and
    polls for the result via ``_JobHolder`` + ``QTimer`` (see module
    docstring). Renders an error result as a headline + remedy + raw
    reason, or the summary + findings grouped by severity."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        client: AiReviewClient,
        request: AiReviewInput,
        question: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI review result")
        self.resize(560, 420)
        self._client = client
        self._request = request
        self._question = question
        self._holder: _JobHolder | None = None
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self._on_poll_timer)
        layout = QtWidgets.QVBoxLayout(self)
        self.result_edit = QtWidgets.QPlainTextEdit("Running AI review...")
        self.result_edit.setReadOnly(True)
        layout.addWidget(self.result_edit)
        layout.addWidget(self._build_button_box())
        self._start()

    def _build_button_box(self) -> QtWidgets.QDialogButtonBox:
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        self.btn_copy = QtWidgets.QPushButton("Copy")
        self.btn_copy.clicked.connect(self._on_copy)
        buttons.addButton(self.btn_copy, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        close_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.clicked.connect(self.accept)
        return buttons

    def _start(self) -> None:
        holder = _JobHolder()
        self._holder = holder
        _start_daemon(_review_worker, holder, self._client, self._request, self._question)
        self._poll_timer.start()

    def _on_poll_timer(self) -> None:
        holder = self._holder
        if holder is None:
            self._poll_timer.stop()
            return
        if not holder.done:
            return
        self._poll_timer.stop()
        self._holder = None
        self.result_edit.setPlainText(_format_result(holder.result))

    def _on_copy(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.result_edit.toPlainText())

    def done(self, result: int) -> None:
        """Stop the poll timer and drop the job reference before teardown —
        a late-arriving worker write then only ever touches the discarded
        holder, never a Qt widget (see module docstring)."""
        self._poll_timer.stop()
        self._holder = None
        super().done(result)


__all__ = ["AiReviewResultDialog", "AiReviewSetupDialog"]
