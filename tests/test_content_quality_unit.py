from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.content_quality import (  # type: ignore[reportMissingImports]
    build_content_quality_rows,
    detect_text_glitches,
    extract_content_quality,
)

# 29 words — clears the 25-word measurement floor on its own so each glitch
# test can add exactly one glitch-bearing sentence and still assert on exact
# counts.
_PADDING = (
    "This is a long padding sentence used only to push the total word count "
    "comfortably past the twenty five word minimum threshold required for "
    "measurement to begin properly today."
)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("it-IT", "Italian (it-IT)"),
        ("en-US", "English (en-US)"),
        ("fr-FR", "French (fr-FR)"),
        ("es-ES", "Spanish (es-ES)"),
    ],
)
def test_extract_content_quality_maps_supported_languages(lang: str, expected: str) -> None:
    html = f"""
    <html lang="{lang}">
      <head>
        <title>Guida divano design</title>
        <meta name="description" content="Guida pratica per scegliere un divano design." />
      </head>
      <body>
        <h1>Guida divano design</h1>
        <h2>Materiali</h2>
        <p>Questo contenuto spiega come scegliere forma, stile, rivestimento e proporzioni in modo chiaro e utile.</p>
        <p>Ogni paragrafo aggiunge dettagli operativi per aiutare l'utente a capire misure, comfort, finiture e manutenzione.</p>
        <p>Il testo resta leggibile, ricco e ben organizzato anche per analisi SEO multilingua.</p>
      </body>
    </html>
    """
    quality = extract_content_quality(BeautifulSoup(html, "html.parser"))

    assert quality["language"] == expected
    assert quality["title_h1_alignment"] == "Exact match"
    assert quality["heading_structure"] == "Good"
    assert quality["meta_description_present"] is True


def test_extract_content_quality_flags_thin_weak_pages() -> None:
    html = """
    <html>
      <body>
        <p>Short page only.</p>
      </body>
    </html>
    """
    quality = extract_content_quality(BeautifulSoup(html, "html.parser"))

    assert quality["language"] == "Not declared"
    assert quality["thin_content_risk"] == "High"
    assert quality["heading_structure"] == "Missing H1"
    assert quality["verdict"] == "Weak"


def test_build_content_quality_rows_handles_empty_state() -> None:
    rows = build_content_quality_rows({})
    assert rows[0] == ["Page language", "-"]
    assert rows[-1] == ["Overall verdict", "-"]


def test_detect_text_glitches_flags_duplicate_words_with_sample() -> None:
    paragraphs = [_PADDING, "The the cat sat on the mat quietly today near the door of the old house."]
    result = detect_text_glitches(paragraphs)
    assert result["duplicate_words"] == 1
    assert result["total"] == 1
    assert result["samples"] and "duplicate word" in result["samples"][0]
    assert "the the" in result["samples"][0].lower()


def test_detect_text_glitches_flags_doubled_punctuation() -> None:
    paragraphs = [_PADDING, "This is amazing!! I can not believe it happened here today at all."]
    result = detect_text_glitches(paragraphs)
    assert result["doubled_punctuation"] == 1
    assert result["total"] == 1
    assert any("doubled punctuation" in sample for sample in result["samples"])


def test_detect_text_glitches_flags_space_before_punctuation() -> None:
    paragraphs = [_PADDING, "This sentence has a stray space before the comma , which is a common typo today."]
    result = detect_text_glitches(paragraphs)
    assert result["space_before_punct"] == 1
    assert result["total"] == 1
    assert any("space before punctuation" in sample for sample in result["samples"])


def test_detect_text_glitches_does_not_flag_ellipsis() -> None:
    paragraphs = [
        _PADDING,
        "Well... I suppose that could be true after all in some strange way today.",
        "Wait ... what do you mean by that exactly in this particular strange context today.",
    ]
    result = detect_text_glitches(paragraphs)
    assert result["doubled_punctuation"] == 0
    assert result["space_before_punct"] == 0
    assert result["total"] == 0


def test_detect_text_glitches_unmeasured_under_word_threshold() -> None:
    # "The the cat sat." has a real duplicate but only 4 words total — below
    # the 25-word floor, so it stays unmeasured rather than a misleading hit.
    assert detect_text_glitches(["The the cat sat."]) == {}


def test_detect_text_glitches_skips_french_declared_language() -> None:
    paragraphs = [_PADDING, "Le le chat!! est là , vraiment très bien aujourd'hui pour de vrai."]
    assert detect_text_glitches(paragraphs, "fr-FR") == {}
    assert detect_text_glitches(paragraphs, "fr") == {}


def test_detect_text_glitches_clean_text_has_zero_total() -> None:
    paragraphs = [_PADDING, "This paragraph is entirely clean with no glitches of any kind present today at all."]
    result = detect_text_glitches(paragraphs)
    assert result["total"] == 0
    assert result["samples"] == []


def test_extract_content_quality_includes_text_glitches_key() -> None:
    html = f"""
    <html lang="en">
      <body>
        <h1>Title</h1>
        <p>{_PADDING}</p>
        <p>The the cat sat on the mat quietly today near the door of the old house.</p>
      </body>
    </html>
    """
    quality = extract_content_quality(BeautifulSoup(html, "html.parser"))

    assert quality["text_glitches"]["duplicate_words"] == 1
    assert quality["text_glitches"]["total"] == 1


def test_extract_content_quality_text_glitches_unmeasured_for_thin_page() -> None:
    html = """
    <html>
      <body>
        <p>Short page only.</p>
      </body>
    </html>
    """
    quality = extract_content_quality(BeautifulSoup(html, "html.parser"))

    assert quality["text_glitches"] == {}
