"""Tests for the v1.1 N5a-fix Bot Matrix heatmap (model + tab)."""

from __future__ import annotations

from qtpy import QtCore, QtGui

from silentfrog.models import BotMatrixModel, build_bot_rows
from silentfrog.models.bot_matrix import (
    COL_BOT,
    COL_LLMS,
    COL_META,
    COL_ROBOTS,
    COL_SSR,
    COL_VERDICT,
    HEATMAP_HEADERS,
)
from silentfrog.tabs import BotMatrixTab


def _ai_crawl(verdict: str = "Allowed", robots_ok: str = "Yes") -> list[str]:
    return [
        "GPTBot",
        "gptbot",
        robots_ok,
        "-",
        "-",
        verdict,
        "No explicit AI restrictions detected",
    ]


def test_headers_are_exactly_six_named_columns() -> None:
    assert HEATMAP_HEADERS == [
        "Bot",
        "Robots.txt",
        "Meta robots",
        "llms.txt",
        "SSR parity",
        "Verdict",
    ]


def test_build_bot_rows_skips_malformed_rows() -> None:
    rows = build_bot_rows(
        [_ai_crawl(), ["incomplete"], "not a row"],
        discovery=None,
        render=None,
    )
    assert len(rows) == 1
    assert rows[0].label == "GPTBot"


def test_model_column_count_is_six_and_row_count_matches_input() -> None:
    bots = build_bot_rows([_ai_crawl(), _ai_crawl(robots_ok="No", verdict="Blocked")])
    model = BotMatrixModel(bots)
    assert model.columnCount() == 6
    assert model.rowCount() == 2


def test_column_zero_is_text_only_other_columns_render_chips() -> None:
    bots = build_bot_rows([_ai_crawl()])
    model = BotMatrixModel(bots)
    display = model.data(model.index(0, COL_BOT), QtCore.Qt.ItemDataRole.DisplayRole)
    assert display == "GPTBot"
    bg = model.data(model.index(0, COL_BOT), QtCore.Qt.ItemDataRole.BackgroundRole)
    assert bg is None
    # Chip columns: DisplayRole is empty, BackgroundRole is a QBrush.
    for col in (COL_ROBOTS, COL_META, COL_LLMS, COL_SSR, COL_VERDICT):
        chip_display = model.data(model.index(0, col), QtCore.Qt.ItemDataRole.DisplayRole)
        chip_bg = model.data(model.index(0, col), QtCore.Qt.ItemDataRole.BackgroundRole)
        assert chip_display == ""
        assert isinstance(chip_bg, QtGui.QBrush)


def test_per_bot_columns_vary_when_one_bot_is_blocked() -> None:
    rows = build_bot_rows(
        [
            _ai_crawl(verdict="Allowed", robots_ok="Yes"),
            _ai_crawl(verdict="Blocked", robots_ok="No"),
        ]
    )
    model = BotMatrixModel(rows)
    good_brush = model.data(model.index(0, COL_VERDICT), QtCore.Qt.ItemDataRole.BackgroundRole)
    bad_brush = model.data(model.index(1, COL_VERDICT), QtCore.Qt.ItemDataRole.BackgroundRole)
    assert good_brush != bad_brush
    good_robots = model.data(model.index(0, COL_ROBOTS), QtCore.Qt.ItemDataRole.BackgroundRole)
    bad_robots = model.data(model.index(1, COL_ROBOTS), QtCore.Qt.ItemDataRole.BackgroundRole)
    assert good_robots != bad_robots


def test_site_wide_columns_are_uniform_across_all_rows() -> None:
    rows = build_bot_rows(
        [_ai_crawl(), _ai_crawl(verdict="Blocked", robots_ok="No")],
        discovery=None,
        render=None,
    )
    model = BotMatrixModel(rows)
    for col in (COL_META, COL_LLMS, COL_SSR):
        top = model.data(model.index(0, col), QtCore.Qt.ItemDataRole.BackgroundRole)
        bot = model.data(model.index(1, col), QtCore.Qt.ItemDataRole.BackgroundRole)
        assert top == bot, f"site-wide column {col} should be uniform"


def test_llms_column_goes_green_when_site_publishes_either_file() -> None:
    discovery = {"llms_txt": {"present": True}, "well_known_ai_json": {"present": False}}
    rows = build_bot_rows([_ai_crawl()], discovery=discovery)
    model = BotMatrixModel(rows)
    no_discovery_rows = build_bot_rows([_ai_crawl()], discovery=None)
    no_discovery_model = BotMatrixModel(no_discovery_rows)
    present = model.data(model.index(0, COL_LLMS), QtCore.Qt.ItemDataRole.BackgroundRole)
    absent = no_discovery_model.data(
        no_discovery_model.index(0, COL_LLMS),
        QtCore.Qt.ItemDataRole.BackgroundRole,
    )
    assert isinstance(present, QtGui.QBrush)
    assert isinstance(absent, QtGui.QBrush)
    # When present, llms.txt status is `good`; when absent, status is `info`.
    assert present != absent


