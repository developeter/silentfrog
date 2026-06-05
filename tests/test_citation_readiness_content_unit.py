from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from silentfrog.citation_readiness_content import (  # type: ignore[reportMissingImports]
    CitationContentPayload,
    build_citation_content_checks,
    extract_citation_content_signals,
)

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def _statuses(payload: CitationContentPayload) -> dict[str, str]:
    return {item.key: item.status for item in build_citation_content_checks(payload)}


def _details(payload: CitationContentPayload) -> dict[str, str]:
    return {item.key: item.details for item in build_citation_content_checks(payload)}


def test_extract_question_headings_en() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_en.html"), "English (en-US)")
    # h2: What/How/When, h3: Why → 4 question headings
    assert len(payload.question_headings) >= 4
    assert payload.language == "en"


def test_extract_question_headings_it() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_it.html"), "Italiano (it-IT)")
    assert len(payload.question_headings) >= 4
    assert payload.language == "it"


def test_extract_question_headings_unsupported_language_returns_empty() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_en.html"), "Deutsch (de-DE)")
    assert payload.question_headings == ()
    assert payload.language == "de"


def test_extract_stats_density_counts_concrete_tokens() -> None:
    payload = extract_citation_content_signals(_soup("citation_stats_density.html"), "English (en-US)")
    assert payload.stats_count >= 8
    assert payload.stats_density > 0.0


def test_extract_definitions_en_matches_x_is_y_pattern() -> None:
    payload = extract_citation_content_signals(_soup("citation_definitions.html"), "English (en-US)")
    assert len(payload.definitions) >= 3
    openers = (" is ", " refers to ", " denote ", " denotes ", " means ", " stands for ")
    assert all(any(opener in definition for opener in openers) for definition in payload.definitions)


def test_build_citation_content_checks_en_question_headings_is_good() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_en.html"), "English (en-US)")
    assert _statuses(payload)["citation_question_headings"] == "good"


def test_build_citation_content_checks_it_question_headings_is_good() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_it.html"), "Italiano (it-IT)")
    assert _statuses(payload)["citation_question_headings"] == "good"


def test_build_citation_content_checks_stats_dense_page_is_good() -> None:
    payload = extract_citation_content_signals(_soup("citation_stats_density.html"), "English (en-US)")
    assert _statuses(payload)["citation_stats_density"] == "good"


def test_build_citation_content_checks_definition_rich_page_is_good() -> None:
    payload = extract_citation_content_signals(_soup("citation_definitions.html"), "English (en-US)")
    assert _statuses(payload)["citation_definition_patterns"] == "good"


def test_build_citation_content_checks_empty_payload_uses_info_for_myth_keys() -> None:
    payload = CitationContentPayload(language="en", word_count=200)
    statuses = _statuses(payload)
    # No question headings or definitions => info (myth-flagged keys).
    assert statuses["citation_question_headings"] == "info"
    assert statuses["citation_definition_patterns"] == "info"
    # No stats and non-zero word count => warning (this one is allowed
    # to warn since stats density is a real best-practice check).
    assert statuses["citation_stats_density"] == "warning"


def test_build_citation_content_checks_unsupported_language_marks_info() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_en.html"), "Deutsch (de-DE)")
    statuses = _statuses(payload)
    details = _details(payload)
    assert statuses["citation_question_headings"] == "info"
    assert statuses["citation_definition_patterns"] == "info"
    assert "Language not supported" in details["citation_question_headings"]
    assert "Language not supported" in details["citation_definition_patterns"]


def test_build_citation_content_checks_not_declared_language_marks_info() -> None:
    payload = extract_citation_content_signals(_soup("citation_question_headings_en.html"), "Not declared")
    statuses = _statuses(payload)
    assert statuses["citation_question_headings"] == "info"
    assert statuses["citation_definition_patterns"] == "info"


@pytest.mark.parametrize(
    "myth_key",
    ["citation_question_headings", "citation_definition_patterns"],
)
def test_citation_content_myth_keys_never_warn(myth_key: str) -> None:
    payload = CitationContentPayload(language="en", word_count=200)
    assert _statuses(payload)[myth_key] not in {"warning", "critical"}


def test_citation_content_payload_roundtrips_through_dict() -> None:
    payload = CitationContentPayload(
        question_headings=("What is RAG?",),
        definitions=("RAG is a technique...",),
        stats_density=1.5,
        stats_count=3,
        word_count=200,
        language="en",
    )
    restored = CitationContentPayload.from_raw(payload.to_dict())
    assert restored == payload
