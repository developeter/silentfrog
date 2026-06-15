"""Unit tests for the v2.0 V13 server-log parser + crawl-budget audit."""

from __future__ import annotations

import json

import pytest

from silentfrog.logs import (
    analyse_entries,
    identify_bot,
    parse_log_line,
    parse_log_text,
)

_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
_COMBINED = f'66.249.66.1 - - [10/Oct/2026:13:55:36 +0000] "GET /page HTTP/1.1" 200 2326 "-" "{_GOOGLEBOT_UA}"'
_CLF = '127.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /old HTTP/1.1" 404 512'
_JSON_LINE = json.dumps(
    {
        "remote_addr": "1.2.3.4",
        "time_local": "10/Oct/2026:13:55:36 +0000",
        "request": "GET /api?x=1 HTTP/1.1",
        "status": 301,
        "body_bytes_sent": 0,
        "http_user_agent": "GPTBot/1.0",
    }
)


def test_parse_combined_line() -> None:
    entry = parse_log_line(_COMBINED)
    assert entry is not None
    assert entry.ip == "66.249.66.1"
    assert entry.method == "GET"
    assert entry.path == "/page"
    assert entry.status == 200
    assert "Googlebot" in entry.user_agent
    assert entry.bytes == 2326


def test_parse_clf_line_without_ua() -> None:
    entry = parse_log_line(_CLF)
    assert entry is not None
    assert entry.path == "/old"
    assert entry.status == 404
    assert entry.user_agent == ""


def test_parse_json_line_strips_query() -> None:
    entry = parse_log_line(_JSON_LINE)
    assert entry is not None
    assert entry.path == "/api"  # query dropped
    assert entry.status == 301
    assert entry.user_agent == "GPTBot/1.0"


def test_parse_log_text_skips_garbage() -> None:
    text = _COMBINED + "\nnot a log line\n\n" + _CLF
    entries = parse_log_text(text)
    assert len(entries) == 2


def test_identify_bot() -> None:
    assert identify_bot(_GOOGLEBOT_UA) == "Googlebot"
    assert identify_bot("Mozilla/5.0 (compatible; GPTBot/1.0)") == "GPTBot"
    assert identify_bot("ClaudeBot/1.0") == "ClaudeBot"
    assert identify_bot("Mozilla/5.0 (Windows NT 10.0) Chrome/120") == ""  # human
    assert identify_bot("") == ""


def test_crawl_budget_report_counts() -> None:
    entries = parse_log_text("\n".join([_COMBINED, _CLF, _JSON_LINE]))
    report = analyse_entries(entries)
    assert report.total_requests == 3
    assert report.bot_requests == 2  # Googlebot + GPTBot (the CLF line has no UA)
    assert report.by_bot["Googlebot"] == 1
    assert report.by_bot["GPTBot"] == 1
    assert report.wasted_404 == 1
    assert report.wasted_redirect == 1
    assert report.by_status_class["2xx"] == 1


def test_crawl_budget_top_404_and_googlebot_paths() -> None:
    lines = [
        '1.1.1.1 - - [d] "GET /missing HTTP/1.1" 404 0',
        '1.1.1.1 - - [d] "GET /missing HTTP/1.1" 404 0',
        f'66.249.66.1 - - [d] "GET /home HTTP/1.1" 200 5 "-" "{_GOOGLEBOT_UA}"',
    ]
    report = analyse_entries(parse_log_text("\n".join(lines)))
    assert report.top_404_paths[0] == ("/missing", 2)
    assert report.googlebot_top_paths[0] == ("/home", 1)


def test_report_to_dict_serialisable() -> None:
    report = analyse_entries(parse_log_text(_COMBINED))
    data = report.to_dict()
    assert json.loads(json.dumps(data))["total_requests"] == 1


@pytest.mark.asyncio
async def test_cli_logs_command(tmp_path) -> None:
    from silentfrog import cli

    log_file = tmp_path / "access.log"
    log_file.write_text("\n".join([_COMBINED, _CLF, _JSON_LINE]), encoding="utf-8")
    out = tmp_path / "report.json"
    args = cli._build_parser().parse_args(["logs", str(log_file), "--out", str(out)])
    code = await cli._logs_cmd(args)
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["total_requests"] == 3
    assert report["wasted_404"] == 1
