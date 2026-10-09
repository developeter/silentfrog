> **Status (2026-10-08).** D1 (header/cookie scoping) landed first as `d6163f4`. PR-F1 fixes
> PLUMB-1, A5, RND-6 (persisted opt-in ticks), PLUMB-3, D2, A6 label part (active-checks label,
> results-page label, `CrawlHistoryRun.settings_summary`), PLUMB-7 (results-table tooltip), and
> A1, A2, PLUMB-5, A3 (Trust > Tech & extraction tab, Excel sheets, AI-export JSON, CHANGELOG
> wording). PR-F2 fixes RND-3, PLUMB-4, INT-10, the RND-5 hint (unmeasured checks show "Info" and a grey
> circle in the GEO badge; the false "SSR box produces Lab CWV" hint is gone), RND-2 (axe now runs on
> CSP pages), A4, D5, D6 and PLUMB-2 (accessibility, topic-embedding, export and fetch-failure
> messages name the reason; ignored header lines are numbered; the Home gear reads "Appearance (theme)"). PR-G covers D4, D3, PLUMB-6, INT-1 to INT-9, INT-11, RND-1,
> RND-4, the A6 concurrency fix and D7. Lab Core Web Vitals collection (RND-5 part A) stays deferred.

**Short answer: mostly, yes.** Almost every box you tick does run in the engine. You see nothing for six reasons, all confirmed with probes:

1. **Ticks are not saved.** Every new Single Page or Site Crawl window starts from defaults, and the two windows keep separate settings. Re-tick after opening a window, before you click Analyze or Start crawl.
2. **Site Crawl uses the Standard profile by default, which skips the four rendering checks.** Ticking one of them switches the profile to Deep. If you set the profile back to Standard, they are skipped, and only a red note in the dialog tells you.
3. **Two boxes show nothing on screen at all:** Detect tech stack and Custom extraction rules.
4. **Some features need things you don't have yet:**
   - Topic embeddings and Stealth are greyed out because their extras are not installed.
   - Semrush has no API key stored.
   - AI share of voice needs an environment variable; there is no checkbox for it.
   - Google needs your own `client_secret.json`, because this build has no built-in Google app.
5. **The feedback is misleading:**
   - The label next to "Crawl settings..." still says "Standard crawl" with everything ticked.
   - The "GEO checks:" badge is always green.
   - On sites that send a Content-Security-Policy, Accessibility says "not run, enable it" even when it is on.
6. **The Site Crawl results table has no columns for these checks.** Double-click a row to see them.

Also, the gear icon on Home is only the dark/light theme ("Appearance"). The real settings are behind the **Crawl settings...** button inside the Single Page and Site Crawl windows.

## 1) Where to look

