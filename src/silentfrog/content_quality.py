from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from bs4 import BeautifulSoup

from .crawl_types import ContentQuality

_WORD_RE = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
}
_TOOLTIPS = {
    "page language": (
        "Explains the language declared for the page. This helps search engines interpret "
        "the content correctly.\n\n"
        "Best practice: set a valid <html lang> value that matches the main visible language "
        "of the page."
    ),
    "word count": (
        "Measures the amount of visible body copy on the page.\n\n"
        "Best practice: Google does not publish a fixed minimum. Aim for enough original text "
        "to satisfy search intent; thin pages often struggle when they stay below roughly 300 words."
    ),
    "paragraph count": (
        "Shows how many readable text blocks the page contains.\n\n"
        "Best practice: break content into multiple paragraphs instead of one long wall of text."
    ),
    "substantial paragraphs": (
        "Counts paragraphs that contain enough text to carry real information.\n\n"
        "Best practice: have several meaningful paragraphs on pages meant to rank, not only short fragments."
    ),
    "average words / paragraph": (
        "Helps identify paragraphs that are too thin or too dense.\n\n"
        "Best practice: keep most paragraphs comfortably scannable, often around 15 to 60 words."
    ),
    "title present": (
        "Checks whether the page has an HTML <title> tag.\n\n"
        "Best practice: always present, unique, descriptive, and aligned with the page intent."
    ),
    "meta description present": (
        "Checks whether a meta description exists.\n\n"
        "Best practice: present, descriptive, and usually around 120 to 160 characters, even though Google may rewrite it."
    ),
    "h1 count": (
        "Counts the main H1 headings on the page.\n\n"
        "Best practice: one clear H1 that reflects the core topic of the page."
    ),
    "h2-h6 count": (
        "Counts supporting subheadings under the main heading.\n\n"
        "Best practice: use subheadings when the page is long enough to need structure and scanning help."
    ),
    "title / h1 alignment": (
        "Checks whether the title tag and H1 point to the same topic.\n\n"
        "Best practice: aligned in meaning, but not necessarily identical word-for-word."
    ),
    "intro paragraph": (
        "Checks whether the opening paragraph gives immediate context to the page.\n\n"
        "Best practice: start with a useful intro that explains the topic early, above the fold where possible."
    ),
    "thin-content risk": (
        "Estimates whether the page may be too light on useful text.\n\n"
        "Best practice: low risk. Google has no fixed threshold, but pages should contain enough unique copy for their intent."
    ),
    "heading structure": (
        "Checks whether the page uses a logical heading hierarchy.\n\n"
        "Best practice: one H1, then clear H2/H3 sections where the content is long enough to justify them."
    ),
    "overall verdict": (
        "Summarizes the main content-quality signals in this tab.\n\n"
        "Best practice: Strong, with no missing core elements and no obvious thin-content or structure issues."
    ),
}


def _normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _word_set(text: str) -> set[str]:
    return {token.casefold() for token in _WORD_RE.findall(text or "")}


def _language_label(raw: str) -> str:
    code = raw.strip().replace("_", "-")
    if not code:
        return "Not declared"
    primary = code.split("-", 1)[0].casefold()
    name = _LANGUAGE_NAMES.get(primary)
    return f"{name} ({code})" if name else code


def _title_h1_alignment(title: str, h1: str) -> str:
    normalized_title = _normalize_text(title)
    normalized_h1 = _normalize_text(h1)
    if not normalized_title or not normalized_h1:
        return "Missing"
    if normalized_title == normalized_h1:
        return "Exact match"
    title_words = _word_set(normalized_title)
    h1_words = _word_set(normalized_h1)
    smallest = min(len(title_words), len(h1_words)) or 1
    overlap = len(title_words & h1_words) / smallest
    return "Aligned" if overlap >= 0.6 else "Different"


def _thin_content_risk(word_count: int) -> str:
    if word_count < 150:
        return "High"
    if word_count < 300:
        return "Medium"
    return "Low"


def _intro_paragraph(paragraph_word_counts: list[int]) -> str:
    if not paragraph_word_counts:
        return "Weak or missing"
    return "Present" if paragraph_word_counts[0] >= 8 else "Weak or missing"


def _heading_structure(h1_count: int, h2_h6_count: int, word_count: int) -> str:
    if h1_count == 0:
        return "Missing H1"
    if h1_count > 1:
        return "Multiple H1s"
    if word_count >= 300 and h2_h6_count == 0:
        return "No subheadings"
    return "Good"


def _verdict(
    *,
    language: str,
    word_count: int,
    title_present: bool,
    meta_description_present: bool,
    h1_count: int,
    title_h1_alignment: str,
    intro_paragraph: str,
    heading_structure: str,
) -> str:
    critical_signals = (
        word_count < 150,
        not title_present,
        h1_count == 0,
    )
    warning_signals = (
        word_count < 300,
        not meta_description_present,
        language == "Not declared",
        title_h1_alignment == "Different",
        intro_paragraph != "Present",
        heading_structure != "Good",
    )
    if any(critical_signals):
        return "Weak"
    if any(warning_signals):
        return "Needs work"
    return "Strong"