def test_ssr_parity_grey_when_render_payload_absent() -> None:
    rows = build_bot_rows([_ai_crawl()], render=None)
    model = BotMatrixModel(rows)
    status = model.data(model.index(0, COL_SSR), QtCore.Qt.ItemDataRole.UserRole)
    assert status == "info"


def test_ssr_parity_paints_warning_when_render_status_warning() -> None:
    rows = build_bot_rows([_ai_crawl()], render={"status": "warning", "reason": "DOM mismatch"})
    model = BotMatrixModel(rows)
    status = model.data(model.index(0, COL_SSR), QtCore.Qt.ItemDataRole.UserRole)
    assert status == "warning"


def test_cell_tooltip_names_the_source_signal() -> None:
    rows = build_bot_rows(
        [_ai_crawl()],
        discovery={"llms_txt": {"present": True}},
    )
    model = BotMatrixModel(rows)
    tip = model.data(model.index(0, COL_ROBOTS), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(tip, str) and "robots.txt" in tip.lower()
    site_tip = model.data(model.index(0, COL_LLMS), QtCore.Qt.ItemDataRole.ToolTipRole)
    assert isinstance(site_tip, str) and "site-wide" in site_tip.lower()


def test_bot_detail_preserves_full_seven_column_data() -> None:
    rows = build_bot_rows([_ai_crawl()])
    model = BotMatrixModel(rows)
    detail = model.bot_detail(0)
    assert detail is not None
    assert detail[0] == "GPTBot"
    assert detail[5] == "Allowed"
    assert "No explicit AI restrictions" in detail[6]


def test_bot_matrix_tab_accepts_full_payload_dict(qtbot) -> None:
    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update(
        {
            "ai_crawl": [_ai_crawl(verdict="Blocked", robots_ok="No")],
            "discovery": {"llms_txt": {"present": True}},
            "render": {"status": "good"},
        }
    )
    summary = tab._summary.text()
    assert "Blocked 1" in summary
    model = tab._model
    assert model is not None
    assert model.rowCount() == 1


def test_bot_matrix_tab_accepts_legacy_row_list(qtbot) -> None:
    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update([_ai_crawl()])
    assert tab._model is not None
    assert tab._model.rowCount() == 1


def test_bot_matrix_tab_drill_down_dialog_title_names_the_bot(qtbot, monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _stub_exec(self) -> int:
        captured["title"] = self.windowTitle()
        return 0

    monkeypatch.setattr("qtpy.QtWidgets.QDialog.exec", _stub_exec)
    tab = BotMatrixTab()
    qtbot.addWidget(tab)
    tab.update([_ai_crawl()])
    model = tab._model
    assert model is not None
    tab._on_row_activated(model.index(0, 0))
    assert "GPTBot" in captured["title"]


def test_llms_column_per_bot_from_ai_json_policies() -> None:
    discovery = {
        "well_known_ai_json": {
            "present": True,
            "parsed": {"agents": {"GPTBot": "allow", "ClaudeBot": "disallow"}},
        }
    }
    rows = build_bot_rows(
        [
            ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "ok"],
            ["ClaudeBot", "claudebot", "Yes", "-", "-", "Allowed", "ok"],
            ["PerplexityBot", "perplexitybot", "Yes", "-", "-", "Allowed", "ok"],
        ],
        discovery=discovery,
    )
    by_label = {r.label: r for r in rows}
    # COL_LLMS is column index 3; statuses tuple covers columns 1..5.
    assert by_label["GPTBot"].statuses[COL_LLMS - 1] == "good"  # explicitly allowed
    assert by_label["ClaudeBot"].statuses[COL_LLMS - 1] == "warning"  # explicitly disallowed
    assert by_label["PerplexityBot"].statuses[COL_LLMS - 1] == "good"  # site-wide fallback (ai.json present)


def test_status_glyphs_cover_every_state() -> None:
    # Accessibility: meaning must not depend on colour alone.
    from silentfrog.tabs import bot_matrix_status_glyph

    assert bot_matrix_status_glyph("good") == "✓"
    assert bot_matrix_status_glyph("allowed") == "✓"
    assert bot_matrix_status_glyph("warning") == "!"
    assert bot_matrix_status_glyph("limited") == "!"
    assert bot_matrix_status_glyph("critical") == "✗"
    assert bot_matrix_status_glyph("blocked") == "✗"
    assert bot_matrix_status_glyph("info") == "–"
    assert bot_matrix_status_glyph("not_measured") == "–"
    assert bot_matrix_status_glyph("") == "–"
