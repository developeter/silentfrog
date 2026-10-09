from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

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
    # v2.0 V10: per-bot SSR rendering — renders the page once per AI-bot
    # user-agent through the shared render pool and diffs each DOM. Off by
    # default; needs Playwright and a rendering profile (DEEP).
    bot_render: bool = False
    # v3 (M8): follow links discovered in the JS-rendered DOM, not just the
    # raw HTML — lets the spider crawl SPA/React/Vue route graphs. Off by
    # default; needs Playwright and a rendering profile (DEEP).
    render_js: bool = False
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
    # v2.0 V20: local topic-embedding coherence scoring. Off by default —
    # needs the `silentfrog[embeddings]` extra; inference is local-only but
    # heavy, so it never runs unopted.
    topic_embeddings: bool = False
    # v2.0 H4: audit profile gating extra HTTP/render/integrations. Defaults to
    # DEEP here so every existing caller keeps today's full coverage (PR-12 ships
    # the mechanism, behaviour-neutral). PR-13 flips the site-crawl default to
    # STANDARD via Crawl Settings; single-page audits stay DEEP.
    profile: AuditProfile = AuditProfile.DEEP
    # v2.0 H7 (PR-16): opt out of TLS certificate verification for this crawl.
    # Off by default — crawler fetches verify against the certifi CA bundle at
    # SECLEVEL>=2. Enable only to audit trusted self-signed / intranet hosts;
    # the transport seam logs a visible warning while it is active.
    allow_insecure_tls: bool = False
    # v2.0 H7 (PR-17): opt out of SSRF protection for this crawl. Off by default
    # — the transport seam rejects fetches that resolve to loopback / intranet /
    # link-local / reserved hosts. Enable only to audit trusted intranet hosts;
    # the seam logs a visible warning while it is active.
    allow_private_network: bool = False
    # v3 (G4 Stage 1): run the vendored axe-core WCAG engine against the
    # rendered page. Off by default; needs Playwright and a rendering
    # profile (DEEP), same gating shape as ``bot_render``.
    accessibility_audit: bool = False

    @classmethod
    def default(cls) -> CrawlOptions:
        return cls(
            gentle_mode=False,
            max_concurrent_per_host=4,
            respect_crawl_delay=False,
            user_agent=DEFAULT_USER_AGENT,
            extra_headers={},
            ssr_parity_check=False,
            bot_render=False,
            render_js=False,
            use_stealth=False,
            custom_extraction=CustomExtractionConfig(),
            tech_stack_detection=False,
            topic_embeddings=False,
            profile=AuditProfile.DEEP,
            allow_insecure_tls=False,
            allow_private_network=False,
            accessibility_audit=False,
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
        bot_render: bool | None = None,
        render_js: bool | None = None,
        use_stealth: bool | None = None,
        custom_rules_text: str = "",
        tech_stack_detection: bool | None = None,
        topic_embeddings: bool | None = None,
        profile: AuditProfile | str | None = None,
        allow_insecure_tls: bool | None = None,
        allow_private_network: bool | None = None,
        accessibility_audit: bool | None = None,
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
            bot_render=bool(bot_render),
            render_js=bool(render_js),
            use_stealth=bool(use_stealth),
            custom_extraction=parse_rules_text(custom_rules_text or ""),
            tech_stack_detection=bool(tech_stack_detection),
            topic_embeddings=bool(topic_embeddings),
            profile=base.profile if profile is None else AuditProfile.from_value(profile),
            allow_insecure_tls=bool(allow_insecure_tls),
            allow_private_network=bool(allow_private_network),
            accessibility_audit=bool(accessibility_audit),
        )


def auto_suggest_profile(url_count: int, selected: AuditProfile) -> AuditProfile:
    """Suggest LIGHTWEIGHT for a large crawl left on the STANDARD default (H4);
    an explicit LIGHTWEIGHT or DEEP choice is always honoured unchanged."""
    if selected is AuditProfile.STANDARD and url_count > _AUTO_LIGHTWEIGHT_THRESHOLD:
        return AuditProfile.LIGHTWEIGHT
    return selected


def parse_header_lines(text: str) -> tuple[dict[str, str], list[int]]:
    """Parse ``Key: Value`` lines. Returns the headers and the 1-based numbers
    of the non-blank lines that were ignored because they are not ``Key: Value``."""
    headers: dict[str, str] = {}
    bad_lines: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            bad_lines.append(number)
            continue
        headers[key.strip()] = value.strip()
    return headers, bad_lines


# --- Persisted opt-in ticks (QSettings seam lives in crawl_prefs.py) ---------
#
# Only the opt-in feature choices survive a restart. Security posture
# (allow_insecure_tls / allow_private_network) and credentials (extra_headers,
# including Cookie) are deliberately NOT part of the stored shape: they must be
# re-entered per session so a stale override or token can never ride along.

# Crawl speed (gentle mode / per-host cap) is deliberately NOT stored: the two
# windows have different defaults (Site Crawl is gentle), so sharing it would let
# an untouched Single Page "OK" silently remove Site Crawl's politeness.
_OPT_IN_BOOL_FIELDS: tuple[str, ...] = (
    "ssr_parity_check",
    "bot_render",
    "render_js",
    "accessibility_audit",
    "tech_stack_detection",
    "topic_embeddings",
    "use_stealth",
)
# Flag -> the optional extra it needs. A stored tick for a flag whose extra is
# no longer installed loads as False (the Settings checkbox would be disabled).
_FLAG_EXTRA: dict[str, str] = {
    "ssr_parity_check": "playwright",
    "bot_render": "playwright",
    "render_js": "playwright",
    "accessibility_audit": "playwright",
    "topic_embeddings": "embeddings",
    "use_stealth": "stealth",
}
_CUSTOM_RULES_KEY = "custom_extraction"


