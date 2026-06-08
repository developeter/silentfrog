from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from silentfrog.content_quality import (  # type: ignore[reportMissingImports]
    build_content_quality_rows,
    extract_content_quality,
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
