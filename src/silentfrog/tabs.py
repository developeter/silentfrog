from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, cast
import sys

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor
from .crawl_types import KeywordEntry, StructuredDataPayload, PerformanceMetrics
from .models import (
    MetaModel,
    ImagesModel,
    RobotsModel,
    CanonicalModel,
    RedirectModel,
    HreflangModel,
    SerpAuditModel,
    HeaderModel,
    LinksModel,
    GenericModel,
    KeywordModel,
)

import html as _html
import json


def _header(view: QtWidgets.QTableView) -> QtWidgets.QHeaderView:
    return cast(QtWidgets.QHeaderView, view.horizontalHeader())


def _is_dark(widget: QtWidgets.QWidget) -> bool:
    app = QtWidgets.QApplication.instance()
    if isinstance(app, QtWidgets.QApplication):
        theme = app.property("silentfrog_theme")
        if theme in {"dark", "light"}:
            return theme == "dark"
    base = widget.palette().color(QPalette.Base)
    return base.isValid() and base.value() < 128


class TableTab(QtWidgets.QWidget):
    def __init__(self, sorting: bool = True, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._table = QtWidgets.QTableView()
        self._table.setSortingEnabled(sorting)
        self._table.setViewportMargins(0, 0, 18, 18)
        self._table.setStyleSheet("QTableView { padding-right: 18px; padding-bottom: 18px; }")
        self._layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout(self)
        if sys.platform == "darwin":
            fusion = QtWidgets.QStyleFactory.create("Fusion")
            if fusion:
                self._table.setStyle(fusion)
            self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        else:
            self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._table)
        self._model: QtCore.QAbstractTableModel | None = None

    @property
    def view(self) -> QtWidgets.QTableView:
        return self._table

    def set_model(self, model: QtCore.QAbstractTableModel) -> None:
        self._model = model
        was_sorted = self._table.isSortingEnabled()
        self._table.setSortingEnabled(False)
        self._table.setModel(model)
        model.layoutChanged.emit()
        self._table.resizeColumnsToContents()
        self._table.setSortingEnabled(was_sorted)


class MetaTab(TableTab):
    def update(self, rows: List[List[str]]) -> None:
        self.set_model(MetaModel(rows))

    def clear(self) -> None:
        self.set_model(MetaModel([], add_placeholders=False))


class HeadersTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)

    def update(self, rows: List[List[str]], title: str | None = None) -> None:
        self.set_model(HeaderModel(rows, title))


class ImagesTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._rows: List[List[str]] = []

    def update(self, rows: List[List[str]]) -> None:
        if rows and len(rows[0]) == 5 and self._rows:
            updates = {row[0]: row for row in rows}
            merged: List[List[str]] = []
            for current in self._rows:
                url = current[0]
                update = updates.get(url)
                if update:
                    _, width, height, human, mime = update
                    if mime and mime != "-":
                        current[3] = mime
                    current[4] = str(width) if width else current[4]
                    current[5] = str(height) if height else current[5]
                    current[6] = human or current[6]
                merged.append(list(current))
            rows = merged
        else:
            rows = [list(row) for row in rows]
        self._rows = rows
        model = ImagesModel(self._rows)
        self.set_model(model)
        _header(self.view).setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
        self.view.setColumnWidth(0, 280)

    def rows(self) -> List[List[str]]:
        return [list(row) for row in self._rows]


class LinksTab(TableTab):
    def update(self, rows: List[List[str]]) -> None:
        self.set_model(LinksModel(rows))
        self.view.setAlternatingRowColors(False)
        _header(self.view).setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)


class RedirectTab(TableTab):
    def update(self, data: Dict[str, object]) -> None:
        chain_raw = data.get("chain", [])
        chain_list: List[str] = []
        if isinstance(chain_raw, list):
            chain_list = [str(item) for item in chain_raw]
        elif chain_raw:
            chain_list = [str(chain_raw)]
        chain = " → ".join(chain_list)
        rows = [
            ["Redirect chain", chain or ""],
            ["Hop count", str(data.get("hops", ""))],
            ["Final status", data.get("final_status", "")],
            ["Loop detected", "Yes" if data.get("loop") else "No"],
        ]
        self.set_model(RedirectModel(["Check", "Value"], rows))
        _header(self.view).setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)


