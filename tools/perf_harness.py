"""Synthetic, no-network performance harness (v2.0 PR-11, H2).

Feeds the REAL crawl pipeline a fixed synthetic corpus offline — ``analyse`` is
stubbed, so no sockets are opened — and measures peak process RSS (psutil) plus
throughput (pages/s) at a chosen scale. The committed reference baseline
(``perf_baseline.json``) and two gates share these numbers:

* **Reference gate** (``--check``): enforces the baseline (+15% RSS, -15%
  pages/s) and the absolute 100k peak-RSS ceiling. Run it on a *controlled*
  machine, NOT shared CI — wall-clock throughput is machine-dependent, so a
  pages/s gate flakes on loaded runners. A release cannot pass PR-11 until this
  gate passes on the reference environment.
* **Suite guard** (``tests/test_perf_harness.py``): asserts the deterministic,
  CI-stable invariant (every URL processed exactly once into a bounded store)
  and treats pages/s as informational.

``psutil`` is a dev/test-only dependency and this tool never runs in the shipped
app. RSS is OS- and platform-dependent; baselines are environment-specific.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import psutil

from silentfrog import site_crawler
from silentfrog.crawl_mode import CrawlMode
from silentfrog.crawl_store import CrawlStore
from silentfrog.crawl_types import CrawlPayload
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig

_BASELINE_PATH = Path(__file__).resolve().parent / "perf_baseline.json"
_RSS_SAMPLE_INTERVAL_S = 0.025
_RSS_TOLERANCE = 0.15
_THROUGHPUT_TOLERANCE = 0.15
_CEILING_HEADROOM = 1.25  # absolute ceiling default = measured peak x this


@dataclass(frozen=True)
class PerfResult:
    urls: int
    repetitions: int
    pages_crawled: int
    store_count: int
    peak_rss_bytes: int
    pages_per_sec: float


@dataclass(frozen=True)
class PerfBaseline:
    urls: int
    peak_rss_bytes: int
    pages_per_sec: float
    ceiling_rss_bytes: int


def _payload_raw(url: str) -> dict:
    """A compact but complete payload — exercises the real persist path
    (zlib + JSON of ``to_mapping``) without per-page links, so the synthetic
    frontier equals the seed set and each scale is deterministic."""
    return {
        "meta": [["title", "T", "1"], ["description", "d", "1"]],
        "headers": [["h1", "T"]],
        "images": [],
        "links": [],
        "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
        "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": [url], "hops": 0, "final_status": "200", "final_url": url, "loop": False},
        "robots": {"*": [["Allow", "/"]]},
        "meta_robots": "index, follow",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {"title": "T", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
        "serp_audit": {},
        "keywords": [],
        "content_quality": {"word_count": 50},
        "ai_visibility": {"summary": {"verdict": "OK", "score": 80}, "checks": []},
        "performance": {"summary": {"verdict": "Good"}},
        "social": {},
    }


async def _fake_analyse(url: str, timeout: int, options: object = None) -> CrawlPayload:
    return CrawlPayload.from_raw(_payload_raw(url))


def _synthetic_config(urls: int) -> SiteCrawlConfig:
    spider = SpiderConfig(
        mode=CrawlMode.LIST,
        respect_robots=False,
        politeness_delay_ms=0,
        crawl_concurrency=8,
        max_urls=urls,
    )
    listing = "\n".join(f"https://perf.local/{i}" for i in range(urls))
    return SiteCrawlConfig.from_text(base_url="https://perf.local", url_list_text=listing, limit=urls, spider=spider)


class _RssSampler(threading.Thread):
    """Polls process RSS on a background thread, tracking the peak across the
    whole measured window (a single before/after reading would miss the peak)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._process = psutil.Process()
        self._done = threading.Event()  # not ``_stop``: that shadows Thread internals
        self.peak = self._process.memory_info().rss

    def run(self) -> None:
        while not self._done.is_set():
            self.peak = max(self.peak, self._process.memory_info().rss)
            self._done.wait(_RSS_SAMPLE_INTERVAL_S)

    def stop(self) -> None:
        self._done.set()
        self.join(timeout=2)
        self.peak = max(self.peak, self._process.memory_info().rss)


def _run_once(urls: int) -> tuple[float, int, int]:
    """One full store-backed crawl of ``urls`` synthetic pages. Returns
    (elapsed_seconds, pages_crawled, rows_persisted)."""
    config = _synthetic_config(urls)
    with tempfile.TemporaryDirectory(prefix="sf-perf-") as tmp:
        store = CrawlStore(Path(tmp) / "perf.db")
        try:
            with mock.patch.object(site_crawler, "analyse", _fake_analyse):
                start = time.perf_counter()
                report = asyncio.run(site_crawler.crawl_site(config, timeout=5, store=store))
                elapsed = time.perf_counter() - start
            return elapsed, report.crawled_count, store.count(report.run_ref.run_id)
        finally:
            store.close()


