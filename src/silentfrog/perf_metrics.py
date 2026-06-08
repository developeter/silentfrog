from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp  # type: ignore[import]  # aiohttp stubs missing
from aiohttp import ClientTimeout  # type: ignore[import]  # aiohttp stubs missing

from .perf_guides import PerformanceContext, open_source_hints

_RESOURCE_FETCH_LIMIT = 20
_RESOURCE_BYTES_TIMEOUT = 5
_RESOURCE_BODY_SAMPLE = 512_000
_RESOURCE_TYPE_ALIASES = {
    "css": "css",
    "font": "font",
    "image": "img",
    "img": "img",
    "js": "js",
    "script": "js",
    "style": "css",
    "stylesheet": "css",
}
_RESOURCE_BREAKDOWN_ORDER = ("html", "css", "js", "img", "font", "other")
_WARNING_PAGE_BYTES = 1_500_000
_CRITICAL_PAGE_BYTES = 2_000_000
_WARNING_JS_BYTES = 350_000
_CRITICAL_JS_BYTES = 700_000
_WARNING_CSS_BYTES = 120_000
_CRITICAL_CSS_BYTES = 200_000
_WARNING_IMAGE_BYTES = 600_000
_CRITICAL_IMAGE_BYTES = 1_500_000
_WARNING_REQUEST_COUNT = 25
_CRITICAL_REQUEST_COUNT = 50
_WARNING_THIRD_PARTY_BYTES = 250_000
_CRITICAL_THIRD_PARTY_BYTES = 600_000
_WARNING_THIRD_PARTY_COUNT = 5
_CRITICAL_THIRD_PARTY_COUNT = 12
_RESOURCE_WEIGHT_RULES = {
    "js": {
        "issue_key": "js_weight",
        "warning_threshold": _WARNING_JS_BYTES,
        "critical_threshold": _CRITICAL_JS_BYTES,
        "warning_message": "JavaScript payload is heavier than ideal.",
        "critical_message": "JavaScript payload is very heavy.",
        "warning_recommendation": "Review bundle size and defer non-critical scripts.",
        "critical_recommendation": "Reduce shipped JS, remove third-party bloat, and split non-critical logic.",
        "evidence_label": "Measured JavaScript weight is",
    },
    "css": {
        "issue_key": "css_weight",
        "warning_threshold": _WARNING_CSS_BYTES,
        "critical_threshold": _CRITICAL_CSS_BYTES,
        "warning_message": "CSS payload is heavier than ideal.",
        "critical_message": "CSS payload is very heavy.",
        "warning_recommendation": "Consolidate stylesheets and trim non-critical CSS.",
        "critical_recommendation": "Inline critical CSS and reduce stylesheet weight.",
        "evidence_label": "Measured CSS weight is",
    },
    "img": {
        "issue_key": "image_weight",
        "warning_threshold": _WARNING_IMAGE_BYTES,
        "critical_threshold": _CRITICAL_IMAGE_BYTES,
        "warning_message": "Image payload is heavier than ideal.",
        "critical_message": "Image payload is very heavy.",
        "warning_recommendation": "Compress large images and review responsive delivery.",
        "critical_recommendation": "Compress images, use next-gen formats, and reduce oversized assets.",
        "evidence_label": "Measured image weight is",
    },
}
_PERFORMANCE_SUMMARY_TOOLTIP = (
    "<b>Performance summary</b><br/>"
    "<b>Verdict</b>: overall SEO-facing performance risk derived from measured resource weight and issue severity.<br/>"
    "<b>Status</b>: final HTTP status of the analysed page.<br/>"
    "<b>TTFB</b>: time to first byte measured for the main document request.<br/>"
    "<b>Total</b>: total request time for the main document, not full browser rendering time.<br/>"
    "<b>Transfer</b>: measured HTML transfer size for the main document.<br/>"
    "<b>Page weight</b>: main document plus measured resource bytes discovered in the source.<br/>"
    "<b>Resources</b>: number of detected external resources and inline assets counted by the audit.<br/>"
    "<b>Third-party</b>: bytes served from hosts outside the page's main registrable domain.<br/>"
    "Best practice: keep the page lean, reduce third-party overhead, and treat large JS/image payloads as SEO risk."
)
_PERFORMANCE_RESOURCE_TOOLTIP = (
    "<b>Resource breakdown</b><br/>"
    "<b>Blocking JS</b>: synchronous scripts in source order that can delay rendering.<br/>"
    "<b>Async/Deferred JS</b>: scripts that are explicitly non-blocking in source.<br/>"
    "<b>CSS / JS / Images / Fonts</b>: measured or inferred bytes by resource type from the HTML source and follow-up fetches.<br/>"
    "Best practice: minimize render-blocking JavaScript, keep CSS lean, compress images, and avoid unnecessary font cost."
)
_PERFORMANCE_ISSUE_TOOLTIPS = {
    "page_weight": (
        "<b>Total page weight</b><br/>"
        "Flags when the combined document and resource payload is too heavy for a fast SEO-friendly page.<br/>"
        "Best practice: keep page weight comfortably below multi-megabyte ranges and avoid shipping unnecessary media."
    ),
    "blocking_js": (
        "<b>Blocking JavaScript</b><br/>"
        "Flags synchronous scripts that can delay rendering for users and crawlers.<br/>"
        "Best practice: defer or async non-critical scripts and reduce blocking JS bytes."
    ),
    "js_weight": (
        "<b>JavaScript payload</b><br/>"
        "Flags pages that ship too much JavaScript before the page becomes useful.<br/>"
        "Best practice: trim bundles, split non-critical code, and reduce third-party JS."
    ),
    "css_weight": (
        "<b>CSS payload</b><br/>"
        "Flags stylesheet weight that is likely too large for fast rendering.<br/>"
        "Best practice: inline critical CSS and keep the remaining stylesheets compact."
    ),
    "image_weight": (
        "<b>Image payload</b><br/>"
        "Flags image bytes that are likely too heavy for a single page.<br/>"
        "Best practice: compress images, use next-gen formats, and avoid oversized source files."
    ),
    "request_count": (
        "<b>Resource request count</b><br/>"
        "Flags pages that load too many individual assets.<br/>"
        "Best practice: reduce the number of requests where practical and remove low-value assets."
    ),
    "third_party_weight": (
        "<b>Third-party overhead</b><br/>"
        "Flags external dependencies that add weight or complexity to the page.<br/>"
        "Best practice: keep third-party tags limited to assets with clear business value."
    ),
}


