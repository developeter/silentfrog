from __future__ import annotations

import html as _html
import json
import sys
from dataclasses import dataclass
from typing import Any, cast

from qtpy import QtCore, QtGui, QtWidgets
from qtpy.QtCore import Qt
from qtpy.QtGui import QPalette

from .ai_visibility import ai_visibility_summary_tooltip
from .content_quality import build_content_quality_rows
from .crawl_types import (
    AiVisibilityPayload,
    ContentQuality,
    KeywordEntry,
    PerformanceMetrics,
    SocialPayload,
    StructuredDataPayload,
)
from .image_diagnostics import DIAGNOSTIC_COL, merge_image_row, normalize_image_rows
from .indexability import build_indexability_rows
from .models import (
    AiVisibilityModel,
    BotMatrixModel,
    CanonicalModel,
    ContentQualityModel,
    GenericModel,
    HeaderModel,
    HreflangModel,
    ImagesModel,
    IndexabilityModel,
    KeywordModel,
    LinksModel,
    MetaModel,
    PerformanceIssueModel,
    RedirectModel,
    RobotsModel,
    SerpAuditModel,
    SocialIssuesModel,
    build_bot_rows,
)
from .perf_metrics import performance_resource_tooltip, performance_summary_tooltip
from .theme import current_theme

_AI_CRAWL_HEADERS = [
    "Agent",
    "Token",
    "Robots.txt OK",
    "Nonstandard directive",
    "Google controls",
    "Verdict",
    "Notes",
]

_AI_CRAWL_HEADER_TOOLTIPS = [
    "The human-readable crawler name. Use this to see which AI-facing agent the row refers to.",
    "The robots.txt user-agent token Silentfrog checked for this crawler.",
    "Whether robots.txt allows this crawler to fetch the current page URL.",
    "Nonstandard AI directives found in meta or X-Robots-Tag, such as noai or noimageai. Silentfrog reports them, but official support should be verified vendor by vendor.",
    "Google search controls that can limit reuse in Google Search features, such as nosnippet, noindex, none, or max-snippet.",
    "Final AI access verdict for this crawler: Allowed, Limited, or Blocked.",
    "Why the verdict was assigned, including matched robots.txt rules or restrictive meta directives.",
]

_AI_VISIBILITY_HEADERS = ["Area", "Check", "Status", "Details", "Recommendation"]

_AI_VISIBILITY_HEADER_TOOLTIPS = [
    "The audit area being evaluated: Access, Topic clarity, Answerability, Citation readiness, or Entity clarity.",
    "The specific AI visibility check performed for this row.",
    "The result for this check: Good, Warning, or Critical.",
    "Evidence from the page that explains why this status was assigned.",
    "The clearest next step to improve this AI visibility signal.",
]


def _header(view: QtWidgets.QTableView) -> QtWidgets.QHeaderView:
    return cast(QtWidgets.QHeaderView, view.horizontalHeader())


def _set_header_modes(
    header: QtWidgets.QHeaderView,
    *modes: tuple[int, QtWidgets.QHeaderView.ResizeMode],
) -> None:
    for column, mode in modes:
        header.setSectionResizeMode(column, mode)


def _configure_table_view_geometry(view: QtWidgets.QTableView) -> None:
    policy = view.sizePolicy()
    policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Policy.Ignored)
    policy.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.Expanding)
    view.setSizePolicy(policy)
    view.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)


def _rich_label(tooltip: str = "") -> QtWidgets.QLabel:
    label = QtWidgets.QLabel()
    label.setWordWrap(True)
    label.setTextFormat(QtCore.Qt.TextFormat.RichText)
    if tooltip:
        label.setToolTip(tooltip)
    return label


def _is_dark(widget: QtWidgets.QWidget) -> bool:
    base = widget.palette().color(QPalette.Base)
    if widget.testAttribute(QtCore.Qt.WidgetAttribute.WA_SetPalette) and base.isValid():
        return base.value() < 128
    app = cast(QtWidgets.QApplication | None, QtWidgets.QApplication.instance())
    if app is not None:
        return current_theme(app) == "dark"
    if base.isValid():
        return base.value() < 128
    return False


