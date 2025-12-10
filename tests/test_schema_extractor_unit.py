from __future__ import annotations

from silentfrog.schema_extractor import _extract_schema_all, _schema_primary_type  # type: ignore[reportMissingImports]
from silentfrog.schema_extractor import _schema_validate_breadcrumb, _schema_validate_product  # type: ignore[reportMissingImports]


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
