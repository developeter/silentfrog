# Site Crawl Feature Spec

## Status

Implemented in v1 scope.

## Goal

Add a scoped **Site Crawl** mode that audits many pages without trying to discover the whole web graph. The mode is designed for large sites where a full unrestricted crawl would be too expensive or too likely to hit WAF/rate limits.

## V1 Scope

- Crawl sources: automatic sitemap discovery from the base URL, explicit sitemap URL, sitemap index URL, and pasted URL lists.
- URL filtering: include path prefixes and exclude patterns.
- Safety default: gentle crawl mode with a 500 URL cap.
- Crawling behavior: no recursive link discovery in v1.
- Result behavior: one summary row per URL plus cached page payloads for detail opening.
- Export behavior: one bulk Excel workbook with summary, issue, and consolidated per-page detail sheets.

## UX Contract

- Home screen has three actions: **Massive Redirect Check**, **Single Page SEO Check**, and **Site Crawl**.
- Site Crawl has its own window and does not expose single-page-only settings or per-page Excel export controls.
- Site Crawl uses separate setup and results screens. Starting a crawl hides the setup form and shows only results, filters, progress, and result actions.
- After URL discovery finishes, the results screen shows how many URLs Silentfrog found to crawl.
- Double-clicking a successful result opens a read-only detail report based on the cached payload.
- Detail reports include an **Analyze images** action that fetches image dimensions, file size, type, and cache headers for that cached page.
- Failed URLs stay in the results table with their error message.
- Site Crawl Excel export includes consolidated detail sheets with `Page URL` as the first column, rather than one worksheet per crawled page.

## Crawl Safety

- Default URL cap is 500.
- Default concurrency is 2 requests per host with gentle mode enabled.
- Robots crawl-delay is respected by default.
- Repeated 403/429 outcomes should be treated as a WAF/rate-limit signal and surfaced to the user.
- If only the base URL is provided, the crawler detects sitemaps from `robots.txt` and common sitemap paths before falling back to the base URL only.
- The crawler must not spoof Googlebot or attempt to bypass Cloudflare/WAF protection.

## Out Of Scope For V1

- Recursive link-following discovery.
- JavaScript rendering.
- Google Search Console integration.
- Server log analysis.
- Crawl history and crawl diff.
- Every single-page worksheet per URL in the bulk Excel export.

## LAGO Test Shape

Light inspection showed:

- `https://www.lago.it/sitemap_it.xml` contains roughly 1,096 URLs.
- Major `lago.it` branches include `negozi`, `design`, `news`, and `progetti-contract`.
- `https://www.lagodesign.com/sitemap_index.xml` exposes language sitemaps for `en`, `fr`, and `es`.
- `lagodesign.com` branches include language-prefixed paths such as `/en/design/`, `/fr/design/`, and `/es/design/`.

This validates branch-filtered sitemap crawling as the correct first version.
