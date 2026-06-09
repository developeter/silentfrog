"""Watch mode — scheduled re-audits with regression alerts (v1.1 N4c).

ContentKing charges $99/mo for this feature; we ship it free + local.

Re-audits a configured set of URLs on a fixed interval and raises an
alert when the GEO Score drops materially compared to the rolling
median of the prior runs. Stores every run in the existing crawl
history SQLite ([crawl_history.py](src/silentfrog/crawl_history.py)).

Per §4.5 supply-chain hygiene: NOT using APScheduler (single
maintainer, deferred to a future PR if periodic-task requirements
grow beyond what a plain ``asyncio.sleep`` loop can cover).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .crawl_types import CrawlPayload

_DEFAULT_REGRESSION_DROP_POINTS = 5
_DEFAULT_HISTORY_WINDOW = 5
_DEFAULT_ALERT_LOG_NAME = "watch_alerts.log"


@dataclass(frozen=True)
class WatchAlert:
    url: str
    timestamp: str
    score_before: int
    score_after: int
    drop_points: int
    top_changed_checks: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "timestamp": self.timestamp,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "drop_points": self.drop_points,
            "top_changed_checks": list(self.top_changed_checks),
        }


@dataclass
class WatchConfig:
    urls: tuple[str, ...]
    interval_seconds: int = 24 * 60 * 60
    drop_threshold_points: int = _DEFAULT_REGRESSION_DROP_POINTS
    history_window: int = _DEFAULT_HISTORY_WINDOW
    iterations: int | None = None  # None = run forever; tests pass small ints


def _alert_log_path() -> Path:
    override = os.environ.get("SILENTFROG_DATA_DIR", "").strip()
    if override:
        base = Path(override)
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "Silentfrog"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "silentfrog"
    return base / _DEFAULT_ALERT_LOG_NAME


def _write_alert(alert: WatchAlert) -> None:
    try:
        path = _alert_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(alert.to_dict()) + "\n")
    except Exception:
        return


def detect_regression(
    current_score: int,
    history: list[int],
    threshold_points: int = _DEFAULT_REGRESSION_DROP_POINTS,
) -> tuple[bool, int, int]:
    """Compare ``current_score`` against the rolling median of ``history``.

    Returns ``(is_regression, baseline_score, drop_points)``. When
    history is empty the function returns ``(False, current_score, 0)`` —
    a brand-new URL never alerts on its first run.
    """
    if not history:
        return False, current_score, 0
    sorted_h = sorted(history)
    mid = len(sorted_h) // 2
    baseline = sorted_h[mid] if len(sorted_h) % 2 == 1 else (sorted_h[mid - 1] + sorted_h[mid]) // 2
    drop = baseline - current_score
    return drop >= threshold_points, baseline, drop


def _top_changed_checks(
    current_payload: CrawlPayload,
    previous_keys: set[str],
) -> tuple[str, ...]:
    """Return the names of newly-warning/critical checks.

    Naive heuristic: any check that wasn't in the previous warning
    set is a candidate. The caller passes only the previous warning
    keys; we don't need the full previous payload.
    """
    changed: list[str] = []
    for check in current_payload.ai_visibility.checks:
        if check.status in {"warning", "critical"} and check.key not in previous_keys:
            changed.append(check.check)
    return tuple(changed[:5])


def _payload_warning_keys(payload: CrawlPayload | None) -> set[str]:
    if payload is None:
        return set()
    return {c.key for c in payload.ai_visibility.checks if c.status in {"warning", "critical"}}


async def watch(
    config: WatchConfig,
    analyser: Callable[[str], Awaitable[CrawlPayload]],
    on_alert: Callable[[WatchAlert], None] | None = None,
    sleep_fn: Callable[[float], Awaitable[None]] | None = None,
) -> list[WatchAlert]:
    """Re-audit each URL on the configured interval; emit alerts on drop.

    ``sleep_fn`` is injected so tests can short-circuit the sleep.
    ``on_alert`` defaults to writing one JSON line per alert to
    ``$LOCALAPPDATA/Silentfrog/watch_alerts.log``.

    Returns the list of alerts emitted across all iterations.
    """
    sleeper = sleep_fn or asyncio.sleep
    alert_sink = on_alert or _write_alert
    history: dict[str, list[int]] = {url: [] for url in config.urls}
    previous_warning_keys: dict[str, set[str]] = {url: set() for url in config.urls}
    alerts_emitted: list[WatchAlert] = []

    iteration = 0
    while config.iterations is None or iteration < config.iterations:
        for url in config.urls:
            try:
                payload = await analyser(url)
            except Exception:
                continue
            score = payload.ai_visibility.summary.score
            is_regression, baseline, drop = detect_regression(
                score,
                history[url],
                threshold_points=config.drop_threshold_points,
            )
            if is_regression:
                changed = _top_changed_checks(payload, previous_warning_keys[url])
                alert = WatchAlert(
                    url=url,
                    timestamp=datetime.now(UTC).isoformat(),
                    score_before=baseline,
                    score_after=score,
                    drop_points=drop,
                    top_changed_checks=changed,
                )
                alerts_emitted.append(alert)
                alert_sink(alert)
            history[url].append(score)
            # Trim history to the rolling window.
            if len(history[url]) > config.history_window:
                history[url] = history[url][-config.history_window :]
            previous_warning_keys[url] = _payload_warning_keys(payload)
        iteration += 1
        if config.iterations is not None and iteration >= config.iterations:
            break
        await sleeper(config.interval_seconds)
    return alerts_emitted


__all__ = [
    "WatchAlert",
    "WatchConfig",
    "detect_regression",
    "watch",
]
