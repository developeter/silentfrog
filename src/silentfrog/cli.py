"""Silentfrog CLI — `silentfrog-cli aggregate|watch <args>` (v1.1 N4).

Surfaces the headless capabilities added in N4 (sitemap-level
aggregation, watch mode) so users + CI can drive them without
launching the Qt GUI. Single console-script entry point declared in
pyproject's ``[project.scripts]`` table.

Subcommands:

    silentfrog-cli aggregate <sitemap_url> [--out report.json]
                              [--concurrency N]
    silentfrog-cli watch <url> [<url>...] [--interval-seconds N]
                                [--iterations N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="silentfrog-cli",
        description="Headless commands for Silentfrog (sitemap aggregate + watch mode).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    aggregate = subparsers.add_parser(
        "aggregate",
        help="Audit every URL in a sitemap and report GEO Score statistics.",
    )
    aggregate.add_argument("sitemap_url", help="URL of the sitemap.xml to load.")
    aggregate.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the JSON report to this path (default: stdout).",
    )
    aggregate.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Max parallel page audits (default: 8).",
    )

    watch = subparsers.add_parser(
        "watch",
        help="Re-audit URLs on a fixed interval; emit JSON-line alerts on GEO Score drops.",
    )
    watch.add_argument("urls", nargs="+", help="URLs to monitor.")
    watch.add_argument(
        "--interval-seconds",
        type=int,
        default=24 * 60 * 60,
        help="Seconds between audit cycles (default: 86400 = 24h).",
    )
    watch.add_argument(
        "--drop-threshold",
        type=int,
        default=5,
        help="GEO Score drop (points) that triggers an alert.",
    )
    watch.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Stop after N cycles (default: run forever).",
    )

    return parser


async def _aggregate_cmd(
    args: argparse.Namespace,
    analyser: Callable[[str], Any] | None = None,
) -> int:
    from .seo_crawler import analyse as default_analyser
    from .sitemap_geo_aggregate import aggregate_sitemap

    analyser = analyser or default_analyser
    report = await aggregate_sitemap(
        args.sitemap_url,
        analyser=analyser,
        max_concurrency=args.concurrency,
    )
    payload = report.to_dict()
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out is None:
        sys.stdout.write(body + "\n")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body + "\n", encoding="utf-8")
        print(f"[aggregate] wrote {args.out}")
    return 0


async def _watch_cmd(
    args: argparse.Namespace,
    analyser: Callable[[str], Any] | None = None,
) -> int:
    from .seo_crawler import analyse as default_analyser
    from .watch_mode import WatchConfig, watch

    analyser = analyser or default_analyser
    config = WatchConfig(
        urls=tuple(args.urls),
        interval_seconds=args.interval_seconds,
        drop_threshold_points=args.drop_threshold,
        iterations=args.iterations,
    )
    alerts = await watch(config, analyser)
    print(f"[watch] {len(alerts)} alert(s) emitted across {config.iterations or '∞'} iterations")
    return 0


_DISPATCH: dict[str, Callable[..., Any]] = {
    "aggregate": _aggregate_cmd,
    "watch": _watch_cmd,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.command]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("[silentfrog-cli] interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
