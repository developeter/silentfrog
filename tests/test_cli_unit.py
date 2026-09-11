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
    assert args.allow_private_network is False
    assert args.allow_insecure_tls is False


def _ok_result(base_url: str):
    from silentfrog.site_crawl_types import SiteCrawlResult

    return SiteCrawlResult(
        url=base_url,
        status="ok",
        redirect_status="",
        final_url=base_url,
        title="Example",
        description_state="ok",
        canonical_state="ok",
        indexability="indexable",
        hreflang_count=0,
        schema_count=0,
        image_issue_count=0,
        h1_state="ok",
        word_count=100,
        link_issue_count=0,
        performance_verdict="-",
        ai_visibility_verdict="-",
    )


async def _stub_crawl_fn(config, timeout, store):
    # A genuinely successful single-page crawl (discovered=1, crawled=1,
    # failed=0) -- NOT the discovered_count=0 shape this stub used to return,
    # which was actually the malformed-URL *failure* case (see
    # test_crawl_cmd_returns_one_when_every_page_fails below).
    from silentfrog.site_crawl_types import SiteCrawlReport

    return SiteCrawlReport.from_results([_ok_result(config.base_url)], discovered_count=1, base_url=config.base_url)


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
async def test_crawl_cmd_threads_ssrf_and_tls_flags_into_crawl_options(tmp_path, monkeypatch) -> None:
    """MAJOR regression: `silentfrog-cli crawl` had no way to reach an
    intranet/loopback/self-signed target -- unlike the GUI's Crawl Settings
    dialog -- because _crawl_cmd built SiteCrawlConfig.from_text() without a
    crawl_options= argument, so allow_private_network/allow_insecure_tls
    stayed at CrawlOptions.from_ui's default (False) regardless of what the
    user passed on the command line."""
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "http://127.0.0.1:8931/", "--allow-private-network", "--allow-insecure-tls"])
    captured: dict[str, object] = {}

    async def _capture_config(config, timeout, store):
        captured["config"] = config
        return await _stub_crawl_fn(config, timeout, store)

    await cli._crawl_cmd(args, crawl_fn=_capture_config)

    config = captured["config"]
    assert config.crawl_options.allow_private_network is True
    assert config.crawl_options.allow_insecure_tls is True


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
async def test_crawl_cmd_returns_one_when_every_page_fails(tmp_path, monkeypatch, capsys) -> None:
    """BLOCKER regression: an unreachable host (e.g. http://192.0.2.1/) never
    raises inside crawl_site/fetch_page -- it records a per-page error and
    still returns a normal 'completed' SiteCrawlReport -- so _crawl_cmd must
    read the run's counts, not rely on an exception, to tell a scheduler
    (cron/Task Scheduler) the crawl failed via the exit code."""
    monkeypatch.setenv("SILENTFROG_DATA_DIR", str(tmp_path))
    parser = cli._build_parser()
    args = parser.parse_args(["crawl", "https://example.com/"])

    async def _all_failed(config, timeout, store):
        from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult

        failed = SiteCrawlResult(
            url=config.base_url,
            status="error",
            redirect_status="",
            final_url=config.base_url,
            title="",
            description_state="missing",
            canonical_state="missing",
            indexability="unknown",
            hreflang_count=0,
            schema_count=0,
            image_issue_count=0,
            h1_state="missing",
            word_count=0,
            link_issue_count=0,
            performance_verdict="-",
            ai_visibility_verdict="-",
            error="Name or service not known",
        )
        return SiteCrawlReport.from_results([failed], discovered_count=1, base_url=config.base_url)

    exit_code = await cli._crawl_cmd(args, crawl_fn=_all_failed)

    assert exit_code == 1
    assert "failed" in capsys.readouterr().err


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


def test_build_parser_accepts_review_subcommand() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["review", "https://example.com/page", "--prompt", "Any blockers?"])
    assert args.command == "review"
    assert args.url == "https://example.com/page"
    assert args.prompt == "Any blockers?"
    assert args.out is None


