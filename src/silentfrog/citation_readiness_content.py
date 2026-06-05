"""Content-pattern signals for citation readiness (M3 of GEO).

Detects question-form headings, statistical-data density, and "X is Y"
style definitions in English and Italian content. Feeds three rows in
the Citation readiness area of the AI Visibility tab.

Per docs/geo_roadmap.md §1.5, ``citation_question_headings`` and
``citation_definition_patterns`` are myth-flagged: absent => "info",
never "warning". ``citation_stats_density`` is a regular best-practice
check — it can emit "warning" when the page contains zero concrete
data points.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import bs4
from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

Tag = bs4.element.Tag

_SUPPORTED_LANGUAGES = ("en", "it")
_MIN_STATS_PER_HUNDRED_WORDS = 0.5  # ≥1 stat per ~200 words

# Question-form opener patterns. Matches at the start of a heading.
_QUESTION_HEADING_EN = re.compile(
    r"^\s*(?:what|why|how|when|where|who|which|is|are|do|does|can|should|could|will)\b",
    re.IGNORECASE,
)
_QUESTION_HEADING_IT = re.compile(
    r"^\s*(?:cosa|cos['’]|come|perch[eé]|quando|dove|chi|quale|quali|"
    r"è|sono|posso|puoi|si\s+può|devo|devi|dobbiamo)\b",
    re.IGNORECASE,
)

# "X is/are Y" definition openers. Designed to catch the first sentence
# of a paragraph: "Retrieval-augmented generation is a technique...".
_DEFINITION_EN = re.compile(
    r"^\s*[A-Z][\w\s'’\-]{2,40}\s+(?:is|are|refers? to|means?|stands? for|denotes?)\s+",
)
_DEFINITION_IT = re.compile(
    r"^\s*[A-ZÀ-Ü][\w\s'’\-à-ü]{2,40}\s+"
    r"(?:è|sono|si\s+definisce|significa|indica|rappresenta)\s+",
)

# Numeric / quantitative tokens. Matches: 42, 3.14, 1,234, 95%, $99, €19,
# 2026, 50 mg, 95 °C. Anchored to word boundaries so "v2" doesn't match.
_STATS_TOKEN = re.compile(
    r"(?<!\w)("
    r"\d+(?:[.,]\d+)?\s*%"                # percentages
    r"|[\$€£¥]\s*\d+(?:[.,]\d+)?"  # currency
    r"|\d+(?:[.,]\d+)?\s*(?:mg|kg|g|ml|l|cm|mm|m|km|MB|GB|TB|MHz|GHz|°C|°F)"
    r"|\d{4}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?"  # years and dates
    r"|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?"     # thousand-separated
    r"|\d+[.,]\d+"                            # decimals
    r")(?!\w)",
    re.UNICODE,
)


@dataclass(frozen=True)
class CitationContentPayload:
    question_headings: tuple[str, ...] = ()
    definitions: tuple[str, ...] = ()
    stats_density: float = 0.0
    stats_count: int = 0
    word_count: int = 0
    language: str = ""

    @classmethod
    def empty(cls) -> "CitationContentPayload":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_headings": list(self.question_headings),
            "definitions": list(self.definitions),
            "stats_density": self.stats_density,
            "stats_count": self.stats_count,
            "word_count": self.word_count,
            "language": self.language,
        }

    @classmethod
    def from_raw(cls, value: Any) -> "CitationContentPayload":
        if not isinstance(value, Mapping):
            return cls.empty()
        return cls(
            question_headings=tuple(_string_tuple(value.get("question_headings"))),
            definitions=tuple(_string_tuple(value.get("definitions"))),
            stats_density=float(value.get("stats_density", 0.0) or 0.0),
            stats_count=int(value.get("stats_count", 0) or 0),
            word_count=int(value.get("word_count", 0) or 0),
            language=str(value.get("language", "")),
        )


def _string_tuple(value: Any) -> Iterable[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return ()
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _language_code(language_hint: str) -> str:
    """Reduce a content_quality.language label to a primary ISO code.

    Inputs look like ``"English (en-US)"`` or ``"Italiano (it-IT)"`` or
    ``"Not declared"``. We return the lowercase primary subtag or "".
    """
    text = (language_hint or "").strip()
    if not text or text.lower() == "not declared":
        return ""
    if "(" in text and text.endswith(")"):
        text = text.rsplit("(", 1)[1][:-1]
    text = text.replace("_", "-").strip()
    primary = text.split("-", 1)[0].strip().lower()
    return primary


_QUESTION_PATTERNS = {"en": _QUESTION_HEADING_EN, "it": _QUESTION_HEADING_IT}
_DEFINITION_PATTERNS = {"en": _DEFINITION_EN, "it": _DEFINITION_IT}


def _heading_texts(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for level in ("h2", "h3"):
        for tag in soup.find_all(level):
            if not isinstance(tag, Tag):
                continue
            text = (tag.get_text() or "").strip()
            if text:
                out.append(text)
    return out


def _paragraph_texts(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("p"):
        if not isinstance(tag, Tag):
            continue
        text = (tag.get_text() or "").strip()
        if text:
            out.append(text)
    return out


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text, re.UNICODE))


def _question_headings(soup: BeautifulSoup, language: str) -> tuple[str, ...]:
    pattern = _QUESTION_PATTERNS.get(language)
    if pattern is None:
        return ()
    return tuple(heading for heading in _heading_texts(soup) if pattern.match(heading))


def _definitions(soup: BeautifulSoup, language: str) -> tuple[str, ...]:
    pattern = _DEFINITION_PATTERNS.get(language)
    if pattern is None:
        return ()
    matches: list[str] = []
    for paragraph in _paragraph_texts(soup):
        first_sentence = re.split(r"(?<=[.!?])\s+", paragraph, maxsplit=1)[0]
        if pattern.match(first_sentence):
            matches.append(first_sentence)
    return tuple(matches)


def _stats_metrics(soup: BeautifulSoup) -> tuple[int, int, float]:
    text = soup.get_text(separator=" ", strip=True)
    words = _word_count(text)
    matches = _STATS_TOKEN.findall(text)
    if not words:
        return len(matches), 0, 0.0
    density = (len(matches) / words) * 100.0
    return len(matches), words, density


def extract_citation_content_signals(soup: BeautifulSoup, language_hint: str) -> CitationContentPayload:
    code = _language_code(language_hint)
    stats_count, words, density = _stats_metrics(soup)
    return CitationContentPayload(
        question_headings=_question_headings(soup, code),
        definitions=_definitions(soup, code),
        stats_density=round(density, 3),
        stats_count=stats_count,
        word_count=words,
        language=code,
    )


_CHECK_META = {
    "citation_question_headings": (
        "H2/H3 headings include question-form phrasing",
        "Where it fits the editorial style, phrase some H2/H3 headings as questions the body answers. "
        "Per Google's AI Optimization Guide, you do NOT need to rewrite content specifically for AI — "
        "this is a positive signal where natural, never a requirement.",
    ),
    "citation_stats_density": (
        "Page contains specific numbers, dates, and units",
        "Include concrete data points (percentages, monetary values, dated events) when accurate and supportable.",
    ),
    "citation_definition_patterns": (
        "Sections open with clear \"X is Y\" definitions",
        "Where it fits the editorial style, open sections with a one-sentence definition. "
        "Per Google's AI Optimization Guide this is a positive signal, never a requirement.",
    ),
}

_AREA = "Citation readiness"


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    title, recommendation = _CHECK_META[key]
    return AiVisibilityCheck(
        area=_AREA,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _language_unsupported_checks(payload: CitationContentPayload) -> list[AiVisibilityCheck]:
    detail = f"Language not supported for content patterns (detected: {payload.language or 'unknown'})."
    return [
        _check("citation_question_headings", "info", detail),
        _check(
            "citation_stats_density",
            _stats_status(payload),
            f"Stats: {payload.stats_count}; density per 100 words: {payload.stats_density:.2f}.",
        ),
        _check("citation_definition_patterns", "info", detail),
    ]


def _question_status(payload: CitationContentPayload) -> str:
    return "good" if payload.question_headings else "info"


def _definition_status(payload: CitationContentPayload) -> str:
    return "good" if payload.definitions else "info"


def _stats_status(payload: CitationContentPayload) -> str:
    if payload.word_count == 0:
        return "info"
    if payload.stats_density >= _MIN_STATS_PER_HUNDRED_WORDS:
        return "good"
    return "warning" if payload.stats_count == 0 else "info"


def build_citation_content_checks(payload: CitationContentPayload) -> list[AiVisibilityCheck]:
    if payload.language not in _SUPPORTED_LANGUAGES:
        return _language_unsupported_checks(payload)
    question_detail = (
        f"Question-form headings: {len(payload.question_headings)}; "
        f"sample: {payload.question_headings[0] if payload.question_headings else '-'}."
    )
    definition_detail = (
        f"Definitions detected: {len(payload.definitions)}; "
        f"sample: {payload.definitions[0] if payload.definitions else '-'}."
    )
    stats_detail = (
        f"Stats: {payload.stats_count}; word count: {payload.word_count}; "
        f"density per 100 words: {payload.stats_density:.2f}; "
        f"threshold: {_MIN_STATS_PER_HUNDRED_WORDS}."
    )
    return [
        _check("citation_question_headings", _question_status(payload), question_detail),
        _check("citation_stats_density", _stats_status(payload), stats_detail),
        _check("citation_definition_patterns", _definition_status(payload), definition_detail),
    ]


__all__ = [
    "CitationContentPayload",
    "build_citation_content_checks",
    "extract_citation_content_signals",
]
