from __future__ import annotations

import re
import string
from collections import Counter
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

from .crawl_constants import STOP, _keyword_density_threshold


def _tokenize(raw: str) -> list[str]:
    cleaned = unescape(raw.lower())
    cleaned = re.sub(rf"[{re.escape(string.punctuation)}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    tokens: list[str] = []
    for token in cleaned.split():
        if not token or token in STOP or len(token) <= 2:
            continue
        if token.isdigit() or any(ch.isdigit() for ch in token):
            continue
        tokens.append(token)
    return tokens


def _phrase_set(tokens: list[str], n: int) -> set[str]:
    if len(tokens) < n:
        return set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _phrase_counter(tokens: list[str], n: int) -> Counter[str]:
    counter: Counter[str] = Counter()
    if len(tokens) < n:
        return counter
    for index in range(len(tokens) - n + 1):
        counter[" ".join(tokens[index : index + n])] += 1
    return counter


def _first_positions(tokens: list[str], n: int) -> dict[str, int]:
    positions: dict[str, int] = {}
    if len(tokens) < n:
        return positions
    for index in range(len(tokens) - n + 1):
        phrase = " ".join(tokens[index : index + n])
        positions.setdefault(phrase, index)
    return positions


def _section_tokens(soup: BeautifulSoup) -> dict[str, list[str]]:
    description = next(
        (
            meta.get("content", "")
            for meta in soup.find_all("meta")
            if str(meta.get("name", "")).lower() == "description"
        ),
        "",
    )
    return {
        "title": _tokenize(soup.title.get_text(" ", strip=True)) if soup.title else [],
        "description": _tokenize(description),
    }


def _heading_tokens(soup: BeautifulSoup) -> list[list[str]]:
    heading_tokens: list[list[str]] = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$", re.IGNORECASE)):
        heading_tokens.append(_tokenize(heading.get_text(" ", strip=True)))
    return heading_tokens


def _heading_counters(heading_tokens: list[list[str]]) -> dict[int, Counter[str]]:
    counters = {1: Counter[str](), 2: Counter[str](), 3: Counter[str]()}
    for tokens in heading_tokens:
        for n in (1, 2, 3):
            counters[n].update(_phrase_counter(tokens, n))
    return counters


def _section_phrase_sets(sections: dict[str, list[str]]) -> dict[str, dict[int, set[str]]]:
    return {section: {n: _phrase_set(tokens, n) for n in (1, 2, 3)} for section, tokens in sections.items()}


def _ngram_stats(body_tokens: list[str]) -> dict[int, dict[str, Any]]:
    stats: dict[int, dict[str, Any]] = {}
    for n in (1, 2, 3):
        stats[n] = {
            "counts": _phrase_counter(body_tokens, n),
            "positions": _first_positions(body_tokens, n),
        }
    return stats


def _keyword_entry(
    *,
    term: str,
    n: int,
    freq: int,
    denominator: int,
    warn_threshold: float,
    first_position: int | None,
    section_phrase_sets: dict[str, dict[int, set[str]]],
    heading_counters: dict[int, Counter[str]],
) -> dict[str, object]:
    density = round((freq / denominator) * 100, 2)
    density_warning = warn_threshold > 0 and density >= warn_threshold
    return {
        "term": term,
        "length": n,
        "frequency": freq,
        "density": density,
        "density_threshold": warn_threshold,
        "density_warning": density_warning,
        "in_title": term in section_phrase_sets["title"][n],
        "in_description": term in section_phrase_sets["description"][n],
        "heading_count": heading_counters[n].get(term, 0),
        "first_position": first_position if first_position is not None else -1,
    }


def _entries_for_ngram(
    n: int,
    counts: Counter[str],
    positions: dict[str, int],
    *,
    total_tokens: int,
    top_n: int,
    warn_threshold: float,
    section_phrase_sets: dict[str, dict[int, set[str]]],
    heading_counters: dict[int, Counter[str]],
) -> list[dict[str, object]]:
    if not counts:
        return []
    denominator = max(total_tokens - n + 1, 1)
    entries: list[dict[str, object]] = []
    for term, freq in counts.most_common(top_n):
        entries.append(
            _keyword_entry(
                term=term,
                n=n,
                freq=freq,
                denominator=denominator,
                warn_threshold=warn_threshold,
                first_position=positions.get(term),
                section_phrase_sets=section_phrase_sets,
                heading_counters=heading_counters,
            )
        )
    return entries


def _extract_keywords(soup: BeautifulSoup, text: str, top_n: int = 20) -> list[dict[str, object]]:
    body_tokens = _tokenize(text)
    total_tokens = len(body_tokens)
    if total_tokens == 0:
        return []

    sections = _section_tokens(soup)
    heading_counters = _heading_counters(_heading_tokens(soup))
    section_phrase_sets = _section_phrase_sets(sections)
    stats = _ngram_stats(body_tokens)
    warn_threshold = _keyword_density_threshold()
    results: list[dict[str, object]] = []

    for n in (1, 2, 3):
        results.extend(
            _entries_for_ngram(
                n,
                stats[n]["counts"],
                stats[n]["positions"],
                total_tokens=total_tokens,
                top_n=top_n,
                warn_threshold=warn_threshold,
                section_phrase_sets=section_phrase_sets,
                heading_counters=heading_counters,
            )
        )
    return results
