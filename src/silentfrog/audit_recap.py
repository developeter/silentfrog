from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html import escape

from qtpy import QtCore, QtGui, QtWidgets

from .audit_issues import AuditIssue, IssueSeverity, severity_color_role
from .hints import Hint, build_hints
from .theme import current_theme


@dataclass(frozen=True, slots=True)
class AuditRecapSummary:
    total: int
    critical: int
    warnings: int
    info: int
    affected_urls: int
    health: str
    detail: str


def summarize_issues(issues: Iterable[AuditIssue], item_count: int = 1) -> AuditRecapSummary:
    rows = list(issues)
    critical = _count_severity(rows, IssueSeverity.CRITICAL)
    warnings = _count_severity(rows, IssueSeverity.WARNING)
    info = _count_severity(rows, IssueSeverity.INFO)
    health = _health_label(critical, warnings)
    affected_urls = len({issue.url for issue in rows if issue.url})
    detail = _health_detail(critical, warnings, info, affected_urls, item_count)
    return AuditRecapSummary(
        total=len(rows),
        critical=critical,
        warnings=warnings,
        info=info,
        affected_urls=affected_urls,
        health=health,
        detail=detail,
    )


class AuditRecapWidget(QtWidgets.QFrame):
    issueActivated = QtCore.Signal(object)

    def __init__(self, title: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("auditRecap")
        self._issues: list[AuditIssue] = []
        self._hints: list[Hint] = []
        self._item_count: int = 1
        self._build_ui(title)
        self.reset()

    def reset(self, text: str = "Run an analysis to build the action recap.") -> None:
        self._issues = []
        self._hints = []
        self._item_count = 1
        self._set_health("Ready", text)
        self._set_counts(0, 0, 0)
        self.action_list.clear()
        self.action_list.addItem("No recap data yet.")

    def update_issues(
        self,
        issues: Iterable[AuditIssue],
        *,
        item_count: int = 1,
        item_label: str = "page",
    ) -> None:
        self._issues = list(issues)
        self._hints = build_hints(self._issues)
        self._item_count = item_count
        summary = summarize_issues(self._issues, item_count=item_count)
        self._set_health(summary.health, _summary_text(summary, item_label))
        self._set_counts(summary.critical, summary.warnings, summary.info)
        self._render_actions()

    def health_text(self) -> str:
        return self.health_label.text()

    def count_text(self, severity: IssueSeverity) -> str:
        labels = {
            IssueSeverity.CRITICAL: self.critical_count,
            IssueSeverity.WARNING: self.warning_count,
            IssueSeverity.INFO: self.info_count,
        }
        return labels[severity].text()

    def _build_ui(self, title: str) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.health_label = QtWidgets.QLabel()
        self.health_label.setWordWrap(True)
        layout.addWidget(self.health_label)
        layout.addLayout(self._build_count_row())

        self.action_list = QtWidgets.QListWidget()
        self.action_list.setAlternatingRowColors(True)
        self.action_list.itemActivated.connect(self._emit_issue)
        self.action_list.itemDoubleClicked.connect(self._emit_issue)
        layout.addWidget(self.action_list)
        self._apply_frame_style()

    def _build_count_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        self.critical_count = self._count_label("Critical", IssueSeverity.CRITICAL)
        self.warning_count = self._count_label("Warnings", IssueSeverity.WARNING)
        self.info_count = self._count_label("Opportunities", IssueSeverity.INFO)
        row.addWidget(self.critical_count)
        row.addWidget(self.warning_count)
        row.addWidget(self.info_count)
        row.addStretch()
        return row

    def _count_label(self, label: str, severity: IssueSeverity) -> QtWidgets.QLabel:
        widget = QtWidgets.QLabel(f"{label}: 0")
        widget.setProperty("severity", severity.value)
        widget.setStyleSheet(_count_style(severity))
        return widget

    def _set_health(self, title: str, detail: str) -> None:
        self.health_label.setText(f"<b>{escape(title)}</b><br>{escape(detail)}")

    def _set_counts(self, critical: int, warnings: int, info: int) -> None:
        self.critical_count.setText(f"Critical: {critical}")
        self.warning_count.setText(f"Warnings: {warnings}")
        self.info_count.setText(f"Opportunities: {info}")

    def _render_actions(self) -> None:
        self.action_list.clear()
        if not self._hints:
            self.action_list.addItem("No prioritized issues detected.")
            return
        # Grouped, priority-ranked hints (G1): one row per issue type with its
        # prevalence, so a site crawl reads as "fix this first, it hits N pages"
        # instead of a flat wall of per-URL rows.
        for hint in self._hints[:8]:
            self.action_list.addItem(self._hint_item(hint))

    def _hint_item(self, hint: Hint) -> QtWidgets.QListWidgetItem:
        prefix = hint.severity.value.upper()
        item = QtWidgets.QListWidgetItem(f"{prefix}: {hint.headline(self._item_count)}")
        item.setData(QtCore.Qt.ItemDataRole.UserRole, hint)
        sample = f"\nExample: {hint.sample_urls[0]}" if hint.sample_urls else ""
        item.setToolTip(f"{hint.recommendation}{sample}")
        item.setForeground(QtGui.QBrush(QtGui.QColor(_severity_text_color(hint.severity))))
        return item

    def _emit_issue(self, item: QtWidgets.QListWidgetItem) -> None:
        hint = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(hint, Hint):
            return
        # Deep-link to the first affected URL by re-emitting its backing issue,
        # so the existing "jump to the page" wiring keeps working.
        target_url = hint.sample_urls[0] if hint.sample_urls else ""
        for issue in self._issues:
            if issue.issue_id == hint.issue_id and issue.url == target_url:
                self.issueActivated.emit(issue)
                return
        matches = [issue for issue in self._issues if issue.issue_id == hint.issue_id]
        if matches:
            self.issueActivated.emit(matches[0])

    def _apply_frame_style(self) -> None:
        border = "#3a3a3a" if current_theme() == "dark" else "#c8cdd2"
        self.setStyleSheet(f"#auditRecap {{ border: 1px solid {border}; border-radius: 8px; padding: 8px;}}")


def _count_severity(issues: Iterable[AuditIssue], severity: IssueSeverity) -> int:
    return sum(1 for issue in issues if issue.severity == severity)


def _health_label(critical: int, warnings: int) -> str:
    if critical:
        return "Needs attention"
    if warnings:
        return "Warnings found"
    return "Healthy"


def _health_detail(critical: int, warnings: int, info: int, affected_urls: int, item_count: int) -> str:
    parts = [
        f"{critical} critical",
        f"{warnings} warnings",
        f"{info} opportunities",
    ]
    if item_count > 1:
        parts.append(f"{affected_urls} affected URLs")
    return ", ".join(parts)


def _summary_text(summary: AuditRecapSummary, item_label: str) -> str:
    if summary.total:
        return f"{summary.detail}. Review the next actions below and open details for evidence."
    return f"No prioritized issues found for this {item_label}."


def _count_style(severity: IssueSeverity) -> str:
    return f"font-weight: 600; padding: 5px 8px; border-radius: 5px; color: {_severity_text_color(severity)};"


def _severity_text_color(severity: IssueSeverity) -> str:
    role = severity_color_role(severity)
    colors = {
        "bad": "#ef5350",
        "warn": "#d99a00",
        "info": "#5a8fd8",
    }
    return colors[role]


__all__ = ["AuditRecapSummary", "AuditRecapWidget", "summarize_issues"]
