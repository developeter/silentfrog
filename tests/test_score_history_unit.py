"""Tests for the v1.1 N5d per-URL GEO Score history store."""

from __future__ import annotations

import pytest

from silentfrog import score_history


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(score_history, "_data_dir", lambda: tmp_path)


def test_recent_returns_empty_when_url_unseen() -> None:
    assert score_history.recent("https://example.com/") == []


def test_record_appends_and_returns_recent_in_order() -> None:
    url = "https://example.com/"
    for score in (90, 88, 92, 85):
        score_history.record(url, score)
    assert score_history.recent(url) == [90, 88, 92, 85]


def test_record_caps_series_at_max_scores(monkeypatch) -> None:
    monkeypatch.setattr(score_history, "_MAX_SCORES", 3)
    url = "https://example.com/"
    for score in (10, 20, 30, 40, 50):
        score_history.record(url, score)
    assert score_history.recent(url) == [30, 40, 50]


def test_recent_respects_limit() -> None:
    url = "https://example.com/"
    for score in range(80, 90):
        score_history.record(url, score)
    assert score_history.recent(url, limit=3) == [87, 88, 89]


def test_recent_with_zero_limit_returns_full_series() -> None:
    url = "https://example.com/"
    for score in (80, 81, 82):
        score_history.record(url, score)
    assert score_history.recent(url, limit=0) == [80, 81, 82]


def test_record_ignores_empty_url() -> None:
    score_history.record("", 90)
    assert score_history.recent("") == []


def test_clear_removes_store(tmp_path) -> None:
    url = "https://example.com/"
    score_history.record(url, 90)
    assert score_history.recent(url) == [90]
    score_history.clear()
    assert score_history.recent(url) == []


def test_corrupt_file_is_treated_as_empty(tmp_path) -> None:
    (tmp_path / "geo_score_history.json").write_text("not json", encoding="utf-8")
    assert score_history.recent("https://example.com/") == []


def test_multiple_urls_kept_independent() -> None:
    score_history.record("https://a.com/", 70)
    score_history.record("https://b.com/", 95)
    assert score_history.recent("https://a.com/") == [70]
    assert score_history.recent("https://b.com/") == [95]


def test_seo_window_records_score_and_pushes_to_sparkline(qtbot) -> None:
    """End-to-end: _update_content_tabs records the score and the
    AiVisibilityTab's sparkline picks it up."""
    from silentfrog.seo_gui import WebpageSeoWindow

    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    win.url_edit.setEditText("https://example.com/sparkline-test")
    data = {
        "ai_visibility": {
            "summary": {
                "score": 82,
                "verdict": "Strong",
                "good_count": 5,
                "warning_count": 1,
                "critical_count": 0,
            },
            "checks": [],
        },
        "images": [],
        "links": [],
        "hreflang": [],
        "content_quality": {},
        "keywords": [],
        "ai_crawl": [],
        "performance": {},
        "schema": {},
        "social": {},
        "redirect": {},
        "canonical": {},
        "meta_robots": "",
        "robots": {},
        "serp": {},
        "serp_audit": {},
    }
    win._record_geo_score_history(data)
    assert score_history.recent("https://example.com/sparkline-test") == [82]
    assert win.ai_visibility_tab._score_history.values() == [82]