# --- v3 G15: zero-dependency text-glitch detector --------------------------
# Honest scope: no dictionary exists in-tree and downloading one is not
# allowed (a bundled dictionary would need its own P4 dependency decision), so
# this is NOT a spellchecker. It only catches language-agnostic copy/paste and
# typing artifacts via cheap regex: consecutive duplicated words, doubled
# punctuation, and a space stranded before a punctuation mark. True
# dictionary spellcheck is later-scope.

_TEXT_GLITCH_MIN_WORDS = 25  # unmeasured below this threshold — mirrors the
# readability language-guard precedent in citation_advanced.py
# (_flesch_reading_ease / _gulpease return None under 25 words rather than a
# misleading score computed on too little text).
_TEXT_GLITCH_MAX_SAMPLES = 5
_TEXT_GLITCH_SAMPLE_CONTEXT = 40  # chars of context either side of a hit


def _doubled_punct_pattern(char: str) -> re.Pattern[str]:
    """Exactly two of the same mark: a 3+ run (e.g. the "..." ellipsis) is
    excluded by the surrounding negative lookaround, uniformly for !?,. —
    a dumb, language-agnostic rule that cannot tell "Wow!!" from a genuine
    stutter, but two-in-a-row punctuation is rare enough in clean copy that
    the tradeoff favors simplicity over dictionary-grade precision."""
    escaped = re.escape(char)
    return re.compile(rf"(?<!{escaped}){escaped}{{2}}(?!{escaped})")


_DOUBLED_PUNCT_RES = tuple(_doubled_punct_pattern(char) for char in "!?,.")

# A space directly before a punctuation mark; excludes the "..." ellipsis so
# a paced "wait ... what" isn't flagged. French (and any language with a
# space-before-punctuation typographic convention, e.g. "Bonjour !") is
# skipped wholesale in detect_text_glitches rather than special-cased here —
# a per-punctuation exception list would still misfire on French quotation
# guillemets ("« like this »").
_SPACE_BEFORE_PUNCT_RE = re.compile(r" (?=[,.!?;:])(?!\.\.\.)")


def _duplicate_words_in_paragraph(paragraph: str) -> list[tuple[int, int]]:
    """Consecutive case-insensitive duplicate tokens, len >= 2. Single-letter
    tokens ("a a", "I I") are excluded to dodge initials/artifacts, but a
    generic rule still can't tell a legitimate doubled word (an interjection
    like "ha ha") from a genuine typo — that remains an accepted
    false-positive source, not something this heuristic can fix."""
    tokens = list(_WORD_RE.finditer(paragraph))
    return [
        (prev.start(), curr.end())
        for prev, curr in zip(tokens, tokens[1:], strict=False)
        if len(prev.group()) >= 2 and prev.group().casefold() == curr.group().casefold()
    ]


def _doubled_punct_in_paragraph(paragraph: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for pattern in _DOUBLED_PUNCT_RES for m in pattern.finditer(paragraph)]


def _space_before_punct_in_paragraph(paragraph: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _SPACE_BEFORE_PUNCT_RE.finditer(paragraph)]


_GLITCH_KINDS = (
    ("duplicate_words", "duplicate word", _duplicate_words_in_paragraph),
    ("doubled_punctuation", "doubled punctuation", _doubled_punct_in_paragraph),
    ("space_before_punct", "space before punctuation", _space_before_punct_in_paragraph),
)


def _paragraph_glitch_hits(paragraph: str) -> list[tuple[str, str, int, int]]:
    return [(key, label, start, end) for key, label, finder in _GLITCH_KINDS for start, end in finder(paragraph)]


def _glitch_sample(paragraph: str, label: str, start: int, end: int) -> str:
    lo = max(start - _TEXT_GLITCH_SAMPLE_CONTEXT, 0)
    hi = min(end + _TEXT_GLITCH_SAMPLE_CONTEXT, len(paragraph))
    context = _SPACE_RE.sub(" ", paragraph[lo:hi]).strip()
    return f'{label}: "{paragraph[start:end]}" — "{context}"'


def detect_text_glitches(paragraph_texts: Sequence[str], language_code: str = "") -> dict[str, object]:
    """Language-agnostic text-glitch pass: duplicated words, doubled
    punctuation, space-before-punctuation. See the module comment above for
    why this is not a spellchecker.

    French is skipped wholesale (``{}``, unmeasured) because its typography
    places a space before ``! ? ; :`` by convention — the dumb
    space-before-punct rule cannot distinguish that from a typo, so the whole
    detector would over-trigger on otherwise clean French copy.
    """
    if language_code.strip().lower().startswith("fr"):
        return {}
    if sum(_word_count(text) for text in paragraph_texts) < _TEXT_GLITCH_MIN_WORDS:
        return {}
    counts = {key: 0 for key, _label, _finder in _GLITCH_KINDS}
    samples: list[str] = []
    for paragraph in paragraph_texts:
        for key, label, start, end in _paragraph_glitch_hits(paragraph):
            counts[key] += 1
            if len(samples) < _TEXT_GLITCH_MAX_SAMPLES:
                samples.append(_glitch_sample(paragraph, label, start, end))
    return {**counts, "total": sum(counts.values()), "samples": samples}


