from __future__ import annotations

import json
from dataclasses import replace

import pytest

from silentfrog.crawl_options import (  # type: ignore[reportMissingImports]
    DEFAULT_USER_AGENT,
    AuditProfile,
    CrawlOptions,
    active_checks_summary,
    crawl_settings_summary,
    opt_in_from_dict,
    opt_in_to_dict,
)

_ALL_EXTRAS = frozenset({"playwright", "embeddings", "stealth"})
_RULES = "Price | css | span.price"


def _ticked() -> CrawlOptions:
    return CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=8,
        header_text="X-Api-Key: secret",
        cookie_text="session=abc",
        ssr_parity_check=True,
        bot_render=True,
        render_js=True,
        accessibility_audit=True,
        tech_stack_detection=True,
        topic_embeddings=True,
        use_stealth=True,
        custom_rules_text=_RULES,
        allow_insecure_tls=True,
        allow_private_network=True,
        profile=AuditProfile.DEEP,
    )


def test_crawl_options_default_values() -> None:
    options = CrawlOptions.default()
    assert options.gentle_mode is False
    assert options.max_concurrent_per_host == 4
    assert options.respect_crawl_delay is False
    assert options.user_agent == DEFAULT_USER_AGENT
    assert options.extra_headers == {}
    assert options.allow_insecure_tls is False  # H7: TLS verified unless opted out
    assert options.allow_private_network is False  # H7: SSRF guarded unless opted out


def test_crawl_options_bot_render_off_by_default() -> None:
    # V10: per-bot SSR rendering is strictly opt-in.
    assert CrawlOptions.default().bot_render is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).bot_render is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, bot_render=True).bot_render is True


def test_crawl_options_accessibility_audit_off_by_default() -> None:
    # v3 G4 Stage 1: axe-core accessibility scan is strictly opt-in.
    assert CrawlOptions.default().accessibility_audit is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).accessibility_audit is False
    opted_in = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, accessibility_audit=True)
    assert opted_in.accessibility_audit is True


def test_crawl_options_topic_embeddings_off_by_default() -> None:
    # V20: local embedding inference is strictly opt-in.
    assert CrawlOptions.default().topic_embeddings is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).topic_embeddings is False
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, topic_embeddings=True).topic_embeddings is True


def test_crawl_options_from_ui_allow_insecure_tls_off_by_default() -> None:
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).allow_insecure_tls is False
    opted_in = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, allow_insecure_tls=True)
    assert opted_in.allow_insecure_tls is True


def test_crawl_options_from_ui_allow_private_network_off_by_default() -> None:
    assert CrawlOptions.from_ui(gentle_mode=False, max_parallel=4).allow_private_network is False
    opted_in = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, allow_private_network=True)
    assert opted_in.allow_private_network is True


def test_crawl_options_from_ui_applies_bounds_and_flags() -> None:
    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=0)
    assert options.gentle_mode is True
    assert options.max_concurrent_per_host == 1  # clamped minimum
    assert options.respect_crawl_delay is True  # defaults to gentle flag
    assert options.user_agent == DEFAULT_USER_AGENT
    assert options.extra_headers == {}

    custom = CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=20,
        user_agent=" CustomUA/2.0 ",
        respect_crawl_delay=True,
        header_text="Authorization: Bearer token\nX-Test: 1",
        cookie_text="session=abc; theme=dark",
    )
    assert custom.gentle_mode is False
    assert custom.max_concurrent_per_host == 16
    assert custom.user_agent == "CustomUA/2.0"
    assert custom.respect_crawl_delay is True
    assert custom.extra_headers == {
        "Authorization": "Bearer token",
        "X-Test": "1",
        "Cookie": "session=abc; theme=dark",
    }


