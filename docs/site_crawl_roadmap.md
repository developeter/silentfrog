# Site Crawl Roadmap

> v1 planning doc. Superseded for v2.0+ hardening by README.md § "Site Crawl hardening (v2.0)" and HANDOFF.md § "v2.0 status" (SQLite store, AuditProfile gating, resumable frontier, hybrid/spider crawl with render_js, per-bot SSR rendering, crawl history/diff, link graph, topic map, redirect mapping, and llms.txt export).

## Milestone Status

- [x] M0 Planning docs
- [x] M1 Home UI and empty Site Crawl window
- [x] M2 Crawl input model and URL discovery
- [x] M3 Polite site crawl engine
- [x] M4 Results table and cached detail opening
- [x] M5 Bulk Excel export
- [x] M6 Tests, docs, and hardening

## V1 Defaults

- Source mode: automatic sitemap discovery, explicit sitemap/branch, and URL list only.
- Link discovery: enabled by default (Hybrid mode: sitemap + spider) when only a base URL is given; Sitemap only / URL list only modes disable it.
- URL cap: 500.
- Speed: gentle by default.
- Details: cached per-page payloads.
- Excel: summary, issue sheets, and consolidated per-page detail sheets.
- UX: setup and results are separate screens.
- Progress: URL discovery count is shown before page crawling starts.

## Future Candidates

- Crawl history and crawl diff.
- JavaScript rendering comparison.
- Google Search Console URL Inspection integration.
- Server log import and Googlebot crawl evidence.
- Internal linking opportunity scoring.
