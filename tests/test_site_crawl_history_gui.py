from __future__ import annotations

import json
from pathlib import Path

from qtpy import QtCore, QtWidgets

from silentfrog.audit_issues import IssueCategory, IssueSeverity  # type: ignore[reportMissingImports]
from silentfrog.crawl_history import (  # type: ignore[reportMissingImports]
    CrawlHistoryIssue,
    CrawlHistoryRun,
    CrawlHistoryStore,
)
from silentfrog.site_crawl_history_gui import CrawlHistoryDialog  # type: ignore[reportMissingImports]


def _issue(issue_id: str, severity: IssueSeverity, url: str) -> CrawlHistoryIssue:
    return CrawlHistoryIssue(
        issue_id=issue_id,
        severity=severity,
        category=IssueCategory.META,
        url=url,
        reason=f"{issue_id} reason",
        recommendation="Fix it.",
        source="Meta",
        confidence="high",
    )


def _run(run_id: str, created_at: str, issues: tuple[CrawlHistoryIssue, ...]) -> CrawlHistoryRun:
    return CrawlHistoryRun(
        run_id=run_id,
        created_at=created_at,
        scope_key="example.com",
        discovered_count=5,
        crawled_count=4,
        failed_count=1,
        skipped_count=0,
        issues=issues,
    )


def _store_with_runs(tmp_path: Path) -> CrawlHistoryStore:
    store = CrawlHistoryStore(tmp_path)
    store.save_run(
        _run(
            "run-1",
            "2026-01-01T00:00:00Z",
            (_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/old"),),
        )
    )
    store.save_run(
        _run(
            "run-2",
            "2026-01-02T00:00:00Z",
            (_issue("meta.description_missing", IssueSeverity.CRITICAL, "https://example.com/new"),),
        )
    )
    return store


def test_history_dialog_lists_runs_and_shows_previous_diff(qtbot, tmp_path: Path) -> None:
    dialog = CrawlHistoryDialog(_store_with_runs(tmp_path))
    qtbot.addWidget(dialog)

    assert dialog.model.rowCount() == 2
    assert dialog.model.index(0, 0).data() == "example.com"
    assert dialog.model.index(0, 7).data() == "run-2"
    assert "Diff from previous run" in dialog.details.toPlainText()
    assert "- 1 new issues" in dialog.details.toPlainText()
    assert "- 1 fixed issues" in dialog.details.toPlainText()


def test_history_dialog_exports_selected_run_json(monkeypatch, qtbot, tmp_path: Path) -> None:
    target = tmp_path / "selected-run.json"
    dialog = CrawlHistoryDialog(_store_with_runs(tmp_path / "history"))
    qtbot.addWidget(dialog)

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    qtbot.mouseClick(dialog.btn_export, QtCore.Qt.MouseButton.LeftButton)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["run_id"] == "run-2"
    assert data["scope_key"] == "example.com"


def test_history_dialog_deletes_selected_local_run(monkeypatch, qtbot, tmp_path: Path) -> None:
    store = _store_with_runs(tmp_path)
    dialog = CrawlHistoryDialog(store)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    qtbot.mouseClick(dialog.btn_delete, QtCore.Qt.MouseButton.LeftButton)

    assert [run.run_id for run in store.load_runs()] == ["run-1"]
    assert dialog.model.rowCount() == 1
