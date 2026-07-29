from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from silentfrog import cli


@dataclass
class _Summary:
    score: int = 80
    verdict: str = "Strong"
    good_count: int = 0
    warning_count: int = 0
    critical_count: int = 0


@dataclass
class _Check:
    area: str
    check: str
    status: str
    key: str = "x"


@dataclass
class _AiV:
    summary: _Summary
    checks: list[_Check]


@dataclass
class _Payload:
    ai_visibility: _AiV


def _payload(score: int = 80) -> _Payload:
    return _Payload(_AiV(summary=_Summary(score=score), checks=[]))


def test_build_parser_accepts_aggregate_subcommand() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["aggregate", "https://example.com/sitemap.xml"])
    assert args.command == "aggregate"
    assert args.sitemap_url == "https://example.com/sitemap.xml"
    assert args.concurrency == 8


def test_build_parser_accepts_watch_subcommand() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(
        ["watch", "https://a.com/", "https://b.com/", "--iterations", "3", "--drop-threshold", "7"]
    )
    assert args.command == "watch"
    assert args.urls == ["https://a.com/", "https://b.com/"]
    assert args.iterations == 3
    assert args.drop_threshold == 7


def test_build_parser_requires_subcommand() -> None:
    parser = cli._build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


@pytest.mark.asyncio
async def test_aggregate_cmd_writes_json_to_out_file(tmp_path, monkeypatch) -> None:
    out = tmp_path / "report.json"
    parser = cli._build_parser()
    args = parser.parse_args(["aggregate", "https://example.com/sitemap.xml", "--out", str(out)])

    async def _stub_analyser(url: str):
        return _payload(80)

    async def _stub_fetch(*_args, **_kwargs):
        return (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/a</loc></url>"
            "</urlset>"
        )

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)
    exit_code = await cli._aggregate_cmd(args, analyser=_stub_analyser)
    assert exit_code == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["count"] == 1
    assert body["measured_count"] == 1


@pytest.mark.asyncio
async def test_aggregate_cmd_writes_to_stdout_when_no_out(capsys, monkeypatch) -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["aggregate", "https://example.com/sitemap.xml"])

    async def _stub_analyser(url: str):
        return _payload(80)

    async def _stub_fetch(*_args, **_kwargs):
        return (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://example.com/a</loc></url>"
            "</urlset>"
        )

    monkeypatch.setattr("silentfrog.sitemap_geo_aggregate.fetch_sitemap", _stub_fetch)
    await cli._aggregate_cmd(args, analyser=_stub_analyser)
    captured = capsys.readouterr()
    body = json.loads(captured.out.strip())
    assert body["count"] == 1


def test_build_parser_accepts_logs_flags() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["logs", "access.log", "--base-url", "https://e.com", "--known-urls", "known.txt"])
    assert args.command == "logs"
    assert args.base_url == "https://e.com"
    assert str(args.known_urls) == "known.txt"


_GOOGLEBOT_LOG = (
    '66.249.66.1 - - [08/Jul/2026:10:00:00 +0000] "GET /gone HTTP/1.1" 404 0 "-" "Googlebot/2.1"\n'
    '66.249.66.1 - - [08/Jul/2026:10:00:01 +0000] "GET /seen HTTP/1.1" 200 100 "-" "Googlebot/2.1"\n'
)


@pytest.mark.asyncio
async def test_logs_cmd_wires_issue_model_findings(tmp_path) -> None:
    # M6 regression: the logs command must feed log_analysis.issues_for_log_report
    # into its output. Fails if the mapper is left unwired again.
    log = tmp_path / "access.log"
    log.write_text(_GOOGLEBOT_LOG, encoding="utf-8")
    known = tmp_path / "known.txt"
    known.write_text("/seen\n/never-hit\n", encoding="utf-8")
    out = tmp_path / "report.json"
    parser = cli._build_parser()
    args = parser.parse_args(
        ["logs", str(log), "--base-url", "https://e.com", "--known-urls", str(known), "--out", str(out)]
    )

    exit_code = await cli._logs_cmd(args)

    assert exit_code == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert "bot_requests" in body  # crawl-budget report preserved
    ids = {issue["issue_id"] for issue in body["issues"]}
    assert "logs.googlebot_blocked" in ids  # Googlebot 404
    assert "logs.important_urls_not_hit" in ids  # /never-hit never crawled
    blocked = next(i for i in body["issues"] if i["issue_id"] == "logs.googlebot_blocked")
    assert blocked["category"] == "logs"
    assert blocked["url"] == "https://e.com/gone"  # base-url applied


@pytest.mark.asyncio
async def test_logs_cmd_without_known_urls_still_emits_issues(tmp_path) -> None:
    # The four config-free findings fire without --known-urls; only orphan /
    # important-not-hit need the known set.
    log = tmp_path / "access.log"
    log.write_text(_GOOGLEBOT_LOG, encoding="utf-8")
    out = tmp_path / "report.json"
    parser = cli._build_parser()
    args = parser.parse_args(["logs", str(log), "--out", str(out)])

    await cli._logs_cmd(args)

    body = json.loads(out.read_text(encoding="utf-8"))
    ids = {issue["issue_id"] for issue in body["issues"]}
    assert "logs.googlebot_blocked" in ids
    assert "logs.important_urls_not_hit" not in ids  # no known set -> not detectable


