from __future__ import annotations

import textwrap
from typing import Dict, List

import pytest
from bs4 import BeautifulSoup

from silentfrog import seo_crawler as crawler  # type: ignore[reportMissingImports]
from silentfrog.image_diagnostics import (
    DECLARED_HEIGHT_COL,
    DECLARED_WIDTH_COL,
    DIAGNOSTIC_COL,
    FORMAT_HINT_COL,
    RESPONSIVE_COL,
    SIZES_COL,
)


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
    assert len(images) == 1
    image = images[0]
    assert image[0] == "https://example.com/images/logo.png"
    assert image[1] == "Logo"
    assert image[2] == "Logo title"
    assert image[3] == "image/png"
    assert image[DECLARED_WIDTH_COL] == ""
    assert image[DECLARED_HEIGHT_COL] == ""
    assert image[RESPONSIVE_COL] == ""
    assert image[SIZES_COL] == ""
    assert image[FORMAT_HINT_COL] == "Consider WebP or AVIF"
    assert image[DIAGNOSTIC_COL] == ""


def test_extract_images_uses_picture_source_when_img_src_is_empty(base_url: str) -> None:
    html = """
    <html>
      <body>
        <picture>
          <source media="(min-width: 1024px)" srcset="/images/hero-large.webp">
          <source srcset="/images/hero-mobile.webp">
          <img src="" width="640" height="480" alt="Hero image" title="Hero title">
        </picture>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    images = crawler._extract_images(base_url, soup)
    assert len(images) == 1
    image = images[0]
    assert image[0] == "https://example.com/images/hero-mobile.webp"
    assert image[1] == "Hero image"
    assert image[2] == "Hero title"
    assert image[3] == "image/webp"
    assert image[DECLARED_WIDTH_COL] == "640"
    assert image[DECLARED_HEIGHT_COL] == "480"
    assert image[RESPONSIVE_COL] == "2 candidates"
    assert image[SIZES_COL] == "Inferred: picture media ((min-width: 1024px))"
    assert image[FORMAT_HINT_COL] == "Next-gen format"


def test_extract_images_infers_sizes_from_srcset_width_descriptors(base_url: str) -> None:
    html = """
    <html>
      <body>
        <img
          src="/images/hero-640.jpg"
          srcset="/images/hero-320.jpg 320w, /images/hero-640.jpg 640w, /images/hero-1280.jpg 1280w"
          alt="Hero image"
        >
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")

    images = crawler._extract_images(base_url, soup)
    assert len(images) == 1
    image = images[0]
    assert image[RESPONSIVE_COL] == "3 candidates"
    assert image[SIZES_COL] == "Inferred: srcset widths (320w, 640w, 1280w)"


def test_extract_links_labels_follow_and_host(base_url: str, soup: BeautifulSoup) -> None:
    links = crawler._extract_links(base_url, soup)
    assert links[0][:4] == [
        "https://example.com/internal",
        "Internal",
        "Interno",
        "follow",
    ]
    assert links[1][:4] == [
        "https://external.example",
        "External",
        "Esterno",
        "nofollow",
    ]
    assert links[0][6] == "Body"
    assert links[0][7] == "Main Heading"


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


def test_keyword_extraction_returns_rich_metrics(sample_html: str) -> None:
    soup = BeautifulSoup(sample_html, "html.parser")
    plain = soup.get_text(" ", strip=True)
    keywords = crawler._extract_keywords(soup, plain, top_n=5)
    assert keywords, "expected at least one keyword entry"
    first = keywords[0]
    assert "term" in first and isinstance(first["term"], str)
    assert "frequency" in first and isinstance(first["frequency"], int)
    assert "density" in first and isinstance(first["density"], float)
    assert "density_threshold" in first and isinstance(first["density_threshold"], float)
    assert "density_warning" in first and isinstance(first["density_warning"], bool)
    assert "in_title" in first and isinstance(first["in_title"], bool)
    assert "heading_count" in first


