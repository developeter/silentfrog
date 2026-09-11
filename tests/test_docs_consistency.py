"""Docs-consistency guards for the Site Crawl docs at 2.0.0.

The 2.0 release roadmap existed because docs described features nobody could
reach; these guards pin the Site Crawl docs to the shipped code. Each guard
first asserts the code fact it depends on, so it disarms itself if the code
changes rather than freezing a doc sentence forever.

Stealth disclosure:

``docs/site_crawl_feature_spec.md``'s Crawl Safety section must not promise an
unconditional "must not spoof Googlebot or bypass Cloudflare/WAF" guarantee
while ``CrawlSettingsDialog`` ships an opt-in "Stealth fetching" checkbox that
does exactly that (see ``settings_dialog.py`` ``_build_stealth_controls``).
The doc must disclose the opt-in escalation path instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from silentfrog.crawl_mode import CrawlMode
from silentfrog.site_crawl_types import SiteCrawlConfig

_SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "site_crawl_feature_spec.md"
_ROADMAP_PATH = Path(__file__).resolve().parents[1] / "docs" / "site_crawl_roadmap.md"
_SETTINGS_DIALOG_PATH = Path(__file__).resolve().parents[1] / "src" / "silentfrog" / "settings_dialog.py"
_SEO_CRAWLER_PATH = Path(__file__).resolve().parents[1] / "src" / "silentfrog" / "seo_crawler.py"
_HISTORY_GUI_PATH = Path(__file__).resolve().parents[1] / "src" / "silentfrog" / "site_crawl_history_gui.py"
_GUI_PATH = Path(__file__).resolve().parents[1] / "src" / "silentfrog" / "site_crawl_gui.py"
_README_PATH = Path(__file__).resolve().parents[1] / "README.md"
_HANDOFF_PATH = Path(__file__).resolve().parents[1] / "HANDOFF.md"


def _crawl_safety_section() -> str:
    text = _SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"## Crawl Safety\n(.*?)\n## ", text, re.DOTALL)
    assert match is not None, "docs/site_crawl_feature_spec.md must have a 'Crawl Safety' section"
    return match.group(1)


def test_crawl_safety_doc_discloses_stealth_optin() -> None:
    dialog_source = _SETTINGS_DIALOG_PATH.read_text(encoding="utf-8")
    exposes_stealth_toggle = "chk_stealth" in dialog_source and "use_stealth" in dialog_source
    assert exposes_stealth_toggle, (
        "This test only guards the doc while CrawlSettingsDialog exposes a "
        "stealth toggle; if that toggle is ever removed, drop this test too."
    )

    section = _crawl_safety_section().lower()
    assert "stealth" in section and "opt-in" in section, (
        "Crawl Safety section must disclose the opt-in 'Stealth fetching' "
        "escalation (Crawl settings -> Advanced) instead of the bare "
        "'must not ... bypass' promise the shipped chk_stealth checkbox "
        "contradicts."
    )


def test_site_crawl_docs_do_not_claim_link_discovery_is_disabled() -> None:
    """HYBRID is the shipped default mode and it follows links.

    ``docs/site_crawl_feature_spec.md`` and ``docs/site_crawl_roadmap.md``
    must not claim recursive link discovery is off/unbuilt while
    ``CrawlMode.HYBRID`` -- the documented default -- has
    ``follows_links is True`` and the GUI exposes a "Crawl mode" combo
    (Auto/Hybrid/Spider/Sitemap only/URL list only) wired to it.
    """
    assert CrawlMode.HYBRID.follows_links is True, (
        "This test only guards the docs while HYBRID (the default mode) "
        "follows links; if that ever changes, the stale-doc claims it "
        "guards against would become true again and this test must be "
        "revisited too."
    )

    spec_text = _SPEC_PATH.read_text(encoding="utf-8")
    assert "no recursive link discovery in v1" not in spec_text, (
        "site_crawl_feature_spec.md must not claim there is no recursive "
        "link discovery -- HYBRID (the default) follows same-host links."
    )
    assert "Recursive link-following discovery." not in spec_text, (
        "site_crawl_feature_spec.md's Out Of Scope list must not include "
        "recursive link-following discovery -- it shipped as the default "
        "Hybrid/Spider crawl mode."
    )

    roadmap_text = _ROADMAP_PATH.read_text(encoding="utf-8")
    assert "Link discovery: disabled." not in roadmap_text, (
        "site_crawl_roadmap.md must not claim link discovery is disabled "
        "-- Hybrid mode (the Auto default for a base-URL-only crawl) "
        "follows same-host links."
    )
    assert "Recursive link discovery with strict scope controls." not in roadmap_text, (
        "site_crawl_roadmap.md's Future Candidates list must not include "
        "recursive link discovery as unbuilt -- it shipped in v2.0 as "
        "crawl_mode.py's SPIDER/HYBRID modes."
    )


def _out_of_scope_section() -> str:
    text = _SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"## Out Of Scope For V1\n(.*?)\n## ", text, re.DOTALL)
    assert match is not None, "docs/site_crawl_feature_spec.md must have an 'Out Of Scope For V1' section"
    return match.group(1)


def test_out_of_scope_list_does_not_name_shipped_js_rendering_or_history_diff() -> None:
    """render_js and crawl history/diff are shipped, reachable v2.0 features.

    ``CrawlSettingsDialog`` (opened from Site Crawl's own "Crawl settings..."
    button) exposes a "Crawl JavaScript-rendered links (SPA sites)" checkbox
    wired to ``CrawlOptions.render_js``, which ``seo_crawler.py`` feeds into
    ``_augment_links_with_rendered_dom`` to merge JS-rendered DOM links into
    the crawl frontier. ``CrawlHistoryDialog`` (opened from "View past
    scans" on both the setup and results screens) lists saved runs and
    diffs them via ``diff_runs``. Neither belongs in "Out Of Scope For V1".
    """
    seo_crawler_source = _SEO_CRAWLER_PATH.read_text(encoding="utf-8")
    render_js_is_wired = (
        "def _augment_links_with_rendered_dom" in seo_crawler_source and "crawl_options.render_js" in seo_crawler_source
    )
    history_gui_source = _HISTORY_GUI_PATH.read_text(encoding="utf-8")
    history_diff_is_wired = "diff_runs" in history_gui_source and "class CrawlHistoryDialog" in history_gui_source
    assert render_js_is_wired and history_diff_is_wired, (
        "This test only guards the Out Of Scope doc while JS rendering and "
        "crawl history/diff are actually shipped; if either is ever ripped "
        "back out, drop the matching guard here too."
    )

    out_of_scope = _out_of_scope_section()
    assert "JavaScript rendering." not in out_of_scope, (
        "site_crawl_feature_spec.md's Out Of Scope list must not include "
        "JavaScript rendering -- CrawlOptions.render_js ships as an opt-in "
        "checkbox in CrawlSettingsDialog and feeds "
        "seo_crawler._augment_links_with_rendered_dom."
    )
    assert "Crawl history and crawl diff." not in out_of_scope, (
        "site_crawl_feature_spec.md's Out Of Scope list must not include "
        "crawl history and crawl diff -- CrawlHistoryDialog/diff_runs ships "
        "and is reachable via 'View past scans' on both Site Crawl screens."
    )


def _status_section() -> str:
    text = _SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"## Status\n(.*?)\n## ", text, re.DOTALL)
    assert match is not None, "docs/site_crawl_feature_spec.md must have a 'Status' section"
    return match.group(1)


def test_status_section_points_to_v2_hardening_docs() -> None:
    """The Status line must not read as a fully current v1-only doc.

    ``site_crawl_gui.py`` wires SQLite-backed storage, AuditProfile gating,
    and the Link graph / Topic map / Map redirects / Generate llms.txt
    buttons that this spec's Status/V1 Scope/Out-Of-Scope sections never
    describe. The bare "Implemented in v1 scope." line (with no version
    marker) gives readers no signal that nine-plus v2.0 features shipped
    after this file was written, so the Status section must point at
    README's "Site Crawl hardening (v2.0)" section and HANDOFF's
    "v2.0 status" section instead.
    """
    gui_source = _GUI_PATH.read_text(encoding="utf-8")
    ships_v2_only_features = all(
        name in gui_source for name in ("btn_llms_txt", "btn_redirect_map", "btn_graph", "btn_cluster_map")
    )
    assert ships_v2_only_features, (
        "This test only guards the Status line while the link graph, topic "
        "map, redirect mapping, and llms.txt export buttons are actually "
        "wired in site_crawl_gui.py; if all of them are ever ripped back "
        "out, drop this guard too."
    )

    readme_text = _README_PATH.read_text(encoding="utf-8")
    assert "Site Crawl hardening (v2.0)" in readme_text, (
        "README.md must keep its 'Site Crawl hardening (v2.0)' section for the feature spec's Status line to point to."
    )
    handoff_text = _HANDOFF_PATH.read_text(encoding="utf-8")
    assert "v2.0 status" in handoff_text, (
        "HANDOFF.md must keep its 'v2.0 status' section for the feature spec's Status line to point to."
    )

    status = _status_section()
    assert "v2.0" in status, (
        "docs/site_crawl_feature_spec.md's Status section must point to "
        "README.md's 'Site Crawl hardening (v2.0)' and HANDOFF.md's "
        "'v2.0 status' sections -- the bare 'Implemented in v1 scope.' "
        "line gives no signal that SQLite storage, AuditProfile gating, "
        "per-bot SSR rendering, link graph, topic map, redirect mapping, "
        "and llms.txt export shipped after this file was written."
    )

    roadmap_text = _ROADMAP_PATH.read_text(encoding="utf-8")
    assert "v2.0" in roadmap_text, (
        "docs/site_crawl_roadmap.md must also point to the v2.0 hardening "
        "docs -- it is a sibling v1 planning doc with the same staleness "
        "problem the Status line guard above targets."
    )


def test_readme_site_crawl_defaults_match_hybrid_auto_mode() -> None:
    cfg = SiteCrawlConfig.from_text(base_url="https://example.com")
    assert cfg.spider.mode is CrawlMode.HYBRID
    assert cfg.spider.mode.follows_links is True

    readme = _README_PATH.read_text(encoding="utf-8")
    assert "without recursively following every link" not in readme, (
        "README must not claim Site Crawl never follows links -- the "
        "default Auto/Hybrid mode (base URL only) does recursively follow "
        "same-host links."
    )
    assert "recursive link discovery: **off** by default" not in readme, (
        "README must not claim recursive link discovery is off by default "
        "-- Hybrid mode, the Auto default when only a base URL is given, "
        "follows same-host links."
    )
