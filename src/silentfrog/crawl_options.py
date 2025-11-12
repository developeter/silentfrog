from __future__ import annotations

from dataclasses import dataclass

DEFAULT_USER_AGENT = "SilentFrog/1.0 (+https://example.com)"


@dataclass(frozen=True)
class CrawlOptions:
    gentle_mode: bool
    max_concurrent_per_host: int
    respect_crawl_delay: bool
    user_agent: str

    @classmethod
    def default(cls) -> CrawlOptions:
        return cls(
            gentle_mode=False,
            max_concurrent_per_host=4,
            respect_crawl_delay=False,
            user_agent=DEFAULT_USER_AGENT,
        )

    @classmethod
    def from_ui(
        cls,
        gentle_mode: bool,
        max_parallel: int,
        *,
        user_agent: str | None = None,
        respect_crawl_delay: bool | None = None,
    ) -> CrawlOptions:
        base = cls.default()
        ua = (user_agent or base.user_agent).strip() or base.user_agent
        max_hosts = max(1, min(16, int(max_parallel)))
        delay_flag = gentle_mode if respect_crawl_delay is None else bool(respect_crawl_delay)
        return cls(
            gentle_mode=gentle_mode,
            max_concurrent_per_host=max_hosts,
            respect_crawl_delay=delay_flag,
            user_agent=ua,
        )


__all__ = ["CrawlOptions", "DEFAULT_USER_AGENT"]