def test_keyword_density_threshold_env(monkeypatch) -> None:
    html = """
    <html>
      <head><title>focus term focus term</title></head>
      <body>focus term focus term focus term focus term focus term focus</body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    plain = soup.get_text(" ", strip=True)
    monkeypatch.setenv("SILENTFROG_KEYWORD_WARN_DENSITY", "1.0")
    keywords = crawler._extract_keywords(soup, plain, top_n=3)
    focus = next(item for item in keywords if item["term"] == "focus")
    assert focus["density_warning"] is True
    assert focus["density_threshold"] == 1.0


def test_schema_extraction_yields_jsonld(sample_html: str) -> None:
    schema = crawler._extract_schema_all(sample_html, "https://example.com/canonical/page")
    assert isinstance(schema, dict), "schema extraction must return a mapping"
    summary = schema.get("summary", {})
    blocks = schema.get("blocks", [])
    assert summary.get("total", 0) >= 1
    assert blocks, "expected at least one structured data block"
    first = blocks[0]
    assert isinstance(first, dict), f"unexpected block type: {type(first)}"
    assert "@context" in first


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
    summary = schema["summary"]
    blocks = schema["blocks"]
    assert summary["total"] >= 2
    assert "BreadcrumbList" in summary["by_type"]
    assert "Product" in summary["by_type"]

    breadcrumb = next(item for item in blocks if isinstance(item, dict) and item.get("@type") == "BreadcrumbList")
    assert breadcrumb.get("_schema_errors"), "breadcrumb block should expose schema errors"
    assert "itemListElement[1] missing position" in breadcrumb["_schema_errors"]
    assert "itemListElement[1] missing item url" in breadcrumb["_schema_errors"]

    product = next(item for item in blocks if isinstance(item, dict) and item.get("@type") == "Product")
    assert product.get("_schema_errors"), "product block should expose schema errors"
    assert "missing offers.price" in product["_schema_errors"]
    assert "missing offers.priceCurrency" in product["_schema_errors"]

    summary_errors = "\n".join(summary["errors"])
    assert "itemListElement[1] missing position" in summary_errors
    assert "missing offers.priceCurrency" in summary_errors


def test_ai_crawl_matrix_respects_meta_and_robots() -> None:
    robots: Dict[str, List[tuple[str, str]]] = {
        "*": [("Disallow", "/private"), ("Allow", "/")],
        "GPTBot": [("Allow", "/")],
        "GoogleBot": [("Allow", "/")],
    }
    rows = crawler._ai_crawl_matrix(robots, "noai, nosnippet", "https://example.com/private/page")
    verdicts = {row[0]: row[5] for row in rows}
    directives = {row[0]: row[3] for row in rows}
    controls = {row[0]: row[4] for row in rows}
    notes = {row[0]: row[6] for row in rows}
    # GPTBot has an explicit Allow rule; Googlebot inherits "*" Allow but
    # picks up Google search controls; every other agent falls under "*"
    # whose first-match-wins resolution at /private is Disallow.
    assert verdicts["GPTBot"] == "Allowed"
    assert verdicts["Googlebot"] == "Limited"
    assert verdicts["Google-Extended"] == "Blocked"
    assert verdicts["ClaudeBot"] == "Blocked"
    assert verdicts["Claude-SearchBot"] == "Blocked"
    assert verdicts["OAI-SearchBot"] == "Blocked"
    assert all(value == "noai" for value in directives.values())
    assert "Blocked by robots.txt: /private" in notes["Google-Extended"]
    assert controls["Googlebot"] == "nosnippet"
    assert controls["GPTBot"] == "-"
    assert "Google search controls: nosnippet" in notes["Googlebot"]
    assert "Nonstandard directives detected: noai" in notes["GPTBot"]


def test_ai_crawl_matrix_limits_googlebot_for_positive_max_snippet() -> None:
    rows = crawler._ai_crawl_matrix({"*": [("Allow", "/")]}, "index, max-snippet:20", "https://example.com/page")
    by_agent = {row[0]: row for row in rows}

    assert by_agent["Googlebot"][4] == "max-snippet:20"
    assert by_agent["Googlebot"][5] == "Limited"
    assert by_agent["GPTBot"][4] == "-"
    assert by_agent["GPTBot"][5] == "Allowed"


def test_serp_schema_snapshot_combined(sample_html: str, soup: BeautifulSoup) -> None:
    preview = crawler._serp_preview("https://example.com/sample", soup)
    schema = crawler._extract_schema_all(sample_html, "https://example.com/sample")
    summary = schema["summary"]
    assert summary["total"] >= 1
    snapshot = {
        "serp": preview,
        "schema_first": schema["blocks"][0],
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