def test_build_parser_review_prompt_defaults_to_empty() -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["review", "https://example.com/page"])
    assert args.prompt == ""


def _review_crawl_payload(url: str = "https://example.com/page"):
    from silentfrog.crawl_types import CrawlPayload

    return CrawlPayload.from_raw(
        {
            "meta": [["title", "Example", "0"], ["description", "An example page.", "0"]],
            "headers": [],
            "images": [],
            "links": [],
            "schema": {
                "summary": {"total": 0, "by_type": {}, "errors": []},
                "blocks": [],
                "issues": [],
                "eligibility": [],
            },
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 400, "h1_count": 1, "verdict": "Strong"},
            "ai_visibility": {
                "summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0},
                "checks": [],
            },
            "performance": {},
            "social": {},
        }
    )


class _StubReviewClient:
    """Records the custom_instructions it was called with; never touches the
    network — mirrors the injectable-client seam ``_review_cmd`` exposes."""

    def __init__(self) -> None:
        self.seen_custom_instructions: str | None = None

    def review(self, request, custom_instructions: str = ""):
        from silentfrog.ai_review import AiReviewFinding, AiReviewResult
        from silentfrog.audit_issues import IssueSeverity

        self.seen_custom_instructions = custom_instructions
        return AiReviewResult(
            provider="stub",
            model="stub-model",
            findings=(
                AiReviewFinding(
                    finding_id="answer_gap",
                    severity=IssueSeverity.WARNING,
                    area="Answerability",
                    reason="No direct answer.",
                    recommendation="Add one.",
                    evidence=(),
                ),
            ),
            raw_summary="One opportunity.",
        )


@pytest.mark.asyncio
async def test_review_cmd_prints_findings_json_with_injected_client(capsys) -> None:
    parser = cli._build_parser()
    args = parser.parse_args(["review", "https://example.com/page", "--prompt", "Any blockers?"])

    async def _stub_analyser(url: str):
        return _review_crawl_payload(url)

    client = _StubReviewClient()
    exit_code = await cli._review_cmd(args, analyser=_stub_analyser, client=client)

    assert exit_code == 0
    assert client.seen_custom_instructions == "Any blockers?"
    body = json.loads(capsys.readouterr().out)
    assert body["provider"] == "stub"
    assert body["summary"] == "One opportunity."
    assert body["findings"][0]["issue_id"] == "ai_review.answer_gap"
    assert body["findings"][0]["category"] == "ai_geo"


@pytest.mark.asyncio
async def test_review_cmd_writes_findings_to_out_file(tmp_path) -> None:
    out = tmp_path / "findings.json"
    parser = cli._build_parser()
    args = parser.parse_args(["review", "https://example.com/page", "--out", str(out)])

    async def _stub_analyser(url: str):
        return _review_crawl_payload(url)

    exit_code = await cli._review_cmd(args, analyser=_stub_analyser, client=_StubReviewClient())

    assert exit_code == 0
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["findings"][0]["reason"] == "No direct answer."


@pytest.mark.asyncio
async def test_review_cmd_no_client_exits_two_without_auditing(monkeypatch) -> None:
    # An unrecognised configured provider (api key set, no/garbage provider
    # name) resolves to no client. That must fail BEFORE auditing the page —
    # auditing is unrelated cost the user shouldn't pay for a config error.
    monkeypatch.setenv("SILENTFROG_AI_API_KEY", "some-key")
    monkeypatch.delenv("SILENTFROG_AI_PROVIDER", raising=False)
    parser = cli._build_parser()
    args = parser.parse_args(["review", "https://example.com/page"])
    audited = []

    async def _stub_analyser(url: str):
        audited.append(url)
        return _review_crawl_payload(url)

    exit_code = await cli._review_cmd(args, analyser=_stub_analyser)

    assert exit_code == 2
    assert audited == []


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