| Control | What else you must do | Single Page: where the result appears | Site Crawl: where the result appears |
|---|---|---|---|
| Run SSR parity check | Single Page: nothing. Site Crawl: profile **Deep**. Then run a new audit. | **AI/GEO > AI Visibility**, row "Server-rendered DOM matches the JS-rendered DOM". **AI/GEO > Bot Matrix**, column "SSR parity". It appears in **Recap** only if Warning or Critical. Ignore the "GEO checks:" badge, which is always green. | Not in the results table. Double-click a row: **AI/GEO > AI Visibility** and **Bot Matrix**. Site Recap if Warning or Critical. Excel sheet "AI Visibility detail". |
| Per-bot SSR rendering (render as each AI bot) | As above (Deep in Site Crawl). It is slow, about 25–30 s per page. | **AI/GEO > Bot Matrix**: one "SSR parity" cell per bot (hover for details). **AI Visibility** row "AI bots receive the same rendered content". Known bug: a bot that gets a 403 still shows green. | Double-click a row: **AI/GEO > Bot Matrix**. |
| Crawl JavaScript-rendered links (SPA sites) | As above (Deep in Site Crawl). | **Indexability > Link**: the JS-only links appear as extra rows, with no marker. | The JS-discovered pages appear as extra rows in the results table. |
| Accessibility audit (axe-core, WCAG) | As above (Deep in Site Crawl). | **Trust > Accessibility** (Rule / Impact / Affected nodes / Help / Sample selector), and **Recap** rows with source "Accessibility". On CSP sites it wrongly says "Accessibility audit not run. Enable it in Crawl Settings…". | Double-click a row: **Trust > Accessibility**. Site Recap. Excel sheet "Accessibility actions". |
| Detect tech stack (Wappalyzer-style) | Nothing. It runs on every profile. | **Not shown anywhere.** It appears only in the file written by **Export for AI analysis** (.md, section "### Tech stack"). | **Not shown anywhere**: not in the table, the row detail, Excel, HTML or the AI export. |
| Custom extraction rules | Write valid `Name \| type \| selector [\| attribute]` lines. Invalid lines are dropped and the only sign is a red label. | **Not shown anywhere.** It appears only in **Export for AI analysis** (.md and .json). | **Not shown anywhere.** |
| Topic embeddings (greyed out) | `pip install silentfrog[embeddings]`. The first run downloads a model of about 90 MB. | **AI/GEO > AI Visibility**, area "Topic clarity", row "Body paragraphs stay on the topic the title promises". | Double-click a row: same row. Also the "Topic map" button. |
| Enable gentle crawl mode / Presets | – | Only the label next to "Crawl settings..." changes ("Gentle crawl"). | Only the label next to "Start crawl" changes ("Gentle crawl, max N/host · … profile"). It is visible on the setup page only. |
| Max parallel requests | Works only with gentle mode on. In Site Crawl, values above 4 have no effect. | No visible effect. | Label "max N/host". |
| Audit profile | Site Crawl only. Single Page is always Deep. | – | Label suffix "· Deep profile". The "Link issues" and "Issues" columns change. |
| Use Semrush in audits + API key + Max Semrush calls per day | Save a key, tick the box, press **OK**, run a new audit. Needs a public domain (not localhost or an IP), a daily cap of at least 2, and the Standard or Deep profile. You have no key stored today. | **AI/GEO > AI Visibility**, area "Authority signals" (6 rows). | Double-click a row: same. Excel sheet "AI Visibility detail". |
| Semrush "Test connection" | – | Result label inside Settings only. Each test uses 1 call from the daily budget. | Same. |
| AI share of voice keys (ChatGPT / Perplexity / Gemini) | There is **no checkbox**. Set the Windows user environment variable `SILENTFROG_AI_SOV_ENABLE=1`, then restart Silentfrog. These are paid API calls. | **AI/GEO > AI Visibility**, rows "AI share of voice — ChatGPT (OpenAI)" / "— Perplexity" / "— Gemini". Until enabled, the badge shows "AI Share of Voice ✗". | Double-click a row: same. |
| AI share of voice "Test keys" | – | Result label inside Settings only. "ok" does **not** mean audits will use the keys. | Same. |
| Connect Google… / Use Google data in audits | Create your own Google Cloud OAuth **Desktop** `client_secret.json`, pick it, connect GSC/GA4, choose the property, tick the box, OK, run a new audit (Standard or Deep). | **AI/GEO > AI Visibility**, areas "Real performance" and "Engagement". | Double-click a row: same. |
| Custom headers / Cookies | – | No result view. The label says "Custom crawl" only when gentle mode is off. These are also sent to external sites the page links to (bug D1). | Nothing is shown. |
| Allow insecure TLS | For local or intranet hosts, also tick private-network. | No indicator. The audit simply succeeds. | Same. |
| Allow private-network targets | – | No indicator. If it is off, the error message does not mention it. | Same. |
| Stealth fetching (greyed out) | `pip install silentfrog[stealth]` | Nothing is shown. | Nothing is shown. |
| Test a URL against robots.txt… | Paste the robots.txt text. "Fetch from URL" ignores your Settings and reports local or blocked sites as "No robots.txt found". | The dialog itself only. | The dialog itself only. |

