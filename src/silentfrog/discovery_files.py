"""Discovery files used by AI engines and standard crawlers.

Probes the three "AI discovery" files (llms.txt, llms-full.txt,
.well-known/ai.json) plus the standard sitemap.xml. All four feed
positive INFO signals into the AI Visibility check list: absent =>
"info" (mapped to "good"), present => "good". Per Google's AI
Optimization Guide, none of these are required for Google AI surfaces,
so warnings/criticals are never emitted from this module.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp import ClientTimeout

from .crawl_http import _headers_from_options
from .crawl_options import CrawlOptions
from .crawl_types import AiVisibilityCheck

_BODY_EXCERPT_LIMIT = 400
_DEFAULT_TIMEOUT = 8


@dataclass(frozen=True)
class DiscoveryEntry:
    """One discovery file: where we looked, what came back."""

    url: str
    status: int
    present: bool
    body_excerpt: str
    parsed: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""  # "fetch", "robots-sitemap", "root-sitemap"


def _empty_entry(url: str = "") -> DiscoveryEntry:
    return DiscoveryEntry(url=url, status=0, present=False, body_excerpt="", parsed={}, source="")


@dataclass(frozen=True)
class DiscoveryPayload:
    llms_txt: DiscoveryEntry = field(default_factory=_empty_entry)
    llms_full_txt: DiscoveryEntry = field(default_factory=_empty_entry)
    well_known_ai_json: DiscoveryEntry = field(default_factory=_empty_entry)
    sitemap: DiscoveryEntry = field(default_factory=_empty_entry)

    @classmethod
    def empty(cls) -> DiscoveryPayload:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "llms_txt": _entry_to_dict(self.llms_txt),
            "llms_full_txt": _entry_to_dict(self.llms_full_txt),
            "well_known_ai_json": _entry_to_dict(self.well_known_ai_json),
            "sitemap": _entry_to_dict(self.sitemap),
        }

    @classmethod
    def from_raw(cls, value: Any) -> DiscoveryPayload:
        if not isinstance(value, Mapping):
            return cls.empty()
        return cls(
            llms_txt=_entry_from_raw(value.get("llms_txt")),
            llms_full_txt=_entry_from_raw(value.get("llms_full_txt")),
            well_known_ai_json=_entry_from_raw(value.get("well_known_ai_json")),
            sitemap=_entry_from_raw(value.get("sitemap")),
        )


def _entry_to_dict(entry: DiscoveryEntry) -> dict[str, Any]:
    return {
        "url": entry.url,
        "status": entry.status,
        "present": entry.present,
        "body_excerpt": entry.body_excerpt,
        "parsed": dict(entry.parsed),
        "source": entry.source,
    }


def _entry_from_raw(value: Any) -> DiscoveryEntry:
    if not isinstance(value, Mapping):
        return _empty_entry()
    parsed = value.get("parsed")
    return DiscoveryEntry(
        url=str(value.get("url", "")),
        status=int(value.get("status", 0) or 0),
        present=bool(value.get("present", False)),
        body_excerpt=str(value.get("body_excerpt", "")),
        parsed=dict(parsed) if isinstance(parsed, Mapping) else {},
        source=str(value.get("source", "")),
    )


def _site_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def _discovery_urls(site_root: str) -> dict[str, str]:
    return {
        "llms_txt": urljoin(site_root, "/llms.txt"),
        "llms_full_txt": urljoin(site_root, "/llms-full.txt"),
        "well_known_ai_json": urljoin(site_root, "/.well-known/ai.json"),
    }


def _sitemap_urls_from_robots(robots_map: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for directives in robots_map.values():
        if not isinstance(directives, (list, tuple)):
            continue
        for pair in directives:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            key, value = str(pair[0]).strip().lower(), str(pair[1]).strip()
            if key == "sitemap" and value:
                found.append(value)
    # dedupe preserving order
    return list(dict.fromkeys(found))


async def _probe(
    session: aiohttp.ClientSession,
    url: str,
    timeout: int,
    parser: str,
) -> DiscoveryEntry:
    if not url:
        return _empty_entry()
    try:
        async with session.get(url, timeout=ClientTimeout(total=timeout), allow_redirects=True) as response:
            status = int(response.status)
            text = await response.text("utf-8", errors="ignore")
    except Exception:
        return DiscoveryEntry(url=url, status=0, present=False, body_excerpt="", parsed={}, source="fetch")
    present = 200 <= status < 300 and bool(text.strip())
    excerpt = text.strip()[:_BODY_EXCERPT_LIMIT]
    parsed = _parse_body(text, parser) if present else {}
    return DiscoveryEntry(url=url, status=status, present=present, body_excerpt=excerpt, parsed=parsed, source="fetch")


def _parse_body(text: str, parser: str) -> Mapping[str, Any]:
    if parser == "json":
        try:
            value = json.loads(text)
        except Exception:
            return {}
        return value if isinstance(value, Mapping) else {}
    if parser == "llms-txt":
        return _parse_llms_txt(text)
    return {}


def _parse_llms_txt(text: str) -> Mapping[str, Any]:
    """Light-touch llms.txt parser: pulls the title and headings.

    The current llms.txt spec is an unofficial Markdown convention.
    We do not attempt full parsing — only enough to confirm the file
    is genuine content and not an HTML 404 page returned with 200.
    """
    title = ""
    headings: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            continue
        if stripped.startswith("## "):
            headings.append(stripped[3:].strip())
    return {"title": title, "headings": headings[:10]}


async def fetch_discovery_files(
    base_url: str,
    robots_map: Mapping[str, Any] | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    crawl_options: CrawlOptions | None = None,
) -> DiscoveryPayload:
    """Probe the four discovery files in parallel.

    Returns an empty payload when ``base_url`` is unparseable; never
    raises. All four checks treat absence as INFO (positive when present,
    neutral when missing) — see §1.5 of docs/geo_roadmap.md.
    """
    site_root = _site_root(base_url)
    if not site_root:
        return DiscoveryPayload.empty()

    urls = _discovery_urls(site_root)
    headers = _headers_from_options(crawl_options or CrawlOptions.default())
    sitemap_candidates = _sitemap_urls_from_robots(robots_map or {})
    sitemap_target, sitemap_source = _resolve_sitemap_target(site_root, sitemap_candidates)

    async with aiohttp.ClientSession(headers=headers) as session:
        llms, llms_full, well_known, sitemap_entry = await asyncio.gather(
            _probe(session, urls["llms_txt"], timeout, parser="llms-txt"),
            _probe(session, urls["llms_full_txt"], timeout, parser="llms-txt"),
            _probe(session, urls["well_known_ai_json"], timeout, parser="json"),
            _sitemap_entry(session, sitemap_target, sitemap_source, sitemap_candidates, timeout),
        )

    return DiscoveryPayload(
        llms_txt=llms,
        llms_full_txt=llms_full,
        well_known_ai_json=well_known,
        sitemap=sitemap_entry,
    )


def _resolve_sitemap_target(site_root: str, candidates: list[str]) -> tuple[str, str]:
    """Pick the URL to probe and remember where the hint came from."""
    if candidates:
        return candidates[0], "robots-sitemap"
    return urljoin(site_root, "/sitemap.xml"), "root-sitemap"


async def _sitemap_entry(
    session: aiohttp.ClientSession,
    target_url: str,
    source: str,
    robots_candidates: list[str],
    timeout: int,
) -> DiscoveryEntry:
    entry = await _probe(session, target_url, timeout, parser="")
    parsed = {"robots_sitemap_count": len(robots_candidates), "robots_sitemap_urls": robots_candidates}
    return DiscoveryEntry(
        url=entry.url,
        status=entry.status,
        present=entry.present,
        body_excerpt=entry.body_excerpt,
        parsed=parsed,
        source=source,
    )


_CHECK_MESSAGES = {
    "access_llms_txt": (
        "llms.txt declares AI crawler entry points",
        "Publish an llms.txt with site policies and entry points; useful for Anthropic, "
        "Perplexity, and OpenAI surfaces. Not required by Google.",
    ),
    "access_llms_full_txt": (
        "llms-full.txt extends llms.txt with the structured content map",
        "Publish llms-full.txt as the long-form companion to llms.txt; useful for non-Google AI engines. "
        "Not required by Google.",
    ),
    "access_well_known_ai_json": (
        ".well-known/ai.json publishes a machine-readable AI access policy",
        "Publish /.well-known/ai.json if you want to expose an explicit AI access policy. Not required by Google.",
    ),
    "access_sitemap": (
        "A sitemap.xml is discoverable",
        "Publish a sitemap.xml and reference it from robots.txt for standard crawlability hygiene.",
    ),
}


def _info_or_good(present: bool) -> str:
    return "good" if present else "info"


def _llms_detail(entry: DiscoveryEntry) -> str:
    if not entry.present:
        return f"URL: {entry.url or '-'}; Status: {entry.status}; Present: No."
    title = entry.parsed.get("title") if isinstance(entry.parsed, Mapping) else ""
    return f"URL: {entry.url}; Status: {entry.status}; Present: Yes; Title: {title or '-'}."


def _ai_json_detail(entry: DiscoveryEntry) -> str:
    if not entry.present:
        return f"URL: {entry.url or '-'}; Status: {entry.status}; Present: No."
    keys = sorted(entry.parsed.keys()) if isinstance(entry.parsed, Mapping) else []
    keys_preview = ", ".join(keys[:6]) or "-"
    return f"URL: {entry.url}; Status: {entry.status}; Present: Yes; Top-level keys: {keys_preview}."


def _sitemap_detail(entry: DiscoveryEntry) -> str:
    parsed = entry.parsed if isinstance(entry.parsed, Mapping) else {}
    robots_count = int(parsed.get("robots_sitemap_count", 0) or 0)
    source_label = "robots.txt" if entry.source == "robots-sitemap" else "site root"
    return (
        f"Source: {source_label}; Robots sitemap directives: {robots_count}; "
        f"URL: {entry.url or '-'}; Status: {entry.status}; Present: {'Yes' if entry.present else 'No'}."
    )


def _check_for(key: str, entry: DiscoveryEntry, detail: str) -> AiVisibilityCheck:
    title, recommendation = _CHECK_MESSAGES[key]
    return AiVisibilityCheck(
        area="Access",
        check=title,
        status=_info_or_good(entry.present),
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def build_discovery_checks(payload: DiscoveryPayload) -> list[AiVisibilityCheck]:
    """Build the four AI Visibility rows for the discovery files."""
    return [
        _check_for("access_llms_txt", payload.llms_txt, _llms_detail(payload.llms_txt)),
        _check_for("access_llms_full_txt", payload.llms_full_txt, _llms_detail(payload.llms_full_txt)),
        _check_for(
            "access_well_known_ai_json",
            payload.well_known_ai_json,
            _ai_json_detail(payload.well_known_ai_json),
        ),
        _check_for("access_sitemap", payload.sitemap, _sitemap_detail(payload.sitemap)),
    ]


# v2.0 V11 — per-agent .well-known/ai.json policy parsing.
_ALLOW_WORDS = {"allow", "allowed", "yes", "true", "permit"}
_DENY_WORDS = {"disallow", "deny", "denied", "blocked", "no", "false", "forbid"}


def _normalize_agent_policy(value: Any) -> str:
    if isinstance(value, bool):
        return "allow" if value else "disallow"
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _ALLOW_WORDS:
            return "allow"
        if word in _DENY_WORDS:
            return "disallow"
        return "unknown"
    if isinstance(value, Mapping):
        for key in ("policy", "access", "default"):
            if key in value:
                return _normalize_agent_policy(value[key])
        if value.get("disallow"):
            return "disallow"
        if value.get("allow"):
            return "allow"
    return "unknown"


def ai_json_agent_policies(discovery: Mapping[str, Any] | None) -> dict[str, str]:
    """Per-agent policies declared in .well-known/ai.json.

    Returns ``{bot_token_lowercased: "allow" | "disallow"}`` for the
    agents the file names explicitly. Tokens with an unknown/unparseable
    policy are omitted. ``discovery`` is the payload's ``discovery`` dict
    (``DiscoveryPayload.to_dict()``). Never raises.
    """
    if not isinstance(discovery, Mapping):
        return {}
    entry = discovery.get("well_known_ai_json")
    parsed = entry.get("parsed") if isinstance(entry, Mapping) else None
    agents = parsed.get("agents") if isinstance(parsed, Mapping) else None
    if not isinstance(agents, Mapping):
        return {}
    policies: dict[str, str] = {}
    for token, raw_policy in agents.items():
        policy = _normalize_agent_policy(raw_policy)
        if policy in {"allow", "disallow"}:
            policies[str(token).strip().lower()] = policy
    return policies


__all__ = [
    "DiscoveryEntry",
    "DiscoveryPayload",
    "ai_json_agent_policies",
    "build_discovery_checks",
    "fetch_discovery_files",
]
