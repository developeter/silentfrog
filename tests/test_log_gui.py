from __future__ import annotations

from pathlib import Path

import pytest
from qtpy import QtWidgets

from silentfrog.log_analysis import (  # type: ignore[reportMissingImports]
    LogAnalysisConfig,
    LogAnalysisReport,
    analyse_log_file,
)
from silentfrog.log_gui import LogWindow, LogWorker  # type: ignore[reportMissingImports]

_GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def _line(path: str, status: int, agent: str = _GOOGLEBOT) -> str:
    return f'66.249.66.1 - - [05/May/2026:10:00:00 +0000] "GET {path} HTTP/1.1" {status} 123 "-" "{agent}"'


def _window(qtbot) -> LogWindow:
    window = LogWindow()
    qtbot.addWidget(window)
    return window


def _model_column(model, column: int) -> list[str]:
    return [model.data(model.index(row, column)) for row in range(model.rowCount())]


def test_window_builds(qtbot) -> None:
    window = _window(qtbot)

    assert window.windowTitle()
    assert window.btn_start.isEnabled() is False
    assert window.table.model().rowCount() == 0


def test_selecting_a_log_file_enables_start(qtbot, tmp_path: Path) -> None:
    window = _window(qtbot)
    path = tmp_path / "access.log"
    path.write_text(_line("/page/", 200), encoding="utf-8")

    window.log_path = str(path)
    window._set_controls_enabled(True)

    assert window.btn_start.isEnabled()


def test_a_sample_log_produces_rows(qtbot, tmp_path: Path) -> None:
    """A single Googlebot 500 produces two findings: the blocked-bot
    CRITICAL and the ai_agent_no_activity INFO (no AI hits in the
    sample) — mirrors tests/test_log_analysis.py's own single-line case."""
    path = tmp_path / "access.log"
    path.write_text(_line("/blocked/", 500), encoding="utf-8")
    window = _window(qtbot)
    window.log_path = str(path)

    report = analyse_log_file(path, window._current_config())
    window._on_finish(report)

    model = window.table.model()
    assert model.rowCount() == 2
    assert "CRITICAL" in _model_column(model, 0)
    assert window.btn_start.isEnabled()
    assert window.bar.isVisible() is False


def test_known_urls_file_unlocks_orphan_detection(qtbot, tmp_path: Path) -> None:
    log_path = tmp_path / "access.log"
    log_path.write_text(
        "\n".join([_line("/design/table/", 200), _line("/orphan/", 200)]),
        encoding="utf-8",
    )
    known_path = tmp_path / "known.txt"
    known_path.write_text("https://example.com/design/table/\n", encoding="utf-8")
    window = _window(qtbot)
    window.log_path = str(log_path)
    window.known_urls_path = str(known_path)

    report = analyse_log_file(log_path, window._current_config())
    window._on_finish(report)

    reasons = _model_column(window.table.model(), 1)
    assert any("not in the provided known url set" in reason.lower() for reason in reasons)


def test_without_a_known_urls_file_orphan_detection_stays_off(qtbot, tmp_path: Path) -> None:
    """CLI parity: an omitted --known-urls leaves important_urls == () and
    orphan/important-not-hit findings never fire (log_analysis.py:178-181,
    200-203) — the GUI's default empty known_urls_path must match."""
    log_path = tmp_path / "access.log"
    log_path.write_text(
        "\n".join([_line("/design/table/", 200), _line("/orphan/", 200)]),
        encoding="utf-8",
    )
    window = _window(qtbot)
    window.log_path = str(log_path)

    report = analyse_log_file(log_path, window._current_config())
    window._on_finish(report)

    reasons = _model_column(window.table.model(), 1)
    assert not any("orphan" in reason.lower() for reason in reasons)


def test_a_failed_analysis_leaves_the_window_usable(qtbot, tmp_path: Path) -> None:
    """Regression guard: the window must never be left 'running forever' —
    controls are re-enabled even when the worker reports failure (None)."""
    window = _window(qtbot)
    window.log_path = str(tmp_path / "missing.log")
    window._set_controls_enabled(False)
    window.bar.setVisible(True)

    window._on_finish(None)

    assert window.btn_start.isEnabled()
    assert window.btn_file.isEnabled()
    assert window.bar.isVisible() is False
    assert window.table.model().rowCount() == 0


def test_a_vanished_known_urls_file_does_not_strand_the_window(
    qtbot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression guard: ``_current_config()`` reads known_urls_path
    synchronously in ``_launch()``, on the GUI thread, before the worker
    even exists. If that file vanishes between picking it and clicking
    Analyse, ``_launch()`` must not let the read raise past it — without
    the try/except, ``_set_controls_enabled(False)``/``bar.setVisible(True)``
    already ran, so the window is stranded 'busy' forever with no worker
    and no message to the user; with the fix it degrades exactly like a
    bad log file does (see test_a_failed_analysis_leaves_the_window_usable)."""
    warnings: list[str] = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    log_path = tmp_path / "access.log"
    log_path.write_text(_line("/page/", 200), encoding="utf-8")
    known_path = tmp_path / "known.txt"
    known_path.write_text("https://example.com/page/\n", encoding="utf-8")
    window = _window(qtbot)
    window.log_path = str(log_path)
    window.known_urls_path = str(known_path)
    window._set_controls_enabled(True)
    known_path.unlink()  # vanished after picking, before Analyse

    window.btn_start.click()

    # Reintroduce the bug (drop the try/except in _launch) and these first
    # two assertions are what break: the controls stay disabled forever
    # because _on_finish(None)/_set_controls_enabled(True) never run.
    assert window.btn_start.isEnabled() is True
    assert window.bar.isVisible() is False
    assert window.worker is None  # never launched: no thread left running
    assert warnings  # user was told, unlike the pre-fix silent stall


def test_worker_handles_an_empty_file_without_raising(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.write_text("", encoding="utf-8")
    worker = LogWorker(str(path), LogAnalysisConfig())
    results: list[object] = []
    failures: list[str] = []
    worker.completed.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run()  # synchronous call: exercises LogWorker.run() with no real thread

    assert failures == []
    assert len(results) == 1
    assert isinstance(results[0], LogAnalysisReport)
    assert results[0].total_requests == 0


def test_worker_handles_a_garbage_file_without_raising(qtbot, tmp_path: Path) -> None:
    path = tmp_path / "garbage.log"
    path.write_text("not a log line\nneither is this one", encoding="utf-8")
    worker = LogWorker(str(path), LogAnalysisConfig())
    results: list[object] = []
    failures: list[str] = []
    worker.completed.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == []
    assert isinstance(results[0], LogAnalysisReport)
    assert results[0].total_requests == 0


def test_worker_emits_failed_and_completed_none_for_a_missing_file(qtbot, tmp_path: Path) -> None:
    worker = LogWorker(str(tmp_path / "does-not-exist.log"), LogAnalysisConfig())
    results: list[object] = []
    failures: list[str] = []
    worker.completed.connect(results.append)
    worker.failed.connect(failures.append)

    worker.run()  # would raise FileNotFoundError uncaught if the try/except were dropped

    assert len(failures) == 1
    assert results == [None]
