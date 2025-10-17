from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, cast

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtGui import QPalette
from .crawl_types import StructuredDataPayload
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
)

import html as _html
import json


def _header(view: QtWidgets.QTableView) -> QtWidgets.QHeaderView:
    return cast(QtWidgets.QHeaderView, view.horizontalHeader())


def _is_dark(widget: QtWidgets.QWidget) -> bool:
    base = widget.palette().color(QPalette.Base)
    return base.value() < 128


class TableTab(QtWidgets.QWidget):
    def __init__(self, sorting: bool = True, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._table = QtWidgets.QTableView()
        self._table.setSortingEnabled(sorting)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)
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
        chain = " → ".join(data.get("chain", []) or [])
        rows = [
            ["Redirect chain", chain or "—"],
            ["Hop count", str(data.get("hops", ""))],
            ["Final status", data.get("final_status", "")],
            ["Loop detected", "Yes" if data.get("loop") else "No"],
        ]
        self.set_model(RedirectModel(["Check", "Value"], rows))
        _header(self.view).setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)


class CanonicalTab(TableTab):
    def update(self, data: Dict[str, object]) -> None:
        rows = [
            ["Canonical URL", data.get("target", "") or "—"],
            ["Self-referencing", "Yes" if data.get("self") else "No"],
            ["Multiple canonicals", "Yes" if data.get("multiple") else "No"],
            ["Canonical status", data.get("status", "") or "—"],
        ]
        self.set_model(CanonicalModel(["Check", "Value"], rows))


class RobotsTab(TableTab):
    def update(self, meta_robots: str, robots_map: Dict[str, List[tuple[str, str]]]) -> None:
        rows: List[List[str]] = [["Meta / X-Robots-Tag", meta_robots or "—"], ["", ""]]
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
    def update(self, rows: List[List[str]]) -> None:
        self.set_model(GenericModel(["Termine", "Freq"], rows))


@dataclass
class _SchemaBlock:
    label: str
    errors: List[str]
    text: str


class SchemaTab(QtWidgets.QTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)

    def update(self, payload: Any) -> None:
        report = StructuredDataPayload.from_raw(payload)
        blocks: List[Any] = list(report.blocks)
        if not blocks and report.fallback_raw:
            blocks = [{"@raw": raw, "_extracted_via": "json-ld-raw"} for raw in report.fallback_raw]
        if not blocks:
            self.setHtml("<span style='color:red;font-weight:bold'>Structured data not found</span>")
            return

        is_dark = _is_dark(self)
        base_bg = '#1e1e1e' if is_dark else '#ffffff'
        base_fg = '#f0f0f0' if is_dark else '#202124'
        pre_bg = '#2a2a2a' if is_dark else '#f7f7f7'
        pre_fg = '#f0f0f0' if is_dark else '#202124'
        pre_border = '#555555' if is_dark else '#cccccc'
        self.setStyleSheet(f"background:{base_bg}; color:{base_fg};")

        summary = report.summary
        syntax_counts = {name: count for name, count in summary.by_syntax.items() if count}
        if not syntax_counts:
            syntax_counts = self._fallback_syntax_counts(blocks)
        type_counts = {name: count for name, count in summary.by_type.items() if count}
        if not type_counts:
            type_counts = self._fallback_type_counts(blocks)

        total = summary.total or sum(syntax_counts.values()) or len(blocks)
        issues = list(summary.errors)

        syntax_labels = {
            "json-ld": "JSON-LD",
            "json-ld-raw": "JSON-LD raw",
            "microdata": "Microdata",
            "microformat": "Microformat",
            "opengraph": "OpenGraph",
            "rdfa": "RDFa",
        }
        syntax_text = ", ".join(
            f"{syntax_labels.get(name, name)} {syntax_counts[name]}"
            for name in sorted(syntax_counts)
        ) or "none"
        type_text = ""
        if type_counts:
            type_text = " &nbsp; Types: " + ", ".join(
                f"{schema_type} x {type_counts[schema_type]}" for schema_type in sorted(type_counts)
            )
        color = "#1a7f37" if total and not issues else ("#b26a00" if total else "#c62828")
        header = (
            f"<div style='font-weight:bold;color:{color}'>Structured data: {total} items &nbsp; "
            f"(Syntax: {syntax_text}){type_text}</div>"
        )

        unique_issues = list(dict.fromkeys(issues))
        issue_html = ""
        if unique_issues:
            items_html = "".join(f"<li>{_html.escape(issue)}</li>" for issue in unique_issues)
            issue_html = f"<div style='color:#c62828;margin:6px 0'><b>Issues</b><ul>{items_html}</ul></div>"

        block_models = [self._build_schema_block(idx, item) for idx, item in enumerate(blocks, start=1)]
        block_html = "".join(
            self._render_block(block, base_fg, pre_bg, pre_fg, pre_border) for block in block_models
        )
        self.setHtml(header + issue_html + block_html)

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
    def _render_block(
        block: _SchemaBlock,
        base_fg: str,
        pre_bg: str,
        pre_fg: str,
        pre_border: str,
    ) -> str:
        label_color = "#c62828" if block.errors else base_fg
        error_section = ""
        if block.errors:
            error_items = "".join(f"<li>{_html.escape(err)}</li>" for err in block.errors)
            error_section = f"<ul style='margin:4px 0 8px 18px;color:#c62828'>{error_items}</ul>"
        return (
            "<div style='margin-top:10px'>"
            f"<div style='font-weight:bold;color:{label_color}'>{_html.escape(block.label)}</div>"
            f"{error_section}"
            f"<pre style='background:{pre_bg};color:{pre_fg};border:1px solid {pre_border};padding:6px;white-space:pre-wrap'>{_html.escape(block.text)}</pre>"
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
            description = description[:157].rstrip() + '…'

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
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)

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
    "SchemaTab",
    "SerpTab",
]
