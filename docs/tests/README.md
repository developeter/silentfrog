# Silentfrog Test Fixtures

This directory stores tiny HTML/JSON snippets that mirror the content our parsers handle in unit tests.

## Fixtures

- fixtures/example_page.html - single-page crawl fixture used by tests/test_seo_crawler.py. It contains canonical, hreflang, favicon, meta description/robots, OpenGraph, JSON-LD, links, images and body copy so every tab can be exercised deterministically.
- fixtures/robots.txt - matching robots.txt served by the local aiohttp test server; demonstrates the allow/disallow mix consumed by RobotsModel and _ai_crawl_matrix.
- fixtures/schema_product.json - standalone JSON-LD list that documents the flattened shape emitted by _extract_schema_all. The Schema tab accepts either dicts with _extracted_via metadata or raw JSON strings; this sample shows the dict form.

## Usage

The HTML and robots fixtures are consumed directly inside tests/test_seo_crawler.py. Additional fixtures live here for documentation so future tests can re-use canonical inputs instead of redefining big inline strings.

When adding new parsers or GUI tabs, commit a minimal reproducible document in fixtures/ and reference it from the tests. This keeps behavioural expectations visible and easy to diff.