def measure(urls: int, repetitions: int = 3, warmup: int = 1) -> PerfResult:
    """Run the synthetic crawl ``repetitions`` times (after ``warmup`` discarded
    runs), sampling peak RSS throughout and taking the median throughput."""
    sampler = _RssSampler()
    sampler.start()
    pages = stored = 0
    durations: list[float] = []
    try:
        for _ in range(warmup):
            _run_once(urls)
        for _ in range(repetitions):
            elapsed, pages, stored = _run_once(urls)
            durations.append(elapsed)
    finally:
        sampler.stop()
    median = statistics.median(durations) if durations else 0.0
    pages_per_sec = urls / median if median > 0 else 0.0
    return PerfResult(urls, repetitions, pages, stored, sampler.peak, pages_per_sec)


def check(result: PerfResult, baseline: PerfBaseline) -> list[str]:
    """Reference-gate comparison: +15% RSS band, the absolute ceiling, and the
    -15% throughput floor. Empty list == pass."""
    failures: list[str] = []
    rss_budget = int(baseline.peak_rss_bytes * (1 + _RSS_TOLERANCE))
    if result.peak_rss_bytes > rss_budget:
        failures.append(f"peak RSS {_mb(result.peak_rss_bytes)} > baseline+15% {_mb(rss_budget)}")
    if result.peak_rss_bytes > baseline.ceiling_rss_bytes:
        failures.append(f"peak RSS {_mb(result.peak_rss_bytes)} > ceiling {_mb(baseline.ceiling_rss_bytes)}")
    floor = baseline.pages_per_sec * (1 - _THROUGHPUT_TOLERANCE)
    if result.pages_per_sec < floor:
        failures.append(f"throughput {result.pages_per_sec:.0f} p/s < baseline-15% {floor:.0f} p/s")
    return failures


def _mb(num_bytes: int) -> str:
    return f"{num_bytes / 1_048_576:.0f}MB"


def load_baseline(path: Path = _BASELINE_PATH) -> PerfBaseline:
    data = json.loads(path.read_text(encoding="utf-8"))
    return PerfBaseline(
        urls=int(data["urls"]),
        peak_rss_bytes=int(data["peak_rss_bytes"]),
        pages_per_sec=float(data["pages_per_sec"]),
        ceiling_rss_bytes=int(data["ceiling_rss_bytes"]),
    )


def write_baseline(result: PerfResult, ceiling_rss_bytes: int, path: Path = _BASELINE_PATH) -> None:
    payload = {
        "urls": result.urls,
        "repetitions": result.repetitions,
        "peak_rss_bytes": result.peak_rss_bytes,
        "pages_per_sec": round(result.pages_per_sec, 1),
        "ceiling_rss_bytes": ceiling_rss_bytes,
        "method": "tools/perf_harness.py --check (synthetic offline crawl; psutil RSS; median pages/s)",
        "note": "Environment-specific; recorded on the controlled reference machine, not shared CI.",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _describe(result: PerfResult) -> str:
    return (
        f"urls={result.urls} reps={result.repetitions} "
        f"peak_rss={_mb(result.peak_rss_bytes)} throughput={result.pages_per_sec:.0f} p/s "
        f"(crawled={result.pages_crawled} stored={result.store_count})"
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synthetic crawl performance harness (PR-11, H2).")
    parser.add_argument("--urls", type=int, default=10_000, help="synthetic corpus size (default 10000)")
    parser.add_argument("--repetitions", type=int, default=3, help="measured runs (median; default 3)")
    parser.add_argument("--warmup", type=int, default=1, help="discarded warm-up runs (default 1)")
    parser.add_argument("--check", action="store_true", help="compare against the committed baseline (reference gate)")
    parser.add_argument("--write-baseline", action="store_true", help="record the committed baseline from this run")
    parser.add_argument("--ceiling-mb", type=int, default=0, help="absolute peak-RSS ceiling in MB (write-baseline)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    # --check always measures at the committed baseline's scale so the RSS band
    # and throughput floor compare like for like.
    baseline = load_baseline() if args.check else None
    urls = baseline.urls if baseline is not None else args.urls
    result = measure(urls, repetitions=args.repetitions, warmup=args.warmup)
    print(_describe(result))
    if result.pages_crawled != urls or result.store_count != urls:
        print(f"FAIL: processed {result.pages_crawled}/persisted {result.store_count} != {urls} URLs")
        return 1
    if args.write_baseline:
        ceiling = args.ceiling_mb * 1_048_576 or int(result.peak_rss_bytes * _CEILING_HEADROOM)
        write_baseline(result, ceiling)
        print(f"wrote baseline -> {_BASELINE_PATH} (ceiling {_mb(ceiling)})")
        return 0
    if baseline is not None:
        failures = check(result, baseline)
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
