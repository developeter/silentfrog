import textwrap
from typing import Dict, List

import pytest
from bs4 import BeautifulSoup

from silentfrog import seo_crawler as crawler


@pytest.fixture
def sample_html() -> str:
    return textwrap.dedent(
        """
        <html>
          <head>
            <title>Sample Title</title>
            <meta name="description" content="Sample description for testing.">
            <meta property="og:site_name" content="ExampleSite">
            <link rel="canonical" href="/canonical/page">
            <link rel="alternate" hreflang="en" href="/en/page">
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"WebPage","name":"Sample","url":"https://example.com/canonical/page"}
            </script>
          </head>
          <body>
            <h1>Main Heading</h1>
            <img src="/images/logo.png" alt="Logo" title="Logo title">
            <a href="/internal" rel="">Internal</a>
            <a href="https://external.example" rel="nofollow">External</a>
          </body>
        </html>
        """
    )


@pytest.fixture
def soup(sample_html: str) -> BeautifulSoup:
    return BeautifulSoup(sample_html, "html.parser")


@pytest.fixture
def base_url() -> str:
    return "https://example.com/base/"


def test_extract_meta_returns_description(soup: BeautifulSoup) -> None:
    meta = crawler._extract_meta(soup)
    assert ["description", "Sample description for testing.", "31"] in meta


def test_extract_headers_picks_h1(soup: BeautifulSoup) -> None:
    headers = crawler._extract_headers(soup)
    assert ["h1", "Main Heading"] in headers


def test_extract_images_normalises_src(base_url: str, soup: BeautifulSoup) -> None:
    images = crawler._extract_images(base_url, soup)
    assert images == [
        ["https://example.com/images/logo.png", "Logo", "Logo title", "image/png", "", "", "", "No"]
    ]


def test_extract_links_labels_follow_and_host(base_url: str, soup: BeautifulSoup) -> None:
    links = crawler._extract_links(base_url, soup)
    assert links[0][:3] == ["https://example.com/internal", "Interno", "Follow"]
    assert links[1][:3] == ["https://external.example", "Esterno", "NoFollow"]


def test_serp_preview_snapshot(soup: BeautifulSoup) -> None:
    preview = crawler._serp_preview("https://example.com/sample", soup)
    assert preview == {
        "title": "Sample Title",
        "description": "Sample description for testing.",
        "display_url": "example.com/…",
    }


def test_title_audit_flags_short_title(soup: BeautifulSoup) -> None:
    headers = crawler._extract_headers(soup)
    audit = crawler._title_audit("Sample Title", headers)
    assert audit == {
        "too_long": "No",
        "too_short": "Yes",
        "px_over": "No",
        "px_under": "Yes",
        "equals_h1": "No",
        "missing": "No",
        "px_len": str(int(len("Sample Title") * 7.2)),
        "char_len": str(len("Sample Title")),
    }


def test_schema_extraction_yields_jsonld(sample_html: str) -> None:
    schema = crawler._extract_schema_all(sample_html, "https://example.com/canonical/page")
    assert schema, "schema extraction should return at least one entry"
    first = schema[0]
    assert isinstance(first, dict)
    assert first["@context"] == "https://schema.org"
    assert first["_extracted_via"] == "json-ld"


def test_schema_validation_flags_breadcrumb_and_product() -> None:
    html = textwrap.dedent(
        """
        <html>
          <head>
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"BreadcrumbList",
             "itemListElement":[{"@type":"ListItem","name":"Home"}]}
            </script>
            <script type="application/ld+json">
            {"@context":"https://schema.org","@type":"Product","name":"Widget",
             "description":"Widget desc","image":"https://example.com/widget.jpg",
             "offers":{"@type":"Offer"}}
            </script>
          </head>
          <body></body>
        </html>
        """
    )
    schema = crawler._extract_schema_all(html, "https://example.com")
    breadcrumb = next(
        item for item in schema if isinstance(item, dict) and item.get("@type") == "BreadcrumbList"
    )
    assert breadcrumb.get("_schema_errors"), "breadcrumb block should expose schema errors"
    assert "itemListElement[1] missing position" in breadcrumb["_schema_errors"]
    assert "itemListElement[1] missing item url" in breadcrumb["_schema_errors"]

    product = next(item for item in schema if isinstance(item, dict) and item.get("@type") == "Product")
    assert product.get("_schema_errors"), "product block should expose schema errors"
    assert "missing offers.price" in product["_schema_errors"]
    assert "missing offers.priceCurrency" in product["_schema_errors"]

    issues_entry = next(item for item in schema if isinstance(item, dict) and "_schema_issues" in item)
    summary = "\n".join(issues_entry["_schema_issues"])
    assert "itemListElement[1] missing position" in summary
    assert "missing offers.priceCurrency" in summary


def test_ai_crawl_matrix_respects_meta_and_robots() -> None:
    robots: Dict[str, List[tuple[str, str]]] = {
        "*": [("Disallow", "/private"), ("Allow", "/")],
        "gptbot": [("Allow", "/")],
    }
    rows = crawler._ai_crawl_matrix(robots, "noai", "https://example.com")
    verdicts = {row[0]: row[-1] for row in rows}
    assert verdicts == {
        "GPTBot": "Blocked",
        "Google-Extended": "Blocked",
        "Gemini": "Blocked",
    }


def test_serp_schema_snapshot_combined(sample_html: str, soup: BeautifulSoup) -> None:
    preview = crawler._serp_preview("https://example.com/sample", soup)
    schema = crawler._extract_schema_all(sample_html, "https://example.com/sample")
    snapshot = {
        "serp": preview,
        "schema_first": schema[0],
    }
    assert snapshot == {
        "serp": {
            "title": "Sample Title",
            "description": "Sample description for testing.",
            "display_url": "example.com/…",
        },
        "schema_first": {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": "Sample",
            "url": "https://example.com/canonical/page",
            "_extracted_via": "json-ld",
        },
    }