class CanonicalTab(TableTab):
    def update(self, data: Dict[str, object]) -> None:
        rows = [
            ["Canonical URL", data.get("target", "") or ""],
            ["Self-referencing", "Yes" if data.get("self") else "No"],
            ["Multiple canonicals", "Yes" if data.get("multiple") else "No"],
            ["Canonical status", data.get("status", "") or ""],
        ]
        self.set_model(CanonicalModel(["Check", "Value"], rows))


class RobotsTab(TableTab):
    def update(self, meta_robots: str, robots_map: Dict[str, List[tuple[str, str]]]) -> None:
        rows: List[List[str]] = [["Meta / X-Robots-Tag", meta_robots or ""], ["", ""]]
        for agent, directives in robots_map.items():
            rows.append([f"User-Agent: {agent}", ""])
            rows.extend([[verb, path] for verb, path in directives])
        if not robots_map:
            rows.append(["robots.txt", "Not fetched or empty"])
        self.set_model(RobotsModel(["Directive", "Value"], rows))
        _header(self.view).setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)


class HreflangTab(TableTab):
    def update(self, rows: List[List[str]]) -> None:
        headers = ["Lang", "Target URL", "Status", "Lang-OK?", "Return?"]
        self.set_model(HreflangModel(headers, rows))
        _header(self.view).setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)


class AiTab(TableTab):
    def update(self, rows: List[List[str]]) -> None:
        headers = ["Agent", "Robots.txt OK", "Meta noai?", "Verdict"]
        self.set_model(GenericModel(headers, rows))
        _header(self.view).setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        _header(self.view).setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)


class KeywordsTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._summary = QtWidgets.QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._entries: List[KeywordEntry] = []
        self._applying_palette = False
        self._layout.insertWidget(0, self._summary)

    def update(self, rows: List[object]) -> None:
        entries: List[KeywordEntry] = []
        for item in rows:
            if isinstance(item, KeywordEntry):
                entries.append(item)
            elif isinstance(item, dict):
                entries.append(KeywordEntry.from_raw(item))
        self._entries = entries
        self._summary.setText(self._summary_text(self._entries))
        model = KeywordModel(entries)
        self.set_model(model)
        self.view.setAlternatingRowColors(True)
        header = _header(self.view)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, model.columnCount()):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeToContents)
        self._apply_palette()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            if self._applying_palette:
                super().changeEvent(event)
                return
            self._summary.setText(self._summary_text(self._entries))
            self._apply_palette()
        super().changeEvent(event)

    def _apply_palette(self) -> None:
        if self._applying_palette:
            return
        self._applying_palette = True
        try:
            is_dark = _is_dark(self)
            summary_color = "#f0f0f0" if is_dark else "#202124"
            self._summary.setStyleSheet(f"color:{summary_color}; margin:4px 0;")
            if is_dark:
                table_stylesheet = (
                    "QTableView {"
                    "background-color:#1e1e1e;"
                    "color:#f0f0f0;"
                    "gridline-color:#444444;"
                    "alternate-background-color:#2b2b2b;"
                    "selection-background-color:#31475b;"
                    "selection-color:#ffffff;"
                    "}"
                    "QHeaderView::section {"
                    "background-color:#2b2b2b;"
                    "color:#f0f0f0;"
                    "}"
                )
            else:
                table_stylesheet = (
                    "QTableView {"
                    "background-color:#ffffff;"
                    "color:#202124;"
                    "gridline-color:#d0d4da;"
                    "alternate-background-color:#f5f7fa;"
                    "selection-background-color:#dbeafe;"
                    "selection-color:#202124;"
                    "}"
                    "QHeaderView::section {"
                    "background-color:#f0f2f5;"
                    "color:#202124;"
                    "}"
                )
            self.view.setStyleSheet(table_stylesheet)
        finally:
            self._applying_palette = False

    def _summary_text(self, entries: List[KeywordEntry]) -> str:
        if not entries:
            return "<span style='color:#c62828;font-weight:bold'>No keywords extracted.</span>"
        top_terms = [entry.term for entry in entries if entry.length == 1][:3]
        dominant = ", ".join(top_terms) if top_terms else "n/a"
        title_hits = sum(1 for entry in entries if entry.in_title)
        heading_coverage = sum(1 for entry in entries if entry.heading_count > 0)
        threshold = max((entry.density_threshold for entry in entries), default=4.0)
        high_density = [entry for entry in entries if entry.density_warning]
        alerts = ""
        if high_density and threshold > 0:
            flagged = ", ".join(entry.term for entry in high_density[:3])
            alerts = (
                f"<br><span style='color:#b26a00'>High density (&gt;{threshold:.2f}%): "
                f"{flagged} ({len(high_density)} flagged)</span>"
            )
        return (
            "<b>Top focus keywords:</b> {dominant}<br>"
            "<b>Terms in title:</b> {title_hits} &nbsp; "
            "<b>Heading coverage:</b> {heading_coverage}"
            "{alerts}"
        ).format(
            dominant=_html.escape(dominant),
            title_hits=title_hits,
            heading_coverage=heading_coverage,
            alerts=alerts,
        )


class PerformanceTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._summary = QtWidgets.QLabel()
        self._summary.setWordWrap(True)
        self._summary.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._opportunities = QtWidgets.QLabel()
        self._opportunities.setWordWrap(True)
        self._opportunities.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._scripts = QtWidgets.QLabel()
        self._scripts.setWordWrap(True)
        self._scripts.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._offender_view: QtWidgets.QTableView = QtWidgets.QTableView()
        self._offender_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._offender_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._offender_view.setSortingEnabled(True)
        self._offender_view.setAlternatingRowColors(True)
        self._current_metrics = PerformanceMetrics.empty()
        self._is_rendering = False
        self._layout.insertWidget(0, self._summary)
        self._layout.insertWidget(1, self._scripts)
        self._layout.addWidget(self._opportunities)
        self._layout.addWidget(self._offender_view)

    def update(self, data: object) -> None:
        metrics = PerformanceMetrics.empty()
        if isinstance(data, PerformanceMetrics):
            metrics = data
        elif isinstance(data, dict):
            metrics = PerformanceMetrics.from_raw(data)
        self._current_metrics = metrics
        self._render(metrics)

    def _render(self, metrics: PerformanceMetrics) -> None:

        if self._is_rendering:

            return

        self._is_rendering = True

        try:

            total_bytes = metrics.transfer_size + sum(

                info.get("bytes", 0) for info in metrics.resource_summary.values()

            )

            transfer_text = self._format_bytes(metrics.transfer_size)

            weight_text = self._format_bytes(total_bytes)

            summary_html = (

                f"<b>Status:</b> {metrics.status or '-'} &nbsp; "

                f"<b>TTFB:</b> {metrics.nav_ttfb_ms:.0f} ms &nbsp; "

                f"<b>Total:</b> {metrics.nav_total_ms:.0f} ms &nbsp; "

                f"<b>Transfer:</b> {transfer_text} &nbsp; "

                f"<b>Page weight:</b> {weight_text}"

            )

            self._summary.setText(summary_html)



            script_html = (

                f"<b>Blocking JS:</b> {metrics.scripts.blocking_count} "

                f"({self._format_bytes(metrics.scripts.blocking_bytes)}) &nbsp; "

                f"<b>Async/Deferred JS:</b> {metrics.scripts.async_count} "

                f"({self._format_bytes(metrics.scripts.async_bytes)})"

            )

            self._scripts.setText(script_html)



            severity_order = {"critical": 3, "warning": 2, "info": 1, "ok": 0}

            dominant = "ok"

            if metrics.opportunity_details:

                dominant = max(

                    (detail.severity.lower() or "info" for detail in metrics.opportunity_details),

                    key=lambda sev: severity_order.get(sev, 1),

                    default="info",

                )

            elif metrics.opportunities:

                dominant = "info"



            dark_theme = _is_dark(self)

            if dark_theme:

                severity_styles = {

                    "critical": ("#3b1f21", "#ffb4ab"),

                    "warning": ("#3b3017", "#ffe082"),

                    "info": ("#1b2f47", "#90caf9"),

                    "ok": ("#1f3325", "#a5d6a7"),

                }

            else:

                severity_styles = {

                    "critical": ("#ffebee", "#c62828"),

                    "warning": ("#fff8e1", "#ef6c00"),

                    "info": ("#e3f2fd", "#1565c0"),

                    "ok": ("#e8f5e9", "#2e7d32"),

                }

            bg_color, fg_color = severity_styles.get(dominant, severity_styles["info"])

            style_block = (

                f"background:{bg_color};color:{fg_color};padding:6px;border-radius:4px;"

                "border:1px solid rgba(255,255,255,0.05);"

            )

            self._summary.setStyleSheet(style_block)

            self._scripts.setStyleSheet(style_block)

            self._opportunities.setStyleSheet(

                "color:#f0f0f0;margin-top:6px;" if dark_theme else "color:#202124;margin-top:6px;"

            )



            rows: List[List[str]] = []

            for r_type, info in metrics.resource_summary.items():

                byte_value = info.get("bytes", 0)

                rows.append([r_type.upper(), str(info.get("count", 0)), self._format_bytes(byte_value)])

            if not rows:

                rows = [["-", "-", "-"]]

            model = GenericModel(["Resource", "Count", "Bytes"], rows)

            self.set_model(model)

            header = _header(self.view)

            header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)

            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)

            header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)



            if dark_theme:

                badge_colors = {"critical": "#ff5252", "warning": "#ffca28", "info": "#64b5f6", "ok": "#81c784"}

                badge_text_color = "#121212"

            else:

                badge_colors = {"critical": "#d32f2f", "warning": "fbc02d", "info": "#1976d2", "ok": "#2e7d32"}

                badge_text_color = "#ffffff"

            opportunity_items: List[str] = []

            if metrics.opportunity_details:

                for detail in metrics.opportunity_details:

                    severity = detail.severity.lower() if detail.severity else "info"

                    color = badge_colors.get(severity, badge_colors["info"])

                    badge = (

                        "<span style='display:inline-block;padding:1px 6px;"

                        f"border-radius:10px;background:{color};color:{badge_text_color};"

                        "font-weight:bold;font-size:11px;'>"

                        f"{severity.title()}</span>"

                    )

                    opportunity_items.append(f"<li>{badge} {_html.escape(detail.message)}</li>")

            elif metrics.opportunities:

                opportunity_items = [f"<li>{_html.escape(item)}</li>" for item in metrics.opportunities]



            if opportunity_items:

                self._opportunities.setText(f"<b>Opportunities</b><ul>{''.join(opportunity_items)}</ul>")

            else:

                ok_color = badge_colors["ok"]

                ok_text = "#b2dfdb" if dark_theme else "#2e7d32"

                self._opportunities.setText(

                    "<b>Opportunities</b><br/>"

                    "<span style='display:inline-block;padding:2px 6px;border-radius:10px;"

                    f"background:{ok_color};color:{badge_text_color};font-weight:bold;font-size:11px;'>OK</span> "

                    f"<span style='color:{ok_text}'>No issues detected.</span>"

                )



            offenders_rows: List[List[str]] = []

            for offender in metrics.top_offenders:

                offenders_rows.append([

                    offender.resource_type.upper() or "-",

                    offender.url or "-",

                    "Blocking" if offender.blocking else "Async",

                    self._format_bytes(offender.bytes),

                ])

            if not offenders_rows:

                offenders_rows = [["-", "-", "-", "-"]]

            offender_model = GenericModel(["Type", "URL", "Script", "Bytes"], offenders_rows)

            self._offender_view.setModel(offender_model)

            offender_header = _header(self._offender_view)

            offender_header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)

            offender_header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

            offender_header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

            offender_header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)



            self._apply_table_palette(self.view)

            self._apply_table_palette(self._offender_view)

        finally:

            self._is_rendering = False

    def clear(self) -> None:
        self.update({})

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() in (
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
        ):
            self._render(self._current_metrics)
            offender_vp = self._offender_view.viewport() if self._offender_view else None
            main_vp = self.view.viewport()
            if offender_vp:
                offender_vp.update()
            if main_vp:
                main_vp.update()
        super().changeEvent(event)

    def _apply_table_palette(self, view: QtWidgets.QTableView) -> None:
        if _is_dark(self):
            stylesheet = (
                "QTableView {"
                "background-color:#1e1e1e;"
                "color:#f0f0f0;"
                "gridline-color:#444444;"
                "alternate-background-color:#262626;"
                "selection-background-color:#31475b;"
                "selection-color:#ffffff;"
                "}"
                "QHeaderView::section {"
                "background-color:#2b2b2b;"
                "color:#f0f0f0;"
                "}"
            )
        else:
            stylesheet = (
                "QTableView {"
                "background-color:#ffffff;"
                "color:#202124;"
                "gridline-color:#d0d4da;"
                "alternate-background-color:#f5f7fa;"
                "selection-background-color:#dbeafe;"
                "selection-color:#202124;"
                "}"
                "QHeaderView::section {"
                "background-color:#f0f2f5;"
                "color:#202124;"
                "}"
            )
        view.setStyleSheet(stylesheet)

    @staticmethod
    def _format_bytes(value: int | float) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        number = max(number, 0.0)
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if number < 1024.0 or unit == units[-1]:
                if unit == "B":
                    return f"{int(number)} {unit}"
                return f"{number:.1f} {unit}"
            number /= 1024.0
        return f"{number:.1f} TB"


