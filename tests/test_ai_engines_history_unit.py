"""Unit tests for the v3 G3 Stage 1 AI-engine share-of-voice history store
(offline — no HTTP, isolated on-disk JSON file per test)."""

from __future__ import annotations

import pytest

from silentfrog.integrations.ai_engines.history import _FILE_NAME, _MAX_SERIES_POINTS, record_point

_DAY = 24 * 60 * 60


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))


_STATS = {"openai": {"mentions": 2, "citations": 1, "prompts": 3}}


def test_record_point_appends_new_days() -> None:
    base = 1_750_000_000
    first = record_point("acme.com", _STATS, now=base)
    assert len(first) == 1
    second = record_point("acme.com", {"openai": {"mentions": 3, "citations": 1, "prompts": 3}}, now=base + _DAY)
    assert len(second) == 2
    assert second[0]["engines"]["openai"]["mentions"] == 2
    assert second[1]["engines"]["openai"]["mentions"] == 3


def test_record_point_replaces_same_day() -> None:
    base = 1_750_000_000
    record_point("acme.com", _STATS, now=base)
    replaced = record_point("acme.com", {"openai": {"mentions": 9, "citations": 9, "prompts": 3}}, now=base + 60)
    assert len(replaced) == 1
    assert replaced[0]["engines"]["openai"]["mentions"] == 9


def test_record_point_caps_series_at_max() -> None:
    base = 1_750_000_000
    series = []
    for day in range(_MAX_SERIES_POINTS + 10):
        series = record_point("acme.com", _STATS, now=base + day * _DAY)
    assert len(series) == _MAX_SERIES_POINTS
    # Oldest-first: the cap drops the earliest points, keeping the latest.
    assert series[-1]["ts"] == base + (_MAX_SERIES_POINTS + 9) * _DAY


def test_record_point_empty_host_is_noop() -> None:
    assert record_point("", _STATS) == []


def test_corrupt_history_file_starts_fresh(tmp_path) -> None:
    path = tmp_path / _FILE_NAME
    path.write_text("{not valid json", encoding="utf-8")
    series = record_point("acme.com", _STATS, now=1_750_000_000)
    assert len(series) == 1
    assert series[0]["engines"]["openai"]["mentions"] == 2


def test_history_keeps_series_isolated_per_host() -> None:
    record_point("acme.com", _STATS, now=1_750_000_000)
    record_point("other.com", _STATS, now=1_750_000_000)
    acme_series = record_point("acme.com", _STATS, now=1_750_086_400)  # next day
    assert len(acme_series) == 2
