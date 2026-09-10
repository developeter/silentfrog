"""Unit tests for the v2.0 V15 tech-stack detection (optional, off by default)."""

from __future__ import annotations

from silentfrog.tech_stack import TechStackPayload, detect_tech


def test_detect_wordpress_from_html_and_generator() -> None:
    html = '<html><head><meta name="generator" content="WordPress 6.5"></head>'
    payload = detect_tech(html, generator="WordPress 6.5")
    assert "WordPress" in payload.by_category.get("CMS", [])


def test_detect_shopify_from_html() -> None:
    payload = detect_tech('<script src="https://cdn.shopify.com/s/x.js"></script>')
    assert "Shopify" in payload.by_category.get("Ecommerce", [])


def test_detect_react_and_nextjs() -> None:
    html = '<div data-reactroot></div><script src="/_next/static/chunks/main.js"></script>'
    names = detect_tech(html).all_names
    assert "React" in names
    assert "Next.js" in names


def test_detect_from_headers_cloudflare_and_nginx() -> None:
    payload = detect_tech("<html></html>", headers={"Server": "cloudflare", "CF-RAY": "abc"})
    assert "Cloudflare" in payload.by_category.get("CDN", [])
    payload2 = detect_tech("<html></html>", headers={"Server": "nginx/1.25"})
    assert "Nginx" in payload2.by_category.get("Server", [])


def test_detect_from_scripts_gtm() -> None:
    payload = detect_tech('<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>')
    assert "Google Tag Manager" in payload.by_category.get("Tag manager", [])


def test_no_detection_returns_empty() -> None:
    payload = detect_tech("<html><body>plain page</body></html>")
    assert payload.by_category == {}
    assert payload.all_names == []


def test_payload_roundtrips_through_dict() -> None:
    payload = detect_tech(
        '<html data-reactroot><meta name="generator" content="WordPress"></html>', generator="WordPress"
    )
    restored = TechStackPayload.from_raw(payload.to_dict())
    assert restored.to_dict() == payload.to_dict()


def test_crawl_options_tech_stack_off_by_default() -> None:
    from silentfrog.crawl_options import CrawlOptions

    assert CrawlOptions.default().tech_stack_detection is False
    on = CrawlOptions.from_ui(gentle_mode=False, max_parallel=2, tech_stack_detection=True)
    assert on.tech_stack_detection is True


def test_crawl_payload_roundtrips_tech_stack() -> None:
    from silentfrog.crawl_types import CrawlPayload

    base = {
        "meta": [],
        "headers": [],
        "images": [],
        "links": [],
        "schema": {"summary": {"total": 0, "by_type": {}}, "blocks": [], "issues": []},
        "canonical": {},
        "redirect": {},
        "robots": {},
        "meta_robots": "",
        "hreflang": [],
        "ai_crawl": [],
        "serp": {},
        "serp_audit": {},
        "keywords": [],
        "content_quality": {},
        "ai_visibility": {},
        "performance": {},
        "social": {},
        "tech_stack": {"by_category": {"CMS": ["WordPress"]}},
    }
    payload = CrawlPayload.from_raw(base)
    assert payload.tech_stack == {"by_category": {"CMS": ["WordPress"]}}
    assert payload.to_mapping()["tech_stack"] == {"by_category": {"CMS": ["WordPress"]}}


def test_settings_dialog_tech_stack_toggle(qtbot) -> None:
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert dialog.chk_tech_stack.isChecked() is False  # off by default
    dialog.chk_tech_stack.setChecked(True)
    assert dialog.options().tech_stack_detection is True


def test_settings_dialog_accessibility_audit_toggle_disabled_without_playwright(qtbot) -> None:
    # v3 G4 Stage 2 — the checkbox exists but is gated on Playwright, same
    # idiom as chk_render_js/chk_bot_render. The dev venv has no Playwright,
    # so it must be disabled and options() must stay False even after a
    # forced setChecked(True) — mirrors the `isEnabled() and isChecked()`
    # guard in CrawlSettingsDialog.options().
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert hasattr(dialog, "chk_accessibility_audit")
    assert dialog.chk_accessibility_audit.isEnabled() is False
    assert dialog.chk_accessibility_audit.isChecked() is False
    dialog.chk_accessibility_audit.setChecked(True)
    assert dialog.options().accessibility_audit is False


