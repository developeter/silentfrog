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


def test_settings_dialog_semrush_defaults(qtbot, monkeypatch) -> None:
    # V17 — the API-key field is empty + masked by default and the
    # max-calls spinbox defaults to 100. Force env-only resolution (no
    # stored key) so the default is deterministic regardless of keychain.
    monkeypatch.delenv("SILENTFROG_SEMRUSH_API_KEY", raising=False)
    from qtpy import QtWidgets

    from silentfrog.crawl_options import CrawlOptions
    from silentfrog.settings_dialog import CrawlSettingsDialog

    dialog = CrawlSettingsDialog(CrawlOptions.default())
    qtbot.addWidget(dialog)
    assert dialog.edit_semrush_key.text() == ""
    assert dialog.edit_semrush_key.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
    assert dialog.spin_semrush_max_calls.value() == 100
