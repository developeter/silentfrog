"""GEO content-method coverage — quotations, readability, vocabulary, anti-stuffing.

Covers content-level methods inspired by the Princeton GEO study (Aggarwal et
al., KDD 2024, arXiv:2311.09735), which found GEO methods improved
generative-engine visibility by up to ~40% overall — quotation addition was the
most effective and keyword stuffing reduced visibility below baseline (see
docs/RESEARCH_CITATIONS.md, source GEO-AGGARWAL-2024):

- ``citation_quotations`` (the study's most effective method)
- ``citation_readability`` (heuristic ≥ 60 band; "easy-to-understand" helped)
- ``citation_vocabulary_diversity`` (heuristic TTR ≥ 0.5 band; the study found
  unique-word variation among its least effective methods)
- ``citation_no_keyword_stuffing`` (heuristic ``SILENTFROG_KEYWORD_WARN_DENSITY``
  threshold; the study found stuffing hurts)
- ``citation_authoritative_tone`` — heuristic first/second-person pronoun density

Numeric thresholds are Silentfrog heuristics, not measured effect sizes. All
rows are myth-friendly: absent → ``info``; present → ``good``. Only
``citation_no_keyword_stuffing`` can warn (when density exceeds the threshold).
Readability has a language-guard fallback (other languages → ``info``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import bs4
from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

Tag = bs4.element.Tag

_SUPPORTED_READABILITY_LANGS = ("en", "it")

# Quotation patterns. <blockquote>, <q>, and "— Attribution" patterns.
_ATTRIBUTION_RE = re.compile(r"[—–-]\s*[A-ZÀ-Ü][\w\s.'’,-]{2,60}$")

# First/second-person pronouns by language. Used by the authoritative-tone
# heuristic: a high density of first/second-person pronouns indicates a
# conversational tone (positive) rather than a passive/impersonal tone.
_AUTHORITATIVE_PRONOUNS = {
    "en": {"we", "i", "our", "us", "you", "your", "yours", "yourself"},
    "it": {"noi", "io", "nostro", "nostra", "nostri", "nostre", "tu", "tuo", "tua"},
}

# Default keyword-density warning threshold. Mirrors
# ``crawl_constants._keyword_density_threshold`` so the env var is honoured.
_DEFAULT_DENSITY_THRESHOLD = 4.0


def _keyword_density_threshold() -> float:
    raw = os.environ.get("SILENTFROG_KEYWORD_WARN_DENSITY", "").strip()
    if not raw:
        return _DEFAULT_DENSITY_THRESHOLD
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return _DEFAULT_DENSITY_THRESHOLD
    return max(value, 0.0)


@dataclass(frozen=True)
class QuotationSignals:
    count: int
    with_attribution: int
    sample: str = ""

    @classmethod
    def empty(cls) -> QuotationSignals:
        return cls(count=0, with_attribution=0, sample="")


@dataclass(frozen=True)
class ReadabilitySignals:
    score: float | None
    language: str
    formula: str = ""

    @classmethod
    def empty(cls) -> ReadabilitySignals:
        return cls(score=None, language="", formula="")


@dataclass(frozen=True)
class AdvancedCitationPayload:
    quotations: QuotationSignals
    readability: ReadabilitySignals
    vocab_ttr: float
    keyword_warning: bool
    authoritative_tone_ratio: float
    word_count: int

    @classmethod
    def empty(cls) -> AdvancedCitationPayload:
        return cls(
            quotations=QuotationSignals.empty(),
            readability=ReadabilitySignals.empty(),
            vocab_ttr=0.0,
            keyword_warning=False,
            authoritative_tone_ratio=0.0,
            word_count=0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "quotations": {
                "count": self.quotations.count,
                "with_attribution": self.quotations.with_attribution,
                "sample": self.quotations.sample,
            },
            "readability": {
                "score": self.readability.score,
                "language": self.readability.language,
                "formula": self.readability.formula,
            },
            "vocab_ttr": self.vocab_ttr,
            "keyword_warning": self.keyword_warning,
            "authoritative_tone_ratio": self.authoritative_tone_ratio,
            "word_count": self.word_count,
        }

    @classmethod
    def from_raw(cls, value: Any) -> AdvancedCitationPayload:
        if not isinstance(value, dict):
            return cls.empty()
        q_raw = value.get("quotations", {}) if isinstance(value.get("quotations"), dict) else {}
        r_raw = value.get("readability", {}) if isinstance(value.get("readability"), dict) else {}
        return cls(
            quotations=QuotationSignals(
                count=int(q_raw.get("count", 0) or 0),
                with_attribution=int(q_raw.get("with_attribution", 0) or 0),
                sample=str(q_raw.get("sample", "")),
            ),
            readability=ReadabilitySignals(
                score=_opt_float(r_raw.get("score")),
                language=str(r_raw.get("language", "")),
                formula=str(r_raw.get("formula", "")),
            ),
            vocab_ttr=float(value.get("vocab_ttr", 0.0) or 0.0),
            keyword_warning=bool(value.get("keyword_warning", False)),
            authoritative_tone_ratio=float(value.get("authoritative_tone_ratio", 0.0) or 0.0),
            word_count=int(value.get("word_count", 0) or 0),
        )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _language_code(language_hint: str) -> str:
    text = (language_hint or "").strip()
    if not text or text.lower() == "not declared":
        return ""
    if "(" in text and text.endswith(")"):
        text = text.rsplit("(", 1)[1][:-1]
    text = text.replace("_", "-").strip()
    return text.split("-", 1)[0].strip().lower()


def detect_quotations(soup: BeautifulSoup) -> QuotationSignals:
    """Count quotation markers and detect named attribution.

    Sources: ``<blockquote>``, ``<q>``, and paragraphs whose body
    follows the ``"text" — Attribution`` pattern.
    """
    quotes: list[str] = []
    for tag in soup.find_all(["blockquote", "q"]):
        if not isinstance(tag, Tag):
            continue
        text = (tag.get_text() or "").strip()
        if text:
            quotes.append(text)
    # Look in <p> for em/en-dash attribution patterns.
    for paragraph in soup.find_all("p"):
        if not isinstance(paragraph, Tag):
            continue
        text = (paragraph.get_text() or "").strip()
        if not text or '"' not in text and "“" not in text:
            continue
        if _ATTRIBUTION_RE.search(text):
            quotes.append(text)
    with_attribution = sum(1 for q in quotes if _ATTRIBUTION_RE.search(q))
    sample = quotes[0][:160] if quotes else ""
    return QuotationSignals(count=len(quotes), with_attribution=with_attribution, sample=sample)


_SYLLABLE_VOWEL_RE_EN = re.compile(r"[aeiouy]+", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"[.!?]+")


def _count_syllables_en(word: str) -> int:
    """Crude English syllable counter — over-approximates by design."""
    word = word.strip().lower()
    if not word:
        return 0
    matches = _SYLLABLE_VOWEL_RE_EN.findall(word)
    syllables = len(matches)
    if word.endswith("e") and syllables > 1:
        syllables -= 1
    return max(syllables, 1)


def _flesch_reading_ease(text: str) -> float | None:
    """Flesch Reading Ease (English).

    Higher is easier. 60-70 = plain English. <30 = academic. Returns
    None when the text is too short to score reliably (< 25 words).
    """
    words = re.findall(r"\b[\w']+\b", text)
    if len(words) < 25:
        return None
    sentences = max(len([s for s in _SENTENCE_RE.split(text) if s.strip()]), 1)
    syllables = sum(_count_syllables_en(w) for w in words)
    score = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    return round(score, 1)


def _count_syllables_it(word: str) -> int:
    """Italian syllable counter — vowel-group based, over-approximates."""
    matches = re.findall(r"[aeiouàèéìòù]+", word.lower(), re.IGNORECASE)
    return max(len(matches), 1)


def _gulpease(text: str) -> float | None:
    """Indice Gulpease (Italian).

    Range: 0-100. >80 = elementary. 60-80 = middle-school. <60 = harder.
    Returns None when the text is too short to score (< 25 words).
    """
    words = re.findall(r"\b[\w']+\b", text, re.UNICODE)
    if len(words) < 25:
        return None
    letters = sum(len(w) for w in words)
    sentences = max(len([s for s in _SENTENCE_RE.split(text) if s.strip()]), 1)
    if not letters:
        return None
    score = 89 + ((300 * sentences - 10 * letters) / len(words))
    return round(score, 1)


def estimate_readability(plain_text: str, language: str) -> ReadabilitySignals:
    """Language-guarded readability scorer."""
    code = _language_code(language)
    if code == "en":
        score = _flesch_reading_ease(plain_text)
        return ReadabilitySignals(score=score, language="en", formula="Flesch Reading Ease")
    if code == "it":
        score = _gulpease(plain_text)
        return ReadabilitySignals(score=score, language="it", formula="Indice Gulpease")
    return ReadabilitySignals(score=None, language=code, formula="")


def vocabulary_diversity(plain_text: str) -> float:
    """Type-token ratio of normalised word tokens. 0..1."""
    tokens = [w.lower() for w in re.findall(r"\b[\w']+\b", plain_text, re.UNICODE)]
    if len(tokens) < 10:
        return 0.0
    return round(len(set(tokens)) / len(tokens), 3)


def _authoritative_tone_ratio(plain_text: str, language: str) -> float:
    code = _language_code(language)
    pronouns = _AUTHORITATIVE_PRONOUNS.get(code)
    if pronouns is None:
        return 0.0
    tokens = [w.lower() for w in re.findall(r"\b[\w']+\b", plain_text, re.UNICODE)]
    if not tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in pronouns)
    return round(hits / len(tokens), 4)


def extract_citation_advanced_signals(
    soup: BeautifulSoup,
    plain_text: str,
    language: str,
    top_keyword_density: float | None = None,
) -> AdvancedCitationPayload:
    """Top-level extractor used by seo_crawler.analyse.

    ``top_keyword_density`` is the density (percent) of the page's
    most-frequent non-stopword token; the caller pulls it from the
    existing keyword pipeline. ``None`` short-circuits the
    anti-stuffing check.
    """
    threshold = _keyword_density_threshold()
    keyword_warning = (top_keyword_density or 0.0) > threshold
    words = re.findall(r"\b[\w']+\b", plain_text, re.UNICODE)
    return AdvancedCitationPayload(
        quotations=detect_quotations(soup),
        readability=estimate_readability(plain_text, language),
        vocab_ttr=vocabulary_diversity(plain_text),
        keyword_warning=keyword_warning,
        authoritative_tone_ratio=_authoritative_tone_ratio(plain_text, language),
        word_count=len(words),
    )


# ---------------------------------------------------------------------------
# AI Visibility row builders
# ---------------------------------------------------------------------------

_CHECK_META: dict[str, tuple[str, str, str]] = {
    "citation_quotations": (
        "Citation readiness",
        "Page contains quotations with named attribution",
        "Add a small number of expert quotes with attribution; the Princeton GEO study "
        "(KDD 2024) found quotation addition the most effective method tested. Quality, not quantity.",
    ),
    "citation_readability": (
        "Citation readiness",
        "Readability sits in the AI-friendly band",
        "Aim for ≥ 60 on Flesch (EN) or Gulpease (IT) — a Silentfrog heuristic band. "
        "Easier-to-understand text was among the methods that helped in the Princeton GEO study (KDD 2024).",
    ),
    "citation_vocabulary_diversity": (
        "Citation readiness",
        "Vocabulary diversity (type-token ratio) is healthy",
        "Vary phrasing where natural; TTR ≥ 0.5 is a Silentfrog heuristic band for editorial prose "
        "(the Princeton GEO study found unique-word variation among its least effective methods).",
    ),
    "citation_no_keyword_stuffing": (
        "Citation readiness",
        "Top keyword density stays below the anti-stuffing threshold",
        "Keep the top keyword density below SILENTFROG_KEYWORD_WARN_DENSITY (heuristic default 4%). "
        "The Princeton GEO study (KDD 2024) found keyword stuffing reduced visibility below baseline.",
    ),
    "citation_authoritative_tone": (
        "Citation readiness",
        "Authoritative tone — first/second-person pronoun density",
        "Lean into a confident editorial voice (we / you / our). An authoritative tone was among the "
        "methods that helped in the Princeton GEO study (KDD 2024).",
    ),
}


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    area, title, recommendation = _CHECK_META[key]
    return AiVisibilityCheck(
        area=area,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _quotation_status(payload: AdvancedCitationPayload) -> tuple[str, str]:
    q = payload.quotations
    if q.with_attribution > 0:
        return "good", f"{q.with_attribution} quotation(s) with attribution detected."
    if q.count > 0:
        return "info", f"{q.count} quotation(s) detected but no clear attribution."
    return "info", "No quotations detected."


def _readability_status(payload: AdvancedCitationPayload) -> tuple[str, str]:
    r = payload.readability
    if r.score is None:
        if r.language not in _SUPPORTED_READABILITY_LANGS:
            return "info", "Language not supported for readability scoring."
        return "info", "Text too short to score (< 25 words)."
    label = "good" if r.score >= 60 else "info"
    return label, f"{r.formula} score: {r.score} (target ≥ 60)."


def _vocab_status(payload: AdvancedCitationPayload) -> tuple[str, str]:
    if payload.word_count < 50:
        return "info", "Text too short to evaluate vocabulary diversity."
    ratio = payload.vocab_ttr
    status = "good" if ratio >= 0.5 else "info"
    return status, f"Type-token ratio: {ratio:.3f} (healthy ≥ 0.5)."


def _stuffing_status(payload: AdvancedCitationPayload) -> tuple[str, str]:
    threshold = _keyword_density_threshold()
    if payload.word_count < 50:
        return "info", "Text too short to evaluate keyword stuffing."
    if payload.keyword_warning:
        return "warning", f"Top keyword density above the {threshold}% Silentfrog heuristic threshold."
    return "good", f"Top keyword density at or below the {threshold}% Silentfrog heuristic threshold."


def _tone_status(payload: AdvancedCitationPayload) -> tuple[str, str]:
    ratio = payload.authoritative_tone_ratio
    if payload.word_count < 50:
        return "info", "Text too short to evaluate authoritative tone."
    # 1-3% pronouns is normal for editorial copy; below 0.2% suggests
    # impersonal/passive voice.
    status = "good" if ratio >= 0.002 else "info"
    return status, f"First/second-person pronoun ratio: {ratio:.4f}."


def build_advanced_citation_checks(payload: AdvancedCitationPayload) -> list[AiVisibilityCheck]:
    rows: list[AiVisibilityCheck] = []
    for key, status_fn in (
        ("citation_quotations", _quotation_status),
        ("citation_readability", _readability_status),
        ("citation_vocabulary_diversity", _vocab_status),
        ("citation_no_keyword_stuffing", _stuffing_status),
        ("citation_authoritative_tone", _tone_status),
    ):
        status, detail = status_fn(payload)
        rows.append(_check(key, status, detail))
    return rows


__all__ = [
    "AdvancedCitationPayload",
    "QuotationSignals",
    "ReadabilitySignals",
    "build_advanced_citation_checks",
    "detect_quotations",
    "estimate_readability",
    "extract_citation_advanced_signals",
    "vocabulary_diversity",
]
