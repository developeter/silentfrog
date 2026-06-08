from __future__ import annotations

import pytest

from silentfrog.crawl_types import CrawlPayload  # type: ignore[reportMissingImports]


def _raw_payload() -> dict[str, object]:
    return {
        "meta": [["title", "Example", "7"]],
        "headers": [["h1", "Example"]],
        "images": [["https://example.com/logo.png", "Logo", "", "image/png", "", "", "", "", "", ""]],
        "links": [["https://example.com", "Example", "Internal", "follow", "200", "OK", "Body", "", "com"]],
        "schema": {
            "summary": {"total": 0, "by_syntax": {}, "by_type": {}, "errors": []},
            "blocks": [],
            "fallback_raw": [],
        },
        "canonical": {"target": "https://example.com", "self": True, "multiple": False, "status": "200"},
        "redirect": {"chain": ["https://example.com"], "hops": 0, "final_status": "200", "loop": False},
        "robots": {"*": [("Allow", "/")]},
        "meta_robots": "index, follow",
        "hreflang": [["en", "https://example.com", "200", "Yes", "Yes"]],
        "ai_crawl": [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "No explicit AI restrictions detected"]],
        "serp": {
            "title": "Example",
            "description": "Example description",
            "url": "https://example.com",
            "site_name": "Example",
            "favicon": "https://example.com/favicon.ico",
            "breadcrumb": "example.com",
        },
        "serp_audit": {
            "too_long": "No",
            "too_short": "No",
            "px_over": "No",
            "px_under": "No",
            "equals_h1": "No",
            "missing": "No",
            "px_len": "100",
            "char_len": "7",
        },
        "keywords": [{"term": "example", "length": 1, "frequency": 2, "density": 2.5}],
        "content_quality": {"verdict": "Strong", "word_count": 120},
        "ai_visibility": {
            "summary": {"verdict": "Strong", "good_count": 1, "warning_count": 0, "critical_count": 0},
            "checks": [],
        },
        "performance": {"status": 200, "transfer_size": 1024},
        "social": {"open_graph": {"title": "OG title"}, "twitter": {"title": "TW title"}},
    }


def test_crawl_payload_from_raw_keeps_optional_sections() -> None:
    payload = CrawlPayload.from_raw(_raw_payload())

    assert payload.meta[0][0] == "title"
    assert payload.images[0][0] == "https://example.com/logo.png"
    assert payload.canonical.is_self is True
    assert payload.serp.site_name == "Example"
    assert payload.keywords[0].term == "example"
    assert payload.content_quality.verdict == "Strong"
    assert payload.ai_visibility.summary.verdict == "Strong"
    assert payload.social.open_graph.title == "OG title"


def test_crawl_payload_from_raw_reports_missing_required_keys() -> None:
    raw = _raw_payload()
    raw.pop("meta")
    raw.pop("headers")

    with pytest.raises(ValueError, match=r"Missing crawl keys: headers, meta"):
        CrawlPayload.from_raw(raw)