def test_opt_in_roundtrip_restores_ticks_but_never_posture_or_credentials() -> None:
    stored = json.loads(json.dumps(opt_in_to_dict(_ticked())))
    loaded = opt_in_from_dict(stored, CrawlOptions.default(), installed=_ALL_EXTRAS)
    for flag in (
        "ssr_parity_check",
        "bot_render",
        "render_js",
        "accessibility_audit",
        "tech_stack_detection",
        "topic_embeddings",
        "use_stealth",
    ):
        assert getattr(loaded, flag) is True, flag
    assert loaded.custom_extraction.names == ["Price"]
    # Security posture + credentials are session-only.
    assert loaded.allow_insecure_tls is False
    assert loaded.allow_private_network is False
    assert loaded.extra_headers == {}
    blob = json.dumps(stored)
    for secret in ("secret", "session=abc", "insecure", "private", "headers", "Cookie"):
        assert secret not in blob


def test_opt_in_empty_or_corrupt_store_is_todays_defaults() -> None:
    base = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)
    for junk in (None, "", "nope", 7, [], {}, {"ssr_parity_check": "yes", "max_concurrent_per_host": "9"}):
        assert opt_in_from_dict(junk, base, installed=_ALL_EXTRAS) == base


def test_opt_in_clamps_to_installed_extras_and_never_touches_profile() -> None:
    stored = opt_in_to_dict(_ticked())
    base = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4, profile=AuditProfile.STANDARD)
    loaded = opt_in_from_dict(stored, base, installed=frozenset())
    assert not any((loaded.ssr_parity_check, loaded.bot_render, loaded.render_js, loaded.accessibility_audit))
    assert loaded.topic_embeddings is False
    assert loaded.use_stealth is False
    assert loaded.tech_stack_detection is True  # needs no extra
    assert loaded.profile is AuditProfile.STANDARD


def test_opt_in_never_stores_or_overrides_crawl_speed() -> None:
    # Speed is per-window (Site Crawl is gentle by default); a shared blob must
    # not let one window silently remove the other's politeness.
    assert "gentle_mode" not in opt_in_to_dict(_ticked())
    assert "max_concurrent_per_host" not in opt_in_to_dict(_ticked())
    stored = {"gentle_mode": False, "max_concurrent_per_host": 99}
    base = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)
    assert opt_in_from_dict(stored, base, installed=_ALL_EXTRAS) == base


def test_opt_in_unusable_custom_extraction_value_keeps_defaults() -> None:
    base = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)
    for junk in (5, "x", True, 1.5, None):
        assert opt_in_from_dict({"custom_extraction": junk}, base, installed=_ALL_EXTRAS) == base


def test_active_checks_summary_lists_ticks_and_posture() -> None:
    assert active_checks_summary(CrawlOptions.default()) == []
    labels = active_checks_summary(_ticked())
    assert labels == [
        "SSR parity",
        "Per-bot SSR",
        "JS links",
        "Accessibility",
        "Tech stack",
        "Custom rules (1)",
        "Embeddings",
        "Stealth",
        "Insecure TLS",
        "Private network",
        "2 custom header(s)",
    ]


@pytest.mark.parametrize("profile", [AuditProfile.LIGHTWEIGHT, AuditProfile.STANDARD])
def test_active_checks_summary_marks_render_checks_skipped_without_deep(profile: AuditProfile) -> None:
    opts = replace(CrawlOptions.default(), ssr_parity_check=True, tech_stack_detection=True, profile=profile)
    assert active_checks_summary(opts) == ["SSR parity (skipped: needs Deep)", "Tech stack"]
    deep = replace(opts, profile=AuditProfile.DEEP)
    assert active_checks_summary(deep) == ["SSR parity", "Tech stack"]


def test_crawl_settings_summary_drops_host_cap_when_gentle_is_off() -> None:
    gentle = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2, profile=AuditProfile.STANDARD)
    assert crawl_settings_summary(gentle) == "Gentle crawl, max 2/host · Standard profile · no optional checks"
    plain = replace(gentle, gentle_mode=False)
    assert "/host" not in crawl_settings_summary(plain)
    assert crawl_settings_summary(plain, show_profile=False) == "Standard crawl · no optional checks"
