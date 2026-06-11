"""Unit tests for the v2.0 V3 crawl frontier."""

from __future__ import annotations

from silentfrog.frontier import CrawlFrontier, FrontierConfig


def _cfg(**kw) -> FrontierConfig:
    base = {"base_host": "e.com"}
    base.update(kw)
    return FrontierConfig(**base)


def test_seed_enqueues_and_dedups() -> None:
    f = CrawlFrontier(_cfg())
    added = f.seed(["https://e.com/a", "https://e.com/b", "https://e.com/a"])
    assert added == 2  # duplicate dropped
    assert len(f) == 2
    assert f.seen_count == 2


def test_pop_is_fifo_breadth_first() -> None:
    f = CrawlFrontier(_cfg())
    f.seed(["https://e.com/1", "https://e.com/2", "https://e.com/3"])
    assert f.pop() == ("https://e.com/1", 0)
    assert f.pop() == ("https://e.com/2", 0)
    assert f.pop() == ("https://e.com/3", 0)
    assert f.pop() is None


def test_depth_cap_blocks_deep_links() -> None:
    f = CrawlFrontier(_cfg(max_depth=2))
    assert f.enqueue("https://e.com/ok", depth=2) is True
    assert f.enqueue("https://e.com/too-deep", depth=3) is False


def test_max_urls_cap() -> None:
    f = CrawlFrontier(_cfg(max_urls=2))
    assert f.enqueue("https://e.com/1", 0) is True
    assert f.enqueue("https://e.com/2", 0) is True
    assert f.enqueue("https://e.com/3", 0) is False  # cap hit


def test_same_host_only_rejects_offsite() -> None:
    f = CrawlFrontier(_cfg(same_host_only=True))
    assert f.enqueue("https://e.com/in", 0) is True
    assert f.enqueue("https://other.com/out", 0) is False


def test_follow_subdomains() -> None:
    f = CrawlFrontier(_cfg(follow_subdomains=True))
    assert f.enqueue("https://blog.e.com/post", 0) is True
    assert f.enqueue("https://e.com/page", 0) is True
    assert f.enqueue("https://evil-e.com/x", 0) is False  # not a real subdomain


def test_same_host_off_allows_any_host() -> None:
    f = CrawlFrontier(_cfg(same_host_only=False))
    assert f.enqueue("https://anywhere.com/x", 0) is True


def test_include_patterns_filter() -> None:
    f = CrawlFrontier(_cfg(include_patterns=("/blog",)))
    assert f.enqueue("https://e.com/blog/post", 0) is True
    assert f.enqueue("https://e.com/shop/item", 0) is False


def test_exclude_patterns_filter() -> None:
    f = CrawlFrontier(_cfg(exclude_patterns=("/admin",)))
    assert f.enqueue("https://e.com/admin/panel", 0) is False
    assert f.enqueue("https://e.com/public", 0) is True


def test_rejects_non_http_urls() -> None:
    f = CrawlFrontier(_cfg())
    assert f.enqueue("mailto:hi@e.com", 0) is False
    assert f.enqueue("javascript:void(0)", 0) is False
    assert f.enqueue("ftp://e.com/file", 0) is False


def test_add_links_filters_and_counts() -> None:
    f = CrawlFrontier(_cfg(max_depth=5))
    added = f.add_links(
        ["https://e.com/a", "https://other.com/b", "https://e.com/c"],
        depth=1,
    )
    assert added == 2  # off-site dropped
    assert len(f) == 2


def test_in_scope_predicate_without_enqueue() -> None:
    f = CrawlFrontier(_cfg(max_depth=2))
    assert f.in_scope("https://e.com/x", 1) is True
    assert f.in_scope("https://other.com/x", 1) is False
    assert f.in_scope("https://e.com/x", 3) is False  # too deep
    assert len(f) == 0  # in_scope never enqueues
