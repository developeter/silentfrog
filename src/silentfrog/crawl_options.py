from __future__ import annotations

from dataclasses import dataclass, field

from .custom_extraction import CustomExtractionConfig, parse_rules_text

DEFAULT_USER_AGENT = "SilentFrog/1.0 (+https://example.com)"


@dataclass(frozen=True)
class CrawlOptions:
    gentle_mode: bool
    max_concurrent_per_host: int
    respect_crawl_delay: bool
    user_agent: str
    extra_headers: dict[str, str]
    ssr_parity_check: bool = False
    # v2.0 V1: opt-in stealth fetcher (Scrapling TLS + browser escalation
    # past WAF blocks). Off by default — needs the `silentfrog[stealth]`
    # extra installed to actually escalate; otherwise the strategy stays
    # on the aiohttp base path.
    use_stealth: bool = False
    # v2.0 V6: user-defined CSS/XPath/regex extraction rules.
    custom_extraction: CustomExtractionConfig = field(default_factory=CustomExtractionConfig)

    @classmethod
    def default(cls) -> CrawlOptions:
        return cls(
            gentle_mode=False,
            max_concurrent_per_host=4,
            respect_crawl_delay=False,
            user_agent=DEFAULT_USER_AGENT,
            extra_headers={},
            ssr_parity_check=False,
            use_stealth=False,
            custom_extraction=CustomExtractionConfig(),
        )

    @classmethod
    def from_ui(
        cls,
        gentle_mode: bool,
        max_parallel: int,
        *,
        user_agent: str | None = None,
        respect_crawl_delay: bool | None = None,
        header_text: str | None = None,
        cookie_text: str | None = None,
        ssr_parity_check: bool = False,
        use_stealth: bool | None = None,
        custom_rules_text: str = "",
    ) -> CrawlOptions:
        base = cls.default()
        ua = (user_agent or base.user_agent).strip() or base.user_agent
        max_hosts = max(1, min(16, int(max_parallel)))
        delay_flag = gentle_mode if respect_crawl_delay is None else bool(respect_crawl_delay)
        extras, _ = parse_header_lines(header_text or "")
        cookie_value = (cookie_text or "").strip()
        if cookie_value:
            extras["Cookie"] = cookie_value
        return cls(
            gentle_mode=gentle_mode,
            max_concurrent_per_host=max_hosts,
            respect_crawl_delay=delay_flag,
            user_agent=ua,
            extra_headers=extras,
            ssr_parity_check=bool(ssr_parity_check),
            use_stealth=bool(use_stealth),
            custom_extraction=parse_rules_text(custom_rules_text or ""),
        )


def parse_header_lines(text: str) -> tuple[dict[str, str], bool]:
    headers: dict[str, str] = {}
    invalid = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            invalid = True
            continue
        key, value = line.split(":", 1)
        key_clean = key.strip()
        if not key_clean:
            invalid = True
            continue
        headers[key_clean] = value.strip()
    return headers, invalid


__all__ = ["CrawlOptions", "DEFAULT_USER_AGENT", "parse_header_lines"]
