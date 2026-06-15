"""Unit tests for the v2.0 V6 custom extraction engine."""

from __future__ import annotations

from silentfrog.custom_extraction import (
    MAX_RULES,
    CustomExtractionConfig,
    CustomExtractionRule,
    RuleType,
    extract,
)

_HTML = """
<html><head><meta name="product-id" content="SKU-123"></head>
<body>
  <h1 class="title">Wooden Chair</h1>
  <span class="price" data-currency="EUR">29.99</span>
  <a class="cta" href="https://shop.example/buy">Buy now</a>
  <span class="price">14.50</span>
  <div class="sku">Internal ref: ABC-9931 end</div>
</body></html>
"""


def _rule(name, type_, selector, attribute="", post_regex="") -> CustomExtractionRule:
    return CustomExtractionRule(
        name=name, type=RuleType(type_), selector=selector, attribute=attribute, post_regex=post_regex
    )


def test_css_extraction_text() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Title", "css", "h1.title"),)))
    assert out["Title"] == "Wooden Chair"


def test_css_extraction_multiple_matches_joined() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Prices", "css", "span.price"),)))
    assert out["Prices"] == "29.99 | 14.50"


def test_attribute_extraction() -> None:
    out = extract(
        _HTML,
        CustomExtractionConfig(rules=(_rule("Link", "attribute", "a.cta", attribute="href"),)),
    )
    assert out["Link"] == "https://shop.example/buy"


def test_attribute_extraction_data_attr() -> None:
    out = extract(
        _HTML,
        CustomExtractionConfig(rules=(_rule("Currency", "attribute", "span.price", attribute="data-currency"),)),
    )
    assert out["Currency"] == "EUR"


def test_xpath_extraction() -> None:
    out = extract(
        _HTML,
        CustomExtractionConfig(rules=(_rule("MetaId", "xpath", "//meta[@name='product-id']/@content"),)),
    )
    assert out["MetaId"] == "SKU-123"


def test_regex_extraction() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Ref", "regex", r"ABC-\d+"),)))
    assert out["Ref"] == "ABC-9931"


def test_post_regex_on_css_value() -> None:
    # Pull just the numeric part out of "Internal ref: ABC-9931 end".
    out = extract(
        _HTML,
        CustomExtractionConfig(rules=(_rule("RefNum", "css", "div.sku", post_regex=r"(\d{4})"),)),
    )
    assert out["RefNum"] == "9931"


def test_invalid_css_selector_yields_empty() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Bad", "css", "h1[unclosed"),)))
    assert out["Bad"] == ""


def test_invalid_xpath_yields_empty_never_raises() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Bad", "xpath", "//[broken"),)))
    assert out["Bad"] == ""


def test_no_match_returns_empty_string() -> None:
    out = extract(_HTML, CustomExtractionConfig(rules=(_rule("Missing", "css", ".nope"),)))
    assert out["Missing"] == ""


def test_config_from_raw_drops_invalid_and_caps_rules() -> None:
    raw = {
        "rules": [
            {"name": "ok", "type": "css", "selector": "h1"},
            {"name": "", "type": "css", "selector": "h1"},  # no name -> dropped
            {"name": "nosel", "type": "css", "selector": ""},  # no selector -> dropped
            *[{"name": f"r{i}", "type": "css", "selector": "p"} for i in range(20)],
        ]
    }
    config = CustomExtractionConfig.from_raw(raw)
    assert len(config.rules) == MAX_RULES
    assert "ok" in config.names
    assert "" not in config.names
    assert "nosel" not in config.names


def test_config_roundtrips_through_dict() -> None:
    config = CustomExtractionConfig(
        rules=(_rule("A", "attribute", "img", attribute="src"), _rule("B", "regex", r"\d+")),
    )
    restored = CustomExtractionConfig.from_raw(config.to_dict())
    assert restored.to_dict() == config.to_dict()


def test_extract_empty_config_returns_empty_dict() -> None:
    assert extract(_HTML, CustomExtractionConfig()) == {}


def test_output_is_length_capped() -> None:
    big = "<html><body>" + "<p>x</p>" * 5000 + "</body></html>"
    out = extract(big, CustomExtractionConfig(rules=(_rule("All", "css", "p"),)))
    assert len(out["All"]) <= 2049  # 2048 + the ellipsis


def test_parse_rules_text_basic() -> None:
    from silentfrog.custom_extraction import parse_rules_text

    config = parse_rules_text(
        "# comment line\n"
        "Title | css | h1.title\n"
        "Link | attribute | a.cta | href\n"
        r"Ref | regex | ABC-\d+" + "\n"
        "\n"
        "Bad\n"  # no selector + css -> dropped
    )
    names = config.names
    assert "Title" in names and "Link" in names and "Ref" in names
    assert "Bad" not in names
    by_name = {r.name: r for r in config.rules}
    assert by_name["Link"].type is RuleType.ATTRIBUTE
    assert by_name["Link"].attribute == "href"


def test_parse_rules_text_defaults_to_css() -> None:
    from silentfrog.custom_extraction import parse_rules_text

    config = parse_rules_text("Title || h1")
    assert config.rules[0].type is RuleType.CSS
    assert config.rules[0].selector == "h1"


def test_crawl_options_from_ui_parses_custom_rules() -> None:
    from silentfrog.crawl_options import CrawlOptions

    opts = CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=2,
        custom_rules_text="Price | css | span.price\nSKU | attribute | meta | content",
    )
    assert opts.custom_extraction.names == ["Price", "SKU"]
    # Round-trips back to text for the settings dialog.
    assert "Price | css | span.price" in opts.custom_extraction.to_text()


def test_crawl_payload_roundtrips_custom_extraction() -> None:
    from silentfrog.crawl_types import CrawlPayload

    base = {
        "meta": [],
        "headers": [],
        "images": [],
        "links": [],
        "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
        "canonical": {},
        "redirect": {},
        "robots": {},
        "meta_robots": "",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {},
        "serp_audit": {},
        "keywords": [],
        "content_quality": {},
        "ai_visibility": {},
        "performance": {},
        "social": {},
        "custom_extraction": {"Price": "29.99", "SKU": "ABC-1"},
    }
    payload = CrawlPayload.from_raw(base)
    assert payload.custom_extraction == {"Price": "29.99", "SKU": "ABC-1"}
    assert payload.to_mapping()["custom_extraction"] == {"Price": "29.99", "SKU": "ABC-1"}
