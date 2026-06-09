"""Bot Matrix heatmap model (v1.1 N5a-fix).

True per-signal × per-bot heatmap that replaces the colour-only-on-
verdict shape shipped in N5a (commit ``d3671f5``).

Rows: 19 bots from ``parsers_meta._AI_AGENTS``.
Columns: ``Bot``, ``Robots.txt``, ``Meta robots``, ``llms.txt``,
``SSR parity``, ``Verdict``. Cells in columns 1–5 render as coloured
chips (cell background, empty display text); cell tooltips name the
source signal. Only column 0 carries text.

Status semantics per column:

- ``Robots.txt`` (per-bot) — ``good`` when ``Allow``, ``critical``
  when ``Disallow``.
- ``Meta robots`` (site-wide) — ``warning`` when a nonstandard
  ``noai``/``noimageai`` directive is present, ``info`` (grey) when
  absent.
- ``llms.txt`` (site-wide) — ``good`` when either ``llms.txt`` or
  ``.well-known/ai.json`` is present, ``info`` (grey) when absent.
  Per §1.5 myth alignment we NEVER paint this red.
- ``SSR parity`` (site-wide) — mirrors ``render.status``: ``good``
  ⇒ green, ``warning`` ⇒ yellow, ``critical`` ⇒ red, ``not_measured``
  / absent ⇒ ``info`` (grey).
- ``Verdict`` (per-bot) — mirrors the M1 ``_ai_verdict``:
  ``Allowed`` ⇒ good, ``Limited`` ⇒ warning, ``Blocked`` ⇒ critical.

The per-bot drill-down dialog reads the 7-column ``detail`` tuple
that ``build_bot_rows`` carries forward from the source
``ai_crawl`` row.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from qtpy import QtCore, QtGui
from qtpy.QtCore import Qt

from ..theme import StatusBrushPalette, status_brushes

HEATMAP_HEADERS: list[str] = [
    "Bot",
    "Robots.txt",
    "Meta robots",
    "llms.txt",
    "SSR parity",
    "Verdict",
]

HEATMAP_HEADER_TOOLTIPS: list[str] = [
    "The audited AI / search-facing crawler.",
    "Per-bot: green = robots.txt allows this bot to fetch the page, red = robots.txt blocks it.",
    (
        "Site-wide: yellow when a nonstandard `noai` or `noimageai` directive is "
        "present in meta robots; grey when absent. Affects every bot equally."
    ),
    (
        "Site-wide: green when the site publishes llms.txt OR .well-known/ai.json; "
        "grey when neither is present. §1.5 myth rule — absence is informational, "
        "never red."
    ),
    (
        "Site-wide: green = server-rendered DOM matches the JS-rendered DOM; "
        "yellow / red = mismatch. Grey when the SSR parity check is not enabled "
        "(Settings → Run SSR parity check)."
    ),
    (
        "Per-bot: combines robots.txt + nonstandard directives + Google search "
        "controls. Green = Allowed, yellow = Limited (e.g. nosnippet), red = Blocked."
    ),
]

# Column indices for tests and for the drill-down dialog wiring.
COL_BOT = 0
COL_ROBOTS = 1
COL_META = 2
COL_LLMS = 3
COL_SSR = 4
COL_VERDICT = 5

# Header tooltip + cell-tooltip prefix mapping for the per-column source signal.
_PER_BOT_COLUMNS: tuple[int, ...] = (COL_ROBOTS, COL_VERDICT)
_SITE_WIDE_COLUMNS: tuple[int, ...] = (COL_META, COL_LLMS, COL_SSR)


@dataclass(frozen=True)
class BotRow:
    """One row of the heatmap. ``statuses`` and ``tooltips`` are
    parallel tuples covering the 5 non-text columns (1..5)."""

    label: str
    statuses: tuple[str, str, str, str, str]
    tooltips: tuple[str, str, str, str, str]
    detail: tuple[str, str, str, str, str, str, str]


class BotMatrixModel(QtCore.QAbstractTableModel):
    """6-column heatmap. Pass a list of ``BotRow`` from ``build_bot_rows``."""

    HEADERS: list[str] = HEATMAP_HEADERS

    def __init__(self, bots: Sequence[BotRow]) -> None:
        super().__init__()
        self._bots: list[BotRow] = list(bots)
        self._brushes: StatusBrushPalette = status_brushes()
        # Neutral chip for `info` / `not_measured` cells. Reuses Qt
        # gray with low alpha so it sits behind dark + light themes
        # without clashing with the existing StatusBrushPalette.
        self._info_brush = QtGui.QBrush(QtGui.QColor(140, 140, 140, 70))

    # ------------------------------------------------------------------
    # QAbstractTableModel overrides
    # ------------------------------------------------------------------
    def rowCount(  # noqa: N802
        self,
        parent: QtCore.QModelIndex = QtCore.QModelIndex(),
    ) -> int:
        return len(self._bots)

    def columnCount(  # noqa: N802
        self,
        parent: QtCore.QModelIndex = QtCore.QModelIndex(),
    ) -> int:
        return len(HEATMAP_HEADERS)

    def data(  # type: ignore[override]
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._bots):
            return None
        bot = self._bots[row]
        if role == Qt.ItemDataRole.DisplayRole:
            return bot.label if col == COL_BOT else ""
        if role == Qt.ItemDataRole.BackgroundRole:
            if col == COL_BOT:
                return None
            status = bot.statuses[col - 1]
            return self._brush_for_status(status)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == COL_BOT:
                return None
            return bot.tooltips[col - 1]
        if role == Qt.ItemDataRole.UserRole:
            # Tests + the tab's drill-down dialog use UserRole to fetch
            # the raw status string for the cell.
            if col == COL_BOT:
                return bot.label
            return bot.statuses[col - 1]
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != QtCore.Qt.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return HEATMAP_HEADERS[section]
        if role == Qt.ItemDataRole.ToolTipRole:
            return HEATMAP_HEADER_TOOLTIPS[section]
        return None

    # ------------------------------------------------------------------
    # Drill-down accessor
    # ------------------------------------------------------------------
    def bot_detail(self, row: int) -> tuple[str, ...] | None:
        """Return the original 7-column AI crawl detail for ``row`` so the
        drill-down dialog can present the same data the dropped AI crawl
        tab used to surface."""
        if 0 <= row < len(self._bots):
            return self._bots[row].detail
        return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _brush_for_status(self, status: str) -> QtGui.QBrush:
        normalised = (status or "").strip().lower()
        if normalised in {"good", "ok", "pass", "allowed"}:
            return self._brushes.good
        if normalised in {"warning", "warn", "limited"}:
            return self._brushes.warn
        if normalised in {"critical", "bad", "blocked"}:
            return self._brushes.bad
        return self._info_brush


# ---------------------------------------------------------------------------
# Builder — turns the raw payload pieces into a list of BotRow
# ---------------------------------------------------------------------------


def _llms_status(discovery: Mapping[str, Any] | None) -> tuple[str, str]:
    """llms.txt is a positive signal — present ⇒ good, absent ⇒ info.

    `.well-known/ai.json` counts too. Per the §1.5 myth rule we never
    return ``warning`` or ``critical`` for absence.
    """
    if not isinstance(discovery, Mapping):
        return "info", "llms.txt / ai.json: discovery payload absent."
    llms_present = bool(_nested(discovery, ("llms_txt", "present")))
    llms_full_present = bool(_nested(discovery, ("llms_full_txt", "present")))
    ai_json_present = bool(_nested(discovery, ("well_known_ai_json", "present")))
    presence_bits = []
    if llms_present:
        presence_bits.append("llms.txt")
    if llms_full_present:
        presence_bits.append("llms-full.txt")
    if ai_json_present:
        presence_bits.append(".well-known/ai.json")
    if presence_bits:
        return "good", f"Site publishes: {', '.join(presence_bits)} (site-wide — affects every bot)."
    return (
        "info",
        "Site publishes neither llms.txt nor .well-known/ai.json — site-wide signal absent for every bot.",
    )


def _ssr_status(render: Mapping[str, Any] | None) -> tuple[str, str]:
    if not isinstance(render, Mapping) or not render:
        return "info", "SSR parity not measured — enable in Settings → Run SSR parity check."
    raw_status = str(render.get("status", "")).strip().lower()
    reason = str(render.get("reason", "")).strip()
    if raw_status == "good":
        return "good", "SSR / JS rendered DOMs match (site-wide)."
    if raw_status == "warning":
        return "warning", f"SSR parity: warning. {reason}" if reason else "SSR parity: warning."
    if raw_status == "critical":
        return "critical", f"SSR parity: critical. {reason}" if reason else "SSR parity: critical."
    if raw_status == "not_measured":
        return "info", reason or "SSR parity not measured."
    return "info", reason or "SSR parity status unknown."


def _meta_status(nonstandard: str) -> tuple[str, str]:
    text = (nonstandard or "").strip()
    if text and text != "-":
        return "warning", f"Nonstandard directive(s) present (site-wide): {text}."
    return "info", "No nonstandard `noai`/`noimageai` directive on this page (site-wide)."


def _robots_status(robots_ok: str) -> tuple[str, str]:
    value = (robots_ok or "").strip()
    if value.lower() == "yes":
        return "good", "robots.txt allows this bot on this URL."
    if value.lower() == "no":
        return "critical", "robots.txt blocks this bot on this URL."
    return "info", "robots.txt status unknown for this bot."


_VERDICT_STATUS_MAP = {
    "allowed": "good",
    "limited": "warning",
    "blocked": "critical",
}


def _verdict_status(verdict: str, notes: str) -> tuple[str, str]:
    value = (verdict or "").strip().lower()
    label = (verdict or "-").strip() or "-"
    status = _VERDICT_STATUS_MAP.get(value, "info")
    tip = f"Verdict: {label}."
    if notes and notes.strip() not in {"", "-"}:
        tip = f"{tip} {notes.strip()}"
    return status, tip


def _nested(mapping: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def build_bot_rows(
    ai_crawl_rows: Sequence[Sequence[Any]],
    discovery: Mapping[str, Any] | None = None,
    render: Mapping[str, Any] | None = None,
) -> list[BotRow]:
    """Produce one ``BotRow`` per AI crawl row.

    ``ai_crawl_rows`` carries the 7-column shape emitted by
    ``parsers_meta._ai_crawl_matrix``: ``[Agent, Token, Robots.txt OK,
    Nonstandard directive, Google controls, Verdict, Notes]``.

    Site-wide signals (llms.txt, SSR parity) are computed once and
    replicated across every row.
    """
    llms_status, llms_tip = _llms_status(discovery)
    ssr_status, ssr_tip = _ssr_status(render)
    rows: list[BotRow] = []
    for raw in ai_crawl_rows:
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            continue
        if len(raw) < 7:
            continue
        bot, token, robots_ok, nonstandard, controls, verdict, notes = (str(value) for value in raw[:7])
        robots_status, robots_tip = _robots_status(robots_ok)
        meta_status, meta_tip = _meta_status(nonstandard)
        verdict_status, verdict_tip = _verdict_status(verdict, notes)
        rows.append(
            BotRow(
                label=bot,
                statuses=(robots_status, meta_status, llms_status, ssr_status, verdict_status),
                tooltips=(robots_tip, meta_tip, llms_tip, ssr_tip, verdict_tip),
                detail=(bot, token, robots_ok, nonstandard, controls, verdict, notes),
            )
        )
    return rows


__all__ = [
    "BotMatrixModel",
    "BotRow",
    "COL_BOT",
    "COL_LLMS",
    "COL_META",
    "COL_ROBOTS",
    "COL_SSR",
    "COL_VERDICT",
    "HEATMAP_HEADERS",
    "HEATMAP_HEADER_TOOLTIPS",
    "build_bot_rows",
]
