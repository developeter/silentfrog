from __future__ import annotations

import json
from pathlib import Path

import silentfrog.schema_extractor as schema_extractor  # type: ignore[reportMissingImports]
from silentfrog.schema_extractor import _extract_schema_all, _schema_primary_type  # type: ignore[reportMissingImports]
from silentfrog.schema_extractor import (  # type: ignore[reportMissingImports]
    _schema_validate_article,
    _schema_validate_breadcrumb,
    _schema_validate_faq_page,
    _schema_validate_how_to,
    _schema_validate_person,
    _schema_validate_product,
    _schema_validate_website,
)
from silentfrog.ai_visibility import _ENTITY_SCHEMA_TYPES, _RICH_SCHEMA_TYPES  # type: ignore[reportMissingImports]

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _wrap_jsonld(obj: dict) -> str:
    return (
        "<html><head>"
        f'<script type="application/ld+json">{json.dumps(obj)}</script>'
        "</head><body></body></html>"
    )


def _wrap_graph(*entries: dict) -> str:
    payload = {"@context": "https://schema.org", "@graph": list(entries)}
    return _wrap_jsonld(payload)


def test_schema_primary_type_parses_hash_and_slash() -> None:
    # Primary type extraction should strip context fragments from strings and lists.
    assert _schema_primary_type("https://schema.org/Product") == "Product"
    assert _schema_primary_type("https://schema.org/#Article") == "Article"
    assert _schema_primary_type(["LocalBusiness", "Organization"]) == "LocalBusiness"
    assert _schema_primary_type(None) == ""


def test_schema_extract_handles_invalid_jsonld() -> None:
    # Invalid JSON-LD should surface as raw block with an error noted in issues.
    html = """
    <html><head>
      <script type="application/ld+json">{invalid json</script>
    </head><body></body></html>
    """
    result = _extract_schema_all(html, "https://example.com")
    assert result["summary"]["total"] == 0
    assert result["blocks"], "Expected a raw block for invalid JSON-LD"
    assert any("Unparseable JSON-LD" in issue for issue in result["issues"])


def test_schema_extract_empty_document_returns_no_blocks() -> None:
    # Empty documents should not invent schema blocks.
    html = "<html><body>No schema here</body></html>"
    result = _extract_schema_all(html, "https://example.com")
    assert result["summary"]["total"] == 0
    assert result["blocks"] == []


def test_schema_validator_breadcrumb_errors() -> None:
    # Breadcrumb validator flags missing entries and required fields.
    errors = _schema_validate_breadcrumb({})
    assert "missing itemListElement" in errors
    item = {"itemListElement": [{"name": "", "position": 0}]}
    errors = _schema_validate_breadcrumb(item)
    assert any("missing item url" in e for e in errors)
    assert any("missing name" in e for e in errors)


def test_schema_validator_product_errors() -> None:
    # Product validator flags missing name/description/image/offers and price/currency in offers.
    errors = _schema_validate_product({})
    assert "missing name" in errors
    assert "missing description" in errors
    assert "missing image" in errors
    assert "missing offers" in errors

    product = {"name": "Test", "description": "Desc", "image": "img.jpg", "offers": [{"@type": "Offer"}]}
    errors = _schema_validate_product(product)
    assert "missing offers.price" in errors
    assert "missing offers.priceCurrency" in errors


def test_schema_validator_product_accepts_price_specification() -> None:
    product = {
        "name": "Test",
        "description": "Desc",
        "image": "img.jpg",
        "offers": [
            {
                "@type": "Offer",
                "priceSpecification": {"price": "29.99", "priceCurrency": "EUR"},
            }
        ],
    }
    errors = _schema_validate_product(product)
    assert "missing offers.price" not in errors
    assert "missing offers.priceCurrency" not in errors


def test_schema_validator_article_errors() -> None:
    errors = _schema_validate_article({})
    assert "missing headline" in errors
    assert "missing image" in errors
    assert "missing datePublished" in errors
    assert "missing author" in errors


def test_schema_validator_faq_page_errors() -> None:
    errors = _schema_validate_faq_page({})
    assert "missing mainEntity" in errors

    faq = {"mainEntity": [{"name": "", "acceptedAnswer": {}}]}
    errors = _schema_validate_faq_page(faq)
    assert any("missing name" in error for error in errors)
    assert any("missing acceptedAnswer.text" in error for error in errors)


