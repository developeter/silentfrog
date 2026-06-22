"""v2.0 PR-11 (H2) — synthetic performance harness.

Two concerns, split by what is deterministic on shared CI:

- **Suite guards (here, run everywhere):** the harness drives the real pipeline
  and every URL is processed exactly once into a bounded store (the CI-stable
  O(1)-per-URL invariant), the instrumentation reports positive RSS/throughput,
  the committed baseline is well-formed, and the reference-gate comparison math
  is correct. No absolute RSS/time thresholds are asserted here — those flake.
- **Reference gate (off-CI):** ``tools/perf_harness.py --check`` enforces the
  committed baseline (+15% RSS, -15% pages/s, absolute 100k ceiling) on a
  controlled machine. Not run in this suite.
"""

from __future__ import annotations

from pathlib import Path

from tools.perf_harness import (
    PerfBaseline,
    PerfResult,
    check,
    load_baseline,
    measure,
)

_BASELINE_PATH = Path(__file__).resolve().parent.parent / "tools" / "perf_baseline.json"


def _result(peak_rss_bytes: int, pages_per_sec: float, urls: int = 100_000) -> PerfResult:
    return PerfResult(
        urls=urls,
        repetitions=2,
        pages_crawled=urls,
        store_count=urls,
        peak_rss_bytes=peak_rss_bytes,
        pages_per_sec=pages_per_sec,
    )


def _baseline(
    peak_rss_bytes: int = 100_000_000, pages_per_sec: float = 1000.0, ceiling: int = 150_000_000
) -> PerfBaseline:
    return PerfBaseline(
        urls=100_000, peak_rss_bytes=peak_rss_bytes, pages_per_sec=pages_per_sec, ceiling_rss_bytes=ceiling
    )


def test_each_url_processed_exactly_once_into_bounded_store() -> None:
    # The deterministic, CI-stable guard: the real pipeline crawls every
    # synthetic URL exactly once and persists exactly one row each. A regression
    # to re-processing (O(n^2)) or duplicate rows breaks these equalities.
    result = measure(urls=600, repetitions=1, warmup=0)
    assert result.pages_crawled == 600
    assert result.store_count == 600


def test_measure_reports_positive_rss_and_throughput() -> None:
    result = measure(urls=300, repetitions=1, warmup=0)
    assert result.peak_rss_bytes > 0  # psutil sampler captured a process RSS
    assert result.pages_per_sec > 0  # throughput recorded (informational)


def test_check_passes_within_tolerance() -> None:
    # +10% RSS (within the +15% band), -10% throughput (within the -15% floor),
    # under the ceiling -> no failures.
    result = _result(peak_rss_bytes=110_000_000, pages_per_sec=900.0)
    assert check(result, _baseline()) == []


def test_check_flags_rss_over_budget() -> None:
    result = _result(peak_rss_bytes=120_000_000, pages_per_sec=1000.0)  # +20% > +15% band
    failures = check(result, _baseline())
    assert any("baseline+15%" in f for f in failures)


def test_check_flags_rss_over_absolute_ceiling() -> None:
    # Budget passes (baseline high) but the absolute ceiling is the hard cap.
    result = _result(peak_rss_bytes=160_000_000, pages_per_sec=1000.0)
    baseline = _baseline(peak_rss_bytes=200_000_000, ceiling=150_000_000)
    failures = check(result, baseline)
    assert any("ceiling" in f for f in failures)
    assert not any("baseline+15%" in f for f in failures)  # only the ceiling bit


def test_check_flags_throughput_regression() -> None:
    result = _result(peak_rss_bytes=100_000_000, pages_per_sec=800.0)  # -20% < -15% floor
    failures = check(result, _baseline())
    assert any("throughput" in f for f in failures)


def test_committed_baseline_is_well_formed() -> None:
    # The committed reference baseline must load and be internally consistent
    # (ceiling at or above the recorded peak, positive throughput).
    assert _BASELINE_PATH.is_file()
    baseline = load_baseline(_BASELINE_PATH)
    assert baseline.urls > 0
    assert baseline.peak_rss_bytes > 0
    assert baseline.pages_per_sec > 0
    assert baseline.ceiling_rss_bytes >= baseline.peak_rss_bytes
