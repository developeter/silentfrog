"""PR-D — AiReviewSetupDialog / AiReviewResultDialog (ai_review_dialog.py).

Every test stubs the dialog's bare seams (``_load_key``, ``_store_key``,
``_app_settings``, and module-level ``auto_config``) so nothing touches the
real OS keychain or QSettings backend — mirrors
tests/test_tech_stack_unit.py's ``CrawlSettingsDialog._app_settings``
stubbing. Result-dialog background work is made synchronous by stubbing
``ai_review_dialog._start_daemon`` (same convention as
tests/test_google_settings_gui.py stubbing ``google_connect_dialog._start_daemon``)
instead of waiting on a real thread/timer.
"""

from __future__ import annotations

from qtpy import QtCore, QtWidgets

from silentfrog import ai_review_dialog
from silentfrog.ai_review import (
    AiProviderConfig,
    AiReviewEvidence,
    AiReviewFinding,
    AiReviewInput,
    AiReviewResult,
    StaticAiReviewClient,
)
from silentfrog.ai_review_dialog import AiReviewResultDialog, AiReviewSetupDialog
from silentfrog.audit_issues import IssueSeverity


def _stub_dialog_seams(
    monkeypatch,
    tmp_path,
    *,
    provider: str = "ollama",
    store_returns: bool = True,
    store_calls: list | None = None,
    load_key_returns: str = "",
) -> None:
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        AiReviewSetupDialog,
        "_app_settings",
        staticmethod(lambda: QtCore.QSettings(ini, QtCore.QSettings.IniFormat)),
    )
    monkeypatch.setattr(AiReviewSetupDialog, "_load_key", staticmethod(lambda _p: load_key_returns))

    def _fake_store(engine: str, key: str) -> bool:
        if store_calls is not None:
            store_calls.append((engine, key))
        return store_returns

    monkeypatch.setattr(AiReviewSetupDialog, "_store_key", staticmethod(_fake_store))
    monkeypatch.setattr(
        "silentfrog.ai_review_dialog.auto_config",
        lambda preferred=None: AiProviderConfig(provider=provider, api_key=""),
    )


def _request() -> AiReviewInput:
    return AiReviewInput(
        target="https://example.com/page",
        scope="page",
        issues=(),
        context=(AiReviewEvidence("Title", "Example"),),
    )


class _RaisingClient:
    """A caller-supplied AiReviewClient stub whose review() raises — every
    concrete client in ai_review_providers.py never raises, but the
    Protocol doesn't guarantee that for every future/test client."""

    def __init__(self, config: AiProviderConfig) -> None:
        self.config = config

    def review(self, request: AiReviewInput, custom_instructions: str = "") -> AiReviewResult:
        raise RuntimeError("boom")


# --- AiReviewSetupDialog ------------------------------------------------


def test_provider_preselection_prefers_saved_then_auto_config(qtbot, monkeypatch, tmp_path) -> None:
    _stub_dialog_seams(monkeypatch, tmp_path, provider="anthropic")
    dialog = AiReviewSetupDialog(None, "https://example.com/page")
    qtbot.addWidget(dialog)
    assert dialog.combo_provider.currentData() == "anthropic"  # no saved value -> auto_config()

    dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("gemini"))
    dialog.accept()  # persists provider=gemini to the shared temp ini

    dialog2 = AiReviewSetupDialog(None, "https://example.com/page")
    qtbot.addWidget(dialog2)
    assert dialog2.combo_provider.currentData() == "gemini"  # saved value wins over auto_config()


def test_key_field_hidden_for_ollama_shown_for_gemini(qtbot, monkeypatch, tmp_path) -> None:
    _stub_dialog_seams(monkeypatch, tmp_path, provider="ollama", load_key_returns="prefilled-key")
    dialog = AiReviewSetupDialog(None, "https://example.com/page")
    qtbot.addWidget(dialog)

    assert dialog.combo_provider.currentData() == "ollama"
    assert dialog.edit_key.isHidden()
    assert dialog.lbl_gemini_help.isHidden()

    dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("gemini"))

    assert not dialog.edit_key.isHidden()
    assert not dialog.lbl_gemini_help.isHidden()
    assert dialog.edit_key.text() == "prefilled-key"  # re-prefilled on provider switch


def test_run_persists_provider_model_and_key_through_the_seams(qtbot, monkeypatch, tmp_path) -> None:
    store_calls: list[tuple[str, str]] = []
    _stub_dialog_seams(monkeypatch, tmp_path, provider="ollama", store_calls=store_calls)
    dialog = AiReviewSetupDialog(None, "https://example.com/page")
    qtbot.addWidget(dialog)
    dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("gemini"))
    dialog.edit_key.setText("typed-key")
    dialog.edit_model.setText("gemini-1.5-pro")

    dialog.accept()

    settings = dialog._app_settings()
    assert settings.value("ai_review/provider") == "gemini"
    assert settings.value("ai_review/model") == "gemini-1.5-pro"
    assert store_calls == [("gemini", "typed-key")]
    config = dialog.config()
    assert config.provider == "gemini"
    assert config.api_key == "typed-key"
    assert config.model == "gemini-1.5-pro"


