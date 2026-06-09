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


def test_main_dispatches_to_aggregate(monkeypatch) -> None:
    called = {}

    async def _stub_handler(args, analyser=None):
        called["args"] = args
        return 0

    monkeypatch.setitem(cli._DISPATCH, "aggregate", _stub_handler)
    code = cli.main(["aggregate", "https://example.com/sitemap.xml"])
    assert code == 0
    assert called["args"].sitemap_url == "https://example.com/sitemap.xml"
