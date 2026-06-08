from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.citation_advanced import (
    AdvancedCitationPayload,
    build_advanced_citation_checks,
    detect_quotations,
    estimate_readability,
    extract_citation_advanced_signals,
    vocabulary_diversity,
)


def _by_key(rows):
    return {r.key: r for r in rows}


def test_detect_quotations_finds_blockquote_with_attribution() -> None:
    soup = BeautifulSoup(
        '<html><body><blockquote>"The future is local-first." — Mario Rossi</blockquote><p>Body</p></body></html>',
        "html.parser",
    )
    signals = detect_quotations(soup)
    assert signals.count == 1
    assert signals.with_attribution == 1


def test_detect_quotations_empty_when_no_quotes() -> None:
    soup = BeautifulSoup("<p>Plain text body, no quotes.</p>", "html.parser")
    signals = detect_quotations(soup)
    assert signals.count == 0
    assert signals.with_attribution == 0


def test_flesch_reading_ease_scores_english_text() -> None:
    text = (
        "The cat sat on the mat. It was a sunny day. "
        "The dog barked at the cat. The cat jumped down. "
        "It ran into the garden quickly and was gone."
    )
    sig = estimate_readability(text, "English (en-US)")
    assert sig.language == "en"
    assert sig.formula == "Flesch Reading Ease"
    assert sig.score is not None
    assert sig.score > 60  # plain English


def test_readability_falls_back_for_unsupported_language() -> None:
    sig = estimate_readability("Deutscher Text mit vielen vielen Wörtern hier.", "Deutsch (de-DE)")
    assert sig.score is None
    assert sig.language == "de"


def test_gulpease_scores_italian_text() -> None:
    text = (
        "Il gatto dorme sul tappeto. La giornata è soleggiata. "
        "Il cane abbaia al gatto. Il gatto salta giù. "
        "Corre velocemente in giardino e poi sparisce subito tra i fiori."
    )
    sig = estimate_readability(text, "Italiano (it-IT)")
    assert sig.language == "it"
    assert sig.formula == "Indice Gulpease"
    assert sig.score is not None


def test_vocabulary_diversity_higher_for_diverse_text() -> None:
    diverse = " ".join(f"word{i}" for i in range(50))
    repetitive = ("repeat " * 50).strip()
    assert vocabulary_diversity(diverse) > vocabulary_diversity(repetitive)


def test_vocabulary_diversity_short_text_returns_zero() -> None:
    assert vocabulary_diversity("tiny") == 0.0


def test_extract_signals_uses_keyword_warning_threshold(monkeypatch) -> None:
    soup = BeautifulSoup("<p>" + " ".join(["word"] * 100) + "</p>", "html.parser")
    payload = extract_citation_advanced_signals(
        soup,
        "word " * 200,
        "English (en-US)",
        top_keyword_density=6.5,
    )
    assert payload.keyword_warning is True


def test_extract_signals_no_keyword_warning_at_safe_density() -> None:
    soup = BeautifulSoup("<p>" + " ".join(["word"] * 100) + "</p>", "html.parser")
    payload = extract_citation_advanced_signals(
        soup,
        "word " * 200,
        "English (en-US)",
        top_keyword_density=2.0,
    )
    assert payload.keyword_warning is False


def test_build_advanced_checks_all_info_when_payload_empty() -> None:
    rows = _by_key(build_advanced_citation_checks(AdvancedCitationPayload.empty()))
    for key in (
        "citation_quotations",
        "citation_readability",
        "citation_vocabulary_diversity",
        "citation_authoritative_tone",
    ):
        assert rows[key].status == "info"
    # Keyword stuffing on an empty payload short-circuits to info
    # because the word count threshold isn't met.
    assert rows["citation_no_keyword_stuffing"].status == "info"


def test_build_advanced_checks_keyword_warning_when_above_threshold() -> None:
    payload = AdvancedCitationPayload(
        quotations=type(AdvancedCitationPayload.empty().quotations)(0, 0, ""),
        readability=type(AdvancedCitationPayload.empty().readability)(None, "en", "Flesch"),
        vocab_ttr=0.4,
        keyword_warning=True,
        authoritative_tone_ratio=0.001,
        word_count=300,
    )
    rows = _by_key(build_advanced_citation_checks(payload))
    assert rows["citation_no_keyword_stuffing"].status == "warning"
    assert "above" in rows["citation_no_keyword_stuffing"].details


def test_advanced_payload_roundtrips_through_dict() -> None:
    payload = AdvancedCitationPayload(
        quotations=type(AdvancedCitationPayload.empty().quotations)(2, 1, "sample"),
        readability=type(AdvancedCitationPayload.empty().readability)(65.0, "en", "Flesch"),
        vocab_ttr=0.6,
        keyword_warning=False,
        authoritative_tone_ratio=0.01,
        word_count=400,
    )
    restored = AdvancedCitationPayload.from_raw(payload.to_dict())
    assert restored == payload


@pytest.mark.parametrize(
    "key",
    [
        "citation_quotations",
        "citation_readability",
        "citation_vocabulary_diversity",
        "citation_authoritative_tone",
    ],
)
def test_advanced_checks_never_warn_when_absent(key: str) -> None:
    rows = _by_key(build_advanced_citation_checks(AdvancedCitationPayload.empty()))
    assert rows[key].status not in {"warning", "critical"}