To see results today: open the window, open **Crawl settings...**, tick the boxes, and in Site Crawl make sure the profile reads **Deep**. Press OK and run a **new** audit. Single Page results are in **Trust > Accessibility** and **AI/GEO > AI Visibility / Bot Matrix**. In Site Crawl, **double-click a row** to see them. For tech stack and extraction, use **Export for AI analysis** on Single Page.

## 2) Fix plan

All findings were confirmed and none were refuted. The plan respects the repo rules: new features stay off by default, no new base dependencies, code-shape limits (80-line functions, nesting ≤2, no if/elif string dispatch, ≤2 bool args), §1.5 (a missing signal is `info`), and payload keys are add-only.

### PR-F: ticked settings are remembered, shown, and appear in results (highest user impact)

Persistence is a schema boundary, so this PR should go through `lean-adversarial-reviewer`.

1. **Save the opt-in ticks across sessions, shared by both windows** (PLUMB-1, A5, RND-6)
   - `crawl_options.py`: add Qt-free functions `opt_in_to_dict(opts)` and `opt_in_from_dict(d, base)`.
     - Saved: `ssr_parity_check`, `bot_render`, `render_js`, `accessibility_audit`, `tech_stack_detection`, `topic_embeddings`, `use_stealth`, `gentle_mode`, `max_concurrent_per_host`, and the custom-rules text.
     - **Never saved:** `allow_insecure_tls`, `allow_private_network`, `extra_headers` (including Cookie).
     - When loading, clamp flags to the extras actually installed, reusing `settings_dialog._playwright_available` / `_embeddings_available` / `_scrapling_available`.
   - Use the existing seam `QSettings("Silentfrog","Silentfrog")` (as in `settings_dialog.py:556` and `ai_review_dialog.py:143`).
     - One shared key, `crawl/opt_in`.
     - A separate `crawl/site_profile` key for Site Crawl.
     - Single Page is always forced to DEEP.
   - Load in `seo_gui.py:152` and `site_crawl_gui.py:384`. Save after Accepted in `seo_gui.py:525` and `site_crawl_gui.py:1132`. Corrupt JSON falls back to the defaults.
   - If nothing is stored, the options stay exactly today's defaults, so everything remains off by default.
   - **Regression tests** (with a monkeypatched QSettings factory):
     - Tick SSR and tech stack in a `WebpageSeoWindow` dialog, then a new `SiteCrawlWindow()` has both flags True and profile `standard`.
     - Empty store gives `CrawlOptions.default()` and the current Site Crawl default.
     - TLS, private-network and Cookie values never appear in the stored JSON.
     - A stored `topic_embeddings=True` loads as False when the extra is missing.

2. **Show which checks are active** (PLUMB-3, D2, label part of A6)
   - Confirmed gap: the Single Page label says "Standard crawl" with everything ticked. The Site Crawl label is hidden on the results page. History records no options.
   - `crawl_options.py`: add `active_checks_summary(opts) -> list[str]`, built from a tuple table rather than if/elif.
     - Check names: SSR parity, Per-bot SSR, JS links, Accessibility, Tech stack, Custom rules (N), Embeddings, Stealth.
     - Posture: Insecure TLS, Private network, N custom header(s).
     - Render checks are suffixed "(skipped: needs Deep)" when `ProfilePolicy.for_profile(profile).render` is False.
   - Use it for the text and tooltip of:
     - `seo_gui._update_settings_label` (528).
     - `site_crawl_gui._update_speed_label` (1174), built from `_effective_options()`. Drop "max N/host" when gentle mode is off.
     - `lbl_history` on the results page, set in `_start_crawl` and `_open_stored_run`.
   - Add `CrawlHistoryRun.settings_summary: str = ""` (add-only; old history files load with "").
   - Table tooltip "Double-click a row for the full per-page audit…" (PLUMB-7).
   - **Regression tests:**
     - With SSR and tech stack on, the label contains both names.
     - Standard profile with SSR on shows "skipped".
     - After `_show_results()`, a visible label contains the summary.
     - An old history JSON loads.
     - `table.toolTip()` is not empty.

