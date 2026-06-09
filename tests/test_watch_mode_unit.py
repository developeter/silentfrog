from __future__ import annotations

from dataclasses import dataclass

import pytest

from silentfrog.watch_mode import WatchAlert, WatchConfig, detect_regression, watch


@dataclass
class _Summary:
    score: int = 100
    verdict: str = "Strong"
    good_count: int = 0
    warning_count: int = 0
    critical_count: int = 0


@dataclass
class _Check:
    area: str
    check: str
    status: str
    key: str


@dataclass
class _AiV:
    summary: _Summary
    checks: list[_Check]


@dataclass
class _Payload:
    ai_visibility: _AiV


def _payload(score: int, warning_keys: tuple[str, ...] = ()) -> _Payload:
    checks = [_Check("Access", f"warn {k}", "warning", k) for k in warning_keys]
    return _Payload(ai_visibility=_AiV(summary=_Summary(score=score), checks=checks))


def test_detect_regression_empty_history_never_alerts() -> None:
    is_reg, baseline, drop = detect_regression(60, [])
    assert is_reg is False
    assert baseline == 60
    assert drop == 0


def test_detect_regression_threshold_inclusive() -> None:
    # Median of [80, 90, 100] is 90; current=85 -> drop=5 (== threshold).
    is_reg, baseline, drop = detect_regression(85, [80, 90, 100], threshold_points=5)
    assert is_reg is True
    assert baseline == 90
    assert drop == 5


def test_detect_regression_below_threshold_does_not_alert() -> None:
    is_reg, _, _ = detect_regression(86, [80, 90, 100], threshold_points=5)
    assert is_reg is False


@pytest.mark.asyncio
async def test_watch_emits_alert_on_drop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("silentfrog.watch_mode._alert_log_path", lambda: tmp_path / "alerts.log")
    iteration = 0
    scores = [90, 90, 90, 70]  # last one is a 20-point drop

    async def _stub_analyser(url: str):
        nonlocal iteration
        score = scores[iteration % len(scores)]
        iteration += 1
        return _payload(score)

    async def _no_sleep(_seconds: float) -> None:
        return None

    config = WatchConfig(
        urls=("https://example.com/",),
        interval_seconds=60,
        drop_threshold_points=5,
        iterations=4,
    )
    alerts = await watch(config, _stub_analyser, sleep_fn=_no_sleep)
    assert len(alerts) == 1
    assert alerts[0].drop_points == 20
    assert alerts[0].score_before == 90
    assert alerts[0].score_after == 70


@pytest.mark.asyncio
async def test_watch_does_not_alert_on_stable_scores(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("silentfrog.watch_mode._alert_log_path", lambda: tmp_path / "alerts.log")

    async def _stub_analyser(url: str):
        return _payload(80)

    async def _no_sleep(_s: float) -> None:
        return None

    alerts = await watch(
        WatchConfig(urls=("https://example.com/",), interval_seconds=60, iterations=3),
        _stub_analyser,
        sleep_fn=_no_sleep,
    )
    assert alerts == []


@pytest.mark.asyncio
async def test_watch_swallows_per_url_analyser_errors(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("silentfrog.watch_mode._alert_log_path", lambda: tmp_path / "alerts.log")
    call_count = 0

    async def _flaky_analyser(url: str):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("transient")
        return _payload(80)

    async def _no_sleep(_s: float) -> None:
        return None

    await watch(
        WatchConfig(urls=("https://example.com/a", "https://example.com/b"), iterations=1),
        _flaky_analyser,
        sleep_fn=_no_sleep,
    )
    # Both URLs were attempted despite one raising.
    assert call_count == 2


def test_watch_alert_roundtrip_through_dict() -> None:
    alert = WatchAlert(
        url="https://example.com/",
        timestamp="2026-06-08T15:00:00Z",
        score_before=90,
        score_after=70,
        drop_points=20,
        top_changed_checks=("Critical thing",),
    )
    data = alert.to_dict()
    assert data["drop_points"] == 20
    assert data["top_changed_checks"] == ["Critical thing"]