@dataclass
class _PerformanceCollectionState:
    base_url: str
    resources: dict[str, dict[str, int]] = field(default_factory=dict)
    fetch_targets: dict[str, list[str]] = field(default_factory=dict)
    resource_entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    script_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    script_entry_map: dict[str, dict[str, Any]] = field(default_factory=dict)


def _normalize_resource_type(resource_type: str) -> str:
    return _RESOURCE_TYPE_ALIASES.get(resource_type.strip().lower(), "other")


def _host_root(raw_url: str) -> str:
    host = (urlparse(raw_url).hostname or "").strip().lower()
    if not host or host == "localhost":
        return host
    if host.replace(".", "").isdigit():
        return host
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2:
        return host
    return ".".join(labels[-2:])


def _is_third_party_resource(base_url: str, resource_url: str) -> bool:
    return bool(resource_url) and _host_root(base_url) != _host_root(resource_url)


def _build_resource_breakdown(transfer_size: int, resources: dict[str, dict[str, int]]) -> list[dict[str, int | str]]:
    html_entry = {"type": "html", "count": 1, "bytes": max(transfer_size, 0)}
    buckets = {
        key: {
            "type": key,
            "count": max(int(value.get("count", 0)), 0),
            "bytes": max(int(value.get("bytes", 0)), 0),
        }
        for key, value in resources.items()
    }
    return [
        html_entry,
        *(buckets.get(key, {"type": key, "count": 0, "bytes": 0}) for key in _RESOURCE_BREAKDOWN_ORDER[1:]),
    ]


