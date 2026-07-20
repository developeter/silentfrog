"""Unit tests for the v3 G3 Stage 1 AI Share of Voice check builder."""

from __future__ import annotations

from silentfrog.integrations.ai_engines.checks import SOV_AREA, build_sov_checks
from silentfrog.integrations.ai_engines.types import EngineShareOfVoice, ShareOfVoiceReport


def test_unmeasured_report_emits_no_rows() -> None:
    assert build_sov_checks(ShareOfVoiceReport()) == []


def test_measured_report_emits_ok_rows_per_engine() -> None:
    report = ShareOfVoiceReport(
        host="acme.com",
        brand="Acme",
        measured=True,
        engines=(
            EngineShareOfVoice(
                engine="openai",
                prompts_sampled=3,
                mention_count=2,
                citation_count=1,
                sentiment="positive",
                competitor_mention_count=0,
                measured=True,
            ),
            EngineShareOfVoice(
                engine="perplexity",
                prompts_sampled=3,
                mention_count=0,
                citation_count=0,
                sentiment="neutral",
                competitor_mention_count=0,
                measured=True,
            ),
        ),
    )
    rows = build_sov_checks(report)
    keys = {row.key for row in rows}
    assert keys == {"sov_openai", "sov_perplexity"}
    # "ok", not "info": measured rows must be non-info so the GEO checks
    # badge can report the group as measured; never warning/critical (§1.5).
    assert all(row.status == "ok" for row in rows)
    assert all(row.area == SOV_AREA for row in rows)
    by_key = {row.key: row for row in rows}
    assert "2/3" in by_key["sov_openai"].details
    assert "sentiment: positive" in by_key["sov_openai"].details


def test_unmeasured_engines_are_excluded() -> None:
    report = ShareOfVoiceReport(
        host="acme.com",
        brand="Acme",
        measured=True,
        engines=(EngineShareOfVoice(engine="gemini", prompts_sampled=3, measured=False),),
    )
    assert build_sov_checks(report) == []


def test_share_row_only_when_competitor_mentions_present() -> None:
    no_competitors = ShareOfVoiceReport(
        host="acme.com",
        brand="Acme",
        measured=True,
        engines=(
            EngineShareOfVoice(
                engine="openai", prompts_sampled=3, mention_count=2, competitor_mention_count=0, measured=True
            ),
        ),
    )
    assert "sov_share" not in {row.key for row in build_sov_checks(no_competitors)}

    with_competitors = ShareOfVoiceReport(
        host="acme.com",
        brand="Acme",
        measured=True,
        engines=(
            EngineShareOfVoice(
                engine="openai", prompts_sampled=3, mention_count=2, competitor_mention_count=3, measured=True
            ),
        ),
    )
    rows = build_sov_checks(with_competitors)
    by_key = {row.key: row for row in rows}
    assert "sov_share" in by_key
    assert by_key["sov_share"].status == "ok"
    assert by_key["sov_share"].area == SOV_AREA
    assert "2 of 5" in by_key["sov_share"].details
