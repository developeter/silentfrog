from __future__ import annotations

from silentfrog.crawl_options import CrawlOptions, DEFAULT_USER_AGENT


def test_crawl_options_default_values() -> None:
    options = CrawlOptions.default()
    assert options.gentle_mode is False
    assert options.max_concurrent_per_host == 4
    assert options.respect_crawl_delay is False
    assert options.user_agent == DEFAULT_USER_AGENT


def test_crawl_options_from_ui_applies_bounds_and_flags() -> None:
    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=0)
    assert options.gentle_mode is True
    assert options.max_concurrent_per_host == 1  # clamped minimum
    assert options.respect_crawl_delay is True  # defaults to gentle flag
    assert options.user_agent == DEFAULT_USER_AGENT

    custom = CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=20,
        user_agent=" CustomUA/2.0 ",
        respect_crawl_delay=True,
    )
    assert custom.gentle_mode is False
    assert custom.max_concurrent_per_host == 16
    assert custom.user_agent == "CustomUA/2.0"
    assert custom.respect_crawl_delay is True
