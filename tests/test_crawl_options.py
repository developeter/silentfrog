from __future__ import annotations

from silentfrog.crawl_options import DEFAULT_USER_AGENT, CrawlOptions  # type: ignore[reportMissingImports]


def test_crawl_options_default_values() -> None:
    options = CrawlOptions.default()
    assert options.gentle_mode is False
    assert options.max_concurrent_per_host == 4
    assert options.respect_crawl_delay is False
    assert options.user_agent == DEFAULT_USER_AGENT
    assert options.extra_headers == {}


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
