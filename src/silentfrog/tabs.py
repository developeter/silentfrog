from __future__ import annotations
from typing import Any, Dict, List

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtGui import QPalette
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
    return view.horizontalHeader()  # type: ignore[return-value]


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


class HeadersTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)

    def update(self, rows: List[List[str]]) -> None:
        self.set_model(HeaderModel(rows))


class ImagesTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._rows: List[List[str]] = []

    def update(self, rows: List[List[str]]) -> None:
        if rows and len(rows[0]) <= 4 and self._rows:
            merged: List[List[str]] = []
            for base_row, result in zip(self._rows, rows):
                url = result[0] if result else base_row[0]
                width = str(result[1]) if len(result) > 1 else str(base_row[3])
                height = str(result[2]) if len(result) > 2 else str(base_row[4])
                human = result[3] if len(result) > 3 else base_row[5]
                alt = base_row[1] if len(base_row) > 1 else ""
                title = base_row[2] if len(base_row) > 2 else ""
                merged.append([url, alt, title, width, height, human])
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


class SchemaTab(QtWidgets.QTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)

    def update(self, items: List[Any]) -> None:
        if not items:
            self.setHtml("<span style='color:red;font-weight:bold'>Schema.org not found</span>")
            return

        is_dark = _is_dark(self)
        base_bg = '#1e1e1e' if is_dark else '#ffffff'
        base_fg = '#f0f0f0' if is_dark else '#202124'
        pre_bg = '#2a2a2a' if is_dark else '#f7f7f7'
        pre_fg = '#f0f0f0' if is_dark else '#202124'
        pre_border = '#555555' if is_dark else '#cccccc'
        self.setStyleSheet(f"background:{base_bg}; color:{base_fg};")

        blocks: List[str] = []
        issues: List[str] = []
        counts = {"json-ld": 0, "microdata": 0, "rdfa": 0, "opengraph": 0, "json-ld-raw": 0}
        for item in items:
            if isinstance(item, dict) and "_schema_issues" in item:
                issues.extend(item["_schema_issues"] or [])
                continue
            if isinstance(item, dict):
                via = str(item.get("_extracted_via", ""))
                counts[via] = counts.get(via, 0) + 1
                blocks.append(json.dumps(item, indent=2, ensure_ascii=False))
            elif isinstance(item, list) and item:
                raw = item[0]
                try:
                    parsed = json.loads(raw)
                    blocks.append(json.dumps(parsed, indent=2, ensure_ascii=False))
                except Exception:
                    counts["json-ld-raw"] = counts.get("json-ld-raw", 0) + 1
                    blocks.append(str(raw))
            else:
                blocks.append(str(item))

        total = sum(counts.values())
        color = "#1a7f37" if total and not issues else ("#b26a00" if total else "#c62828")
        header = (
            f"<div style='font-weight:bold;color:{color}'>Schema.org: {total} items &nbsp; "
            f"(JSON-LD {counts.get('json-ld',0)}, Microdata {counts.get('microdata',0)}, "
            f"RDFa {counts.get('rdfa',0)}, OpenGraph {counts.get('opengraph',0)}, "
            f"Raw {counts.get('json-ld-raw',0)})</div>"
        )
        issue_html = ""
        if issues:
            items_html = "".join(f"<li>{_html.escape(issue)}</li>" for issue in sorted(set(issues)))
            issue_html = f"<div style='color:#c62828;margin:6px 0'><b>Issues</b><ul>{items_html}</ul></div>"
        pre_blocks = "".join(
            f"<pre style='background:{pre_bg};color:{pre_fg};border:1px solid {pre_border};padding:6px;white-space:pre-wrap'>{_html.escape(block)}</pre>"
            for block in blocks
        )
        self.setHtml(header + issue_html + pre_blocks)

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