@pytest.mark.asyncio
async def test_watch_cmd_runs_for_iterations(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("silentfrog.watch_mode._alert_log_path", lambda: tmp_path / "alerts.log")
    parser = cli._build_parser()
    args = parser.parse_args(["watch", "https://example.com/", "--iterations", "2", "--interval-seconds", "1"])
    iteration = 0
    scores = [90, 70]  # second is a regression

    async def _stub_analyser(url: str):
        nonlocal iteration
        score = scores[iteration % len(scores)]
        iteration += 1
        return _payload(score)

    # Patch asyncio.sleep inside watch_mode so we don't actually wait.
    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr("silentfrog.watch_mode.asyncio.sleep", _no_sleep)
    exit_code = await cli._watch_cmd(args, analyser=_stub_analyser)
    assert exit_code == 0


def test_build_parser_accepts_crawl_subcommand() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(
        [
            "crawl",
            "https://example.com/",
            "--limit",
            "50",
            "--timeout",
            "5",
            "--digest",
            "--sitemap",
            "https://e.com/s.xml",
        ]
    )
    assert args.command == "crawl"
    assert args.base_url == "https://example.com/"
    assert args.sitemap_url == "https://e.com/s.xml"
    assert args.limit == 50
    assert args.timeout == 5
    assert args.digest is True
    assert args.out_report is None


def test_build_parser_crawl_defaults() -> None:
    from silentfrog.site_crawl_types import DEFAULT_SITE_CRAWL_LIMIT

    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])
    assert args.limit == DEFAULT_SITE_CRAWL_LIMIT
    assert args.timeout == 10
    assert args.digest is False
    assert args.url_list is None


async def _stub_crawl_fn(config, timeout, store):
    from silentfrog.site_crawl_types import SiteCrawlReport

    return SiteCrawlReport.from_results([], discovered_count=0, base_url=config.base_url)


@pytest.mark.asyncio
async def test_crawl_cmd_prints_digest_and_returns_zero(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])

    exit_code = await cli._crawl_cmd(args, crawl_fn=_stub_crawl_fn)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "History: saved first run" in captured.out


@pytest.mark.asyncio
async def test_crawl_cmd_failure_returns_one(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])

    async def _boom(config, timeout, store):
        raise RuntimeError("network down")

    exit_code = await cli._crawl_cmd(args, crawl_fn=_boom)

    assert exit_code == 1
    assert "network down" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_crawl_cmd_with_digest_calls_deliver_fn(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/", "--digest"])
    delivered = []

    async def _stub_deliver(digest):
        delivered.append(digest)
        return {"webhook": True}

    exit_code = await cli._crawl_cmd(args, crawl_fn=_stub_crawl_fn, deliver_fn=_stub_deliver)

    assert exit_code == 0
    assert len(delivered) == 1
    assert "webhook: sent" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_crawl_cmd_without_digest_flag_never_delivers(tmp_path, monkeypatch) -> None:
    # Zero-network-by-default contract: --digest omitted must never call deliver_fn,
    # even if transports happen to be configured in the environment.
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])
    delivered = []

    async def _stub_deliver(digest):
        delivered.append(digest)
        return {"webhook": True}

    exit_code = await cli._crawl_cmd(args, crawl_fn=_stub_crawl_fn, deliver_fn=_stub_deliver)

    assert exit_code == 0
    assert delivered == []


@pytest.mark.asyncio
async def test_crawl_cmd_out_report_writes_html_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    out = tmp_path / "report.html"
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/", "--out-report", str(out)])

    exit_code = await cli._crawl_cmd(args, crawl_fn=_stub_crawl_fn)

    assert exit_code == 0
    assert out.exists()
    assert "<html" in out.read_text(encoding="utf-8")


def test_main_dispatches_to_aggregate(monkeypatch) -> None:
    called = {}

    async def _stub_handler(args, analyser=None):
        called["args"] = args
        return 0

    monkeypatch.setitem(cli._DISPATCH, "aggregate", _stub_handler)
    code = cli.main(["aggregate", "https://example.com/sitemap.xml"])
    assert code == 0
    assert called["args"].sitemap_url == "https://example.com/sitemap.xml"


def test_print_encodable_survives_cp1252_stdout(monkeypatch) -> None:
    # Windows Task Scheduler redirects stdout through the console codepage;
    # a digest carrying non-cp1252 crawl content (non-Latin titles, arrows)
    # must degrade to replacement characters, never UnicodeEncodeError.
    import io
    import sys

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    cli._print_encodable("Health → 標題 · ok")

    stream.flush()
    raw = stream.buffer.getvalue().decode("cp1252")
    assert "ok" in raw