3. **Give tech stack and custom extraction a place on screen** (A1, A2, PLUMB-5, A3)
   - `tabs.py`: add `TechExtractionTab` with two tables:
     - Category | Technologies, built from `TechStackPayload.from_raw(raw).by_category`.
     - Rule | Value.
     - Empty state: "Not enabled — tick it in Crawl settings".
   - `tab_buckets.py`: add the leaf "Tech & extraction" to the Trust bucket.
   - Wire it in `seo_gui._populate_tabs`, `_update_content_tabs` and `_clear_results`, and in `SiteCrawlDetailDialog._table_entries`.
   - Excel:
     - Single page: sheet in `exporters/excel.py`.
     - Site: "Tech & extraction detail" sheet in `site_crawl_excel.py`, built from the run repository stream.
   - `llm_export._page_json`: add `tech_stack`, `accessibility`, `lighthouse`, `rich_results` and `integrations`.
   - Correct the wording at `CHANGELOG.md:447`.
   - **Regression tests** (local fixture with a WordPress generator meta and `span.price`):
     - The new tab's model contains "42.00 EUR" and "WordPress" in both windows.
     - The site xlsx contains "42.00".
     - `json_data["tech_stack"]` is present.

4. **Make statuses honest** (RND-3, PLUMB-4, INT-10, RND-5 hint)
   - `crawl_types.AiVisibilityCheck`: add `measured: bool = True`.
     - `from_raw`: `measured = raw_status != "info" and value.get("measured", True)`.
     - `to_dict` emits it, so it survives every round trip.
   - `tabs._collect_badge_checks` emits `info` when `measured` is False. The AI Visibility "Status" column shows "Info" (with no colour) for unmeasured rows.
   - Score and verdict are unchanged.
   - Fix the "Lab CWV" hint in `geo_checks_badge.py:61-64`, which wrongly says the SSR box produces lab CWV. Actually collecting lab CWV (RND-5 part A) is deferred as a feature.
   - **Regression tests:**
     - `analyse(default)`, then `to_mapping()`, then `AiVisibilityTab`: the badge shows "SSR parity ○" in grey (#9aa0a6).
     - With SSR on and Playwright: "SSR parity ✓".
     - The GEO score is identical before and after the change on the same payload.

5. **Replace silent "nothing" with a reason** (RND-2, A4, D5, D6, PLUMB-2)
   - `render_pool._render_with_browser`: when `inject_js` is set, call `new_page(bypass_csp=True, …)`.
     - `collect_accessibility` returns `{measured: False, reason}` on failure.
     - `tabs._accessibility_rows` shows that reason.
     - Update the fake in `tests/test_render_pool_unit.py:56` to accept `**kwargs`.
   - `embeddings/topic.build_topic_embedding_check` returns an info row "Not measured: <reason>" when a reason is present. `llm_export._integration_lines` prints the reason instead of "feature off".
   - `http_client.fetch` classifies the cause (`ssrf` or `tls`, unwrapping aiohttp's `os_error`/`__cause__`) and carries it through `HttpResponse`, `FetchResult` and `_strategy_fetch`. `_fetch_failure_message` then names the Settings box to tick.
   - `parse_header_lines` returns the numbers of bad lines, and the dialog shows "Line(s) N ignored: expected 'Key: Value'".
   - README "gear icon" text becomes "Crawl settings..." (README.md:383 and the other "Settings →" mentions). The Home gear tooltip becomes "Appearance (theme)".
   - **Regression tests:**
     - A `/csp` fixture with axe on gives `accessibility.measured` True and at least 1 violation.
     - `TopicEmbeddingsPayload(reason="x")` gives a row with "Not measured: x".
     - Loopback with defaults gives an error containing "Allow private-network targets".
     - A bad header line makes `lbl_headers_error` visible and containing "2".

### PR-G: integrations and fetch correctness

This also needs adversarial review (networking/SSRF, concurrency). **D1 is a credential leak, so land it as the first commit.**

1. **D1: scope headers and cookies to the audited host.**
   - `crawl_http.py`: add `_base_headers` and `_scoped_extra_headers(opts, origin, target)`.
   - Probe sessions use only the base headers: link probes (`seo_crawler.py:167`), canonical (`parsers_meta.py:667`), hreflang (`:719`), and `_trace_redirects` (`crawl_http.py:341`, per hop). Canonical and hreflang switch to manual redirect hops.
   - Test: two local servers. The external one receives no Cookie, Authorization or custom header from any probe; the origin server still does.
2. **D4, D3, PLUMB-6: carry the options everywhere they should apply.**
   - D4: thread the headers into `fetch_text`, `_parse_robots`, `fetch_robots_matcher` and `RobotsCache`.
   - D3: `RobotsSimDialog(self, options_provider=self.options)`. The worker wraps the fetch in the TLS/SSRF scopes, and status messages come from a dict lookup, not if/elif.
   - PLUMB-6: `analyse_images(..., options)` takes the scopes and headers. Pass it from Single Page and from both places that open `SiteCrawlDetailDialog`.
   - Tests:
     - A cookie-gated robots.txt with `Disallow: /secret` means /secret is not crawled.
     - The robots tester's "Fetch from URL" on 127.0.0.1 with private-network ticked reaches the server.
     - `run_image_analysis` on a loopback PNG returns its real size.
3. **INT-2, INT-3, INT-1: integrations say why they show nothing.**
   - INT-2: new `ai_engines/config.py` (JSON, like SemrushConfig) plus a "Use AI share of voice in audits" checkbox. `_enabled()` is true for the env var OR the config, and the default stays OFF.
   - INT-3: `_collect_semrush` and `_collect_google_metrics` return `{measured: False, enabled: True, reason}`. The gates at `ai_visibility.py:1003/1006` accept `enabled`, the "Not connected" rows use the reason, and the badge gains "Authority (Semrush)" and "Google" groups.
   - INT-1: tooltip based on `builtin_client_available()`, plus a "Not connected yet" warning next to "Use Google data".
   - Tests:
     - Config on, env unset: `_enabled()` is True. Both off: 0 POSTs.
     - Semrush enabled with no key gives exactly one info row and the badge shows "gated".
4. **INT-4, INT-5, INT-6, INT-7: stop paid-call waste.**
   - INT-4: in-flight task per (loop, host) with `asyncio.shield` for share of voice.
   - INT-5: per-(loop, domain) lock around the Semrush cache, budget check, fetch and cache write.
   - INT-6: memo keyed by host plus a hash of the keys, stored only if an engine was measured.
   - INT-7: spinbox minimum 2, tooltip, and `test_connection` checks the budget.
   - Tests:
     - 4 concurrent `fetch_share_of_voice` calls make engines × prompts POSTs.
     - 4 concurrent `fetch_domain_overview` calls make 2 calls.
     - After a 401, fixing the key re-samples.
5. **RND-1, RND-4, A6, INT-8, INT-9, INT-11, D7: smaller correctness fixes.**
   - RND-1: `RenderResult.http_status`, plus a two-sided bot diff and "Bot received…" problem tokens.
   - RND-4: pass `active_render_pool()` when Playwright is available.
   - A6: `crawl_concurrency = max(4, max_concurrent_per_host)`.
   - INT-8: GA4 bounce row becomes `info`.
   - INT-9: `_ERROR_RE` for Semrush errors.
   - INT-11: recommendation text says "restart the app".
   - D7: when private-network is on, the favicon comes from the origin `/favicon.ico` instead of Google.
   - Tests:
     - A fake pool returning 403 for gptbot gives a status other than good.
     - Gentle mode with par=8 gives a peak of 8 requests in flight.
     - A bounce rate of 0.9 gives the same score as no GA4.
     - `ERROR 120 :: WRONG KEY` shows "WRONG KEY".
     - A loopback audit records no URL containing google.com.

Deferred and not in either PR: actually collecting lab Core Web Vitals (RND-5 part A, PerformanceObserver). PR-F only removes the false claim that the SSR box produces them.