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
    silentfrog-cli export --format llm <url> [--mode compact|full]
    silentfrog-cli logs <access.log> [--base-url URL] [--known-urls FILE]
                        [--out report.json]
    silentfrog-cli crawl <base_url> [--sitemap URL] [--url-list FILE]
                         [--limit N] [--timeout N] [--digest]
                         [--out-report report.html]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
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

    _add_export_parser(subparsers)
    _add_logs_parser(subparsers)
    _add_crawl_parser(subparsers)
    return parser


def _add_export_parser(subparsers: Any) -> None:
    export = subparsers.add_parser(
        "export",
        help="Audit a URL and write an LLM-friendly Markdown + JSON bundle for Claude.",
    )
    export.add_argument("url", help="The page URL to audit and export.")
    export.add_argument(
        "--format", dest="fmt", choices=["llm"], default="llm", help="Export format (only 'llm' for now)."
    )
    export.add_argument(
        "--mode",
        choices=["compact", "full"],
        default="compact",
        help="compact = warnings/criticals only (default); full = every check.",
    )
    export.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path stem (writes .md and .json). Default: ./silentfrog_audit.",
    )


def _add_logs_parser(subparsers: Any) -> None:
    logs = subparsers.add_parser(
        "logs",
        help="Analyse a server access log for crawl-budget waste (404s, redirects, bot fetches).",
    )
    logs.add_argument("path", type=Path, help="Path to the access log file (CLF / Combined / JSON).")
    logs.add_argument("--out", type=Path, default=None, help="Write the JSON report to this path (default: stdout).")
    logs.add_argument(
        "--base-url",
        default="",
        help="Site base URL, so log findings render as absolute URLs (e.g. https://example.com).",
    )
    logs.add_argument(
        "--known-urls",
        type=Path,
        default=None,
        help="File with one known URL per line; unlocks orphan-crawl and important-URL-not-hit findings.",
    )


def _add_crawl_parser(subparsers: Any) -> None:
    from .site_crawl_types import DEFAULT_SITE_CRAWL_LIMIT

    crawl = subparsers.add_parser(
        "crawl",
        help="Run one full site crawl, save it to history, and print a change digest (v3 G9, for OS schedulers).",
    )
    crawl.add_argument("base_url", help="Base URL to crawl (site root or start page).")
    crawl.add_argument("--sitemap", dest="sitemap_url", default="", help="Sitemap URL to seed the crawl from.")
    crawl.add_argument(
        "--url-list",
        type=Path,
        default=None,
        help="File with one URL per line to audit exactly (LIST mode).",
    )
    crawl.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_SITE_CRAWL_LIMIT,
        help=f"Max URLs to crawl (default: {DEFAULT_SITE_CRAWL_LIMIT}).",
    )
    crawl.add_argument("--timeout", type=int, default=10, help="Per-request timeout in seconds (default: 10).")
    crawl.add_argument(
        "--digest",
        action="store_true",
        help="Send the digest via configured transports (SILENTFROG_ALERT_WEBHOOK_URL / SMTP env vars).",
    )
    crawl.add_argument(
        "--out-report",
        type=Path,
        default=None,
        help="Also write the HTML report (v3 G8) to this path.",
    )


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


async def _export_cmd(
    args: argparse.Namespace,
    analyser: Callable[[str], Any] | None = None,
) -> int:
    from .exporters import export_page_for_llm, write_llm_export
    from .seo_crawler import analyse as default_analyser

    analyser = analyser or default_analyser
    payload = await analyser(args.url)
    export = export_page_for_llm(payload, args.url, mode=args.mode)
    out = args.out or Path("silentfrog_audit")
    written = write_llm_export(export, out, fmt="both")
    for path in written:
        print(f"[export] wrote {path}")
    print("[export] paste the .md into a Claude chat for a prioritised fix list")
    return 0


