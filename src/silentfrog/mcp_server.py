"""Silentfrog MCP server — `silentfrog-mcp serve` (v3 G6).

Exposes Silentfrog's headless audit + saved-crawl history to AI clients
(Claude Desktop / Claude Code) over the Model Context Protocol: JSON-RPC 2.0,
newline-delimited, on stdio. Hand-rolled with the standard library only — the
`mcp` SDK is a real dependency for what is, on the wire, ~300 lines of framing
and three tool handlers; the dependency-policy gate (`tools/dependency_policy.py`)
freezes the base dependency set and no new extra is justified for this.

Layout (kept separate per AGENTS §1 — parsing / dispatch / tool logic):
- line framing + JSON-RPC envelope: ``_parse_line``, ``_route``, ``serve``
- method dispatch: ``_METHODS`` (dict, no if/elif ladder)
- tool catalogue + implementations: ``_TOOLS``, the ``_call_*`` functions

Three tools:
- ``audit_page`` — one-URL SEO/GEO audit, formatted for an LLM.
- ``list_crawls`` — saved Site Crawl runs from local history.
- ``get_crawl_summary`` — one saved run's counts, top hints, and trend.

Every tool runs through the same TLS-verified / SSRF-guarded audit path as
the GUI and CLI (``seo_crawler.analyse``); optional integrations stay off
unless separately enabled elsewhere (Settings / env knobs) — this server
adds no new opt-in surface.

Windows stdio traps handled at ``serve()`` start (never at import time, so a
plain ``import silentfrog.mcp_server`` — e.g. from a test — has no side
effects):
1. Console stdio can default to cp1252; every stream is reconfigured to
   UTF-8 (best-effort — some stream types don't support ``reconfigure``).
2. stdout is the protocol channel. The real stdout handle is captured once
   for the frame writer, then ``sys.stdout`` is repointed at ``sys.stderr``
   so a stray ``print()`` from anywhere in the import graph cannot corrupt
   a response line.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any, TextIO

from .audit_issues import AuditIssue, IssueSeverity
from .crawl_history import CrawlHistoryRun, CrawlHistoryStore
from .crawl_options import AuditProfile
from .crawl_trends import CrawlTrend, TrendPoint, build_trend
from .exporters.llm_export import export_page_for_llm
from .hints import Hint, build_hints

_DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_PARSE_ERROR = -32700
_METHOD_NOT_FOUND = -32601
_TOP_HINTS_CAP = 8

ReadLine = Callable[[], Awaitable[str]]
WriteLine = Callable[[str], None]
# Injected in tests to avoid real network calls; production default runs the
# actual headless audit (see ``_default_audit_runner``).
AuditRunner = Callable[[str, AuditProfile], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class ServerContext:
    audit_runner: AuditRunner


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    call: Callable[[dict[str, Any], ServerContext], Awaitable[dict[str, Any]]]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


# ---------------------------------------------------------------------------
# JSON-RPC envelope helpers
# ---------------------------------------------------------------------------


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _parse_line(line: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Decode one JSON-RPC frame. Returns ``(message, None)`` on success or
    ``(None, error_response)`` — id is always null here since an unparseable
    or non-object frame carries no reliable request id to echo (JSON-RPC 2.0)."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return None, _error_response(None, _PARSE_ERROR, "Parse error")
    if not isinstance(message, dict):
        return None, _error_response(None, _PARSE_ERROR, "Parse error")
    return message, None


async def _route(message: dict[str, Any], ctx: ServerContext) -> dict[str, Any] | None:
    # JSON-RPC 2.0 notifications (no "id" member) never get a response, known
    # method or not — this is what makes `notifications/initialized` and any
    # other `notifications/*` a no-op without a special case per method.
    if "id" not in message:
        return None
    request_id = message["id"]
    method = str(message.get("method", ""))
    handler = _METHODS.get(method)
    if handler is None:
        return _error_response(request_id, _METHOD_NOT_FOUND, f"Method not found: {method}")
    # `or {}` alone would let a truthy non-dict params (int/str/list) through
    # to handlers that call .get() on it, killing the serve loop.
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}
    result = await handler(params, ctx)
    return _result_response(request_id, result)


async def _handle_line(line: str, ctx: ServerContext) -> dict[str, Any] | None:
    message, parse_error = _parse_line(line)
    if parse_error is not None:
        return parse_error
    return await _route(message, ctx)


# ---------------------------------------------------------------------------
# Top-level JSON-RPC methods
# ---------------------------------------------------------------------------


def _server_version() -> str:
    try:
        return importlib_metadata.version("silentfrog")
    except importlib_metadata.PackageNotFoundError:
        return "dev"


async def _handle_initialize(params: dict[str, Any], _ctx: ServerContext) -> dict[str, Any]:
    protocol_version = params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": protocol_version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "silentfrog", "version": _server_version()},
    }


async def _handle_ping(_params: dict[str, Any], _ctx: ServerContext) -> dict[str, Any]:
    return {}


async def _handle_tools_list(_params: dict[str, Any], _ctx: ServerContext) -> dict[str, Any]:
    return {"tools": [tool.as_dict() for tool in _TOOLS.values()]}


async def _handle_tools_call(params: dict[str, Any], ctx: ServerContext) -> dict[str, Any]:
    name = str(params.get("name", ""))
    tool = _TOOLS.get(name)
    if tool is None:
        return _tool_error(f"Unknown tool: {name!r}")
    try:
        return await tool.call(params.get("arguments") or {}, ctx)
    except Exception as exc:  # noqa: BLE001 — a tool failure must not crash the serve loop
        return _tool_error(f"{name} failed: {exc}")


_METHODS: dict[str, Callable[[dict[str, Any], ServerContext], Awaitable[dict[str, Any]]]] = {
    "initialize": _handle_initialize,
    "ping": _handle_ping,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
}


# ---------------------------------------------------------------------------
# Tool result helpers
# ---------------------------------------------------------------------------


def _tool_ok(text: str, structured: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "structuredContent": structured, "isError": False}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "structuredContent": {}, "isError": True}


# ---------------------------------------------------------------------------
# Tool: audit_page
# ---------------------------------------------------------------------------

_AUDIT_PROFILE_BY_NAME = {"standard": AuditProfile.STANDARD, "deep": AuditProfile.DEEP}

_AUDIT_PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "The page URL to audit."},
        "mode": {
            "type": "string",
            "enum": ["compact", "full"],
            "default": "compact",
            "description": "compact = warnings/critical checks only; full = every check.",
        },
        "profile": {
            "type": "string",
            "enum": ["standard", "deep"],
            "default": "standard",
            "description": "standard = bounded probing (default for agent calls); deep = full probing/render.",
        },
    },
    "required": ["url"],
}


async def _default_audit_runner(url: str, profile: AuditProfile) -> Any:
    # Deferred import: an agent client that only calls `list_crawls` /
    # `get_crawl_summary` never pulls in the full fetch/parse/render stack,
    # and `silentfrog-mcp --help` stays snappy (mirrors cli.py's lazy imports).
    from . import seo_crawler
    from .crawl_options import CrawlOptions

    # STANDARD by default: bounded link/canonical/redirect probing and no
    # render/heavy integrations — an agent-driven call should not silently
    # incur DEEP's full fan-out unless the caller explicitly asks for it.
    options = dataclasses.replace(CrawlOptions.default(), profile=profile)
    return await seo_crawler.analyse(url, options=options)


async def _call_audit_page(arguments: dict[str, Any], ctx: ServerContext) -> dict[str, Any]:
    url = str(arguments.get("url", "")).strip()
    if not url:
        return _tool_error("audit_page requires a non-empty 'url'.")
    mode = str(arguments.get("mode") or "compact")
    profile_name = str(arguments.get("profile") or "standard").lower()
    profile = _AUDIT_PROFILE_BY_NAME.get(profile_name, AuditProfile.STANDARD)
    payload = await ctx.audit_runner(url, profile)
    export = export_page_for_llm(payload, url, mode=mode)
    return _tool_ok(export.markdown, export.json_data)


# ---------------------------------------------------------------------------
# Tool: list_crawls
# ---------------------------------------------------------------------------

_LIST_CRAWLS_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _compact_run(run: CrawlHistoryRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "created_at": run.created_at,
        "scope_key": run.scope_key,
        "crawled_count": run.crawled_count,
        "critical_count": run.severity_count(IssueSeverity.CRITICAL),
        "warning_count": run.severity_count(IssueSeverity.WARNING),
        "info_count": run.severity_count(IssueSeverity.INFO),
        "health_score": run.health_score(),
        "has_store": run.has_store,
    }


def _runs_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["| Run | Scope | Crawled | Critical | Warning | Health |", "|---|---|---|---|---|---|"]
    lines.extend(
        f"| {r['run_id']} | {r['scope_key']} | {r['crawled_count']} | "
        f"{r['critical_count']} | {r['warning_count']} | {r['health_score']} |"
        for r in rows
    )
    return "\n".join(lines)


async def _call_list_crawls(_arguments: dict[str, Any], _ctx: ServerContext) -> dict[str, Any]:
    runs = CrawlHistoryStore().load_runs()
    if not runs:
        return _tool_ok(
            "No saved crawls yet. Run a Site Crawl in Silentfrog to populate history.",
            {"runs": []},
        )
    rows = [_compact_run(run) for run in runs]
    return _tool_ok(_runs_markdown(rows), {"runs": rows})


# ---------------------------------------------------------------------------
# Tool: get_crawl_summary
# ---------------------------------------------------------------------------

_GET_CRAWL_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"run_id": {"type": "string", "description": "A run_id returned by list_crawls."}},
    "required": ["run_id"],
}


def _to_audit_issue(issue: Any) -> AuditIssue:
    # CrawlHistoryIssue.to_audit_issue() (crawl_history.py) never supplies
    # AuditIssue.evidence — a required field added after that method was
    # written — so it raises TypeError on every call (also hit by
    # site_crawl_gui.py's "reopen scan" recap). crawl_history.py is out of
    # scope for this change, so build the AuditIssue directly here instead
    # of relying on that broken method.
    return AuditIssue(
        issue_id=issue.issue_id,
        category=issue.category,
        severity=issue.severity,
        source=issue.source,
        reason=issue.reason,
        recommendation=issue.recommendation,
        evidence=(),
        url=issue.url,
        confidence=issue.confidence,
    )


def _hint_lines(hints: list[Hint]) -> list[str]:
    if not hints:
        return ["_No hints — clean crawl._"]
    return [f"- {hint.headline()}" for hint in hints]


def _trend_lines(points: tuple[TrendPoint, ...]) -> list[str]:
    if len(points) < 2:
        return ["_Only one saved run so far — trend needs at least two._"]
    return [f"- {point.created_at}: health {point.health_score}" for point in points]


def _hint_dict(hint: Hint) -> dict[str, Any]:
    return {
        "issue_id": hint.issue_id,
        "severity": hint.severity.value,
        "headline": hint.headline(),
        "affected_urls": hint.affected_urls,
        "recommendation": hint.recommendation,
    }


def _trend_point_dict(point: TrendPoint) -> dict[str, Any]:
    return {"run_id": point.run_id, "created_at": point.created_at, "health_score": point.health_score}


def _summary_markdown(run: CrawlHistoryRun, hints: list[Hint], trend: CrawlTrend) -> str:
    lines = [
        f"## Crawl summary — {run.scope_key}",
        f"- Run: {run.run_id} ({run.created_at})",
        f"- Crawled: {run.crawled_count}  Critical: {run.severity_count(IssueSeverity.CRITICAL)}  "
        f"Warning: {run.severity_count(IssueSeverity.WARNING)}  Info: {run.severity_count(IssueSeverity.INFO)}",
        f"- Health score: {run.health_score()} (lower is better)",
        "",
        "### Top hints",
        *_hint_lines(hints),
        "",
        "### Health-score trend",
        *_trend_lines(trend.points),
    ]
    return "\n".join(lines)


def _summary_structured(run: CrawlHistoryRun, hints: list[Hint], trend: CrawlTrend) -> dict[str, Any]:
    run_dict = run.to_dict()
    # The full per-URL issue list can be thousands of rows; hints already
    # summarize it, so the structured payload drops it rather than dumping it.
    run_dict.pop("issues", None)
    return {
        "run": run_dict,
        "hints": [_hint_dict(hint) for hint in hints],
        "trend_points": [_trend_point_dict(point) for point in trend.points],
    }


async def _call_get_crawl_summary(arguments: dict[str, Any], _ctx: ServerContext) -> dict[str, Any]:
    run_id = str(arguments.get("run_id", "")).strip()
    if not run_id:
        return _tool_error("get_crawl_summary requires a non-empty 'run_id'.")
    runs = CrawlHistoryStore().load_runs()
    run = next((item for item in runs if item.run_id == run_id), None)
    if run is None:
        return _tool_error(f"No saved crawl with run_id={run_id!r}.")
    scoped = [item for item in runs if item.scope_key == run.scope_key]
    hints = build_hints(_to_audit_issue(issue) for issue in run.issues)[:_TOP_HINTS_CAP]
    trend = build_trend(scoped)
    return _tool_ok(_summary_markdown(run, hints, trend), _summary_structured(run, hints, trend))


_TOOLS: dict[str, ToolSpec] = {
    "audit_page": ToolSpec(
        name="audit_page",
        description="Run a local Silentfrog SEO/GEO audit on one URL and return an LLM-ready summary.",
        input_schema=_AUDIT_PAGE_SCHEMA,
        call=_call_audit_page,
    ),
    "list_crawls": ToolSpec(
        name="list_crawls",
        description="List saved Site Crawl runs from local crawl history.",
        input_schema=_LIST_CRAWLS_SCHEMA,
        call=_call_list_crawls,
    ),
    "get_crawl_summary": ToolSpec(
        name="get_crawl_summary",
        description="Summarize one saved crawl run: counts, health score, top hints, and its health-score trend.",
        input_schema=_GET_CRAWL_SUMMARY_SCHEMA,
        call=_call_get_crawl_summary,
    ),
}


# ---------------------------------------------------------------------------
# stdio serve loop
# ---------------------------------------------------------------------------


def _reconfigure_utf8(stream: Any) -> None:
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        return  # exotic/already-detached stream (e.g. under some test runners) — best effort only


def _capture_protocol_stdout() -> TextIO:
    """Grab the real stdout for the JSON-RPC channel, then repoint
    ``sys.stdout`` at ``sys.stderr`` so a stray ``print()`` anywhere in the
    import graph can never corrupt a response line. Called once, at serve
    start — never at import time, and never when read/write are injected
    (tests inject both, so production stdio is untouched during a test run)."""
    protocol_stdout = sys.stdout
    _reconfigure_utf8(sys.stdin)
    _reconfigure_utf8(protocol_stdout)
    _reconfigure_utf8(sys.stderr)
    sys.stdout = sys.stderr
    return protocol_stdout


async def _default_read_line() -> str:
    return await asyncio.to_thread(sys.stdin.readline)


def _make_default_write_line(stream: TextIO) -> WriteLine:
    def _write(line: str) -> None:
        stream.write(line + "\n")
        stream.flush()

    return _write


async def serve(
    *,
    read_line: ReadLine | None = None,
    write_line: WriteLine | None = None,
    audit_runner: AuditRunner | None = None,
) -> None:
    """Newline-delimited JSON-RPC 2.0 loop over stdio.

    Requests are handled strictly sequentially — an MCP client over stdio
    issues one call at a time, so there is no request pipelining to support
    here (unlike, say, the render pool's worker concurrency).

    ``read_line``/``write_line`` are injected so tests can drive the loop
    without touching real stdio (cloned from ``watch_mode.watch``'s
    ``sleep_fn``/``on_alert`` injectable-primitive pattern).
    """
    reader = read_line or _default_read_line
    writer = write_line if write_line is not None else _make_default_write_line(_capture_protocol_stdout())
    ctx = ServerContext(audit_runner=audit_runner or _default_audit_runner)
    while True:
        raw_line = await reader()
        if raw_line == "":
            return  # EOF
        line = raw_line.strip()
        if not line:
            continue
        response = await _handle_line(line, ctx)
        if response is not None:
            writer(json.dumps(response, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="silentfrog-mcp",
        description="Local Model Context Protocol server exposing Silentfrog audits.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Run the JSON-RPC-over-stdio MCP server (blocks until stdin EOF).")
    return parser


async def _serve_cmd(_args: argparse.Namespace) -> int:
    await serve()
    return 0


_DISPATCH: dict[str, Callable[[argparse.Namespace], Awaitable[int]]] = {
    "serve": _serve_cmd,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _DISPATCH[args.command]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("[silentfrog-mcp] interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