def extract_content_quality(soup: BeautifulSoup) -> dict[str, object]:
    html_tag = soup.find("html")
    body = soup.body or soup
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.IGNORECASE)})
    description = description_tag.get("content", "").strip() if description_tag else ""
    paragraphs = [paragraph.get_text(" ", strip=True) for paragraph in body.find_all("p")]
    paragraph_word_counts = [count for count in map(_word_count, paragraphs) if count > 0]
    h1_tags = body.find_all(re.compile(r"^h1$", re.IGNORECASE))
    h2_h6_tags = body.find_all(re.compile(r"^h[2-6]$", re.IGNORECASE))
    first_h1 = h1_tags[0].get_text(" ", strip=True) if h1_tags else ""
    body_text = body.get_text(" ", strip=True)
    word_count = _word_count(body_text)
    average_words = round(sum(paragraph_word_counts) / len(paragraph_word_counts), 1) if paragraph_word_counts else 0.0
    raw_lang = html_tag.get("lang", "") if html_tag else ""
    quality = ContentQuality(
        language=_language_label(raw_lang),
        word_count=word_count,
        paragraph_count=len(paragraph_word_counts),
        substantial_paragraph_count=sum(count >= 12 for count in paragraph_word_counts),
        average_words_per_paragraph=average_words,
        title_present=bool(title),
        meta_description_present=bool(description),
        h1_count=len(h1_tags),
        h2_h6_count=len(h2_h6_tags),
        title_h1_alignment=_title_h1_alignment(title, first_h1),
        intro_paragraph=_intro_paragraph(paragraph_word_counts),
        thin_content_risk=_thin_content_risk(word_count),
        heading_structure=_heading_structure(len(h1_tags), len(h2_h6_tags), word_count),
        verdict="",
    )
    verdict = _verdict(
        language=quality.language,
        word_count=quality.word_count,
        title_present=quality.title_present,
        meta_description_present=quality.meta_description_present,
        h1_count=quality.h1_count,
        title_h1_alignment=quality.title_h1_alignment,
        intro_paragraph=quality.intro_paragraph,
        heading_structure=quality.heading_structure,
    )
    return {
        "language": quality.language,
        "word_count": quality.word_count,
        "paragraph_count": quality.paragraph_count,
        "substantial_paragraph_count": quality.substantial_paragraph_count,
        "average_words_per_paragraph": quality.average_words_per_paragraph,
        "title_present": quality.title_present,
        "meta_description_present": quality.meta_description_present,
        "h1_count": quality.h1_count,
        "h2_h6_count": quality.h2_h6_count,
        "title_h1_alignment": quality.title_h1_alignment,
        "intro_paragraph": quality.intro_paragraph,
        "thin_content_risk": quality.thin_content_risk,
        "heading_structure": quality.heading_structure,
        "verdict": verdict,
        # v3 G15: add-only key, absent on pre-G15 blobs — consumers use .get().
        "text_glitches": detect_text_glitches(paragraphs, raw_lang),
    }


def build_content_quality_rows(data: Mapping[str, Any] | ContentQuality | None) -> list[list[str]]:
    if not data:
        return [
            ["Page language", "-"],
            ["Word count", "-"],
            ["Paragraph count", "-"],
            ["Substantial paragraphs", "-"],
            ["Average words / paragraph", "-"],
            ["Title present", "-"],
            ["Meta description present", "-"],
            ["H1 count", "-"],
            ["H2-H6 count", "-"],
            ["Title / H1 alignment", "-"],
            ["Intro paragraph", "-"],
            ["Thin-content risk", "-"],
            ["Heading structure", "-"],
            ["Overall verdict", "-"],
        ]
    quality = data if isinstance(data, ContentQuality) else ContentQuality.from_raw(data)
    return [
        ["Page language", quality.language or "-"],
        ["Word count", str(quality.word_count)],
        ["Paragraph count", str(quality.paragraph_count)],
        ["Substantial paragraphs", str(quality.substantial_paragraph_count)],
        ["Average words / paragraph", f"{quality.average_words_per_paragraph:.1f}"],
        ["Title present", "Yes" if quality.title_present else "No"],
        ["Meta description present", "Yes" if quality.meta_description_present else "No"],
        ["H1 count", str(quality.h1_count)],
        ["H2-H6 count", str(quality.h2_h6_count)],
        ["Title / H1 alignment", quality.title_h1_alignment or "-"],
        ["Intro paragraph", quality.intro_paragraph or "-"],
        ["Thin-content risk", quality.thin_content_risk or "-"],
        ["Heading structure", quality.heading_structure or "-"],
        ["Overall verdict", quality.verdict or "-"],
    ]


def content_quality_tooltip(label: str) -> str:
    return _TOOLTIPS.get(label.strip().lower(), "")


__all__ = [
    "build_content_quality_rows",
    "content_quality_tooltip",
    "detect_text_glitches",
    "extract_content_quality",
]