def _build_performance_summary(
    base_url: str,
    transfer_size: int,
    resources: dict[str, dict[str, int]],
    resource_entries: dict[str, list[dict[str, Any]]],
) -> dict[str, int]:
    third_party_urls: dict[str, int] = {}
    for entries in resource_entries.values():
        for entry in entries:
            url = str(entry.get("url", "")).strip()
            if not url.startswith(("http://", "https://")):
                continue
            if not _is_third_party_resource(base_url, url):
                continue
            third_party_urls[url] = max(int(entry.get("bytes", 0) or 0), 0)

    total_resource_bytes = sum(max(int(info.get("bytes", 0)), 0) for info in resources.values())
    total_resource_count = sum(max(int(info.get("count", 0)), 0) for info in resources.values())
    return {
        "transfer_size": max(transfer_size, 0),
        "total_resource_bytes": total_resource_bytes,
        "total_page_bytes": max(transfer_size, 0) + total_resource_bytes,
        "total_resource_count": total_resource_count,
        "third_party_bytes": sum(third_party_urls.values()),
        "third_party_count": len(third_party_urls),
    }


def _build_performance_issues(
    resources: dict[str, dict[str, int]],
    script_stats: dict[str, dict[str, int]],
    summary: dict[str, int],
) -> list[dict[str, str]]:
    issue_builders = (
        _page_weight_issue(summary),
        _blocking_js_issue(script_stats),
        *(_resource_weight_issue(resource_key, resources) for resource_key in ("js", "css", "img")),
        _request_count_issue(summary),
        _third_party_issue(summary),
    )
    return [issue for issue in issue_builders if issue is not None]


