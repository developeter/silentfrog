from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .custom_extraction import CustomExtractionConfig, parse_rules_text

DEFAULT_USER_AGENT = "SilentFrog/1.0 (+https://example.com)"

# v2.0 H4: how many internal links STANDARD probes for HTTP status per page. DEEP
# probes them all; the cap keeps STANDARD's per-page request budget bounded so it
# does not scale with link count (the F6 fan-out).
_STANDARD_LINK_PROBE_CAP = 25
# v2.0 H4: above this many target URLs a STANDARD site crawl auto-suggests
# LIGHTWEIGHT so per-page probing fan-out does not blow up the request budget.
_AUTO_LIGHTWEIGHT_THRESHOLD = 50_000


class AuditProfile(StrEnum):
    """v2.0 H4 — selectable per-page **network** cost. Profiles gate extra HTTP
    requests, rendering, and integrations ONLY; deterministic local parsing (SEO,
    structure, E-E-A-T, schema) and internal link extraction stay on in every
    profile, and site-wide discovery is fetched once per origin in all profiles."""

    LIGHTWEIGHT = "lightweight"
    STANDARD = "standard"
    DEEP = "deep"

    @classmethod
    def from_value(cls, value: object) -> AuditProfile:
        """Resolve a stored/UI value to a profile, defaulting to STANDARD."""
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.STANDARD


@dataclass(frozen=True)
class ProfilePolicy:
    """The network gates a profile applies, resolved once and threaded through
    ``analyse``. A typed config (not loose flags) so call sites read clearly."""

    probe_link_status: bool
    link_probe_cap: int  # 0 = unbounded (DEEP); >0 = bounded (STANDARD)
    probe_canonical: bool
    trace_redirects: bool
    probe_hreflang: bool
    download_social: bool
    probe_resources: bool
    render: bool
    run_integrations: bool

    @classmethod
    def for_profile(cls, profile: AuditProfile) -> ProfilePolicy:
        if profile is AuditProfile.LIGHTWEIGHT:
            # Local parse + link extraction + per-origin discovery only.
            return cls(
                probe_link_status=False,
                link_probe_cap=0,
                probe_canonical=False,
                trace_redirects=False,
                probe_hreflang=False,
                download_social=False,
                probe_resources=False,
                render=False,
                run_integrations=False,
            )
        if profile is AuditProfile.DEEP:
            # Full coverage — every probe/render/integration (gated only by their
            # own enable flags, e.g. ssr_parity_check).
            return cls(
                probe_link_status=True,
                link_probe_cap=0,
                probe_canonical=True,
                trace_redirects=True,
                probe_hreflang=True,
                download_social=True,
                probe_resources=True,
                render=True,
                run_integrations=True,
            )
        # STANDARD (default): bounded link/canonical/redirect probing; hreflang
        # parse-only; no social downloads, resource probing, or render.
        return cls(
            probe_link_status=True,
            link_probe_cap=_STANDARD_LINK_PROBE_CAP,
            probe_canonical=True,
            trace_redirects=True,
            probe_hreflang=False,
            download_social=False,
            probe_resources=False,
            render=False,
            run_integrations=True,
        )


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
    # v2.0 V15: tech-stack (Wappalyzer-style) detection. Off by default;
    # opt-in via Crawl Settings.
    tech_stack_detection: bool = False
    # v2.0 H4: audit profile gating extra HTTP/render/integrations. Defaults to
    # DEEP here so every existing caller keeps today's full coverage (PR-12 ships
    # the mechanism, behaviour-neutral). PR-13 flips the site-crawl default to
    # STANDARD via Crawl Settings; single-page audits stay DEEP.
    profile: AuditProfile = AuditProfile.DEEP

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
            tech_stack_detection=False,
            profile=AuditProfile.DEEP,
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
        tech_stack_detection: bool | None = None,
        profile: AuditProfile | str | None = None,
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
            tech_stack_detection=bool(tech_stack_detection),
            profile=base.profile if profile is None else AuditProfile.from_value(profile),
        )


def auto_suggest_profile(url_count: int, selected: AuditProfile) -> AuditProfile:
    """Suggest LIGHTWEIGHT for a large crawl left on the STANDARD default (H4);
    an explicit LIGHTWEIGHT or DEEP choice is always honoured unchanged."""
    if selected is AuditProfile.STANDARD and url_count > _AUTO_LIGHTWEIGHT_THRESHOLD:
        return AuditProfile.LIGHTWEIGHT
    return selected


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


__all__ = [
    "AuditProfile",
    "CrawlOptions",
    "DEFAULT_USER_AGENT",
    "ProfilePolicy",
    "auto_suggest_profile",
    "parse_header_lines",
]