def opt_in_to_dict(opts: CrawlOptions) -> dict[str, Any]:
    """JSON-native snapshot of the opt-in ticks (never TLS/SSRF overrides or
    headers/cookies — see the module note above)."""
    data: dict[str, Any] = {name: bool(getattr(opts, name)) for name in _OPT_IN_BOOL_FIELDS}
    data[_CUSTOM_RULES_KEY] = opts.custom_extraction.to_dict()
    return data


def _stored_flags(data: Mapping[str, Any], base: CrawlOptions, installed: Collection[str]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for name in _OPT_IN_BOOL_FIELDS:
        stored = data.get(name)
        value = stored if isinstance(stored, bool) else getattr(base, name)
        needed = _FLAG_EXTRA.get(name)
        changes[name] = bool(value) and (needed is None or needed in installed)
    return changes


def opt_in_from_dict(data: object, base: CrawlOptions, *, installed: Collection[str]) -> CrawlOptions:
    """Apply stored opt-in ticks onto ``base``. Anything missing, mistyped or
    unusable (corrupt store, extra not installed) keeps ``base``'s value, so an
    empty store reproduces today's defaults exactly. ``installed`` names the
    optional extras importable right now: ``playwright`` / ``embeddings`` /
    ``stealth``. Credentials, TLS/SSRF overrides and the profile are never read
    from the store."""
    if not isinstance(data, Mapping):
        return base
    changes = _stored_flags(data, base, installed)
    rules = data.get(_CUSTOM_RULES_KEY)
    if isinstance(rules, (Mapping, list)):
        changes[_CUSTOM_RULES_KEY] = CustomExtractionConfig.from_raw(rules)
    return replace(base, **changes)


# --- "What will actually run" summary -----------------------------------------

# (options attribute, label template, needs a rendering profile). ``{n}`` is the
# count for list-like attributes; booleans contribute 1 when ticked.
_SUMMARY_ROWS: tuple[tuple[str, str, bool], ...] = (
    ("ssr_parity_check", "SSR parity", True),
    ("bot_render", "Per-bot SSR", True),
    ("render_js", "JS links", True),
    ("accessibility_audit", "Accessibility", True),
    ("tech_stack_detection", "Tech stack", False),
    ("custom_extraction", "Custom rules ({n})", False),
    ("topic_embeddings", "Embeddings", False),
    ("use_stealth", "Stealth", False),
    ("allow_insecure_tls", "Insecure TLS", False),
    ("allow_private_network", "Private network", False),
    ("extra_headers", "{n} custom header(s)", False),
)
_SKIPPED_SUFFIX = " (skipped: needs Deep)"


def _active_count(value: object) -> int:
    if isinstance(value, CustomExtractionConfig):
        return len(value.rules)
    if isinstance(value, bool):
        return int(value)
    return len(value) if isinstance(value, Mapping) else 0


def active_checks_summary(opts: CrawlOptions) -> list[str]:
    """Human labels for every opt-in check / posture override that is ticked.
    Render-dependent checks are suffixed when the profile will not render them,
    so the label never claims a check that the profile silently drops."""
    renders = ProfilePolicy.for_profile(opts.profile).render
    labels: list[str] = []
    for attr, template, needs_render in _SUMMARY_ROWS:
        count = _active_count(getattr(opts, attr))
        if not count:
            continue
        suffix = _SKIPPED_SUFFIX if needs_render and not renders else ""
        labels.append(template.format(n=count) + suffix)
    return labels


def active_checks_tooltip(opts: CrawlOptions) -> str:
    """Tooltip form of the summary: one active check per line."""
    checks = active_checks_summary(opts)
    if not checks:
        return "No optional checks ticked. Open Crawl settings... to enable some."
    bullets = "\n".join(f"- {label}" for label in checks)
    return f"Active checks:\n{bullets}"


def crawl_mode_label(opts: CrawlOptions) -> str:
    """Pacing description; ``max N/host`` only matters while gentle mode is on."""
    if opts.gentle_mode:
        return f"Gentle crawl, max {opts.max_concurrent_per_host}/host"
    return "Custom crawl" if opts.extra_headers else "Standard crawl"


def crawl_settings_summary(opts: CrawlOptions, *, show_profile: bool = True) -> str:
    """One line: pacing, (optional) profile, then the active checks."""
    parts = [crawl_mode_label(opts)]
    if show_profile:
        parts.append(f"{opts.profile.value.capitalize()} profile")
    checks = active_checks_summary(opts)
    parts.append(", ".join(checks) if checks else "no optional checks")
    return " · ".join(parts)


__all__ = [
    "AuditProfile",
    "CrawlOptions",
    "DEFAULT_USER_AGENT",
    "ProfilePolicy",
    "active_checks_summary",
    "active_checks_tooltip",
    "auto_suggest_profile",
    "crawl_mode_label",
    "crawl_settings_summary",
    "opt_in_from_dict",
    "opt_in_to_dict",
    "parse_header_lines",
]
