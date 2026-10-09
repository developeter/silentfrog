"""v2.0 PR-13 (H4) — Settings profile selector, auto-suggest, single-page DEEP.

- the Crawl Settings dialog exposes a profile selector for SITE crawls and
  round-trips the choice; the single-page dialog hides it and preserves DEEP;
- a large site crawl left on the STANDARD default auto-suggests LIGHTWEIGHT
  (an explicit choice is honoured);
- the site-crawl default is STANDARD, while single-page audits stay DEEP with
  coverage equivalent to pre-H4 (every network category enabled).
"""

from __future__ import annotations

import json

import pytest
from qtpy import QtWidgets

from silentfrog import crawl_prefs
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


def test_settings_dialog_insecure_tls_opt_in_roundtrips(qtbot) -> None:
    # H7 (PR-16): the insecure-TLS opt-in is off by default and only flows out
    # of the dialog when the operator explicitly checks it.
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    assert dialog.chk_allow_insecure_tls.isChecked() is False
    assert dialog.options().allow_insecure_tls is False
    dialog.chk_allow_insecure_tls.setChecked(True)
    assert dialog.options().allow_insecure_tls is True


def test_settings_dialog_private_network_opt_in_roundtrips(qtbot) -> None:
    # H7 (PR-17): the private-network opt-in is off by default and only flows
    # out of the dialog when the operator explicitly checks it.
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    assert dialog.chk_allow_private_network.isChecked() is False
    assert dialog.options().allow_private_network is False
    dialog.chk_allow_private_network.setChecked(True)
    assert dialog.options().allow_private_network is True


def test_settings_dialog_stealth_opt_in_roundtrips(qtbot, monkeypatch) -> None:
    # v2.0 R1 (V1): use_stealth is off by default and only flows out of the
    # dialog when checked. chk_stealth is gated on the optional
    # silentfrog[stealth] extra (same idiom as chk_ssr_parity), so the extra
    # must be faked available here to exercise the roundtrip on a dev venv
    # that doesn't have scrapling installed.
    monkeypatch.setattr("silentfrog.settings_dialog._scrapling_available", lambda: True)
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    assert dialog.chk_stealth.isChecked() is False
    assert dialog.options().use_stealth is False
    dialog.chk_stealth.setChecked(True)
    assert dialog.options().use_stealth is True


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


def test_settings_dialog_render_check_switches_profile_to_deep(qtbot, monkeypatch) -> None:
    # Regression: ticking a rendering GEO check under Standard used to do
    # nothing visible even though the crawl silently skips it (H4) — the
    # dialog now switches to Deep and explains why.
    monkeypatch.setattr("silentfrog.settings_dialog._playwright_available", lambda: True)
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD)
    dialog = CrawlSettingsDialog(options, show_profile=True)
    qtbot.addWidget(dialog)

    assert dialog.lbl_render_profile_note.isHidden()
    dialog.chk_ssr_parity.setChecked(True)

    assert dialog.profile_combo.currentData() == AuditProfile.DEEP.value
    assert not dialog.lbl_render_profile_note.isHidden()
    assert "profile set to Deep" in dialog.lbl_render_profile_note.text()


def test_settings_dialog_lowering_profile_shows_skip_warning(qtbot, monkeypatch) -> None:
    monkeypatch.setattr("silentfrog.settings_dialog._playwright_available", lambda: True)
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD)
    dialog = CrawlSettingsDialog(options, show_profile=True)
    qtbot.addWidget(dialog)
    dialog.chk_ssr_parity.setChecked(True)  # auto-switches to Deep, per the test above

    dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData(AuditProfile.STANDARD.value))

    assert not dialog.lbl_render_profile_note.isHidden()
    assert dialog.lbl_render_profile_note.text() == "Rendering checks are skipped under the Standard profile."
    # No auto-untick: the user's choice still flows out of options().
    assert dialog.options().ssr_parity_check is True


def test_settings_dialog_render_note_hidden_when_nothing_ticked_or_deep(qtbot, monkeypatch) -> None:
    monkeypatch.setattr("silentfrog.settings_dialog._playwright_available", lambda: True)
    options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD)
    dialog = CrawlSettingsDialog(options, show_profile=True)
    qtbot.addWidget(dialog)
    dialog.chk_ssr_parity.setChecked(True)
    assert not dialog.lbl_render_profile_note.isHidden()

    dialog.chk_ssr_parity.setChecked(False)
    assert dialog.lbl_render_profile_note.isHidden()

    dialog.chk_ssr_parity.setChecked(True)  # back on Deep already, no note needed
    assert dialog.lbl_render_profile_note.isHidden()


