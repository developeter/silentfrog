"""Unit tests for the v2.0 V17 Semrush daily call budget."""

from __future__ import annotations

import importlib

from silentfrog.integrations.semrush import budget


def test_remaining_decrements_after_record_call(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    assert budget.remaining(5) == 5
    budget.record_call()
    assert budget.remaining(5) == 4
    budget.record_call()
    assert budget.remaining(5) == 3


def test_remaining_never_negative(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    budget.record_call()
    budget.record_call()
    assert budget.remaining(1) == 0


def test_rolls_over_by_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    budget.record_call()
    budget.record_call()
    assert budget.remaining(10) == 8

    # Freeze "today" to a different date — the counter file key changes, so
    # the previous day's spend no longer applies.
    class _FakeDateTime:
        @staticmethod
        def now(tz=None):  # noqa: ANN001
            import datetime as _dt

            return _dt.datetime(2099, 1, 1, tzinfo=tz)

    monkeypatch.setattr(budget, "datetime", _FakeDateTime)
    assert budget.remaining(10) == 10


def test_corrupt_counter_file_never_raises(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    importlib.reload(budget)
    path = budget._counter_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    # Corrupt file fails open as zero spent — no exception.
    assert budget.remaining(7) == 7
    budget.record_call()  # must not raise even after a corrupt read
    assert budget.remaining(7) == 6
