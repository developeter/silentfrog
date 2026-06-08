from __future__ import annotations

from bs4 import BeautifulSoup

from silentfrog.keywords import (  # type: ignore[reportMissingImports]
    _extract_keywords,
    _keyword_density_threshold,
)


def test_keywords_density_flags_and_positions() -> None:
    # Ensures density warning, title/description flags, and first_position are set for high-frequency terms.
    html = """
    <html>
      <head>
        <title>Hello World</title>
        <meta name="description" content="Hello world again">
      </head>
      <body>
        Hello hello hello world world test test
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    results = _extract_keywords(soup, text, top_n=3)
    hello_entry = next(item for item in results if item["term"] == "hello")
    assert hello_entry["density"] >= _keyword_density_threshold()
    assert hello_entry["density_warning"] is True
    assert hello_entry["first_position"] == 0
    assert hello_entry["in_title"] is True
    assert hello_entry["in_description"] is True


def test_keywords_ignore_numbers_and_digits() -> None:
    # Confirms tokens containing digits are dropped from keyword extraction.
    html = "<html><body>abc 123 abc1 abc two2 three</body></html>"
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    results = _extract_keywords(soup, text, top_n=5)
    terms = {item["term"] for item in results}
    assert "abc" in terms
    assert "123" not in terms
    assert "abc1" not in terms
    assert "two2" not in terms


def test_keywords_output_keeps_expected_order_and_flags() -> None:
    html = """
    <html>
      <head>
        <title>alpha beta alpha</title>
        <meta name="description" content="alpha beta gamma">
      </head>
      <body>
        <h1>alpha beta</h1>
        alpha beta alpha beta alpha gamma gamma
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    results = _extract_keywords(soup, text, top_n=2)

    assert [(item["term"], item["length"]) for item in results[:4]] == [
        ("alpha", 1),
        ("beta", 1),
        ("alpha beta", 2),
        ("beta alpha", 2),
    ]
    alpha = next(item for item in results if item["term"] == "alpha")
    alpha_beta = next(item for item in results if item["term"] == "alpha beta")
    assert alpha["in_title"] is True
    assert alpha["in_description"] is True
    assert alpha["heading_count"] == 1
    assert alpha["first_position"] == 0
    assert alpha_beta["in_title"] is True
    assert alpha_beta["heading_count"] == 1