def test_schema_extract_builds_eligibility_rows() -> None:
    html = """
    <html><head>
      <script type="application/ld+json">
      {
        "@context":"https://schema.org",
        "@graph":[
          {
            "@type":"BreadcrumbList",
            "itemListElement":[
              {"@type":"ListItem","position":1,"name":"Home","item":"https://example.com/"}
            ]
          },
          {
            "@type":"Product",
            "name":"Chair",
            "description":"Wooden chair",
            "image":"https://example.com/chair.jpg",
            "offers":[{"@type":"Offer"}]
          }
        ]
      }
      </script>
    </head><body></body></html>
    """
    result = _extract_schema_all(html, "https://example.com")
    eligibility = {row["type"]: row for row in result["eligibility"]}

    assert eligibility["BreadcrumbList"]["eligibility"] == "Eligible"
    assert eligibility["Product"]["eligibility"] == "Incomplete"
    assert "missing offers.price" in eligibility["Product"]["missing_fields"]


def test_schema_validator_person_valid_fixture_has_no_errors() -> None:
    person = _load_fixture("schema_person_valid.json")
    assert _schema_validate_person(person) == []


def test_schema_validator_person_missing_name_fixture() -> None:
    person = _load_fixture("schema_person_missing_name.json")
    assert _schema_validate_person(person) == ["missing name"]


def test_schema_extract_person_inside_graph_marks_eligible() -> None:
    person = _load_fixture("schema_person_valid.json")
    html = _wrap_graph(person)
    result = _extract_schema_all(html, "https://example.com/")
    eligibility = {row["type"]: row for row in result["eligibility"]}
    assert eligibility["Person"]["detected"] is True
    assert eligibility["Person"]["eligibility"] == "Eligible"
    assert eligibility["Person"]["missing_fields"] == []


def test_schema_validator_how_to_valid_fixture_has_no_errors() -> None:
    howto = _load_fixture("schema_howto_valid.json")
    assert _schema_validate_how_to(howto) == []


def test_schema_validator_how_to_missing_step_fixture() -> None:
    howto = _load_fixture("schema_howto_missing_step.json")
    assert _schema_validate_how_to(howto) == ["missing step"]


def test_schema_extract_how_to_inside_graph_marks_incomplete_when_steps_missing() -> None:
    howto = _load_fixture("schema_howto_missing_step.json")
    html = _wrap_graph(howto)
    result = _extract_schema_all(html, "https://example.com/")
    eligibility = {row["type"]: row for row in result["eligibility"]}
    assert eligibility["HowTo"]["detected"] is True
    assert eligibility["HowTo"]["eligibility"] == "Incomplete"
    assert "missing step" in eligibility["HowTo"]["missing_fields"]


def test_schema_validator_website_valid_fixture_has_no_errors() -> None:
    website = _load_fixture("schema_website_valid.json")
    assert _schema_validate_website(website) == []


def test_schema_validator_website_missing_url_flags_error() -> None:
    errors = _schema_validate_website({"@type": "WebSite", "name": "Example"})
    assert errors == ["missing url"]


def test_schema_extract_website_inside_graph_marks_eligible() -> None:
    website = _load_fixture("schema_website_valid.json")
    html = _wrap_graph(website)
    result = _extract_schema_all(html, "https://example.com/")
    eligibility = {row["type"]: row for row in result["eligibility"]}
    assert eligibility["WebSite"]["detected"] is True
    assert eligibility["WebSite"]["eligibility"] == "Eligible"


def test_person_counts_as_entity_and_howto_website_as_rich_citation() -> None:
    # Person is an entity-clarity schema; HowTo and WebSite are rich citation schemas.
    # Guards the M0 promise that the new types feed both AI Visibility consumers.
    assert "person" in _ENTITY_SCHEMA_TYPES
    assert "howto" in _RICH_SCHEMA_TYPES
    assert "website" in _RICH_SCHEMA_TYPES


def test_schema_extract_person_fixture_parity_between_extruct_and_fallback(
    monkeypatch,
) -> None:
    # M0 risk register: extruct and the manual fallback must agree on Person.
    # Both code paths feed `_annotate_schema_blocks` which calls `_SCHEMA_VALIDATORS`;
    # this asserts the same fixture yields identical missing-field errors either way.
    person = _load_fixture("schema_person_missing_name.json")
    html = _wrap_jsonld(person)

    extruct_result = _extract_schema_all(html, "https://example.com/")

    monkeypatch.setattr(schema_extractor, "USE_EXTRUCT", False)
    fallback_result = _extract_schema_all(html, "https://example.com/")

    extruct_person = {row["type"]: row for row in extruct_result["eligibility"]}["Person"]
    fallback_person = {row["type"]: row for row in fallback_result["eligibility"]}["Person"]

    assert extruct_person["detected"] is True
    assert fallback_person["detected"] is True
    assert extruct_person["missing_fields"] == fallback_person["missing_fields"]
    assert extruct_person["missing_fields"] == ["missing name"]
