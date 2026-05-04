# Site Crawl Roadmap

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
- Link discovery: disabled.
- URL cap: 500.
- Speed: gentle by default.
- Details: cached per-page payloads.
- Excel: summary, issue sheets, and consolidated per-page detail sheets.
- UX: setup and results are separate screens.
- Progress: URL discovery count is shown before page crawling starts.

## Future Candidates

- Recursive link discovery with strict scope controls.
- Crawl history and crawl diff.
- JavaScript rendering comparison.
- Google Search Console URL Inspection integration.
- Server log import and Googlebot crawl evidence.
- Internal linking opportunity scoring.
