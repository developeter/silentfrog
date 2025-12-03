from __future__ import annotations

import re
import string
from collections import Counter
from html import unescape
from typing import Any, Dict, List

from bs4 import BeautifulSoup
from .crawl_constants import STOP, _keyword_density_threshold


def _extract_keywords(soup: BeautifulSoup, text: str, top_n: int = 20) -> list[dict[str, object]]:
    def _tokenize(raw: str) -> list[str]:
        cleaned = unescape(raw.lower())
        cleaned = re.sub(r"[{}]".format(re.escape(string.punctuation)), " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        tokens = []
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
        for i in range(len(tokens) - n + 1):
            counter[" ".join(tokens[i : i + n])] += 1
        return counter

    def _first_positions(tokens: list[str], n: int) -> dict[str, int]:
        positions: dict[str, int] = {}
        if len(tokens) < n:
            return positions
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i : i + n])
            if phrase not in positions:
                positions[phrase] = i
        return positions

    body_tokens = _tokenize(text)
    total_tokens = len(body_tokens)
    if total_tokens == 0:
        return []

    sections = {
        "title": _tokenize(soup.title.get_text(" ", strip=True)) if soup.title else [],
        "description": _tokenize(
            next(
                (
                    meta.get("content", "")
                    for meta in soup.find_all("meta")
                    if str(meta.get("name", "")).lower() == "description"
                ),
                "",
            )
        ),
    }

    heading_tokens: list[list[str]] = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$", re.IGNORECASE)):
        heading_tokens.append(_tokenize(heading.get_text(" ", strip=True)))

    heading_counters = {1: Counter[str](), 2: Counter[str](), 3: Counter[str]()}
    for tokens in heading_tokens:
        for n in (1, 2, 3):
            heading_counters[n].update(_phrase_counter(tokens, n))

    section_phrase_sets = {section: {n: _phrase_set(tokens, n) for n in (1, 2, 3)} for section, tokens in sections.items()}

    ngram_stats: Dict[int, Dict[str, Any]] = {}
    for n in (1, 2, 3):
        counts = _phrase_counter(body_tokens, n)
        if not counts:
            counts = Counter()
        positions = _first_positions(body_tokens, n)
        ngram_stats[n] = {"counts": counts, "positions": positions}

    warn_threshold = _keyword_density_threshold()
    results: list[dict[str, object]] = []
    for n in (1, 2, 3):
        counts: Counter[str] = ngram_stats[n]["counts"]
        if not counts:
            continue
        denominator = max(total_tokens - n + 1, 1)
        for term, freq in counts.most_common(top_n):
            density = round((freq / denominator) * 100, 2)
            first_pos = ngram_stats[n]["positions"].get(term)
            density_warning = warn_threshold > 0 and density >= warn_threshold
            entry = {
                "term": term,
                "length": n,
                "frequency": freq,
                "density": density,
                "density_threshold": warn_threshold,
                "density_warning": density_warning,
                "in_title": term in section_phrase_sets["title"][n],
                "in_description": term in section_phrase_sets["description"][n],
                "heading_count": heading_counters[n].get(term, 0),
                "first_position": first_pos if first_pos is not None else -1,
            }
            results.append(entry)

    return results
