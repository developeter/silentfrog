from __future__ import annotations

from qtpy import QtCore

from silentfrog.audit_issues import (  # type: ignore[reportMissingImports]
    AuditIssue,
    IssueCategory,
    IssueEvidence,
    IssueSeverity,
)
from silentfrog.audit_recap import AuditRecapWidget, summarize_issues  # type: ignore[reportMissingImports]


def _issue(severity: IssueSeverity, url: str = "https://example.com/page") -> AuditIssue:
    return AuditIssue(
        issue_id=f"test.{severity.value}",
        category=IssueCategory.META,
        severity=severity,
        source="Meta",
        reason=f"{severity.value} issue",
        recommendation="Fix the issue.",
        evidence=(IssueEvidence("Evidence", "value"),),
        url=url,
    )


def test_summarize_issues_uses_conservative_counts() -> None:
    summary = summarize_issues(
        [
            _issue(IssueSeverity.CRITICAL, "https://example.com/a"),
            _issue(IssueSeverity.WARNING, "https://example.com/b"),
            _issue(IssueSeverity.INFO, "https://example.com/b"),
        ],
        item_count=2,
    )

    assert summary.health == "Needs attention"
    assert summary.critical == 1
    assert summary.warnings == 1
    assert summary.info == 1
    assert summary.affected_urls == 2


def test_recap_widget_renders_counts_and_emits_issue(qtbot) -> None:
    widget = AuditRecapWidget("Page recap")
    qtbot.addWidget(widget)
    issue = _issue(IssueSeverity.WARNING)
    emitted: list[AuditIssue] = []
    widget.issueActivated.connect(emitted.append)

    widget.update_issues([issue], item_count=1, item_label="page")
    item = widget.action_list.item(0)
    widget.action_list.itemActivated.emit(item)

    assert "Warnings found" in widget.health_text()
    assert widget.count_text(IssueSeverity.WARNING) == "Warnings: 1"
    assert item.data(QtCore.Qt.ItemDataRole.UserRole) == issue
    assert emitted == [issue]
