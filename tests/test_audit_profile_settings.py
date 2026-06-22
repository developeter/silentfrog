"""v2.0 PR-13 (H4) — Settings profile selector, auto-suggest, single-page DEEP.

- the Crawl Settings dialog exposes a profile selector for SITE crawls and
  round-trips the choice; the single-page dialog hides it and preserves DEEP;
- a large site crawl left on the STANDARD default auto-suggests LIGHTWEIGHT
  (an explicit choice is honoured);
- the site-crawl default is STANDARD, while single-page audits stay DEEP with
  coverage equivalent to pre-H4 (every network category enabled).
"""

from __future__ import annotations

from silentfrog.crawl_options import AuditProfile, CrawlOptions, ProfilePolicy, auto_suggest_profile
from silentfrog.settings_dialog import CrawlSettingsDialog
from silentfrog.site_crawl_gui import SiteCrawlWindow


def test_auto_suggest_profile() -> None:
    # STANDARD default downgrades to LIGHTWEIGHT for a large crawl...
    assert auto_suggest_profile(1_000_000, AuditProfile.STANDARD) is AuditProfile.LIGHTWEIGHT
    # ...but a small crawl keeps STANDARD, and explicit choices are honoured.
    assert auto_suggest_profile(100, AuditProfile.STANDARD) is AuditProfile.STANDARD
    assert auto_suggest_profile(1_000_000, AuditProfile.DEEP) is AuditProfile.DEEP
    assert auto_suggest_profile(1_000_000, AuditProfile.LIGHTWEIGHT) is AuditProfile.LIGHTWEIGHT


def test_settings_dialog_profile_selector_roundtrips(qtbot) -> None:
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD)
    dialog = CrawlSettingsDialog(options, show_profile=True)
    qtbot.addWidget(dialog)

    assert dialog.profile_combo.currentData() == AuditProfile.STANDARD.value  # initialized from options
    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData(AuditProfile.LIGHTWEIGHT.value))
    assert dialog.options().profile is AuditProfile.LIGHTWEIGHT  # user choice flows out


def test_settings_dialog_hidden_selector_preserves_deep(qtbot) -> None:
    # Single-page dialog: no selector shown, the DEEP profile is preserved so a
    # single-page audit can never silently downgrade its coverage.
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    assert dialog.options().profile is AuditProfile.DEEP


def test_site_crawl_window_defaults_to_standard_profile(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    assert win._crawl_options.profile is AuditProfile.STANDARD


def test_site_crawl_auto_suggests_lightweight_for_large_limit(qtbot) -> None:
    win = SiteCrawlWindow()
    qtbot.addWidget(win)
    win.limit_spin.setMaximum(2_000_000)

    win.limit_spin.setValue(200_000)  # above the auto-suggest threshold
    assert win._effective_options().profile is AuditProfile.LIGHTWEIGHT
    win.limit_spin.setValue(100)  # small crawl keeps the selected STANDARD
    assert win._effective_options().profile is AuditProfile.STANDARD


def test_single_page_audit_is_deep_with_full_coverage(qtbot) -> None:
    # Coverage-equivalence: single-page audits run DEEP, and DEEP enables EVERY
    # network category (no probe/render/integration dropped vs pre-H4).
    from silentfrog.seo_gui import WebpageSeoWindow

    win = WebpageSeoWindow()
    qtbot.addWidget(win)
    assert win._crawl_options.profile is AuditProfile.DEEP

    deep = ProfilePolicy.for_profile(AuditProfile.DEEP)
    assert all(
        [
            deep.probe_link_status,
            deep.probe_canonical,
            deep.trace_redirects,
            deep.probe_hreflang,
            deep.download_social,
            deep.probe_resources,
            deep.render,
            deep.run_integrations,
        ]
    )
    assert deep.link_probe_cap == 0  # unbounded link probing, like today
