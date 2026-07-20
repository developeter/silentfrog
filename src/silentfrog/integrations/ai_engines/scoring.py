"""Pure scoring helpers for AI-engine share-of-voice (v3 G3 Stage 1).

No I/O, no network — every function here is a deterministic string/count
transform so it can be unit-tested without a session double. ``sentiment_label``
is a hand-rolled keyword-count heuristic (EVIDENCE_HEURISTIC-classed in
``research_evidence.CHECK_EVIDENCE``, see ``ai_visibility.py``); it makes no
claim about a reader's actual sentiment, only about word-level tone in the
sampled answer text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .types import EngineAnswer

_WORD_RE = re.compile(r"[a-z']+")
_URL_TOKEN_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# ~15 positive / ~15 negative keywords. Deliberately small and generic —
# this is a coarse tone signal, not a trained sentiment model.
_POSITIVE_WORDS = frozenset(
    {
        "excellent",
        "reliable",
        "trusted",
        "recommended",
        "popular",
        "great",
        "best",
        "leading",
        "innovative",
        "easy",
        "robust",
        "secure",
        "accurate",
        "helpful",
        "strong",
    }
)
_NEGATIVE_WORDS = frozenset(
    {
        "scam",
        "unreliable",
        "poor",
        "avoid",
        "bad",
        "worst",
        "slow",
        "buggy",
        "expensive",
        "complaint",
        "risky",
        "outdated",
        "limited",
        "difficult",
        "negative",
    }
)


def mentions_brand(text: str, brand: str) -> bool:
    """Case-insensitive, word-boundary-ish match — ``brand`` must appear as
    a whole word/phrase, not as a substring of a longer word."""
    brand = (brand or "").strip()
    if not brand or not text:
        return False
    pattern = r"\b" + re.escape(brand) + r"\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def cites_domain(answer: EngineAnswer, domain: str) -> bool:
    """``domain`` present in any structured citation URL, else present as a
    substring of a bare URL-ish token inside the answer text."""
    domain = (domain or "").strip().lower()
    if not domain:
        return False
    for citation in answer.citations:
        if domain in citation.lower():
            return True
    for token in _URL_TOKEN_RE.findall(answer.text or ""):
        if domain in token.lower():
            return True
    return False


def sentiment_label(text: str) -> str:
    """ "positive" | "neutral" | "negative" by keyword-count comparison; a
    tie (including zero hits on both sides) is "neutral"."""
    words = _WORD_RE.findall((text or "").lower())
    positive = sum(1 for word in words if word in _POSITIVE_WORDS)
    negative = sum(1 for word in words if word in _NEGATIVE_WORDS)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def count_competitor_mentions(texts: Sequence[str], competitors: Sequence[str]) -> int:
    """Total (answer, competitor) hits across all sampled answers — the raw
    numerator/denominator input for the "share of voice" check."""
    return sum(1 for text in texts for competitor in competitors if mentions_brand(text, competitor))


__all__ = ["cites_domain", "count_competitor_mentions", "mentions_brand", "sentiment_label"]