def test_settings_dialog_render_note_hidden_for_single_page_dialog(qtbot, monkeypatch) -> None:
    # show_profile=False dialogs stay DEEP and hide the profile selector, so
    # the note must never appear even with a render check ticked.
    monkeypatch.setattr("silentfrog.settings_dialog._playwright_available", lambda: True)
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    dialog.chk_ssr_parity.setChecked(True)
    assert dialog.lbl_render_profile_note.isHidden()


def test_settings_dialog_restores_warning_for_stored_render_flag_under_standard(qtbot, monkeypatch) -> None:
    # _initialize_options must reflect stored settings without replaying the
    # user-facing auto-switch-to-Deep action.
    monkeypatch.setattr("silentfrog.settings_dialog._playwright_available", lambda: True)
    options = CrawlOptions.from_ui(
        gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD, ssr_parity_check=True
    )
    dialog = CrawlSettingsDialog(options, show_profile=True)
    qtbot.addWidget(dialog)

    assert dialog.profile_combo.currentData() == AuditProfile.STANDARD.value  # not auto-switched
    assert not dialog.lbl_render_profile_note.isHidden()
    assert dialog.lbl_render_profile_note.text() == "Rendering checks are skipped under the Standard profile."


def test_settings_dialog_scrolls_and_keeps_buttons_onscreen(qtbot) -> None:
    # B1: a tall settings dialog must scroll its body and never push the
    # OK/Cancel/Help row below the taskbar.
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=True)
    qtbot.addWidget(dialog)

    # the setting groups live inside a scroll area (overflow scrolls, not clips)
    assert dialog.findChild(QtWidgets.QScrollArea) is not None

    # the dialog never exceeds the available screen height, so the buttons stay reachable
    screen = dialog.screen() or QtWidgets.QApplication.primaryScreen()
    assert dialog.height() <= screen.availableGeometry().height()

    # the button box is pinned outside the scroll area (parented to the dialog), always visible
    button_box = dialog.findChild(QtWidgets.QDialogButtonBox)
    assert button_box is not None
    assert button_box.parentWidget() is dialog


# --- PR-F1: opt-in ticks persist across sessions, shared by both windows -------


@pytest.fixture
def _extras(monkeypatch):
    """Hermetic w.r.t. installed extras: every optional extra reads as present."""
    for probe in ("_playwright_available", "_embeddings_available", "_scrapling_available"):
        monkeypatch.setattr(f"silentfrog.settings_dialog.{probe}", lambda: True)


def _accept_with(monkeypatch, tick) -> None:
    """Drive the real Crawl-settings dialog: apply ``tick(dialog)`` then accept."""

    def _exec(self) -> int:
        tick(self)
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(CrawlSettingsDialog, "exec", _exec)


def _tick_secrets_and_checks(dialog: CrawlSettingsDialog) -> None:
    dialog.chk_ssr_parity.setChecked(True)
    dialog.chk_tech_stack.setChecked(True)
    dialog.chk_allow_insecure_tls.setChecked(True)
    dialog.chk_allow_private_network.setChecked(True)
    dialog.edit_cookies.setText("session=topsecret")
    dialog.txt_headers.setPlainText("X-Api-Key: topsecret")


def test_ticks_made_in_single_page_reach_a_new_site_crawl_window(qtbot, monkeypatch, _extras) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    _accept_with(monkeypatch, _tick_secrets_and_checks)
    page._open_crawl_settings()

    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    assert site._crawl_options.ssr_parity_check is True
    assert site._crawl_options.tech_stack_detection is True
    assert site._crawl_options.profile is AuditProfile.STANDARD  # Site Crawl keeps its own profile
    # Posture and credentials never survive into a new window...
    assert site._crawl_options.allow_insecure_tls is False
    assert site._crawl_options.allow_private_network is False
    assert site._crawl_options.extra_headers == {}
    again = WebpageSeoWindow()
    qtbot.addWidget(again)
    assert again._crawl_options.ssr_parity_check is True
    assert again._crawl_options.profile is AuditProfile.DEEP
    # ...and none of it is in the stored blob at all.
    stored = json.dumps(crawl_prefs.app_settings().value(crawl_prefs.OPT_IN_KEY))
    assert "topsecret" not in stored and "tls" not in stored.lower() and "private" not in stored.lower()


def test_site_profile_is_remembered_separately_and_single_page_stays_deep(qtbot, monkeypatch, _extras) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    _accept_with(
        monkeypatch,
        lambda dialog: dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData("lightweight")),
    )
    site._open_crawl_settings()

    reopened = SiteCrawlWindow()
    qtbot.addWidget(reopened)
    assert reopened._crawl_options.profile is AuditProfile.LIGHTWEIGHT
    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    assert page._crawl_options.profile is AuditProfile.DEEP


