"""Smoke tests for the v1.1 N5b Multi-URL Dashboard window."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from silentfrog.dashboard_gui import DashboardWindow, parse_urls


@dataclass
class _Summary:
    score: int = 80
    verdict: str = "Strong"
    good_count: int = 0
    warning_count: int = 0
    critical_count: int = 0


@dataclass
class _Check:
    area: str
    check: str
    status: str
    key: str = "x"


@dataclass
class _AiV:
    summary: _Summary
    checks: list[_Check]


@dataclass
class _Payload:
    ai_visibility: _AiV


def _payload(score: int = 80, warning: str = "") -> _Payload:
    checks = []
    if warning:
        checks.append(_Check("Topic clarity", warning, "warning"))
    return _Payload(_AiV(summary=_Summary(score=score), checks=checks))


def test_parse_urls_keeps_valid_http_entries() -> None:
    text = "https://example.com/a\n  https://example.com/b\nftp://nope.com\ngarbage line\nhttp://example.com/c,\n"
    assert parse_urls(text) == [
        "https://example.com/a",
        "https://example.com/b",
        "http://example.com/c",
    ]


def test_parse_urls_empty_input() -> None:
    assert parse_urls("") == []
    assert parse_urls("\n  \n") == []


def test_dashboard_window_has_expected_widgets(qtbot) -> None:
    win = DashboardWindow()
    qtbot.addWidget(win)
    assert win.windowTitle().startswith("Silentfrog")
    assert win.audit_button is not None
    assert win.url_input is not None
    assert win.results_table is not None
    assert win.results_table.columnCount() == 4


def test_dashboard_audit_no_urls_updates_status(qtbot) -> None:
    win = DashboardWindow()
    qtbot.addWidget(win)
    win.url_input.setPlainText("garbage\nftp://no")
    win.audit_button.click()
    assert "No valid URLs" in win.status_label.text()


@pytest.mark.qt_no_exception_capture
def test_dashboard_audit_populates_table_with_stubbed_analyser(qtbot) -> None:
    async def _stub(url: str):
        return _payload(score=90 if "good" in url else 60, warning="Some warning")

    win = DashboardWindow(analyser=_stub)
    qtbot.addWidget(win)
    win.url_input.setPlainText("https://example.com/good\nhttps://example.com/bad")
    win.audit_button.click()
    qtbot.waitUntil(lambda: win.audit_button.isEnabled(), timeout=5000)
    assert win.results_table.rowCount() == 2
    scores = [win.results_table.item(row, 1).data(0) if win.results_table.item(row, 1) else None for row in range(2)]
    assert 90 in scores
    assert 60 in scores
