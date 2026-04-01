from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


def _tokens(meta_robots: str) -> set[str]:
    return {token for token in re.split(r"[\s,]+", (meta_robots or "").lower()) if token}


def _path_match(path: str, rule: str) -> bool:
    normalized = (rule or "").strip()
    if not normalized:
        return False
    rule_path = urlparse(normalized).path or normalized
    return path.startswith(rule_path)


def _robots_allowed(page_url: str, robots_map: Mapping[str, Iterable[tuple[str, str]]]) -> bool:
    path = urlparse(page_url).path or "/"
    directives = robots_map.get("*", [])
    matches: list[tuple[int, bool]] = []
    for verb, rule in directives:
        if not _path_match(path, rule):
            continue
        rule_path = urlparse(rule).path or rule
        matches.append((len(rule_path), str(verb).strip().lower() == "allow"))
    if not matches:
        return True
    best_length = max(length for length, _ in matches)
    best = [allowed for length, allowed in matches if length == best_length]
    return any(best)


def _index_directive(meta_robots: str) -> str:
    directives = _tokens(meta_robots)
    if {"none", "noindex"} & directives:
        return "Noindex"
    return "Index"


def _follow_directive(meta_robots: str) -> str:
    directives = _tokens(meta_robots)
    if {"none", "nofollow"} & directives:
        return "Nofollow"
    return "Follow"


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _is_good_canonical_status(value: str) -> bool:
    code = _to_int(value)
    return code is not None and 200 <= code < 400


@dataclass(frozen=True, slots=True)
class _IndexabilityInputs:
    final_status: str
    hops: int
    crawl_allowed: bool
    index_directive: str
    canonical_url: str
    canonical_self: bool
    canonical_status: str
    multiple_canonicals: bool


def _verdict(inputs: _IndexabilityInputs) -> str:
    status_code = _to_int(inputs.final_status)
    if status_code is None or not 200 <= status_code < 300:
        return "Not indexable"
    if not inputs.crawl_allowed:
        return "Blocked by robots.txt"
    if inputs.index_directive == "Noindex":
        return "Noindex"
    if inputs.hops > 0:
        return "Redirected"
    if inputs.canonical_url and not inputs.canonical_self:
        return "Canonicalized elsewhere"
    if inputs.multiple_canonicals:
        return "Indexable with warnings"
    if inputs.canonical_url and not _is_good_canonical_status(inputs.canonical_status):
        return "Indexable with warnings"
    return "Indexable"


def build_indexability_rows(
    redirect: Mapping[str, Any],
    canonical: Mapping[str, Any],
    meta_robots: str,
    robots_map: Mapping[str, Iterable[tuple[str, str]]],
) -> list[list[str]]:
    chain_raw = redirect.get("chain", [])
    chain = [str(item).strip() for item in chain_raw] if isinstance(chain_raw, list) else []
    chain = [item for item in chain if item]
    requested_url = chain[0] if chain else ""
    final_url = chain[-1] if chain else requested_url
    final_status = str(redirect.get("final_status", "") or "")
    hops = _to_int(redirect.get("hops", 0)) or 0
    crawl_allowed = _robots_allowed(final_url or requested_url, robots_map)
    index_directive = _index_directive(meta_robots)
    follow_directive = _follow_directive(meta_robots)
    canonical_url = str(canonical.get("target", "") or "")
    canonical_self = bool(canonical.get("self"))
    canonical_status = str(canonical.get("status", "") or "")
    multiple_canonicals = bool(canonical.get("multiple"))
    verdict = _verdict(
        _IndexabilityInputs(
            final_status=final_status,
            hops=hops,
            crawl_allowed=crawl_allowed,
            index_directive=index_directive,
            canonical_url=canonical_url,
            canonical_self=canonical_self,
            canonical_status=canonical_status,
            multiple_canonicals=multiple_canonicals,
        )
    )
    return [
        ["Requested URL", requested_url or "-"],
        ["Final URL", final_url or "-"],
        ["Final status", final_status or "-"],
        ["Redirect hops", str(hops)],
        ["Crawl allowed by robots.txt", "Yes" if crawl_allowed else "No"],
        ["Meta / X-Robots-Tag", meta_robots or "-"],
        ["Index directive", index_directive],
        ["Follow directive", follow_directive],
        ["Canonical URL", canonical_url or "-"],
        ["Canonical self-reference", "Yes" if canonical_self else "No"],
        ["Canonical status", canonical_status or "-"],
        ["Multiple canonicals", "Yes" if multiple_canonicals else "No"],
        ["Overall verdict", verdict],
    ]


__all__ = ["build_indexability_rows"]