@dataclass
class _SchemaBlock:
    label: str
    errors: List[str]
    text: str


class SchemaTab(QtWidgets.QTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self._state: Dict[str, Any] | None = None
        self._is_rendering = False

    def update(self, payload: Any) -> None:
        report = StructuredDataPayload.from_raw(payload)
        blocks: List[Any] = list(report.blocks)
        if not blocks and report.fallback_raw:
            blocks = [{"@raw": raw, "_extracted_via": "json-ld-raw"} for raw in report.fallback_raw]
        if not blocks:
            self._state = None
            self.setHtml("<span style='color:#c62828;font-weight:bold'>Structured data not found</span>")
            return

        summary = report.summary
        syntax_counts = {name: count for name, count in summary.by_syntax.items() if count} or self._fallback_syntax_counts(blocks)
        type_counts = {name: count for name, count in summary.by_type.items() if count} or self._fallback_type_counts(blocks)

        total = summary.total or sum(syntax_counts.values()) or len(blocks)
        block_models = [self._build_schema_block(idx, item) for idx, item in enumerate(blocks, start=1)]
        self._state = {
            "summary": summary,
            "blocks": block_models,
            "syntax_counts": syntax_counts,
            "type_counts": type_counts,
            "issues": list(summary.errors),
            "total": total,
        }
        self._render()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() in (
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
        ):
            self._render()
        super().changeEvent(event)

    def _theme(self) -> Dict[str, str]:
        is_dark = _is_dark(self)
        if is_dark:
            return {
                "background": "#1e1e1e",
                "foreground": "#f0f0f0",
                "block_bg": "#262626",
                "block_fg": "#f0f0f0",
                "block_border": "#444444",
                "issue": "#ff8a80",
                "warn": "#ffd54f",
                "ok": "#81c784",
            }
        return {
            "background": "#ffffff",
            "foreground": "#202124",
            "block_bg": "#f7f7f7",
            "block_fg": "#202124",
            "block_border": "#cccccc",
            "issue": "#c62828",
            "warn": "#b26a00",
            "ok": "#1a7f37",
        }

    def _render(self) -> None:
        if not self._state or self._is_rendering:
            return
        self._is_rendering = True
        try:
            theme = self._theme()
            self.setStyleSheet(f"background:{theme['background']}; color:{theme['foreground']};")

            summary = self._state["summary"]
            syntax_counts = self._state["syntax_counts"]
            type_counts = self._state["type_counts"]
            total = self._state["total"]
            issues = list(dict.fromkeys(self._state["issues"]))

            syntax_labels = {
                "json-ld": "JSON-LD",
                "json-ld-raw": "JSON-LD raw",
                "microdata": "Microdata",
                "microformat": "Microformat",
                "opengraph": "OpenGraph",
                "rdfa": "RDFa",
            }
            syntax_text = ", ".join(
                f"{syntax_labels.get(name, name)} {syntax_counts[name]}" for name in sorted(syntax_counts)
            ) or "none"
            type_text = (
                " &nbsp; Types: "
                + ", ".join(f"{schema_type} {type_counts[schema_type]}" for schema_type in sorted(type_counts))
                if type_counts
                else ""
            )
            if total == 0:
                header_color = theme["issue"]
            elif issues:
                header_color = theme["warn"]
            else:
                header_color = theme["ok"]
            header = (
                f"<div style='font-weight:bold;color:{header_color}'>Structured data: {total} items &nbsp; "
                f"(Syntax: {syntax_text}){type_text}</div>"
            )

            if issues:
                items_html = "".join(f"<li>{_html.escape(item)}</li>" for item in issues)
                issue_html = f"<div style='color:{theme['issue']};margin:6px 0'><b>Issues</b><ul>{items_html}</ul></div>"
            else:
                issue_html = ""

            block_html = "".join(self._render_block(block, theme) for block in self._state["blocks"])
            self.setHtml(header + issue_html + block_html)
        finally:
            self._is_rendering = False

    @staticmethod
    def _fallback_syntax_counts(blocks: List[Any]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in blocks:
            if isinstance(item, dict):
                via = str(item.get("_extracted_via", "")).strip()
                if via:
                    counts[via] = counts.get(via, 0) + 1
        return counts

    @staticmethod
    def _fallback_type_counts(blocks: List[Any]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in blocks:
            if isinstance(item, dict):
                type_hint = SchemaTab._extract_type(item.get("@type"))
                if type_hint:
                    counts[type_hint] = counts.get(type_hint, 0) + 1
        return counts

    @staticmethod
    def _build_schema_block(index: int, item: Any) -> _SchemaBlock:
        label = f"Block #{index}"
        if isinstance(item, dict):
            via = str(item.get("_extracted_via", "")).strip()
            type_hint = SchemaTab._extract_type(item.get("@type"))
            label = SchemaTab._compose_label(label, type_hint, via)
            errors = [str(err).strip() for err in item.get("_schema_errors", []) if str(err).strip()]
            cleaned = {key: value for key, value in item.items() if key not in {"_schema_errors"}}
            text = json.dumps(cleaned, indent=2, ensure_ascii=False)
            if "@raw" in cleaned and isinstance(cleaned["@raw"], str):
                label = f"{label} (JSON-LD raw)"
            return _SchemaBlock(label, errors, text)
        if isinstance(item, list):
            text = json.dumps(item, indent=2, ensure_ascii=False)
            return _SchemaBlock(f"{label} (list)", [], text)
        return _SchemaBlock(label, [], str(item))

    @staticmethod
    def _compose_label(base: str, type_hint: str, via: str) -> str:
        label = base
        if type_hint:
            label += f" ({type_hint})"
        if via:
            label += f" via {via}"
        return label

    @staticmethod
    def _extract_type(raw: Any) -> str:
        candidate = ""
        if isinstance(raw, str):
            candidate = raw
        elif isinstance(raw, list):
            for part in raw:
                if isinstance(part, str) and part.strip():
                    candidate = part
                    break
        if not candidate:
            return ""
        text = candidate.strip()
        if not text:
            return ""
        for sep in ("#", "/"):
            if sep in text:
                text = text.rsplit(sep, 1)[-1]
        return text.strip()

    @staticmethod
    def _render_block(block: _SchemaBlock, theme: Dict[str, str]) -> str:
        label_color = theme["issue"] if block.errors else theme["foreground"]
        error_section = ""
        if block.errors:
            error_items = "".join(f"<li>{_html.escape(err)}</li>" for err in block.errors)
            error_section = f"<ul style='margin:4px 0 8px 18px;color:{theme['issue']}'>{error_items}</ul>"
        return (
            "<div style='margin-top:10px'>"
            f"<div style='font-weight:bold;color:{label_color}'>{_html.escape(block.label)}</div>"
            f"{error_section}"
            f"<pre style='background:{theme['block_bg']};color:{theme['block_fg']};"
            f"border:1px solid {theme['block_border']};padding:6px;white-space:pre-wrap'>"
            f"{_html.escape(block.text)}</pre>"
            "</div>"
        )
class SerpTab(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview = QtWidgets.QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.table = QtWidgets.QTableView()
        self.table.setSortingEnabled(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview)
        layout.addWidget(self.table)
        self._model: QtCore.QAbstractTableModel | None = None

    def update(self, serp: Dict[str, str], audit: Dict[str, str]) -> None:
        description = serp.get('description', '')
        if len(description) > 160:
            description = description[:157].rstrip() + ''

        self.preview.setStyleSheet('background:#ffffff;color:#202124;border:1px solid #d0d0d0;')
        favicon_html = ''
        if serp.get('favicon'):
            favicon_html = f"<img src=\"{serp['favicon']}\" width='30' height='30' alt='icon'/>"
        serp_html = f"""
        <div style='font-family:Roboto,Arial,sans-serif;font-size:14px;line-height:1.3;background:#ffffff;color:#202124;padding:8px'>
           <table cellpadding='0' cellspacing='0' style='border:none;margin:0;padding:0'>
              <tr>
                <td rowspan='2' style='padding-right:6px;vertical-align:middle'>
                  {favicon_html}
                </td>
                <td style='font-size:14px;color:#202124;font-weight:500;vertical-align:bottom'>
                  {serp.get('site_name', '')}
                </td>
              </tr>
              <tr>
                <td style='font-size:12px;color:#4d5156;vertical-align:top'>
                  {serp.get('breadcrumb', '')}
                </td>
              </tr>
            </table>
            <div>
                <a href='{serp.get('url', '')}'
                style='font-size:18px;font-weight:400;color:#1a0dab;text-decoration:none;display:inline-block;max-width:600px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>
                    {serp.get('title', '')}
                </a>
            </div>
            <div style='font-size:14px;color:#4d5156;margin-top:3px;max-width:600px'>
                {description}
            </div>
        </div>
        """
        self.preview.setHtml(serp_html)

        rows = [
            ["Length (chars)", audit.get("char_len", "")],
            ["Length (pixels)", audit.get("px_len", "")],
            ["> 60 chars", audit.get("too_long", "")],
            ["< 30 chars", audit.get("too_short", "")],
            ["> 561 px", audit.get("px_over", "")],
            ["< 200 px", audit.get("px_under", "")],
            ["Equals H1", audit.get("equals_h1", "")],
            ["Missing", audit.get("missing", "")],
        ]
        self._model = SerpAuditModel(["Check", "Result"], rows)
        self.table.setModel(self._model)
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)

__all__ = [
    "TableTab",
    "MetaTab",
    "HeadersTab",
    "ImagesTab",
    "LinksTab",
    "RedirectTab",
    "CanonicalTab",
    "RobotsTab",
    "HreflangTab",
    "AiTab",
    "KeywordsTab",
    "PerformanceTab",
    "SchemaTab",
    "SerpTab",
]
