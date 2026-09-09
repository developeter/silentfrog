from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from silentfrog.redirect import (  # type: ignore[reportMissingImports]
    RedirectRunResult,
    RedirectSummary,
)
from silentfrog.redirect_gui import RedirectWindow, _summary_text  # type: ignore[reportMissingImports]


def _window(qtbot) -> RedirectWindow:
    window = RedirectWindow()
    qtbot.addWidget(window)
    return window


def _result(tmp_path: pathlib.Path, **summary_kwargs) -> RedirectRunResult:
    report = tmp_path / "input_results.xlsx"
    pd.DataFrame({"Old URL": []}).to_excel(report, index=False)
    return RedirectRunResult(report, RedirectSummary(**summary_kwargs), cancelled=False)


def test_controls_are_usable_again_after_a_run(qtbot, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Regression: Start and every option widget were disabled on launch and
    never re-enabled, so a second file could not be checked without closing
    and reopening the window. The report dialog is stubbed out because it is
    modal; the control state around it is the behaviour under test."""
    window = _window(qtbot)
    monkeypatch.setattr(RedirectWindow, "_show_report", lambda self, result: None)
    window.excel_path = str(tmp_path / "input.xlsx")
    window._set_controls_enabled(False)

    window._on_finish(_result(tmp_path, total=1, correct=1))

    assert window.btn_start.isEnabled()
    assert window.spin_timeout.isEnabled()
    assert window.chk_robots.isEnabled()
    assert window.btn_pause.isEnabled() is False
    assert window.btn_open.isEnabled()


def test_a_failed_load_leaves_the_window_usable(qtbot, tmp_path: pathlib.Path) -> None:
    window = _window(qtbot)
    window.excel_path = str(tmp_path / "input.xlsx")
    window._set_controls_enabled(False)

    window._on_finish(None)

    assert window.btn_start.isEnabled()
    assert window.btn_open.isEnabled() is False


def test_options_come_from_the_widgets_including_the_ssrf_opt_in(qtbot) -> None:
    window = _window(qtbot)
    window.spin_timeout.setValue(21)
    window.spin_threads.setValue(3)
    window.chk_robots.setChecked(False)
    window.chk_ssl.setChecked(True)
    window.chk_private.setChecked(True)

    options = window._current_options()

    assert options.timeout == 21
    assert options.max_workers == 3
    assert options.respect_robots is False
    assert options.verify_ssl is False, "the checkbox reads 'ignore TLS errors', so verification must be off"
    assert options.allow_private_network is True


def test_private_network_is_opt_in_by_default(qtbot) -> None:
    assert _window(qtbot)._current_options().allow_private_network is False


def test_log_is_capped_so_a_huge_sheet_cannot_grow_it_without_bound(qtbot) -> None:
    window = _window(qtbot)
    for index in range(2500):
        window.txt_log.appendPlainText(f"row {index}")

    assert window.txt_log.blockCount() <= 2000


@pytest.mark.parametrize(
    ("summary", "cancelled", "expected"),
    [
        (RedirectSummary(total=3, correct=3), False, "3 of 3 redirects correct"),
        (RedirectSummary(total=3, correct=1, wrong=2, loops=1), False, "2 to fix"),
        (RedirectSummary(total=3, correct=3), True, "Stopped early."),
    ],
)
def test_summary_text_says_what_happened(summary: RedirectSummary, cancelled: bool, expected: str) -> None:
    assert expected in _summary_text(summary, cancelled)