def test_empty_store_keeps_todays_defaults(qtbot) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    assert page._crawl_options == CrawlOptions.default()
    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    assert site._crawl_options == CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)


def test_corrupt_store_falls_back_to_defaults(qtbot) -> None:
    settings = crawl_prefs.app_settings()
    settings.setValue(crawl_prefs.OPT_IN_KEY, "{not json")
    settings.setValue(crawl_prefs.SITE_PROFILE_KEY, "bogus")
    settings.sync()
    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    assert site._crawl_options == CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)


def test_stored_tick_for_a_missing_extra_loads_unticked(qtbot, monkeypatch) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    crawl_prefs.save_opt_in_options(
        CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, topic_embeddings=True, tech_stack_detection=True)
    )
    monkeypatch.setattr("silentfrog.settings_dialog._embeddings_available", lambda: False)
    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    assert page._crawl_options.topic_embeddings is False
    assert page._crawl_options.tech_stack_detection is True


# --- PR-F1: the label shows which checks will actually run ---------------------


def test_single_page_label_lists_active_checks(qtbot, monkeypatch, _extras) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    assert "no optional checks" in page.lbl_settings_state.text()
    _accept_with(monkeypatch, _tick_secrets_and_checks)
    page._open_crawl_settings()
    text = page.lbl_settings_state.text()
    assert "SSR parity" in text and "Tech stack" in text
    assert "skipped" not in text  # Single Page is always Deep
    assert "SSR parity" in page.lbl_settings_state.toolTip()


def test_site_label_marks_render_checks_skipped_under_standard(qtbot, monkeypatch, _extras) -> None:
    site = SiteCrawlWindow()
    qtbot.addWidget(site)

    def _tick(dialog: CrawlSettingsDialog) -> None:
        dialog.chk_ssr_parity.setChecked(True)
        dialog.chk_tech_stack.setChecked(True)
        dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData("standard"))

    _accept_with(monkeypatch, _tick)
    site._open_crawl_settings()
    assert site._crawl_options.profile is AuditProfile.STANDARD
    text = site.lbl_speed.text()
    assert "SSR parity (skipped: needs Deep)" in text
    assert "Tech stack" in text and "Standard profile" in text


def test_site_label_drops_host_cap_when_gentle_is_off(qtbot) -> None:
    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    assert "max 2/host" in site.lbl_speed.text()
    site._crawl_options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=8, profile=AuditProfile.STANDARD)
    site._update_speed_label()
    assert "/host" not in site.lbl_speed.text()


def test_untouched_single_page_save_keeps_site_crawl_gentle(qtbot) -> None:
    crawl_prefs.save_opt_in_options(CrawlOptions.default())
    site = SiteCrawlWindow()
    qtbot.addWidget(site)
    assert site._crawl_options.gentle_mode is True
    assert site._crawl_options.max_concurrent_per_host == 2


def test_unusable_stored_custom_extraction_does_not_stop_windows_opening(qtbot) -> None:
    from silentfrog.seo_gui import WebpageSeoWindow

    settings = crawl_prefs.app_settings()
    settings.setValue(crawl_prefs.OPT_IN_KEY, '{"custom_extraction": 5}')
    settings.sync()
    base = CrawlOptions.default()
    assert crawl_prefs.load_opt_in_options(base) == base
    page = WebpageSeoWindow()
    qtbot.addWidget(page)
    assert page._crawl_options == CrawlOptions.default()


def test_bad_header_lines_are_reported_by_number() -> None:
    # PR-F2 D6: the parser says WHICH lines it dropped (1-based, blank lines count).
    from silentfrog.crawl_options import parse_header_lines

    headers, bad = parse_header_lines("X-One: 1\nnot a header\n\n: novalue-key\nX-Two: 2")
    assert headers == {"X-One": "1", "X-Two": "2"}
    assert bad == [2, 4]
    assert parse_header_lines("") == ({}, [])


def test_settings_dialog_names_the_ignored_header_lines(qtbot) -> None:
    dialog = CrawlSettingsDialog(CrawlOptions.default(), show_profile=False)
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.lbl_headers_error.isVisible()
    dialog.txt_headers.setPlainText("X-Ok: 1\nbroken line")
    assert dialog.lbl_headers_error.isVisible()
    assert dialog.lbl_headers_error.text() == "Line(s) 2 ignored: expected 'Key: Value'."
    dialog.txt_headers.setPlainText("X-Ok: 1")
    assert not dialog.lbl_headers_error.isVisible()
