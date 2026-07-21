"""v3 G6 — `silentfrog-mcp serve` (hand-rolled MCP server over stdio)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import pytest

from silentfrog import mcp_server
from silentfrog.audit_issues import IssueCategory, IssueSeverity
from silentfrog.crawl_history import CrawlHistoryIssue, CrawlHistoryRun, CrawlHistoryStore
from silentfrog.crawl_options import AuditProfile
from silentfrog.crawl_types import CrawlPayload


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path, monkeypatch):
    # Clone of the brand_mentions/crawl_history isolation fixture pattern —
    # CrawlHistoryStore() reads this env var, so list_crawls/get_crawl_summary
    # never touch the developer's real $LOCALAPPDATA/Silentfrog history.
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))


def _reader_from(lines: list[str]) -> Callable[[], Awaitable[str]]:
    queue = list(lines)

    async def _read() -> str:
        if not queue:
            return ""  # EOF
        return queue.pop(0)

    return _read


def _collecting_writer() -> tuple[list[str], Callable[[str], None]]:
    written: list[str] = []
    return written, written.append


def _request(request_id: int, method: str, params: dict | None = None) -> str:
    body: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body)


def _notification(method: str, params: dict | None = None) -> str:
    body: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body)


async def _unused_runner(url: str, profile: AuditProfile) -> CrawlPayload:
    raise AssertionError("audit_runner should not be invoked by this test")


def _stub_payload(url: str, score: int = 55) -> CrawlPayload:
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "Example title", "13"], ["description", "Example description.", "20"]],
            "headers": [["h1", "Example"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}, "errors": []}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {
                "title": "Example",
                "description": "",
                "url": url,
                "site_name": "",
                "breadcrumb": "",
                "favicon": "",
            },
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 250},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 1,
                    "warning_count": 1,
                    "critical_count": 0,
                },
                "checks": [
                    {
                        "area": "Content",
                        "check": "Thin content",
                        "status": "warning",
                        "details": "250 words",
                        "recommendation": "Add depth",
                        "key": "content.thin",
                    }
                ],
            },
            "performance": {"status": 200, "summary": {"verdict": "Good"}},
            "social": {},
        }
    )


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_handshake_echoes_protocol_and_advertises_tools_capability() -> None:
    lines = [
        _request(1, "initialize", {"protocolVersion": "2025-06-18"}),
        _notification("notifications/initialized"),
    ]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert len(written) == 1  # the notification produced no output line
    response = json.loads(written[0])
    assert response["id"] == 1
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "silentfrog"
    assert "tools" in result["capabilities"]


@pytest.mark.asyncio
async def test_serve_initialize_defaults_protocol_version_when_absent() -> None:
    lines = [_request(1, "initialize", {})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    response = json.loads(written[0])
    assert response["result"]["protocolVersion"] == "2025-06-18"


@pytest.mark.asyncio
async def test_ping_returns_empty_result() -> None:
    lines = [_request(1, "ping")]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert json.loads(written[0])["result"] == {}


@pytest.mark.asyncio
async def test_serve_survives_non_dict_params_and_keeps_answering() -> None:
    # A truthy non-dict params (int/list) must be treated as {} — it used to
    # reach handlers calling .get() on it and kill the whole serve loop.
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": 5}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": ["not", "a", "dict"]}),
        _request(3, "ping"),
    ]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert len(written) == 3  # every request answered; the loop never died
    first = json.loads(written[0])
    assert first["id"] == 1
    assert first["result"]["protocolVersion"] == "2025-06-18"  # defaults applied
    second = json.loads(written[1])
    assert second["id"] == 2
    assert second["result"]["isError"] is True  # no tool name -> tool-level error, not a crash
    assert json.loads(written[2])["result"] == {}  # ping still answers


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_describes_three_tools_with_schemas() -> None:
    lines = [_request(2, "tools/list")]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    tools = {tool["name"]: tool for tool in json.loads(written[0])["result"]["tools"]}
    assert set(tools) == {"audit_page", "list_crawls", "get_crawl_summary"}
    for tool in tools.values():
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
    assert tools["audit_page"]["inputSchema"]["required"] == ["url"]


# ---------------------------------------------------------------------------
# tools/call audit_page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_page_returns_markdown_and_structured_content() -> None:
    async def _stub_runner(url: str, profile: AuditProfile) -> CrawlPayload:
        assert profile is AuditProfile.STANDARD  # bounded default for agent-driven calls
        return _stub_payload(url)

    lines = [_request(1, "tools/call", {"name": "audit_page", "arguments": {"url": "https://example.com/page"}})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_stub_runner)

    result = json.loads(written[0])["result"]
    assert result["isError"] is False
    assert "GEO Score" in result["content"][0]["text"]
    assert result["structuredContent"]["page"]["url"] == "https://example.com/page"


@pytest.mark.asyncio
async def test_audit_page_forwards_requested_deep_profile() -> None:
    seen = {}

    async def _stub_runner(url: str, profile: AuditProfile) -> CrawlPayload:
        seen["profile"] = profile
        return _stub_payload(url)

    lines = [
        _request(
            1,
            "tools/call",
            {"name": "audit_page", "arguments": {"url": "https://example.com/page", "profile": "deep"}},
        )
    ]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_stub_runner)

    assert seen["profile"] is AuditProfile.DEEP
    assert json.loads(written[0])["result"]["isError"] is False


@pytest.mark.asyncio
async def test_audit_page_missing_url_is_tool_error() -> None:
    lines = [_request(1, "tools/call", {"name": "audit_page", "arguments": {}})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert json.loads(written[0])["result"]["isError"] is True


@pytest.mark.asyncio
async def test_audit_page_runner_failure_is_tool_error_and_loop_survives() -> None:
    async def _boom(url: str, profile: AuditProfile) -> CrawlPayload:
        raise RuntimeError("network blocked")

    lines = [
        _request(1, "tools/call", {"name": "audit_page", "arguments": {"url": "https://example.com"}}),
        _request(2, "ping"),
    ]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_boom)

    first = json.loads(written[0])
    assert first["result"]["isError"] is True
    assert "network blocked" in first["result"]["content"][0]["text"]
    second = json.loads(written[1])
    assert second["result"] == {}  # the loop kept serving after the failure


@pytest.mark.asyncio
async def test_tools_call_unknown_tool_name_is_tool_error() -> None:
    lines = [_request(1, "tools/call", {"name": "does_not_exist", "arguments": {}})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert json.loads(written[0])["result"]["isError"] is True


# ---------------------------------------------------------------------------
# list_crawls / get_crawl_summary
# ---------------------------------------------------------------------------


def _history_issue(issue_id: str, severity: IssueSeverity, url: str) -> CrawlHistoryIssue:
    return CrawlHistoryIssue(
        issue_id=issue_id,
        severity=severity,
        category=IssueCategory.META,
        url=url,
        reason=f"{issue_id} reason",
        recommendation="Fix it.",
        source="meta",
        confidence="high",
    )


def _seed_two_runs() -> tuple[CrawlHistoryRun, CrawlHistoryRun]:
    store = CrawlHistoryStore()
    first = CrawlHistoryRun(
        run_id="example.com-run-1",
        created_at="2026-01-01T00:00:00Z",
        scope_key="example.com",
        discovered_count=2,
        crawled_count=2,
        failed_count=0,
        skipped_count=0,
        issues=(_history_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),),
    )
    second = CrawlHistoryRun(
        run_id="example.com-run-2",
        created_at="2026-01-02T00:00:00Z",
        scope_key="example.com",
        discovered_count=2,
        crawled_count=2,
        failed_count=0,
        skipped_count=0,
        issues=(
            _history_issue("meta.title_missing", IssueSeverity.WARNING, "https://example.com/a"),
            _history_issue("links.broken", IssueSeverity.CRITICAL, "https://example.com/b"),
        ),
    )
    store.save_run(first)
    store.save_run(second)
    return first, second


@pytest.mark.asyncio
async def test_list_crawls_returns_saved_runs() -> None:
    _seed_two_runs()
    lines = [_request(1, "tools/call", {"name": "list_crawls"})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    result = json.loads(written[0])["result"]
    assert result["isError"] is False
    run_ids = {row["run_id"] for row in result["structuredContent"]["runs"]}
    assert run_ids == {"example.com-run-1", "example.com-run-2"}


@pytest.mark.asyncio
async def test_list_crawls_empty_history_is_friendly() -> None:
    lines = [_request(1, "tools/call", {"name": "list_crawls"})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    result = json.loads(written[0])["result"]
    assert result["structuredContent"]["runs"] == []
    assert "No saved crawls" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_get_crawl_summary_returns_hints_and_trend() -> None:
    _first, second = _seed_two_runs()
    lines = [_request(1, "tools/call", {"name": "get_crawl_summary", "arguments": {"run_id": second.run_id}})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    result = json.loads(written[0])["result"]
    assert result["isError"] is False
    structured = result["structuredContent"]
    assert "issues" not in structured["run"]  # summarized via hints, not dumped per-URL
    assert structured["hints"]  # at least one hint headline
    assert len(structured["trend_points"]) == 2  # both scoped runs
    assert "Top hints" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_get_crawl_summary_unknown_run_id_is_tool_error() -> None:
    lines = [_request(1, "tools/call", {"name": "get_crawl_summary", "arguments": {"run_id": "missing"}})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert json.loads(written[0])["result"]["isError"] is True


# ---------------------------------------------------------------------------
# Protocol edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found() -> None:
    lines = [_request(9, "bogus/thing")]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    response = json.loads(written[0])
    assert response["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_unparseable_line_returns_parse_error_with_null_id() -> None:
    lines = ["not json {{{"]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    response = json.loads(written[0])
    assert response["error"]["code"] == -32700
    assert response["id"] is None


@pytest.mark.asyncio
async def test_notification_without_id_produces_no_output_line() -> None:
    lines = [_notification("notifications/progress", {"value": 1})]
    written, writer = _collecting_writer()

    await mcp_server.serve(read_line=_reader_from(lines), write_line=writer, audit_runner=_unused_runner)

    assert written == []


@pytest.mark.asyncio
async def test_serve_returns_cleanly_on_eof() -> None:
    written, writer = _collecting_writer()

    result = await mcp_server.serve(read_line=_reader_from([]), write_line=writer, audit_runner=_unused_runner)

    assert result is None
    assert written == []


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_dispatches_to_serve(monkeypatch) -> None:
    called = {}

    async def _stub_serve_cmd(args):
        called["args"] = args
        return 0

    monkeypatch.setitem(mcp_server._DISPATCH, "serve", _stub_serve_cmd)
    code = mcp_server.main(["serve"])
    assert code == 0
    assert called["args"].command == "serve"


def test_main_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        mcp_server.main([])