async def _logs_cmd(args: argparse.Namespace, analyser: Callable[[str], Any] | None = None) -> int:
    from .logs import analyse_entries, parse_log_text

    text = args.path.read_text(encoding="utf-8", errors="ignore")
    report = analyse_entries(parse_log_text(text))
    output = report.to_dict()
    # M6: also feed the shared issue model — the crawl-budget report above stays,
    # and the prioritized log findings (Googlebot blocked/redirected, crawl waste,
    # orphans, important-not-hit) are added as AuditIssues under "issues".
    issues = _log_issues(args)
    output["issues"] = issues
    body = json.dumps(output, indent=2, ensure_ascii=False)
    if args.out is None:
        sys.stdout.write(body + "\n")
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body + "\n", encoding="utf-8")
        print(f"[logs] wrote {args.out}")
    ai_requests = report.ai_agents.get("ai_requests", 0)
    ai_bot_count = len(report.ai_agents.get("bots", {}))
    print(
        f"[logs] {report.total_requests} requests, {report.bot_requests} from bots, "
        f"{report.wasted_404} 4xx, {report.wasted_redirect} 3xx, {len(issues)} issues, "
        f"{ai_requests} AI-agent requests from {ai_bot_count} bots",
        file=sys.stderr,
    )
    return 0


def _log_issues(args: argparse.Namespace) -> list[dict[str, object]]:
    """Run the issue-model log mapper over the same file and serialize findings.

    A second parse (via log_analysis, not the logs/ crawl-budget path) — cheap
    for a one-shot CLI, and it keeps the two log surfaces independent."""
    from .log_analysis import LogAnalysisConfig, analyse_log_file, issues_for_log_report

    config = LogAnalysisConfig(
        site_base_url=getattr(args, "base_url", "") or "",
        important_urls=_read_known_urls(getattr(args, "known_urls", None)),
    )
    report = analyse_log_file(args.path, config)
    return [issue.to_dict() for issue in issues_for_log_report(report)]


def _read_known_urls(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return tuple(line.strip() for line in lines if line.strip())


def _print_encodable(text: str) -> None:
    """Print without ever raising UnicodeEncodeError: scheduled runs redirect
    stdout through the console codepage (cp1252 under Windows Task Scheduler),
    and crawl-derived characters outside it must not kill a run that already
    succeeded — unencodable characters degrade to replacements instead."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


async def _crawl_cmd(
    args: argparse.Namespace,
    crawl_fn: Any | None = None,
    deliver_fn: Callable[[Any], Awaitable[dict[str, bool]]] | None = None,
) -> int:
    from .scheduled_crawl import build_digest, run_scheduled_crawl
    from .site_crawl_types import SiteCrawlConfig

    config = SiteCrawlConfig.from_text(
        base_url=args.base_url,
        sitemap_url=args.sitemap_url,
        url_list_text=_read_url_list_file(args.url_list),
        limit=args.limit,
    )
    try:
        report, run, diff = await run_scheduled_crawl(config, timeout=args.timeout, crawl_fn=crawl_fn)
    except Exception as exc:  # noqa: BLE001
        print(f"[crawl] failed: {exc}", file=sys.stderr)
        return 1
    digest = build_digest(run, diff, config.base_url)
    _print_encodable(digest.subject)
    _print_encodable(digest.markdown)
    if args.out_report is not None:
        _write_html_report(report, args.out_report)
    if args.digest:
        await _deliver_digest(digest, deliver_fn)
    return 0


def _read_url_list_file(path: Path | None) -> str:
    if path is None:
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _write_html_report(report: Any, out_path: Path) -> None:
    from .exporters import export_site_crawl_html

    export_site_crawl_html(report, out_path)
    print(f"[crawl] wrote {out_path}")


async def _deliver_digest(
    digest: Any,
    deliver_fn: Callable[[Any], Awaitable[dict[str, bool]]] | None,
) -> None:
    from .alert_transport import deliver_digest as default_deliver_fn

    deliver = deliver_fn or default_deliver_fn
    results = await deliver(digest)
    if not results:
        print("[crawl] --digest set but no transport is configured (see README)", file=sys.stderr)
        return
    for transport, ok in results.items():
        print(f"[crawl] {transport}: {'sent' if ok else 'failed'}", file=sys.stderr)


_DISPATCH: dict[str, Callable[..., Any]] = {
    "aggregate": _aggregate_cmd,
    "watch": _watch_cmd,
    "export": _export_cmd,
    "logs": _logs_cmd,
    "crawl": _crawl_cmd,
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
