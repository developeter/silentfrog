"""Unit tests for the v2.0 V3 CrawlMode enum."""

from __future__ import annotations

from silentfrog.crawl_mode import CrawlMode


def test_from_value_maps_known_strings() -> None:
    assert CrawlMode.from_value("sitemap") is CrawlMode.SITEMAP
    assert CrawlMode.from_value("LIST") is CrawlMode.LIST
    assert CrawlMode.from_value("spider") is CrawlMode.SPIDER
    assert CrawlMode.from_value("hybrid") is CrawlMode.HYBRID


def test_from_value_defaults_to_hybrid_on_garbage() -> None:
    assert CrawlMode.from_value("nonsense") is CrawlMode.HYBRID
    assert CrawlMode.from_value(None) is CrawlMode.HYBRID
    assert CrawlMode.from_value("") is CrawlMode.HYBRID


def test_from_value_passes_through_enum() -> None:
    assert CrawlMode.from_value(CrawlMode.SPIDER) is CrawlMode.SPIDER


def test_follows_links() -> None:
    assert CrawlMode.SPIDER.follows_links
    assert CrawlMode.HYBRID.follows_links
    assert not CrawlMode.SITEMAP.follows_links
    assert not CrawlMode.LIST.follows_links


def test_uses_sitemap() -> None:
    assert CrawlMode.SITEMAP.uses_sitemap
    assert CrawlMode.HYBRID.uses_sitemap
    assert not CrawlMode.SPIDER.uses_sitemap
    assert not CrawlMode.LIST.uses_sitemap