def _issue(key: str, severity: str, message: str, evidence: str, recommendation: str) -> dict[str, str]:
    return {
        "key": key,
        "severity": severity,
        "message": message,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _threshold_severity(value: int, warning_threshold: int, critical_threshold: int) -> str | None:
    if value >= critical_threshold:
        return "critical"
    if value >= warning_threshold:
        return "warning"
    return None


def _page_weight_issue(summary: dict[str, int]) -> dict[str, str] | None:
    total_page_bytes = summary["total_page_bytes"]
    severity = _threshold_severity(total_page_bytes, _WARNING_PAGE_BYTES, _CRITICAL_PAGE_BYTES)
    if severity is None:
        return None
    messages = {
        "warning": (
            "Total page weight is above the recommended range.",
            "Trim heavy resources before they affect crawl efficiency and user load time.",
        ),
        "critical": (
            "Total page weight is very high.",
            "Reduce heavy assets, defer non-critical resources, and compress media.",
        ),
    }
    message, recommendation = messages[severity]
    return _issue(
        "page_weight",
        severity,
        message,
        f"Measured page weight is {_format_bytes(total_page_bytes)}.",
        recommendation,
    )


def _blocking_js_issue(script_stats: dict[str, dict[str, int]]) -> dict[str, str] | None:
    blocking_count = script_stats["blocking"]["count"]
    if blocking_count <= 0:
        return None
    blocking_bytes = script_stats["blocking"]["bytes"]
    severity = "critical" if blocking_bytes >= _WARNING_JS_BYTES else "warning"
    return _issue(
        "blocking_js",
        severity,
        "Blocking JavaScript was detected in the page source.",
        f"{blocking_count} blocking script(s), {_format_bytes(blocking_bytes)} total.",
        "Move non-critical scripts to defer/async and reduce blocking script weight.",
    )


def _resource_weight_issue(resource_key: str, resources: dict[str, dict[str, int]]) -> dict[str, str] | None:
    rule = _RESOURCE_WEIGHT_RULES[resource_key]
    resource_bytes = resources[resource_key]["bytes"]
    severity = _threshold_severity(resource_bytes, rule["warning_threshold"], rule["critical_threshold"])
    if severity is None:
        return None
    return _issue(
        str(rule["issue_key"]),
        severity,
        str(rule[f"{severity}_message"]),
        f"{rule['evidence_label']} {_format_bytes(resource_bytes)}.",
        str(rule[f"{severity}_recommendation"]),
    )


def _request_count_issue(summary: dict[str, int]) -> dict[str, str] | None:
    total_resources = summary["total_resource_count"]
    severity = _threshold_severity(total_resources, _WARNING_REQUEST_COUNT, _CRITICAL_REQUEST_COUNT)
    if severity is None:
        return None
    messages = {
        "warning": (
            "The page loads many resources.",
            "Review request count and consolidate static assets where practical.",
        ),
        "critical": (
            "The page loads a very high number of resources.",
            "Reduce request count by bundling or removing non-critical assets.",
        ),
    }
    message, recommendation = messages[severity]
    return _issue(
        "request_count",
        severity,
        message,
        f"{total_resources} resources were detected.",
        recommendation,
    )


def _third_party_issue(summary: dict[str, int]) -> dict[str, str] | None:
    third_party_bytes = summary["third_party_bytes"]
    third_party_count = summary["third_party_count"]
    critical = third_party_bytes >= _CRITICAL_THIRD_PARTY_BYTES or third_party_count >= _CRITICAL_THIRD_PARTY_COUNT
    if critical:
        return _issue(
            "third_party_weight",
            "critical",
            "Third-party resources contribute significant weight.",
            f"{third_party_count} third-party resource(s), {_format_bytes(third_party_bytes)} total.",
            "Audit off-domain dependencies and remove low-value third-party assets.",
        )
    warning = third_party_bytes >= _WARNING_THIRD_PARTY_BYTES or third_party_count >= _WARNING_THIRD_PARTY_COUNT
    if warning:
        return _issue(
            "third_party_weight",
            "warning",
            "Third-party resources are adding noticeable overhead.",
            f"{third_party_count} third-party resource(s), {_format_bytes(third_party_bytes)} total.",
            "Reduce third-party dependencies and lazy-load what is not critical.",
        )
    return None


def _build_performance_summary_metadata(summary: dict[str, int], issues: list[dict[str, str]]) -> dict[str, int | str]:
    counts = {
        "critical": sum(1 for issue in issues if issue["severity"] == "critical"),
        "warning": sum(1 for issue in issues if issue["severity"] == "warning"),
        "info": sum(1 for issue in issues if issue["severity"] == "info"),
    }
    verdict = "Good"
    if counts["critical"] > 0:
        verdict = "High performance risk"
    elif counts["warning"] > 0:
        verdict = "Needs work"
    return {
        **summary,
        "critical_issue_count": counts["critical"],
        "warning_issue_count": counts["warning"],
        "info_issue_count": counts["info"],
        "verdict": verdict,
    }


def performance_summary_tooltip() -> str:
    return _PERFORMANCE_SUMMARY_TOOLTIP


def performance_resource_tooltip() -> str:
    return _PERFORMANCE_RESOURCE_TOOLTIP


def performance_issue_tooltip(issue_key: str) -> str:
    return _PERFORMANCE_ISSUE_TOOLTIPS.get(issue_key.strip().lower(), "")


def _empty_resources() -> dict[str, dict[str, int]]:
    return {
        "css": {"count": 0, "bytes": 0},
        "js": {"count": 0, "bytes": 0},
        "img": {"count": 0, "bytes": 0},
        "font": {"count": 0, "bytes": 0},
        "other": {"count": 0, "bytes": 0},
    }


def _new_collection_state(base_url: str) -> _PerformanceCollectionState:
    resources = _empty_resources()
    return _PerformanceCollectionState(
        base_url=base_url,
        resources=resources,
        fetch_targets={key: [] for key in resources},
        resource_entries={key: [] for key in resources},
        script_stats={
            "blocking": {"count": 0, "bytes": 0},
            "async": {"count": 0, "bytes": 0},
        },
        script_entry_map={},
    )


def _register_resource(
    state: _PerformanceCollectionState,
    resource_type: str,
    raw_url: str,
    *,
    blocking: bool | None = None,
    label: str | None = None,
    preset_bytes: int | None = None,
) -> None:
    bucket = _normalize_resource_type(resource_type)
    url = raw_url.strip()
    if not url or bucket not in state.resources:
        return
    state.resources[bucket]["count"] += 1
    if url.startswith("data:"):
        size_val = _data_uri_size(url)
        state.resources[bucket]["bytes"] += size_val
        entry = {
            "type": bucket.upper(),
            "url": label or url[:80],
            "bytes": size_val,
            "blocking": bool(blocking),
        }
        state.resource_entries[bucket].append(entry)
        if bucket == "js":
            kind = "blocking" if blocking else "async"
            state.script_stats[kind]["count"] += 1
            state.script_stats[kind]["bytes"] += size_val
        return
    absolute = urljoin(state.base_url, url)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return
    normalized = urlunparse(parsed)
    state.fetch_targets[bucket].append(normalized)
    entry = {
        "type": bucket.upper(),
        "url": normalized,
        "bytes": max(preset_bytes or 0, 0),
        "blocking": bool(blocking),
    }
    state.resource_entries[bucket].append(entry)
    if bucket != "js":
        return
    kind = "blocking" if blocking else "async"
    state.script_stats[kind]["count"] += 1
    state.script_entry_map[normalized] = {"kind": kind, "entry": entry}


def _register_inline_script(state: _PerformanceCollectionState, text: str) -> None:
    if not text:
        return
    inline_bytes = len(text.encode("utf-8"))
    state.resources["js"]["count"] += 1
    state.resources["js"]["bytes"] += inline_bytes
    state.script_stats["blocking"]["count"] += 1
    state.script_stats["blocking"]["bytes"] += inline_bytes
    state.resource_entries["js"].append(
        {"type": "JS", "url": "(inline script)", "bytes": inline_bytes, "blocking": True}
    )


def _collect_link_resources(state: _PerformanceCollectionState, soup: Any) -> None:
    for link in soup.find_all("link"):
        rel_tokens = {str(token).lower() for token in (link.get("rel") or [])}
        href = str(link.get("href") or "")
        if not href:
            continue
        if "stylesheet" in rel_tokens or str(link.get("type") or "").lower() == "text/css":
            _register_resource(state, "css", href)
            continue
        if "preload" in rel_tokens:
            target = _normalize_resource_type(str(link.get("as") or ""))
            if target in state.resources:
                _register_resource(state, target, href)
                continue
        if any("font" in token for token in rel_tokens):
            _register_resource(state, "font", href)


def _collect_script_resources(state: _PerformanceCollectionState, soup: Any) -> None:
    for script in soup.find_all("script"):
        src = str(script.get("src") or "")
        if src:
            _register_resource(
                state,
                "js",
                src,
                blocking=not (script.has_attr("async") or script.has_attr("defer")),
            )
            continue
        _register_inline_script(state, script.string or "")


def _collect_image_resources(state: _PerformanceCollectionState, soup: Any) -> None:
    for img in soup.find_all("img"):
        src = str(img.get("src") or "")
        if src:
            _register_resource(state, "img", src)


def _merge_remote_resource_sizes(
    state: _PerformanceCollectionState,
    remote_sizes: dict[str, int],
    url_sizes: dict[str, dict[str, int]],
) -> None:
    for resource_type, size in remote_sizes.items():
        state.resources[resource_type]["bytes"] += size
        per_type = url_sizes.get(resource_type, {})
        for entry in state.resource_entries[resource_type]:
            url = entry.get("url", "")
            if not url:
                continue
            entry_size = per_type.get(url)
            if entry_size is None:
                continue
            entry["bytes"] = entry_size
            if resource_type != "js":
                continue
            script_info = state.script_entry_map.get(url)
            if script_info:
                state.script_stats[script_info["kind"]]["bytes"] += entry_size


def _top_offenders(resource_entries: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    offenders: list[dict[str, Any]] = []
    for entries in resource_entries.values():
        offenders.extend(entries)
    offenders.sort(key=lambda item: item.get("bytes", 0), reverse=True)
    return offenders[:10]


def _add_opportunity(opportunities: list[str], details: list[dict[str, str]], message: str, severity: str) -> None:
    text = message.strip()
    if not text:
        return
    opportunities.append(text)
    details.append({"message": text, "severity": severity})


def _collect_opportunities(
    transfer_size: int,
    response: Any,
    resources: dict[str, dict[str, int]],
    script_stats: dict[str, dict[str, int]],
) -> tuple[list[str], list[dict[str, str]]]:
    opportunities: list[str] = []
    opportunity_details: list[dict[str, str]] = []
    total_resource_bytes = sum(info.get("bytes", 0) for info in resources.values())
    total_page_weight = transfer_size + total_resource_bytes

    if transfer_size > 800_000:
        _add_opportunity(
            opportunities,
            opportunity_details,
            "Main document size exceeds 800 KB; consider compression or trimming inline data.",
            "critical",
        )
    if total_page_weight > 2_000_000:
        _add_opportunity(
            opportunities,
            opportunity_details,
            "Total page weight is above 2 MB; consider deferring or optimizing heavy assets.",
            "critical",
        )
    if resources["js"]["count"] > 20:
        _add_opportunity(
            opportunities,
            opportunity_details,
            "More than 20 external scripts detected; bundle or defer non-critical JS.",
            "warning",
        )
    if resources["css"]["count"] > 10:
        _add_opportunity(
            opportunities,
            opportunity_details,
            "High stylesheet count; inline critical CSS and combine static files.",
            "warning",
        )
    if script_stats["blocking"]["count"] > 0:
        _add_opportunity(
            opportunities,
            opportunity_details,
            f"{script_stats['blocking']['count']} blocking script(s) detected; add async/defer where possible.",
            "warning",
        )

    context = PerformanceContext(
        transfer_size=transfer_size,
        css_count=resources["css"]["count"],
        js_count=resources["js"]["count"],
        img_count=resources["img"]["count"],
        font_count=resources["font"]["count"],
        nav_total_ms=response.total_ms,
        nav_ttfb_ms=response.ttfb_ms,
    )
    guide_hints = open_source_hints(context)
    opportunities.extend(guide_hints)
    for hint in guide_hints:
        opportunity_details.append({"message": hint, "severity": "info"})
    return opportunities, opportunity_details


def _data_uri_size(data_uri: str) -> int:
    if not data_uri.startswith("data:"):
        return 0
    if ";base64," in data_uri:
        encoded = data_uri.split(";base64,", 1)[1]
        padding = encoded.count("=")
        return int(len(encoded) * 3 / 4) - padding
    if "," in data_uri:
        payload = data_uri.split(",", 1)[1]
        return len(payload.encode("utf-8"))
    return 0


def _limited_fetch_targets(targets: dict[str, list[str]]) -> list[tuple[str, str]]:
    url_bucket: list[tuple[str, str]] = []
    for resource_type, urls in targets.items():
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            if len(seen) > _RESOURCE_FETCH_LIMIT:
                break
            url_bucket.append((resource_type, url))
    return url_bucket


def _header_content_length(headers: Any) -> int | None:
    length = headers.get("Content-Length")
    if length is None:
        return None
    try:
        return max(int(length), 0)
    except (TypeError, ValueError):
        return None


def _should_abort_after_head_error(exc: aiohttp.ClientResponseError) -> bool:
    return exc.status not in {403, 405}


async def _probe_size_via_get(session: aiohttp.ClientSession, url: str, timeout: ClientTimeout) -> int:
    try:
        async with session.get(url, allow_redirects=True, timeout=timeout) as resp:
            content_length = _header_content_length(resp.headers)
            if content_length is not None:
                return content_length
            total = 0
            async for chunk in resp.content.iter_chunked(16384):
                total += len(chunk)
                if total >= _RESOURCE_BODY_SAMPLE:
                    break
            return total
    except Exception:
        return 0


async def _probe_size_via_head(session: aiohttp.ClientSession, url: str, timeout: ClientTimeout) -> int | None:
    try:
        async with session.head(url, allow_redirects=True, timeout=timeout) as resp:
            return _header_content_length(resp.headers)
    except aiohttp.ClientResponseError as exc:
        if _should_abort_after_head_error(exc):
            return 0
        return None
    except Exception:
        return None


async def _probe_remote_resource(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    resource_type: str,
    url: str,
    timeout: ClientTimeout,
) -> tuple[str, str, int]:
    async with semaphore:
        head_size = await _probe_size_via_head(session, url, timeout)
        if head_size:
            return resource_type, url, head_size
        if head_size == 0:
            return resource_type, url, 0
        return resource_type, url, await _probe_size_via_get(session, url, timeout)


def _merge_remote_probe_results(
    aggregated: dict[str, int],
    per_url: dict[str, dict[str, int]],
    results: list[tuple[str, str, int]],
) -> None:
    for resource_type, url, size in results:
        if size <= 0:
            continue
        aggregated[resource_type] += size
        per_url.setdefault(resource_type, {})[url] = size


async def _measure_remote_resources(
    targets: dict[str, list[str]],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    aggregated = dict.fromkeys(targets, 0)
    per_url: dict[str, dict[str, int]] = {key: {} for key in targets}
    url_bucket = _limited_fetch_targets(targets)

    if not url_bucket:
        return aggregated, per_url

    timeout = ClientTimeout(total=_RESOURCE_BYTES_TIMEOUT)
    connector = aiohttp.TCPConnector(ssl=False)
    semaphore = asyncio.Semaphore(6)

    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *(
                _probe_remote_resource(session, semaphore, resource_type, url, timeout)
                for resource_type, url in url_bucket
            )
        )

    _merge_remote_probe_results(aggregated, per_url, results)
    return aggregated, per_url


def _format_bytes(value: int | float) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    number = max(number, 0.0)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if number < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.1f} {unit}"
        number /= 1024.0
    return f"{number:.1f} TB"


async def _collect_performance_metrics(response: Any, soup: Any) -> dict[str, object]:
    transfer_size = len(response.body.encode("utf-8", errors="ignore"))
    state = _new_collection_state(response.url)
    _collect_link_resources(state, soup)
    _collect_script_resources(state, soup)
    _collect_image_resources(state, soup)

    remote_sizes, url_sizes = await _measure_remote_resources(state.fetch_targets)
    _merge_remote_resource_sizes(state, remote_sizes, url_sizes)

    opportunities, opportunity_details = _collect_opportunities(
        transfer_size,
        response,
        state.resources,
        state.script_stats,
    )
    resource_breakdown = _build_resource_breakdown(transfer_size, state.resources)
    summary = _build_performance_summary(response.url, transfer_size, state.resources, state.resource_entries)
    issues = _build_performance_issues(state.resources, state.script_stats, summary)
    summary_with_meta = _build_performance_summary_metadata(summary, issues)

    return {
        "nav_ttfb_ms": response.ttfb_ms,
        "nav_total_ms": response.total_ms,
        "transfer_size": transfer_size,
        "status": response.status,
        "resource_summary": state.resources,
        "resource_breakdown": resource_breakdown,
        "summary": summary_with_meta,
        "issues": issues,
        "opportunities": opportunities,
        "top_offenders": _top_offenders(state.resource_entries),
        "scripts": {"blocking": state.script_stats["blocking"], "async": state.script_stats["async"]},
        "opportunity_details": opportunity_details,
    }
