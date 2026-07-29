"""Unit tests for the v2.0 V13 server-log parser + crawl-budget audit."""

from __future__ import annotations

import json

import pytest

from silentfrog.logs import (
    analyse_entries,
    classify_bot,
    identify_bot,
    parse_log_line,
    parse_log_text,
)
from silentfrog.logs.bot_fingerprint import _BOT_SIGNATURES, AI_KINDS

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


def test_classify_bot_kinds() -> None:
    gptbot = classify_bot("Mozilla/5.0 (compatible; GPTBot/1.0)")
    assert gptbot is not None
    assert gptbot.label == "GPTBot"
    assert gptbot.vendor == "OpenAI"
    assert gptbot.kind == "ai_training"

    chatgpt_user = classify_bot("ChatGPT-User/1.0")
    assert chatgpt_user is not None and chatgpt_user.kind == "ai_assistant"

    oai_search = classify_bot("OAI-SearchBot/1.0")
    assert oai_search is not None and oai_search.kind == "ai_search"

    googlebot = classify_bot(_GOOGLEBOT_UA)
    assert googlebot is not None and googlebot.kind == "search"

    semrush = classify_bot("Mozilla/5.0 (compatible; SemrushBot/7~bl)")
    assert semrush is not None and semrush.kind == "other"

    assert classify_bot("Mozilla/5.0 (Windows NT 10.0) Chrome/120") is None
    assert classify_bot("") is None


def test_classify_bot_specificity_pairs() -> None:
    # Each pair: the more specific label must win over its shorter cousin.
    cases = [
        ("Applebot-Extended/1.0", "Applebot-Extended"),
        ("Applebot/1.0", "Applebot"),
        ("Meta-ExternalFetcher/1.0", "Meta-ExternalFetcher"),
        ("Meta-ExternalAgent/1.1", "Meta-ExternalAgent"),
        ("DuckAssistBot/1.0", "DuckAssistBot"),
        ("DuckDuckBot/1.0", "DuckDuckBot"),
        ("cohere-training-data-crawler/1.0", "cohere-training-data-crawler"),
        ("cohere-ai/1.0", "cohere-ai"),
        ("omgilibot/1.0", "omgilibot"),
        ("omgili/1.0", "omgili"),
    ]
    for user_agent, expected_label in cases:
        classification = classify_bot(user_agent)
        assert classification is not None, user_agent
        assert classification.label == expected_label


def test_bot_signature_ordering_is_specific_first() -> None:
    # If needle A contains needle B, A must sit before B in the table, or B's
    # match would shadow A's more specific UA. Assert this over every pair.
    needles = [signature.needle for signature in _BOT_SIGNATURES]
    for i, earlier in enumerate(needles):
        for later in needles[i + 1 :]:
            assert earlier not in later, (
                f"{earlier!r} sits before {later!r} but is a substring of it — "
                "reorder so the more specific needle comes first"
            )


def test_bot_taxonomy_size_and_ai_coverage() -> None:
    assert len(_BOT_SIGNATURES) >= 40
    ai_count = sum(1 for signature in _BOT_SIGNATURES if signature.kind in AI_KINDS)
    assert ai_count >= 28


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


def test_crawl_budget_report_ai_agents_section() -> None:
    lines = [
        '1.1.1.1 - - [d] "GET /a HTTP/1.1" 200 0 "-" "GPTBot/1.0"',
        '1.1.1.1 - - [d] "GET /b HTTP/1.1" 403 0 "-" "GPTBot/1.0"',
        '1.1.1.1 - - [d] "GET /c HTTP/1.1" 200 0 "-" "ChatGPT-User/1.0"',
        f'66.249.66.1 - - [d] "GET /home HTTP/1.1" 200 5 "-" "{_GOOGLEBOT_UA}"',
    ]
    report = analyse_entries(parse_log_text("\n".join(lines)))
    ai_agents = report.ai_agents

    assert ai_agents["ai_requests"] == 3
    assert ai_agents["bots"]["GPTBot"]["requests"] == 2
    assert ai_agents["bots"]["GPTBot"]["blocked_4xx_5xx"] == 1
    assert ai_agents["bots"]["GPTBot"]["kind"] == "ai_training"
    assert ai_agents["bots"]["ChatGPT-User"]["requests"] == 1
    assert ai_agents["bots"]["ChatGPT-User"]["blocked_4xx_5xx"] == 0
    # 3 AI hits out of 4 total bot requests (GPTBot x2 + ChatGPT-User + Googlebot).
    assert ai_agents["ai_share_of_bot_traffic"] == 0.75
    assert json.loads(json.dumps(report.to_dict()))["ai_agents"]["ai_requests"] == 3


def test_crawl_budget_report_ai_agents_empty_when_no_ai_hits() -> None:
    report = analyse_entries(parse_log_text(_COMBINED))
    assert report.ai_agents == {}


@pytest.mark.asyncio
async def test_cli_logs_command(tmp_path, capsys) -> None:
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
    # _JSON_LINE's UA is GPTBot/1.0 with a 301 -> one AI-agent request, no blocks.
    assert report["ai_agents"]["ai_requests"] == 1
    assert report["ai_agents"]["bots"]["GPTBot"]["kind"] == "ai_training"
    stderr = capsys.readouterr().err
    assert "1 AI-agent requests from 1 bots" in stderr
