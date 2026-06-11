"""Crawl modes (v2.0 V3).

- ``SITEMAP`` — only URLs found in sitemaps (the v1.x behaviour).
- ``LIST`` — only the explicit URL list the user supplied.
- ``SPIDER`` — start at the base URL and follow same-host links.
- ``HYBRID`` — seed from (sitemap URLs ∪ base URL) then spider-follow
  links; union + dedupe. The default — catches orphan pages sitemaps
  miss AND pages internal links miss.
"""

from __future__ import annotations

from enum import StrEnum


class CrawlMode(StrEnum):
    SITEMAP = "sitemap"
    LIST = "list"
    SPIDER = "spider"
    HYBRID = "hybrid"

    @classmethod
    def from_value(cls, value: object) -> CrawlMode:
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        for member in cls:
            if member.value == text:
                return member
        return cls.HYBRID

    @property
    def follows_links(self) -> bool:
        return self in {CrawlMode.SPIDER, CrawlMode.HYBRID}

    @property
    def uses_sitemap(self) -> bool:
        return self in {CrawlMode.SITEMAP, CrawlMode.HYBRID}


__all__ = ["CrawlMode"]
