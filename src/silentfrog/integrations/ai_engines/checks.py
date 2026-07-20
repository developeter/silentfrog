"""AI share-of-voice AI Visibility checks (v3 G3 Stage 1).

A new "AI Share of Voice" area surfacing BYO-key prompt-sampling results
per engine (mentions / citations / sentiment) plus an optional
brand-vs-competitor share row. Measured rows carry status ``ok`` — they
are observational, and per §1.5 an off-page signal is never
``warning``/``critical``; the non-``info`` status is what lets the GEO
checks badge report the group as measured. Unmeasured (feature off or no
key) => no rows at all, so a stock audit stays silent (mirrors
``brand_mentions``, not the always-on Semrush pattern).
"""

from __future__ import annotations

from ...crawl_types import AiVisibilityCheck
from .types import EngineShareOfVoice, ShareOfVoiceReport

SOV_AREA = "AI Share of Voice"

_ENGINE_LABELS = {
    "openai": "ChatGPT (OpenAI)",
    "perplexity": "Perplexity",
    "gemini": "Gemini",
}

_ENGINE_RECOMMENDATION = (
    "Observational counts from a small BYO-key prompt sample — not a ranking guarantee. Re-sample "
    "periodically (Settings -> AI Share of Voice) to build a local trend; a single audit is a snapshot."
)
_SHARE_RECOMMENDATION = (
    "Improve off-site authority and topical coverage so generative engines have more to draw on when "
    "answering brand-vs-competitor prompts. Counts only, from a small sample — treat as directional."
)


def _engine_row(engine: EngineShareOfVoice) -> AiVisibilityCheck:
    label = _ENGINE_LABELS.get(engine.engine, engine.engine or "engine")
    details = (
        f"Mentioned in {engine.mention_count}/{engine.prompts_sampled} sampled answers; "
        f"cited in {engine.citation_count}; sentiment: {engine.sentiment}."
    )
    return AiVisibilityCheck(
        area=SOV_AREA,
        check=f"AI share of voice — {label}",
        status="ok",
        details=details,
        recommendation=_ENGINE_RECOMMENDATION,
        key=f"sov_{engine.engine}",
    )


def _share_row(engines: tuple[EngineShareOfVoice, ...]) -> AiVisibilityCheck | None:
    """Only emitted when at least one competitor mention was actually
    tallied — the operational proxy for "competitors configured", since the
    report itself does not persist the raw env-configured competitor list."""
    competitor_total = sum(engine.competitor_mention_count for engine in engines)
    if competitor_total <= 0:
        return None
    brand_total = sum(engine.mention_count for engine in engines)
    total = brand_total + competitor_total
    return AiVisibilityCheck(
        area=SOV_AREA,
        check="Brand share of voice vs configured competitors",
        status="ok",
        details=(f"Brand mentioned in {brand_total} of {total} brand-vs-competitor mentions across sampled answers."),
        recommendation=_SHARE_RECOMMENDATION,
        key="sov_share",
    )


def build_sov_checks(report: ShareOfVoiceReport) -> list[AiVisibilityCheck]:
    """Unmeasured => ``[]`` (stock audit silent). Measured => one ``ok`` row
    per measured engine, plus an overall share row when any competitor
    mention was tallied."""
    if not report.measured:
        return []
    measured_engines = tuple(engine for engine in report.engines if engine.measured)
    rows = [_engine_row(engine) for engine in measured_engines]
    share_row = _share_row(measured_engines)
    if share_row is not None:
        rows.append(share_row)
    return rows


__all__ = ["SOV_AREA", "build_sov_checks"]
