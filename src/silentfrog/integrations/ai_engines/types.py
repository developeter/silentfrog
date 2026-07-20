"""Typed AI-engine share-of-voice payloads (v3 G3 Stage 1).

Frozen slots dataclasses so BYO-key prompt-sampling results cross module
boundaries typed, per AGENTS.md. ``measured`` distinguishes "we actually
sampled the engine" from "the integration isn't connected" — absent data
is informational and never penalises the GEO Score (§1.5 myth rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class EngineAnswer:
    """One sampled prompt/answer pair from a single engine. Not persisted
    directly — ``client.py`` folds these into an ``EngineShareOfVoice``."""

    engine: str = ""
    prompt: str = ""
    text: str = ""
    citations: tuple[str, ...] = field(default_factory=tuple)
    measured: bool = False


@dataclass(frozen=True, slots=True)
class EngineShareOfVoice:
    engine: str = ""
    prompts_sampled: int = 0
    mention_count: int = 0
    citation_count: int = 0
    # "positive" | "neutral" | "negative" — see scoring.sentiment_label.
    sentiment: str = "neutral"
    competitor_mention_count: int = 0
    measured: bool = False

    @classmethod
    def from_dict(cls, value: Any) -> EngineShareOfVoice:
        if not isinstance(value, dict):
            return cls()
        return cls(
            engine=str(value.get("engine", "")),
            prompts_sampled=_to_int(value.get("prompts_sampled", 0)),
            mention_count=_to_int(value.get("mention_count", 0)),
            citation_count=_to_int(value.get("citation_count", 0)),
            sentiment=str(value.get("sentiment", "neutral")).strip() or "neutral",
            competitor_mention_count=_to_int(value.get("competitor_mention_count", 0)),
            measured=bool(value.get("measured", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "prompts_sampled": self.prompts_sampled,
            "mention_count": self.mention_count,
            "citation_count": self.citation_count,
            "sentiment": self.sentiment,
            "competitor_mention_count": self.competitor_mention_count,
            "measured": self.measured,
        }


@dataclass(frozen=True, slots=True)
class ShareOfVoiceReport:
    host: str = ""
    brand: str = ""
    engines: tuple[EngineShareOfVoice, ...] = field(default_factory=tuple)
    measured: bool = False

    @classmethod
    def empty(cls) -> ShareOfVoiceReport:
        return cls()

    @classmethod
    def from_dict(cls, value: Any) -> ShareOfVoiceReport:
        if not isinstance(value, dict):
            return cls()
        raw_engines = value.get("engines", [])
        engines = (
            tuple(EngineShareOfVoice.from_dict(item) for item in raw_engines if isinstance(item, dict))
            if isinstance(raw_engines, (list, tuple))
            else ()
        )
        return cls(
            host=str(value.get("host", "")),
            brand=str(value.get("brand", "")),
            engines=engines,
            measured=bool(value.get("measured", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "brand": self.brand,
            "engines": [engine.to_dict() for engine in self.engines],
            "measured": self.measured,
        }


__all__ = ["EngineAnswer", "EngineShareOfVoice", "ShareOfVoiceReport"]