def test_run_store_failure_keeps_dialog_open_then_second_run_accepts(qtbot, monkeypatch, tmp_path) -> None:
    # The warning must actually be SEEN, not flash past as the dialog closes
    # underneath it -- show() + waitExposed() so isVisible() is meaningful
    # (a never-shown widget always reports isVisible() False regardless of
    # setVisible(), per tests/test_site_crawl_history_gui.py's isHidden note).
    _stub_dialog_seams(monkeypatch, tmp_path, provider="ollama", store_returns=False)
    dialog = AiReviewSetupDialog(None, "https://example.com/page")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.combo_provider.setCurrentIndex(dialog.combo_provider.findData("gemini"))
    dialog.edit_key.setText("typed-key")

    dialog.accept()  # first Run: storage fails -> stays open with the warning

    assert dialog.lbl_key_warning.isVisible()
    assert "keychain" in dialog.lbl_key_warning.text().lower()
    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert dialog.config().api_key == "typed-key"  # never lost, even though storage failed

    dialog.accept()  # second Run: same failure, but must proceed anyway

    assert dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert dialog.config().api_key == "typed-key"


# --- AiReviewResultDialog ------------------------------------------------


def test_result_dialog_shows_remedy_for_error_result(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(ai_review_dialog, "_start_daemon", lambda target, *args: target(*args))
    result = AiReviewResult(
        provider="ollama",
        model="llama3.2",
        findings=(),
        raw_summary="error: connection refused / not reachable at http://localhost:11434",
    )
    dialog = AiReviewResultDialog(None, StaticAiReviewClient(result), _request(), "")
    qtbot.addWidget(dialog)
    dialog._on_poll_timer()  # the stubbed worker already finished

    text = dialog.result_edit.toPlainText()
    assert "AI review failed" in text
    assert "Ollama is not reachable" in text  # provider_remedy
    assert "connection refused / not reachable at http://localhost:11434" in text  # raw reason


def test_result_dialog_groups_findings_by_severity(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(ai_review_dialog, "_start_daemon", lambda target, *args: target(*args))
    findings = (
        AiReviewFinding(
            finding_id="a",
            severity=IssueSeverity.CRITICAL,
            area="Area1",
            reason="R1",
            recommendation="Rec1",
            evidence=(AiReviewEvidence("Ev", "V"),),
        ),
        AiReviewFinding(
            finding_id="b",
            severity=IssueSeverity.INFO,
            area="Area2",
            reason="R2",
            recommendation="Rec2",
            evidence=(),
        ),
    )
    result = AiReviewResult(
        provider="gemini", model="gemini-2.5-flash", findings=findings, raw_summary="Two opportunities."
    )
    dialog = AiReviewResultDialog(None, StaticAiReviewClient(result), _request(), "")
    qtbot.addWidget(dialog)
    dialog._on_poll_timer()

    text = dialog.result_edit.toPlainText()
    assert "Two opportunities." in text
    assert "[CRITICAL]" in text
    assert "[INFO]" in text
    assert text.index("[CRITICAL]") < text.index("[INFO]")  # severity order preserved
    assert "Area1" in text and "Rec1" in text
    assert "Ev: V" in text


def test_closing_before_completion_stops_timer_and_ignores_late_write(qtbot, monkeypatch) -> None:
    started: dict[str, object] = {}

    def _fake_start_daemon(target, *args) -> None:
        started["target"] = target
        started["args"] = args  # do not run -- simulate a still-running worker

    monkeypatch.setattr(ai_review_dialog, "_start_daemon", _fake_start_daemon)
    result = AiReviewResult(provider="ollama", model="llama3.2", findings=(), raw_summary="ok")
    dialog = AiReviewResultDialog(None, StaticAiReviewClient(result), _request(), "")
    qtbot.addWidget(dialog)

    assert dialog._poll_timer.isActive()
    holder_before_close = dialog._holder
    assert holder_before_close is not None

    dialog.done(QtWidgets.QDialog.DialogCode.Rejected)

    assert not dialog._poll_timer.isActive()
    assert dialog._holder is None

    started["target"](*started["args"])  # the orphaned worker finishes late

    assert holder_before_close.done is True  # it wrote into the discarded holder...
    assert dialog._holder is None  # ...which the dialog never reads again
    assert "Running AI review" in dialog.result_edit.toPlainText()  # untouched


def test_review_worker_client_exception_renders_error_instead_of_hanging(qtbot, monkeypatch) -> None:
    # Without the worker's try/except, holder.done stays False forever and
    # the dialog spins on "Running AI review..." with no error shown.
    monkeypatch.setattr(ai_review_dialog, "_start_daemon", lambda target, *args: target(*args))
    client = _RaisingClient(AiProviderConfig(provider="ollama", api_key=""))
    dialog = AiReviewResultDialog(None, client, _request(), "")
    qtbot.addWidget(dialog)

    dialog._on_poll_timer()  # the stubbed worker already ran (and raised)

    text = dialog.result_edit.toPlainText()
    assert "AI review failed" in text
    assert "boom" in text
    assert not dialog._poll_timer.isActive()
