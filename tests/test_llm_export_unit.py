"""Unit tests for the v2.0 V5 / PR-C LLM-friendly evidence dossier export."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from silentfrog.crawl_run_repository import CrawlRunRef, stream_report_results
from silentfrog.crawl_store import CrawlStore, StoredAudit
from silentfrog.crawl_types import CrawlPayload
from silentfrog.exporters.llm_export import (
    _apply_size_cap,
    _cell,
    export_crawl_for_llm,
    export_page_for_llm,
    write_llm_export,
)
from silentfrog.site_crawl_types import SiteCrawlReport, SiteCrawlResult

_CHECKS = [
    {"area": "Access", "check": "robots.txt", "status": "good", "details": "ok", "recommendation": "-", "key": "a"},
    {
        "area": "Content",
        "check": "Thin content",
        "status": "warning",
        "details": "Only 412 words",
        "recommendation": "Add depth",
        "key": "b",
    },
    {
        "area": "Topic clarity",
        "check": "Missing H1",
        "status": "critical",
        "details": "No H1",
        "recommendation": "Add an H1",
        "key": "c",
    },
    {
        "area": "Perf",
        "check": "CrUX LCP",
        "status": "info",
        "details": "Not measured",
        "recommendation": "Enable PSI",
        "key": "d",
    },
]


def _minimal_payload(url: str, score: int, checks: list[dict]) -> CrawlPayload:
    """The bare-minimum shape (old-store-like): every optional group empty."""
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "My Title", "8"], ["description", "A description.", "14"]],
            "headers": [["h1", "My Title"]],
            "images": [],
            "links": [],
            "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
            "canonical": {"target": url, "self": True, "multiple": False, "status": "200"},
            "redirect": {"chain": [url], "hops": 0, "final_status": "200", "final_url": url, "loop": False},
            "robots": {"*": [["Allow", "/"]]},
            "meta_robots": "index, follow",
            "hreflang": [],
            "ai_crawl": [],
            "serp": {"title": "T", "description": "", "url": url, "site_name": "", "breadcrumb": "", "favicon": ""},
            "serp_audit": {},
            "keywords": [],
            "content_quality": {"word_count": 412},
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 1,
                    "warning_count": sum(1 for c in checks if c["status"] == "warning"),
                    "critical_count": sum(1 for c in checks if c["status"] == "critical"),
                },
                "checks": checks,
            },
            "performance": {"summary": {"verdict": "Good"}},
            "social": {},
        }
    )


def _payload(url: str, score: int, checks: list[dict]) -> CrawlPayload:
    """A realistic, fully-populated payload exercising every dossier section."""
    return CrawlPayload.from_raw(
        {
            "meta": [["title", "My Title", "8"], ["description", "A description of the page.", "27"]],
            "headers": [["h1", "My Title"], ["h2", "Section one"], ["h3", "Sub section"]],
            "images": [
                # missing alt
                ["https://e.com/hero.jpg", "", "", "image/jpeg", "800", "600", "", "", "", "", "", "", "", "", "", ""],
                # oversized (300KB) with alt
                [
                    "https://e.com/big.png",
                    "Big banner",
                    "",
                    "image/png",
                    "2000",
                    "1500",
                    "307200",
                    "3600",
                    "lazy",
                    "",
                    "800",
                    "600",
                    "",
                    "",
                    "",
                    "",
                ],
            ],
            "links": [
                [f"{url}other", "Other page", "Interno", "follow", "200", "", "body", "H2", "com"],
                [
                    "https://broken.example/dead",
                    "Dead link",
                    "Esterno",
                    "follow",
                    "404",
                    "Not found",
                    "body",
                    "",
                    "example",
                ],
                ["https://e.com/nf", "No follow me", "Interno", "nofollow", "200", "", "footer", "", "com"],
            ],
            "schema": {
                "summary": {"total": 1, "by_type": {"Article": 1}, "errors": ["Missing author"]},
                "blocks": [{"@type": "Article", "_extracted_via": "json-ld"}],
                "issues": ["Missing author"],
                "eligibility": [
                    {
                        "type": "Article",
                        "detected": True,
                        "count": 1,
                        "eligibility": "Incomplete",
                        "missing_fields": ["author"],
                        "warnings": [],
                    }
                ],
            },
            "canonical": {"target": f"{url}canonical", "self": False, "multiple": False, "status": "200"},
            "redirect": {
                "chain": [url, f"{url}final"],
                "hops": 1,
                "final_status": "200",
                "final_url": f"{url}final",
                "loop": False,
            },
            "robots": {"*": [["Allow", "/"]], "gptbot": [["Disallow", "/private"]]},
            "meta_robots": "index, follow",
            "hreflang": [["en", f"{url}en", "200", "Yes", "Yes"], ["it", f"{url}it", "200", "Yes", "Yes"]],
            "ai_crawl": [["GPTBot", "gptbot", "Yes", "No", "No", "Allowed", "-"]],
            "serp": {
                "title": "My Title",
                "description": "A description of the page.",
                "url": url,
                "site_name": "Example",
                "breadcrumb": "Home > Page",
                "favicon": "",
            },
            "serp_audit": {"too_long": "No", "too_short": "No", "equals_h1": "No", "missing": "No"},
            "keywords": [
                {
                    "term": "widgets",
                    "length": 1,
                    "frequency": 12,
                    "density": 2.5,
                    "in_title": True,
                    "in_description": True,
                    "heading_count": 2,
                    "first_position": 4,
                }
            ],
            "content_quality": {
                "language": "en",
                "word_count": 412,
                "verdict": "Weak",
                "text_glitches": {
                    "duplicate_words": 2,
                    "doubled_punctuation": 1,
                    "space_before_punct": 1,
                    "total": 4,
                    "samples": ["the the"],
                },
            },
            "ai_visibility": {
                "summary": {
                    "verdict": "Needs work",
                    "score": score,
                    "good_count": 1,
                    "warning_count": sum(1 for c in checks if c["status"] == "warning"),
                    "critical_count": sum(1 for c in checks if c["status"] == "critical"),
                },
                "checks": checks,
            },
            "performance": {
                "nav_ttfb_ms": 120.0,
                "nav_total_ms": 900.0,
                "transfer_size": 50000,
                "summary": {
                    "transfer_size": 50000,
                    "total_resource_bytes": 400000,
                    "total_page_bytes": 450000,
                    "total_resource_count": 40,
                    "third_party_bytes": 100000,
                    "third_party_count": 5,
                    "verdict": "Needs work",
                },
                "scripts": {"blocking": {"count": 2, "bytes": 30000}, "async": {"count": 5, "bytes": 60000}},
                "heaviest_resources": [{"url": "https://e.com/big.js", "bytes": 200000, "type": "js"}],
                "third_party_hosts": [{"host": "ads.example", "bytes": 100000, "count": 5}],
            },
            "social": {
                "open_graph": {"title": "OG Title", "description": "", "image": "https://e.com/og.jpg", "issues": []},
                "twitter": {"title": "", "description": "", "image": "", "issues": ["Missing twitter:card"]},
            },
            "custom_extraction": {"Price": "29.99", "SKU": "ABC-1"},
            "tech_stack": {"by_category": {"CMS": ["WordPress"]}},
            "lighthouse": {"measured": True, "performance": 80, "accessibility": 90, "best_practices": 85, "seo": 95},
            "rich_results": {"measured": True, "eligible_types": ["Article"], "source": "schema", "warnings": []},
            "semrush": {"measured": True, "domain_authority": 42, "organic_keywords": 100, "organic_traffic": 500},
            "requested_url": url,
            "final_url": f"{url}final",
            "discovery": {
                "llms_txt": {
                    "url": f"{url}llms.txt",
                    "status": 200,
                    "present": True,
                    "body_excerpt": "",
                    "parsed": {},
                    "source": "fetch",
                },
                "llms_full_txt": {
                    "url": "",
                    "status": 0,
                    "present": False,
                    "body_excerpt": "",
                    "parsed": {},
                    "source": "",
                },
                "well_known_ai_json": {
                    "url": "",
                    "status": 0,
                    "present": False,
                    "body_excerpt": "",
                    "parsed": {},
                    "source": "",
                },
                "sitemap": {
                    "url": f"{url}sitemap.xml",
                    "status": 200,
                    "present": True,
                    "body_excerpt": "",
                    "parsed": {},
                    "source": "root-sitemap",
                },
            },
            "eeat": {"byline": "Jane Doe", "publish_date": "2026-01-01", "same_as": ["https://x.com/jane"]},
            "structure": {
                "semantic_container_counts": {"article": 1},
                "internal_link_count": 5,
                "images_with_alt": 1,
                "images_total": 2,
            },
            "citation_content": {"question_headings": ["What is it?"], "stats_count": 3, "word_count": 412},
            "citation_advanced": {"vocab_ttr": 0.5, "keyword_warning": False, "word_count": 412},
            "seo_basics": {"viewport_present": True, "descriptive_url": True, "url_path": "/page"},
            "render": {
                "status": "good",
                "missing_headings": [],
                "missing_main_text_chars": 0,
                "missing_links": 0,
                "reason": "",
            },
            "bot_render": {
                "measured": True,
                "reason": "",
                "bots": {"gptbot": {"status": "good", "missing_links": 0, "reason": "-"}},
            },
            "perf_vitals": {"lcp_ms": 2000, "cls": 0.05, "inp_ms": 150},
            "perf_crux": {"lcp_p75_ms": 2500, "cls_p75": 0.08},
            "gsc": {"measured": True, "clicks": 100, "impressions": 5000},
            "ga4": {"measured": True, "sessions": 300, "conversions": 12},
            "topic_embeddings": {"measured": True, "coherence": 0.8},
            "brand_mentions": {"measured": True, "mentions_30d": 5},
            "ai_sov": {"measured": True, "share_of_voice": 0.2},
            "accessibility": {
                "measured": True,
                "violations": [{"id": "color-contrast", "impact": "serious", "nodes": 3, "help": "Fix contrast"}],
                "counts": {"serious": 1},
            },
            "pseudo_links": {"total": 2, "counts": {"onclick_div": 2}, "samples": ["<div onclick=...>"]},
        }
    )


def test_page_export_has_preamble_and_score() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    assert "for AI analysis" in export.markdown
    assert "priority order" in export.markdown
    assert "senior technical SEO" in export.markdown
    assert "Score: 72/100" in export.markdown
    assert "https://e.com/p" in export.markdown


def test_page_export_compact_drops_good_and_info_checks() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p", mode="compact")
    assert "Thin content" in export.markdown  # warning kept
    assert "Missing H1" in export.markdown  # critical kept
    assert "robots.txt | ok |" not in export.markdown  # good check row dropped
    assert "CrUX LCP" not in export.markdown  # info dropped


def test_page_export_full_keeps_all_checks() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p", mode="full")
    assert "robots.txt" in export.markdown
    assert "CrUX LCP" in export.markdown


def test_page_export_critical_sorted_before_warning() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    assert export.markdown.index("Missing H1") < export.markdown.index("Thin content")


def test_page_export_json_mirror() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    data = export.json_data
    assert data["type"] == "page"
    assert data["page"]["geo_score"] == 72
    assert data["page"]["word_count"] == 412
    assert json.loads(export.json_text)["page"]["geo_score"] == 72


def test_page_export_full_dossier_sections_present() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    headings = [
        "## 1. Page identity",
        "## 2. GEO score",
        "## 3. Prioritised issues",
        "## 4. AI-visibility checks by area",
        "## 5. Content",
        "## 6. Links & images",
        "## 7. International & structured data",
        "## 8. Performance",
        "## 9. AI crawler access",
        "## 10. Optional integrations",
    ]
    for heading in headings:
        assert heading in md, heading


def test_page_export_identity_has_redirect_and_canonical_facts() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert f"{url}final" in md  # final URL in the redirect chain
    assert "Redirect hops: 1" in md
    assert f"{url}canonical" in md  # declared canonical target
    assert "Canonical self-reference: No" in md  # mismatch surfaced
    assert "gptbot" in md  # per-agent robots.txt directive


def test_page_export_discovery_facts() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    assert "llms.txt" in export.markdown
    assert f"{url}llms.txt" in export.markdown
    assert "sitemap.xml" in export.markdown


def test_page_export_headings_outline_in_document_order() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "Heading outline" in md
    assert md.index("Section one") < md.index("Sub section")


def test_page_export_keywords_and_text_glitches() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "widgets" in md
    assert "Text glitches" in md
    assert "the the" in md


def test_page_export_links_and_images() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "Broken / erroring links" in md
    assert "https://broken.example/dead" in md
    assert "Nofollow (rel)" in md
    assert "Images missing alt text" in md
    assert "https://e.com/hero.jpg" in md
    assert "Oversized images" in md
    assert "https://e.com/big.png" in md
    assert "Pseudo-links" in md
    assert "onclick_div" in md


def test_page_export_hreflang_schema_and_social() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert f"{url}en" in md
    assert "Article" in md
    assert "Incomplete" in md
    assert "Missing twitter:card" in md


def test_page_export_performance_and_ai_crawler() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "TTFB: 120 ms" in md
    assert "https://e.com/big.js" in md
    assert "ads.example" in md
    assert "GPTBot" in md
    assert "SSR / render parity" in md
    assert "Per-bot render diffs" in md


def test_page_export_optional_integrations_measured() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "Google Search Console" in md
    assert "Tech stack" in md
    assert "WordPress" in md
    assert "Accessibility (axe-core)" in md
    assert "color-contrast" in md


def test_page_export_not_measured_markers_for_empty_integrations() -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p", mode="full")
    md = export.markdown
    assert "Not measured (feature off)" in md
    assert "### Google Search Console" in md
    assert "### Accessibility (axe-core)" in md
    assert "### Lighthouse (lab)" in md
    # No fabricated failure language for an absent optional signal.
    assert "GSC failed" not in md


def test_page_export_issues_include_evidence_and_recommendation() -> None:
    url = "https://e.com/page/"
    export = export_page_for_llm(_payload(url, 55, _CHECKS), url, mode="full")
    md = export.markdown
    assert "Recommendation:" in md
    assert "Evidence:" in md
    assert "Confidence:" in md


def test_crawl_export_rollup_and_worst_pages() -> None:
    results = [
        SiteCrawlResult.from_payload("https://e.com/good", _minimal_payload("https://e.com/good", 95, _CHECKS[:1])),
        SiteCrawlResult.from_payload("https://e.com/bad", _minimal_payload("https://e.com/bad", 40, _CHECKS)),
        SiteCrawlResult.from_payload("https://e.com/mid", _minimal_payload("https://e.com/mid", 70, _CHECKS[:2])),
    ]
    export = export_crawl_for_llm(results, worst_n=2)
    assert "URLs audited: 3" in export.markdown
    assert "min 40" in export.markdown
    assert "max 95" in export.markdown
    assert "https://e.com/bad" in export.markdown
    assert export.json_data["distribution"]["count"] == 3
    assert export.json_data["worst_pages"][0]["url"] == "https://e.com/bad"


def test_crawl_export_streams_results_from_run_repository(tmp_path: Path) -> None:
    url = "https://e.com/stripped"
    payload = _minimal_payload(url, 20, _CHECKS)
    db = tmp_path / "crawl.db"
    store = CrawlStore(db)
    run_id = store.start_run("e.com", "https://e.com/", "list")
    store.save_audit(run_id, StoredAudit(url=url, http_status="200", payload=payload.to_mapping()))
    store.finish_run(run_id)
    store.close()

    stripped = replace(SiteCrawlResult.from_payload(url, payload), payload=None)
    without = export_crawl_for_llm([stripped])
    assert without.json_data["distribution"]["count"] == 0
    assert url not in {p["url"] for p in without.json_data["worst_pages"]}

    run_report = SiteCrawlReport.from_run(
        CrawlRunRef(db, run_id),
        discovered_count=1,
        crawled_count=1,
        skipped_count=0,
        failed_count=0,
        base_url="https://e.com/",
    )
    streamed = export_crawl_for_llm(list(stream_report_results(run_report)))
    assert streamed.json_data["distribution"]["count"] == 1
    assert url in {p["url"] for p in streamed.json_data["worst_pages"]}


def test_crawl_export_issue_frequency() -> None:
    results = [
        SiteCrawlResult.from_payload("https://e.com/a", _minimal_payload("https://e.com/a", 50, _CHECKS)),
        SiteCrawlResult.from_payload("https://e.com/b", _minimal_payload("https://e.com/b", 55, _CHECKS)),
    ]
    export = export_crawl_for_llm(results)
    assert any(item["check"] == "Missing H1" and item["count"] == 2 for item in export.json_data["common_issues"])


def test_crawl_export_hints_duplicates_errors_and_page_index() -> None:
    dup_a = _payload("https://e.com/dup-a/", 30, _CHECKS)
    dup_b = replace(_payload("https://e.com/dup-b/", 35, _CHECKS), meta=dup_a.meta)
    error_payload = _minimal_payload("https://e.com/error", 0, [])
    results = [
        SiteCrawlResult.from_payload("https://e.com/dup-a/", dup_a),
        SiteCrawlResult.from_payload("https://e.com/dup-b/", dup_b),
        SiteCrawlResult.failed("https://e.com/fail", "Timeout"),
    ]
    export = export_crawl_for_llm(results, mode="full")
    md = export.markdown
    assert "## Site-wide hints" in md
    assert "## Duplicate content" in md
    assert "My Title" in md  # shared duplicate title surfaces
    assert "## Error & redirecting pages" in md
    assert "https://e.com/fail" in md
    assert "## Site-wide discovery" in md
    assert "llms.txt" in md
    assert "Page index" in md
    assert "https://e.com/dup-a/" in md
    assert export.json_data["duplicates"]["titles"]
    assert export.json_data["duplicates"]["titles"][0]["count"] == 2
    assert "https://e.com/fail" in export.json_data["errors"]["http_errors"]
    _ = error_payload  # constructed for readability; not directly asserted


def test_crawl_export_page_index_caps_at_500_with_marker() -> None:
    results = [
        SiteCrawlResult.from_payload(f"https://e.com/{i}", _minimal_payload(f"https://e.com/{i}", 50, []))
        for i in range(510)
    ]
    export = export_crawl_for_llm(results, worst_n=1)
    assert "(+10 more)" in export.markdown
    # Both the markdown table and its JSON mirror cap at 500 rows.
    assert len(export.json_data["page_index"]) == 500


def test_crawl_export_compact_vs_full_worst_page_detail() -> None:
    url = "https://e.com/worst/"
    payload = _payload(url, 10, _CHECKS)
    results = [SiteCrawlResult.from_payload(url, payload)]
    compact = export_crawl_for_llm(results, mode="compact", worst_n=1)
    full = export_crawl_for_llm(results, mode="full", worst_n=1)
    assert "CrUX LCP" not in compact.markdown
    assert "CrUX LCP" in full.markdown


def test_write_llm_export_writes_md_and_json(tmp_path) -> None:
    export = export_page_for_llm(_minimal_payload("https://e.com/p", 72, _CHECKS), "https://e.com/p")
    paths = write_llm_export(export, tmp_path / "audit", fmt="both")
    suffixes = {p.suffix for p in paths}
    assert suffixes == {".md", ".json"}
    assert all(p.exists() for p in paths)
    md = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "GEO score" in md or "GEO Score" in md


def test_page_export_includes_custom_extraction() -> None:
    payload = _minimal_payload("https://e.com/p", 80, _CHECKS)
    object.__setattr__(payload, "custom_extraction", {"Price": "29.99", "SKU": "ABC-1"})
    export = export_page_for_llm(payload, "https://e.com/p")
    assert "Custom extraction" in export.markdown
    assert "Price" in export.markdown
    assert "29.99" in export.markdown
    assert export.json_data["custom_extraction"]["SKU"] == "ABC-1"


def test_cell_escapes_pipes_and_newlines() -> None:
    assert _cell("a | b\nc") == "a \\| b c"
    assert _cell(None) == ""
    assert _cell(0) == "0"


def test_apply_size_cap_truncates_and_marks() -> None:
    huge = "\n".join(f"line {i}" for i in range(200_000))
    capped = _apply_size_cap(huge)
    assert len(capped.encode("utf-8")) <= 1_500_000 + 200
    assert "truncated" in capped
    untouched = "short document"
    assert _apply_size_cap(untouched) == untouched