class _TooltipTableView(QtWidgets.QTableView):
    def viewportEvent(self, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.ToolTip:
            return super().viewportEvent(event)
        help_event = cast(QtGui.QHelpEvent, event)
        index = self.indexAt(help_event.pos())
        model = self.model()
        tooltip = model.data(index, Qt.ItemDataRole.ToolTipRole) if model and index.isValid() else ""
        if tooltip:
            QtWidgets.QToolTip.showText(help_event.globalPos(), str(tooltip), self.viewport(), self.visualRect(index))
            return True
        QtWidgets.QToolTip.hideText()
        event.ignore()
        return True


class _TooltipHeaderView(QtWidgets.QHeaderView):
    def event(self, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.ToolTip:
            return super().event(event)
        help_event = cast(QtGui.QHelpEvent, event)
        section = self.logicalIndexAt(help_event.pos())
        model = self.model()
        tooltip = (
            model.headerData(section, self.orientation(), Qt.ItemDataRole.ToolTipRole) if model and section >= 0 else ""
        )
        if tooltip:
            rect = QtCore.QRect(self.sectionViewportPosition(section), 0, self.sectionSize(section), self.height())
            QtWidgets.QToolTip.showText(help_event.globalPos(), str(tooltip), self.viewport(), rect)
            return True
        QtWidgets.QToolTip.hideText()
        event.ignore()
        return True


class TableTab(QtWidgets.QWidget):
    def __init__(self, sorting: bool = True, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._table = _TooltipTableView()
        _configure_table_view_geometry(self._table)
        self._table.setHorizontalHeader(_TooltipHeaderView(QtCore.Qt.Orientation.Horizontal, self._table))
        self._table.setSortingEnabled(sorting)
        header = _header(self._table)
        header.setSectionsClickable(sorting)
        header.setSortIndicatorShown(sorting)
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
        header = _header(self._table)
        header.setSectionsClickable(was_sorted)
        header.setSortIndicatorShown(was_sorted)


class SocialTab(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._og_preview = QtWidgets.QTextBrowser()
        self._tw_preview = QtWidgets.QTextBrowser()
        for view in (self._og_preview, self._tw_preview):
            view.setOpenExternalLinks(True)
            view.setMaximumHeight(320)
            view.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self._issues = QtWidgets.QTableView()
        _configure_table_view_geometry(self._issues)
        self._issues.setSortingEnabled(True)
        layout = QtWidgets.QVBoxLayout(self)
        previews = QtWidgets.QHBoxLayout()
        og_box = QtWidgets.QVBoxLayout()
        og_label = QtWidgets.QLabel("OpenGraph preview")
        og_label.setStyleSheet("font-weight:600;")
        og_box.addWidget(og_label)
        og_box.addWidget(self._og_preview)

        tw_box = QtWidgets.QVBoxLayout()
        tw_label = QtWidgets.QLabel("Twitter Card preview")
        tw_label.setStyleSheet("font-weight:600;")
        tw_box.addWidget(tw_label)
        tw_box.addWidget(self._tw_preview)

        previews.addLayout(og_box)
        previews.addLayout(tw_box)
        layout.addLayout(previews)
        layout.addWidget(self._issues)

    @property
    def view(self) -> QtWidgets.QTableView:
        return self._issues

    def _card_html(
        self,
        title: str,
        desc: str,
        url: str,
        site: str,
        img_src: str,
        link_url: str,
        theme: str,
    ) -> str:
        bg = "#ffffff" if theme == "light" else "#2b2b2b"
        fg = "#202124" if theme == "light" else "#e0e0e0"
        border = "#d0d0d0" if theme == "light" else "#444444"
        img_html = (
            f'<a href="{link_url}"><img src="{img_src}" alt="" width="240" '
            f'style="border-radius:4px;border:1px solid {border};"/></a>'
            if img_src
            else ""
        )
        return (
            f"<div style='background:{bg};color:{fg};border:1px solid {border};padding:8px;"
            f'font-family:"Segoe UI",sans-serif; font-size:12px;\'>'
            f"<div style='display:flex;gap:8px;align-items:flex-start;'>"
            f"{img_html}"
            f"<div>"
            f"<div style='font-weight:600;margin-bottom:4px;'>{_html.escape(title) or 'No title'}</div>"
            f"<div style='margin-bottom:6px;'>{_html.escape(desc) or 'No description'}</div>"
            f"<div style='color:{border};font-size:11px;'>{_html.escape(site or url)}</div>"
            f"</div></div></div>"
        )

    def update(self, data: dict[str, object]) -> None:
        app = cast(QtWidgets.QApplication | None, QtWidgets.QApplication.instance())
        theme = current_theme(app)
        payload = SocialPayload.from_raw(data if isinstance(data, dict) else {})
        og = payload.open_graph
        tw = payload.twitter
        og_img = og.image_data or og.image
        tw_img = tw.image_data or tw.image
        self._og_preview.setHtml(
            self._card_html(og.title, og.description, og.url, og.site_name, og_img, og.image or og.url, theme)
        )
        self._tw_preview.setHtml(
            self._card_html(tw.title, tw.description, tw.url, tw.site_name, tw_img, tw.image or tw.url, theme)
        )
        rows: list[list[str]] = []
        for source, issues in (("OpenGraph", og.issues), ("Twitter", tw.issues)):
            for issue in issues:
                rows.append([source, issue])
        if not rows:
            rows = [["Info", "No social issues detected"]]
        self._issues.setModel(SocialIssuesModel(rows))
        _set_header_modes(
            cast(QtWidgets.QHeaderView, self._issues.horizontalHeader()),
            (0, QtWidgets.QHeaderView.ResizeToContents),
            (1, QtWidgets.QHeaderView.Stretch),
        )


class MetaTab(TableTab):
    def update(self, rows: list[list[str]]) -> None:
        self.set_model(MetaModel(rows))

    def clear(self) -> None:
        self.set_model(MetaModel([], add_placeholders=False))


class HeadersTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)

    def update(self, rows: list[list[str]], title: str | None = None) -> None:
        self.set_model(HeaderModel(rows, title))


class ImagesTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._rows: list[list[str]] = []

    def update(self, rows: list[list[str]]) -> None:
        if rows and len(rows[0]) == 6 and self._rows:
            updates = {row[0]: row for row in rows}
            merged: list[list[str]] = []
            for current in self._rows:
                merged.append(merge_image_row(current, updates.get(current[0], [])))
            rows = merged
        else:
            rows = normalize_image_rows(rows)
        self._rows = rows
        model = ImagesModel(self._rows)
        self.set_model(model)
        _set_header_modes(
            _header(self.view),
            (0, QtWidgets.QHeaderView.Interactive),
            (DIAGNOSTIC_COL, QtWidgets.QHeaderView.Stretch),
        )
        self.view.setColumnWidth(0, 280)

    def rows(self) -> list[list[str]]:
        return [list(row) for row in self._rows]


class LinksTab(TableTab):
    def update(self, rows: list[list[str]]) -> None:
        self.set_model(LinksModel(rows))
        self.view.setAlternatingRowColors(False)
        _set_header_modes(_header(self.view), (0, QtWidgets.QHeaderView.Stretch))


class RedirectTab(TableTab):
    def update(self, data: dict[str, object]) -> None:
        chain_raw = data.get("chain", [])
        chain_list: list[str] = []
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
        _set_header_modes(_header(self.view), (1, QtWidgets.QHeaderView.Stretch))


class CanonicalTab(TableTab):
    def update(self, data: dict[str, object]) -> None:
        rows = [
            ["Canonical URL", data.get("target", "") or ""],
            ["Self-referencing", "Yes" if data.get("self") else "No"],
            ["Multiple canonicals", "Yes" if data.get("multiple") else "No"],
            ["Canonical status", data.get("status", "") or ""],
        ]
        self.set_model(CanonicalModel(["Check", "Value"], rows))


class IndexabilityTab(TableTab):
    def update(
        self,
        redirect: dict[str, object],
        canonical: dict[str, object],
        meta_robots: str,
        robots_map: dict[str, list[tuple[str, str]]],
    ) -> None:
        rows = build_indexability_rows(redirect, canonical, meta_robots, robots_map)
        self.set_model(IndexabilityModel(["Check", "Value"], rows))
        _set_header_modes(_header(self.view), (1, QtWidgets.QHeaderView.Stretch))


class ContentQualityTab(TableTab):
    def update(self, data: object) -> None:
        source = data if isinstance(data, dict) else {}
        quality = data if isinstance(data, ContentQuality) else ContentQuality.from_raw(source)
        payload = quality.to_dict()
        rows = build_content_quality_rows(payload if any(payload.values()) else {})
        self.set_model(ContentQualityModel(["Check", "Value"], rows))
        _set_header_modes(_header(self.view), (1, QtWidgets.QHeaderView.Stretch))


class RobotsTab(TableTab):
    def update(self, meta_robots: str, robots_map: dict[str, list[tuple[str, str]]]) -> None:
        rows: list[list[str]] = [["Meta / X-Robots-Tag", meta_robots or ""], ["", ""]]
        for agent, directives in robots_map.items():
            rows.append([f"User-Agent: {agent}", ""])
            rows.extend([[verb, path] for verb, path in directives])
        if not robots_map:
            rows.append(["robots.txt", "Not fetched or empty"])
        self.set_model(RobotsModel(["Directive", "Value"], rows))
        _set_header_modes(_header(self.view), (1, QtWidgets.QHeaderView.Stretch))


class HreflangTab(TableTab):
    def update(self, rows: list[list[str]]) -> None:
        headers = ["Lang", "Target URL", "Status", "Lang-OK?", "Return?"]
        self.set_model(HreflangModel(headers, rows))
        _set_header_modes(_header(self.view), (1, QtWidgets.QHeaderView.Stretch))


class BotMatrixTab(TableTab):
    """v1.1 N5a-fix — true per-signal × per-bot heatmap.

    Replaces the original "AI crawl" flat table AND the first
    cut of "Bot Matrix" (which was only AI crawl with paint).
    Rows are the 19 bots; columns are 5 signals (Robots.txt /
    Meta robots / llms.txt / SSR parity / Verdict) plus a text
    Bot label column. Cells render as coloured chips; double-
    click pops the 7-column drill-down dialog that surfaces
    everything the dropped AI crawl tab used to show.
    """

    _CHIP_SIZE = 14
    _CHIP_RADIUS = 3

    def __init__(self) -> None:
        super().__init__(sorting=False)  # heatmap order = _AI_AGENTS order; sorting confuses chip cells
        self._summary = _rich_label(
            "<b>Bot Matrix</b> — 19 AI / search bots × 5 access signals. "
            "Cells render as coloured chips: green = good, yellow = warning, red = critical, grey = "
            "not measured / not applicable. Site-wide columns (Meta robots / llms.txt / SSR parity) "
            "show the same chip across every row by design. Double-click any row for the full "
            "per-bot reasoning."
        )
        self._layout.insertWidget(0, self._summary)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.view.doubleClicked.connect(self._on_row_activated)
        self.view.setItemDelegate(_ChipDelegate(self.view))
        self._model: BotMatrixModel | None = None

    def update(self, data: object) -> None:
        """Accept the full crawl payload dict OR just the ``ai_crawl`` rows.

        Bridging both shapes keeps the test suite (which feeds the
        raw list) and the production wiring (which now passes the
        full payload to pick up the discovery + render keys) on
        the same code path.
        """
        ai_crawl_rows, discovery, render = self._unpack(data)
        bots = build_bot_rows(ai_crawl_rows, discovery, render)
        model = BotMatrixModel(bots)
        self._model = model
        self.set_model(model)
        verdicts = [bot.detail[5].strip() for bot in bots]
        counts = {label: verdicts.count(label) for label in ("Allowed", "Limited", "Blocked")}
        self._summary.setText(
            "<b>Bot Matrix</b> &nbsp; "
            f"Allowed {counts['Allowed']} &nbsp; "
            f"Limited {counts['Limited']} &nbsp; "
            f"Blocked {counts['Blocked']} &nbsp;&nbsp; "
            "<i>(double-click a row for the full 7-column bot detail)</i>"
        )
        _set_header_modes(
            _header(self.view),
            (0, QtWidgets.QHeaderView.ResizeToContents),
            (1, QtWidgets.QHeaderView.Fixed),
            (2, QtWidgets.QHeaderView.Fixed),
            (3, QtWidgets.QHeaderView.Fixed),
            (4, QtWidgets.QHeaderView.Fixed),
            (5, QtWidgets.QHeaderView.Stretch),
        )
        header = _header(self.view)
        for col in (1, 2, 3, 4):
            header.resizeSection(col, 90)

    @staticmethod
    def _unpack(data: object) -> tuple[list[list[str]], dict | None, dict | None]:
        if isinstance(data, list):
            return [list(row) for row in data if isinstance(row, (list, tuple))], None, None
        if isinstance(data, dict):
            raw_rows = data.get("ai_crawl", []) or []
            rows = [list(row) for row in raw_rows if isinstance(row, (list, tuple))]
            discovery = data.get("discovery") if isinstance(data.get("discovery"), dict) else None
            render = data.get("render") if isinstance(data.get("render"), dict) else None
            return rows, discovery, render
        return [], None, None

    def _on_row_activated(self, index: QtCore.QModelIndex) -> None:
        if self._model is None:
            return
        detail = self._model.bot_detail(index.row())
        if detail is None:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"{detail[0]} — bot details")
        layout = QtWidgets.QFormLayout(dialog)
        for header_idx, header in enumerate(_AI_CRAWL_HEADERS):
            value = detail[header_idx] if header_idx < len(detail) else ""
            label = QtWidgets.QLabel(str(value))
            label.setWordWrap(True)
            layout.addRow(f"<b>{header}</b>", label)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addRow(close)
        dialog.exec()


class _ChipDelegate(QtWidgets.QStyledItemDelegate):
    """Paints a centred 14×14 rounded-rect chip using the cell's
    BackgroundRole brush. Column 0 falls through to the default text
    delegate so the bot name renders normally."""

    _CHIP_SIZE = 14
    _CHIP_RADIUS = 3

    def paint(  # noqa: D401
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        if index.column() == 0:
            super().paint(painter, option, index)
            return
        # Manual fill — but defer selection highlight to the base style first.
        widget = option.widget
        style = widget.style() if widget is not None else QtWidgets.QApplication.style()
        # Draw the cell background (handles selection highlight, alternate row, etc.).
        painter.save()
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""  # we render the chip; suppress any DisplayRole text
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, widget)
        brush_data = index.data(QtCore.Qt.ItemDataRole.BackgroundRole)
        if isinstance(brush_data, QtGui.QBrush):
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(brush_data)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            rect = option.rect
            cx = rect.center().x()
            cy = rect.center().y()
            chip = QtCore.QRectF(
                cx - self._CHIP_SIZE / 2,
                cy - self._CHIP_SIZE / 2,
                self._CHIP_SIZE,
                self._CHIP_SIZE,
            )
            painter.drawRoundedRect(chip, self._CHIP_RADIUS, self._CHIP_RADIUS)
        painter.restore()

    def sizeHint(  # noqa: N802, D401
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        base = super().sizeHint(option, index)
        if index.column() == 0:
            return base
        return QtCore.QSize(max(base.width(), 90), max(base.height(), 24))


_GEO_SCORE_TOOLTIP = (
    "GEO Score 0-100, derived from the AI Visibility check list.\n\n"
    "Formula: score = max(0, min(100, 100 - 4 x warnings - 10 x criticals)).\n"
    "Higher is better. 100 means every check is good or info. The first warning "
    "costs 4 points; the first critical costs 10 points."
)


def _collect_badge_checks(raw: object, payload: AiVisibilityPayload) -> list[dict[str, str]]:
    """Return a list of {key, status} dicts preserving the original `info`
    status (which AiVisibilityPayload.from_raw folds into `good`)."""
    if isinstance(raw, dict):
        raw_checks = raw.get("checks", [])
        if isinstance(raw_checks, list):
            return [
                {
                    "key": str(item.get("key", "")),
                    "status": str(item.get("status", "")).strip().lower(),
                }
                for item in raw_checks
                if isinstance(item, dict)
            ]
    # Fallback: caller passed an AiVisibilityPayload directly. We can't
    # recover the pre-normalised status; treat everything as measured.
    return [{"key": c.key or "", "status": c.status or ""} for c in payload.checks]


class AiVisibilityTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._geo_score = _rich_label(_GEO_SCORE_TOOLTIP)
        self._summary = _rich_label(ai_visibility_summary_tooltip())
        # v1.1 N5a-fix — "GEO checks enabled" badge row at the top
        # surfaces which v1.1 measurement groups are actually
        # producing data vs which are gated off (env var / Settings).
        # Refreshed on every update() call with the new payload's
        # check list.
        from .geo_checks_badge import build_badges, render_label, render_tooltip

        self._badge_build = build_badges
        self._badge_render_label = render_label
        self._badge_render_tooltip = render_tooltip
        initial_badges = build_badges([])
        self._badges_label = _rich_label(render_tooltip(initial_badges))
        self._badges_label.setText(render_label(initial_badges))
        # v1.1 N5c — pure-Qt sparkline (no QChart dep). Sits on the
        # same row as the GEO Score label and updates whenever the
        # caller pushes a new history list via set_score_history.
        from .sparkline import Sparkline as _Sparkline  # local import keeps tabs.py optional-free

        self._score_history = _Sparkline()
        self._score_history.setToolTip(
            "GEO Score history. The line auto-scales to the range of the recorded runs; "
            "feed it via AiVisibilityTab.set_score_history([int, ...])."
        )
        header_row = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(self._geo_score)
        header_layout.addStretch(1)
        header_layout.addWidget(self._score_history)
        self._row_resize_pending = False
        self.view.setWordWrap(True)
        self.view.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self.view.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        _header(self.view).sectionResized.connect(self._schedule_row_resize)
        self._layout.insertWidget(0, self._badges_label)
        self._layout.insertWidget(1, header_row)
        self._layout.insertWidget(2, self._summary)

    def set_score_history(self, scores: list[int]) -> None:
        """Push a new GEO Score history series into the sparkline."""
        self._score_history.set_values(scores)

    def _schedule_row_resize(self, *_args: object) -> None:
        if self._row_resize_pending:
            return
        self._row_resize_pending = True
        QtCore.QTimer.singleShot(0, self._apply_row_resize)

    def _apply_row_resize(self) -> None:
        self._row_resize_pending = False
        try:
            if self.view.model() is None:
                return
            if not self.isVisible() or self.view.viewport().width() <= 0:
                return
            self.view.resizeRowsToContents()
        except RuntimeError:
            # A queued resize can fire after a transient detail dialog is closed.
            return

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._schedule_row_resize()
        super().showEvent(event)

    def update(self, data: object) -> None:
        payload = data if isinstance(data, AiVisibilityPayload) else AiVisibilityPayload.from_raw(data)
        summary = payload.summary
        verdict = summary.verdict or "-"
        # Refresh the GEO checks enablement badges. Read from the RAW dict
        # when available — AiVisibilityPayload.from_raw normalizes `info` →
        # `good` (per §1.5 myth rule, treating not-measured as a positive
        # signal), which would hide gated-off features from the badge logic.
        check_dicts = _collect_badge_checks(data, payload)
        badges = self._badge_build(check_dicts)
        self._badges_label.setText(self._badge_render_label(badges))
        self._badges_label.setToolTip(self._badge_render_tooltip(badges))
        self._geo_score.setText(f"<b>GEO Score:</b> {summary.score} / 100")
        self._summary.setText(
            f"<b>Verdict:</b> {verdict} &nbsp; "
            f"<b>Good:</b> {summary.good_count} &nbsp; "
            f"<b>Warnings:</b> {summary.warning_count} &nbsp; "
            f"<b>Critical:</b> {summary.critical_count}"
        )
        rows = [
            [check.area, check.check, check.status.title(), check.details or "-", check.recommendation or "-"]
            for check in payload.checks
        ]
        check_keys = [check.key or "ai_visibility" for check in payload.checks]
        if not rows:
            rows = [["Info", "No AI visibility data yet", "-", "Run an analysis to populate this tab.", "-"]]
            check_keys = ["ai_visibility"]
        self.set_model(AiVisibilityModel(_AI_VISIBILITY_HEADERS, rows, check_keys, _AI_VISIBILITY_HEADER_TOOLTIPS))
        _set_header_modes(
            _header(self.view),
            (0, QtWidgets.QHeaderView.ResizeToContents),
            (1, QtWidgets.QHeaderView.Stretch),
            (2, QtWidgets.QHeaderView.ResizeToContents),
            (3, QtWidgets.QHeaderView.Stretch),
            (4, QtWidgets.QHeaderView.Stretch),
        )
        self._schedule_row_resize()


class KeywordsTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._summary = _rich_label()
        self._entries: list[KeywordEntry] = []
        self._applying_palette = False
        self._layout.insertWidget(0, self._summary)

    def update(self, rows: list[object]) -> None:
        entries: list[KeywordEntry] = []
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
        _set_header_modes(header, (0, QtWidgets.QHeaderView.Stretch))
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

    def _summary_text(self, entries: list[KeywordEntry]) -> str:
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
            f"<b>Top focus keywords:</b> {_html.escape(dominant)}<br>"
            f"<b>Terms in title:</b> {title_hits} &nbsp; "
            f"<b>Heading coverage:</b> {heading_coverage}"
            f"{alerts}"
        )


class PerformanceTab(TableTab):
    def __init__(self) -> None:
        super().__init__(sorting=True)
        self._summary = _rich_label()
        self._opportunities = _rich_label()
        self._scripts = _rich_label()
        self._offender_view: QtWidgets.QTableView = QtWidgets.QTableView()
        _configure_table_view_geometry(self._offender_view)
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
            dark_theme = _is_dark(self)
            self._summary.setText(self._summary_html(metrics))
            self._summary.setToolTip(performance_summary_tooltip())
            self._scripts.setText(self._scripts_html(metrics))
            self._scripts.setToolTip(performance_resource_tooltip())
            self._apply_summary_styles(metrics, dark_theme)
            issue_rows, issue_keys = self._issue_table_data(metrics)
            model = PerformanceIssueModel(["Issue", "Severity", "Evidence", "Recommendation"], issue_rows, issue_keys)
            self.set_model(model)
            _set_header_modes(
                _header(self.view),
                (0, QtWidgets.QHeaderView.Stretch),
                (1, QtWidgets.QHeaderView.ResizeToContents),
                (2, QtWidgets.QHeaderView.Stretch),
                (3, QtWidgets.QHeaderView.Stretch),
            )
            self._opportunities.setText(self._opportunities_html(metrics, dark_theme))
            self._offender_view.setModel(GenericModel(["Type", "URL", "Script", "Bytes"], self._offender_rows(metrics)))
            _set_header_modes(
                _header(self._offender_view),
                (0, QtWidgets.QHeaderView.ResizeToContents),
                (1, QtWidgets.QHeaderView.Stretch),
                (2, QtWidgets.QHeaderView.ResizeToContents),
                (3, QtWidgets.QHeaderView.ResizeToContents),
            )
            self._apply_table_palette(self.view)
            self._apply_table_palette(self._offender_view)
        finally:
            self._is_rendering = False

    def _resource_bytes(self, metrics: PerformanceMetrics) -> dict[str, int]:
        if metrics.resource_breakdown:
            return {row.resource_type: row.bytes for row in metrics.resource_breakdown}
        return {name: info.get("bytes", 0) for name, info in metrics.resource_summary.items()}

    def _summary_html(self, metrics: PerformanceMetrics) -> str:
        summary = metrics.summary
        total_bytes = summary.total_page_bytes or (
            metrics.transfer_size + sum(info.get("bytes", 0) for info in metrics.resource_summary.values())
        )
        resource_count = summary.total_resource_count or sum(
            info.get("count", 0) for info in metrics.resource_summary.values()
        )
        return (
            f"<b>Verdict:</b> {summary.verdict or 'Good'} &nbsp; "
            f"<b>Status:</b> {metrics.status or '-'} &nbsp; "
            f"<b>TTFB:</b> {metrics.nav_ttfb_ms:.0f} ms &nbsp; "
            f"<b>Total:</b> {metrics.nav_total_ms:.0f} ms &nbsp; "
            f"<b>Transfer:</b> {self._format_bytes(summary.transfer_size or metrics.transfer_size)} &nbsp; "
            f"<b>Page weight:</b> {self._format_bytes(total_bytes)} &nbsp; "
            f"<b>Resources:</b> {resource_count} &nbsp; "
            f"<b>Third-party:</b> {self._format_bytes(summary.third_party_bytes)}"
        )

    def _scripts_html(self, metrics: PerformanceMetrics) -> str:
        resource_bytes = self._resource_bytes(metrics)
        return (
            f"<b>Blocking JS:</b> {metrics.scripts.blocking_count} "
            f"({self._format_bytes(metrics.scripts.blocking_bytes)}) &nbsp; "
            f"<b>Async/Deferred JS:</b> {metrics.scripts.async_count} "
            f"({self._format_bytes(metrics.scripts.async_bytes)})<br/>"
            f"<b>CSS:</b> {self._format_bytes(resource_bytes.get('css', 0))} &nbsp; "
            f"<b>JS:</b> {self._format_bytes(resource_bytes.get('js', 0))} &nbsp; "
            f"<b>Images:</b> {self._format_bytes(resource_bytes.get('img', 0))} &nbsp; "
            f"<b>Fonts:</b> {self._format_bytes(resource_bytes.get('font', 0))}"
        )

    @staticmethod
    def _dominant_severity(metrics: PerformanceMetrics) -> str:
        summary = metrics.summary
        if summary.critical_issue_count > 0:
            return "critical"
        if summary.warning_issue_count > 0:
            return "warning"
        if summary.info_issue_count > 0:
            return "info"
        if metrics.opportunity_details:
            severity_order = {"critical": 3, "warning": 2, "info": 1, "ok": 0}
            return max(
                (detail.severity.lower() or "info" for detail in metrics.opportunity_details),
                key=lambda severity: severity_order.get(severity, 1),
                default="info",
            )
        return "info" if metrics.opportunities else "ok"

    @staticmethod
    def _severity_styles(dark_theme: bool) -> dict[str, tuple[str, str]]:
        if dark_theme:
            return {
                "critical": ("#3b1f21", "#ffb4ab"),
                "warning": ("#3b3017", "#ffe082"),
                "info": ("#1b2f47", "#90caf9"),
                "ok": ("#1f3325", "#a5d6a7"),
            }
        return {
            "critical": ("#ffebee", "#c62828"),
            "warning": ("#fff8e1", "#ef6c00"),
            "info": ("#e3f2fd", "#1565c0"),
            "ok": ("#e8f5e9", "#2e7d32"),
        }

    def _apply_summary_styles(self, metrics: PerformanceMetrics, dark_theme: bool) -> None:
        bg_color, fg_color = self._severity_styles(dark_theme).get(
            self._dominant_severity(metrics),
            self._severity_styles(dark_theme)["info"],
        )
        style_block = (
            f"background:{bg_color};color:{fg_color};padding:6px;border-radius:4px;"
            "border:1px solid rgba(255,255,255,0.05);"
        )
        self._summary.setStyleSheet(style_block)
        self._scripts.setStyleSheet(style_block)
        self._opportunities.setStyleSheet(
            "color:#f0f0f0;margin-top:6px;" if dark_theme else "color:#202124;margin-top:6px;"
        )

    @staticmethod
    def _issue_table_data(metrics: PerformanceMetrics) -> tuple[list[list[str]], list[str]]:
        rows = [
            [
                issue.message or "-",
                issue.severity.title(),
                issue.evidence or "-",
                issue.recommendation or "-",
            ]
            for issue in metrics.issues
        ]
        if rows:
            return rows, [issue.key for issue in metrics.issues]
        return [["No major performance issues detected", "OK", "-", "-"]], [""]

    @staticmethod
    def _badge_palette(dark_theme: bool) -> tuple[dict[str, str], str, str]:
        if dark_theme:
            return (
                {"critical": "#ff5252", "warning": "#ffca28", "info": "#64b5f6", "ok": "#81c784"},
                "#121212",
                "#b2dfdb",
            )
        return (
            {"critical": "#d32f2f", "warning": "#fbc02d", "info": "#1976d2", "ok": "#2e7d32"},
            "#ffffff",
            "#2e7d32",
        )

    @staticmethod
    def _badge_html(color: str, text_color: str, label: str) -> str:
        return (
            "<span style='display:inline-block;padding:1px 6px;"
            f"border-radius:10px;background:{color};color:{text_color};"
            "font-weight:bold;font-size:11px;'>"
            f"{label}</span>"
        )

    def _opportunities_html(self, metrics: PerformanceMetrics, dark_theme: bool) -> str:
        badge_colors, badge_text_color, ok_text = self._badge_palette(dark_theme)
        if metrics.opportunity_details:
            items = [
                "<li>{badge} {message}</li>".format(
                    badge=self._badge_html(
                        badge_colors.get(detail.severity.lower() or "info", badge_colors["info"]),
                        badge_text_color,
                        (detail.severity or "Info").title(),
                    ),
                    message=_html.escape(detail.message),
                )
                for detail in metrics.opportunity_details
            ]
            return f"<b>Opportunities</b><ul>{''.join(items)}</ul>"
        if metrics.opportunities:
            items = [f"<li>{_html.escape(item)}</li>" for item in metrics.opportunities]
            return f"<b>Opportunities</b><ul>{''.join(items)}</ul>"
        return (
            "<b>Opportunities</b><br/>"
            f"{self._badge_html(badge_colors['ok'], badge_text_color, 'OK')} "
            f"<span style='color:{ok_text}'>No issues detected.</span>"
        )

    def _offender_rows(self, metrics: PerformanceMetrics) -> list[list[str]]:
        rows = [
            [
                offender.resource_type.upper() or "-",
                offender.url or "-",
                "Blocking" if offender.blocking else "Async",
                self._format_bytes(offender.bytes),
            ]
            for offender in metrics.top_offenders
        ]
        return rows or [["-", "-", "-", "-"]]

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
    errors: list[str]
    text: str
    # v2.0 hotfix follow-up: group nested component types (PostalAddress,
    # ListItem, Offer…) under their parent instead of as independent blocks.
    role: str = "primary"
    nested_in: str = ""
    type_hint: str = ""


class SchemaTab(QtWidgets.QTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self._state: dict[str, Any] | None = None
        self._is_rendering = False

    def update(self, payload: Any) -> None:
        report = StructuredDataPayload.from_raw(payload)
        blocks: list[Any] = list(report.blocks)
        if not blocks and report.fallback_raw:
            blocks = [{"@raw": raw, "_extracted_via": "json-ld-raw"} for raw in report.fallback_raw]
        if not blocks:
            self._state = None
            self.setHtml("<span style='color:#c62828;font-weight:bold'>Structured data not found</span>")
            return

        summary = report.summary
        syntax_counts = {
            name: count for name, count in summary.by_syntax.items() if count
        } or self._fallback_syntax_counts(blocks)
        type_counts = {name: count for name, count in summary.by_type.items() if count} or self._fallback_type_counts(
            blocks
        )

        total = summary.total or sum(syntax_counts.values()) or len(blocks)
        block_models = [self._build_schema_block(idx, item) for idx, item in enumerate(blocks, start=1)]
        self._state = {
            "summary": summary,
            "blocks": block_models,
            "syntax_counts": syntax_counts,
            "type_counts": type_counts,
            "eligibility": list(report.eligibility),
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

    def _theme(self) -> dict[str, str]:
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

            syntax_counts = self._state["syntax_counts"]
            type_counts = self._state["type_counts"]
            eligibility = self._state["eligibility"]
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
            syntax_text = (
                ", ".join(f"{syntax_labels.get(name, name)} {syntax_counts[name]}" for name in sorted(syntax_counts))
                or "none"
            )
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
            block_models = self._state["blocks"]
            nested_count = sum(1 for b in block_models if getattr(b, "role", "primary") == "nested")
            primary_count = max(0, len(block_models) - nested_count)
            count_text = f"{primary_count} item{'s' if primary_count != 1 else ''}"
            if nested_count:
                count_text += f" (+{nested_count} nested component{'s' if nested_count != 1 else ''})"
            header = (
                f"<div style='font-weight:bold;color:{header_color}'>Structured data: {count_text} &nbsp; "
                f"(Syntax: {syntax_text}){type_text}</div>"
            )
            eligibility_html = self._render_eligibility(eligibility, theme)

            if issues:
                items_html = "".join(f"<li>{_html.escape(item)}</li>" for item in issues)
                issue_html = (
                    f"<div style='color:{theme['issue']};margin:6px 0'><b>Issues</b><ul>{items_html}</ul></div>"
                )
            else:
                issue_html = ""

            block_html = self._render_blocks_grouped(self._state["blocks"], theme)
            self.setHtml(header + eligibility_html + issue_html + block_html)
        finally:
            self._is_rendering = False

    @staticmethod
    def _render_eligibility(rows: list[Any], theme: dict[str, str]) -> str:
        if not rows:
            return ""
        status_colors = {
            "eligible": theme["ok"],
            "incomplete": theme["warn"],
            "not detected": theme["foreground"],
        }
        header = (
            "<div style='margin-top:10px;font-weight:bold'>Eligibility summary</div>"
            "<table style='width:100%;border-collapse:collapse;margin-top:6px'>"
            "<tr>"
            f"<th style='text-align:left;border:1px solid {theme['block_border']};padding:4px;background:{theme['block_bg']}'>Type</th>"
            f"<th style='text-align:left;border:1px solid {theme['block_border']};padding:4px;background:{theme['block_bg']}'>Detected</th>"
            f"<th style='text-align:left;border:1px solid {theme['block_border']};padding:4px;background:{theme['block_bg']}'>Eligibility</th>"
            f"<th style='text-align:left;border:1px solid {theme['block_border']};padding:4px;background:{theme['block_bg']}'>Missing fields</th>"
            f"<th style='text-align:left;border:1px solid {theme['block_border']};padding:4px;background:{theme['block_bg']}'>Warnings</th>"
            "</tr>"
        )
        body = []
        for row in rows:
            status = str(getattr(row, "eligibility", "")).strip()
            status_color = status_colors.get(status.lower(), theme["foreground"])
            detected = "Yes" if getattr(row, "detected", False) else "No"
            count = int(getattr(row, "count", 0) or 0)
            detected_text = detected if count <= 1 else f"{detected} ({count} blocks)"
            missing_fields = getattr(row, "missing_fields", []) or []
            warnings = getattr(row, "warnings", []) or []
            body.append(
                "<tr>"
                f"<td style='border:1px solid {theme['block_border']};padding:4px'>{_html.escape(str(getattr(row, 'schema_type', '')))}</td>"
                f"<td style='border:1px solid {theme['block_border']};padding:4px'>{_html.escape(detected_text)}</td>"
                f"<td style='border:1px solid {theme['block_border']};padding:4px;color:{status_color};font-weight:bold'>{_html.escape(status)}</td>"
                f"<td style='border:1px solid {theme['block_border']};padding:4px'>{_html.escape(', '.join(missing_fields) or '-')}</td>"
                f"<td style='border:1px solid {theme['block_border']};padding:4px'>{_html.escape('; '.join(warnings) or '-')}</td>"
                "</tr>"
            )
        return header + "".join(body) + "</table>"

    @staticmethod
    def _fallback_syntax_counts(blocks: list[Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in blocks:
            if isinstance(item, dict):
                via = str(item.get("_extracted_via", "")).strip()
                if via:
                    counts[via] = counts.get(via, 0) + 1
        return counts

    @staticmethod
    def _fallback_type_counts(blocks: list[Any]) -> dict[str, int]:
        counts: dict[str, int] = {}
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
            internal = {"_schema_errors", "_schema_role", "_schema_nested_in"}
            cleaned = {key: value for key, value in item.items() if key not in internal}
            text = json.dumps(cleaned, indent=2, ensure_ascii=False)
            if "@raw" in cleaned and isinstance(cleaned["@raw"], str):
                label = f"{label} (JSON-LD raw)"
            role = str(item.get("_schema_role", "primary")).strip() or "primary"
            nested_in = str(item.get("_schema_nested_in", "")).strip()
            return _SchemaBlock(label, errors, text, role=role, nested_in=nested_in, type_hint=type_hint)
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
    def _render_blocks_grouped(blocks: list[_SchemaBlock], theme: dict[str, str]) -> str:
        """Render top-level (primary) blocks, with each block's nested
        component types grouped + labelled directly beneath it instead of
        as independent blocks."""
        primary = [b for b in blocks if b.role != "nested"]
        nested = [b for b in blocks if b.role == "nested"]
        parts: list[str] = []
        used: set[int] = set()
        for block in primary:
            parts.append(SchemaTab._render_block(block, theme))
            for child in nested:
                if id(child) not in used and child.nested_in and child.nested_in == block.type_hint:
                    used.add(id(child))
                    parts.append(SchemaTab._render_block(child, theme, nested=True))
        leftover = [b for b in nested if id(b) not in used]
        if leftover:
            parts.append(
                f"<div style='margin-top:14px;font-weight:bold;color:{theme['foreground']}'>"
                "Other nested components</div>"
            )
            parts.extend(SchemaTab._render_block(child, theme, nested=True) for child in leftover)
        return "".join(parts)

    @staticmethod
    def _render_block(block: _SchemaBlock, theme: dict[str, str], nested: bool = False) -> str:
        label_color = theme["issue"] if block.errors else theme["foreground"]
        error_section = ""
        if block.errors:
            error_items = "".join(f"<li>{_html.escape(err)}</li>" for err in block.errors)
            error_section = f"<ul style='margin:4px 0 8px 18px;color:{theme['issue']}'>{error_items}</ul>"
        if nested:
            tag = f"&#8627; nested component &middot; in {_html.escape(block.nested_in or 'parent')}"
            badge = f"<span style='color:{theme['warn']};font-size:11px;font-weight:bold'>{tag}</span>"
            wrapper_open = (
                f"<div style='margin:6px 0 6px 22px;border-left:2px solid {theme['block_border']};padding-left:10px'>"
            )
            label_html = f"<div style='color:{label_color}'>{_html.escape(block.label)} &nbsp; {badge}</div>"
        else:
            wrapper_open = "<div style='margin-top:10px'>"
            label_html = f"<div style='font-weight:bold;color:{label_color}'>{_html.escape(block.label)}</div>"
        return (
            f"{wrapper_open}"
            f"{label_html}"
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
        _configure_table_view_geometry(self.table)
        self.table.setSortingEnabled(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview)
        layout.addWidget(self.table)
        self._model: QtCore.QAbstractTableModel | None = None

    def update(self, serp: dict[str, str], audit: dict[str, str]) -> None:
        description = serp.get("description", "")
        if len(description) > 160:
            description = description[:157].rstrip() + ""

        self.preview.setStyleSheet("background:#ffffff;color:#202124;border:1px solid #d0d0d0;")
        favicon_html = ""
        if serp.get("favicon"):
            favicon_html = f"<img src=\"{serp['favicon']}\" width='30' height='30' alt='icon'/>"
        serp_html = f"""
        <div style='font-family:Roboto,Arial,sans-serif;font-size:14px;line-height:1.3;background:#ffffff;color:#202124;padding:8px'>
           <table cellpadding='0' cellspacing='0' style='border:none;margin:0;padding:0'>
              <tr>
                <td rowspan='2' style='padding-right:6px;vertical-align:middle'>
                  {favicon_html}
                </td>
                <td style='font-size:14px;color:#202124;font-weight:500;vertical-align:bottom'>
                  {serp.get("site_name", "")}
                </td>
              </tr>
              <tr>
                <td style='font-size:12px;color:#4d5156;vertical-align:top'>
                  {serp.get("breadcrumb", "")}
                </td>
              </tr>
            </table>
            <div>
                <a href='{serp.get("url", "")}'
                style='font-size:18px;font-weight:400;color:#1a0dab;text-decoration:none;display:inline-block;max-width:600px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>
                    {serp.get("title", "")}
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
    "ContentQualityTab",
    "RobotsTab",
    "HreflangTab",
    "BotMatrixTab",
    "AiVisibilityTab",
    "KeywordsTab",
    "PerformanceTab",
    "SchemaTab",
    "SerpTab",
    "SocialTab",
]