def test_settings_dialog_stealth_toggle_disabled_without_scrapling(qtbot) -> None:
    # v2.0 R1 (V1) — chk_stealth is gated on the optional silentfrog[stealth]
    # extra, same idiom as chk_ssr_parity/chk_accessibility_audit. The dev
    # venv has no scrapling, so it must be disabled and options() must stay
    # False even after a forced setChecked(True) — mirrors the
    # `isEnabled() and isChecked()` guard in CrawlSettingsDialog.options().
    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert hasattr(dialog, "chk_stealth")
    assert dialog.chk_stealth.isEnabled() is False
    assert dialog.chk_stealth.isChecked() is False
    dialog.chk_stealth.setChecked(True)
    assert dialog.options().use_stealth is False


def test_settings_dialog_semrush_defaults(qtbot, monkeypatch, tmp_path) -> None:
    # V17 — the API-key field is empty + masked by default and the
    # max-calls spinbox defaults to 100. Stub the keychain lookup and point
    # the settings seam at a temp ini so the defaults are deterministic
    # regardless of the developer's keychain or registry.
    monkeypatch.delenv("SILENTFROG_SEMRUSH_API_KEY", raising=False)
    from qtpy import QtCore, QtWidgets

    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        CrawlSettingsDialog,
        "_app_settings",
        staticmethod(lambda: QtCore.QSettings(ini, QtCore.QSettings.IniFormat)),
    )
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert dialog.edit_semrush_key.text() == ""
    assert dialog.edit_semrush_key.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
    assert dialog.spin_semrush_max_calls.value() == 100


class _FakeKeyringModule:
    """Stand-in for the optional ``keyring`` module — records every
    ``set_password`` call so persistence tests don't touch the real OS
    keychain."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append((service, username, password))


def test_settings_dialog_sov_defaults(qtbot, monkeypatch, tmp_path) -> None:
    # v3 G3 Stage 2 — the three AI-engine BYO-key fields are empty + masked
    # by default. Stub the keychain lookup and point the settings seam at a
    # temp ini, same isolation as test_settings_dialog_semrush_defaults.
    monkeypatch.delenv("SILENTFROG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("SILENTFROG_GEMINI_API_KEY", raising=False)
    from qtpy import QtCore, QtWidgets

    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        CrawlSettingsDialog,
        "_app_settings",
        staticmethod(lambda: QtCore.QSettings(ini, QtCore.QSettings.IniFormat)),
    )
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert set(dialog.edit_sov_keys) == {"openai", "perplexity", "gemini"}
    for edit in dialog.edit_sov_keys.values():
        assert edit.text() == ""
        assert edit.echoMode() == QtWidgets.QLineEdit.EchoMode.Password


def test_settings_dialog_sov_persist_calls_keyring_set_password(qtbot, monkeypatch, tmp_path) -> None:
    # accept() with a filled BYO-key field must persist it to the
    # `silentfrog-ai-engines` keychain service under the engine's own name.
    import sys

    from qtpy import QtCore

    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        CrawlSettingsDialog,
        "_app_settings",
        staticmethod(lambda: QtCore.QSettings(ini, QtCore.QSettings.IniFormat)),
    )
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.edit_sov_keys["openai"].setText("sk-test-123")

    fake_keyring = _FakeKeyringModule()
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    dialog.accept()

    assert ("silentfrog-ai-engines", "openai", "sk-test-123") in fake_keyring.calls
    # Untouched engines stay unpersisted (empty fields are skipped).
    assert not any(call[1] == "perplexity" for call in fake_keyring.calls)


def test_settings_dialog_sov_persist_swallows_missing_keyring(qtbot, monkeypatch, tmp_path) -> None:
    # keyring is an optional extra; accept() must not raise when it's absent.
    import sys

    from qtpy import QtCore

    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(
        CrawlSettingsDialog,
        "_app_settings",
        staticmethod(lambda: QtCore.QSettings(ini, QtCore.QSettings.IniFormat)),
    )
    monkeypatch.setattr(CrawlSettingsDialog, "_load_semrush_key", staticmethod(lambda: ""))
    monkeypatch.setattr(CrawlSettingsDialog, "_load_sov_key", staticmethod(lambda engine: ""))

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    dialog.edit_sov_keys["gemini"].setText("gk-test-456")

    monkeypatch.setitem(sys.modules, "keyring", None)  # simulates keyring not installed

    dialog.accept()  # must not raise
