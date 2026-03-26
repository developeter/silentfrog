from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse, urljoin

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


def _build_resource_breakdown(transfer_size: int, resources: Dict[str, Dict[str, int]]) -> list[dict[str, int | str]]:
    html_entry = {"type": "html", "count": 1, "bytes": max(transfer_size, 0)}
    buckets = {
        key: {
            "type": key,
            "count": max(int(value.get("count", 0)), 0),
            "bytes": max(int(value.get("bytes", 0)), 0),
        }
        for key, value in resources.items()
    }
    return [html_entry, *(buckets.get(key, {"type": key, "count": 0, "bytes": 0}) for key in _RESOURCE_BREAKDOWN_ORDER[1:])]


def _build_performance_summary(
    base_url: str,
    transfer_size: int,
    resources: Dict[str, Dict[str, int]],
    resource_entries: Dict[str, List[Dict[str, Any]]],
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
    resources: Dict[str, Dict[str, int]],
    script_stats: Dict[str, Dict[str, int]],
    summary: dict[str, int],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def _append(key: str, severity: str, message: str, evidence: str, recommendation: str) -> None:
        issues.append(
            {
                "key": key,
                "severity": severity,
                "message": message,
                "evidence": evidence,
                "recommendation": recommendation,
            }
        )

    total_page_bytes = summary["total_page_bytes"]
    if total_page_bytes >= _CRITICAL_PAGE_BYTES:
        _append(
            "page_weight",
            "critical",
            "Total page weight is very high.",
            f"Measured page weight is {_format_bytes(total_page_bytes)}.",
            "Reduce heavy assets, defer non-critical resources, and compress media.",
        )
    elif total_page_bytes >= _WARNING_PAGE_BYTES:
        _append(
            "page_weight",
            "warning",
            "Total page weight is above the recommended range.",
            f"Measured page weight is {_format_bytes(total_page_bytes)}.",
            "Trim heavy resources before they affect crawl efficiency and user load time.",
        )

    blocking_count = script_stats["blocking"]["count"]
    blocking_bytes = script_stats["blocking"]["bytes"]
    if blocking_count > 0:
        severity = "critical" if blocking_bytes >= _WARNING_JS_BYTES else "warning"
        _append(
            "blocking_js",
            severity,
            "Blocking JavaScript was detected in the page source.",
            f"{blocking_count} blocking script(s), {_format_bytes(blocking_bytes)} total.",
            "Move non-critical scripts to defer/async and reduce blocking script weight.",
        )

    js_bytes = resources["js"]["bytes"]
    if js_bytes >= _CRITICAL_JS_BYTES:
        _append(
            "js_weight",
            "critical",
            "JavaScript payload is very heavy.",
            f"Measured JavaScript weight is {_format_bytes(js_bytes)}.",
            "Reduce shipped JS, remove third-party bloat, and split non-critical logic.",
        )
    elif js_bytes >= _WARNING_JS_BYTES:
        _append(
            "js_weight",
            "warning",
            "JavaScript payload is heavier than ideal.",
            f"Measured JavaScript weight is {_format_bytes(js_bytes)}.",
            "Review bundle size and defer non-critical scripts.",
        )

    css_bytes = resources["css"]["bytes"]
    if css_bytes >= _CRITICAL_CSS_BYTES:
        _append(
            "css_weight",
            "critical",
            "CSS payload is very heavy.",
            f"Measured CSS weight is {_format_bytes(css_bytes)}.",
            "Inline critical CSS and reduce stylesheet weight.",
        )
    elif css_bytes >= _WARNING_CSS_BYTES:
        _append(
            "css_weight",
            "warning",
            "CSS payload is heavier than ideal.",
            f"Measured CSS weight is {_format_bytes(css_bytes)}.",
            "Consolidate stylesheets and trim non-critical CSS.",
        )

    image_bytes = resources["img"]["bytes"]
    if image_bytes >= _CRITICAL_IMAGE_BYTES:
        _append(
            "image_weight",
            "critical",
            "Image payload is very heavy.",
            f"Measured image weight is {_format_bytes(image_bytes)}.",
            "Compress images, use next-gen formats, and reduce oversized assets.",
        )
    elif image_bytes >= _WARNING_IMAGE_BYTES:
        _append(
            "image_weight",
            "warning",
            "Image payload is heavier than ideal.",
            f"Measured image weight is {_format_bytes(image_bytes)}.",
            "Compress large images and review responsive delivery.",
        )

    total_resources = summary["total_resource_count"]
    if total_resources >= _CRITICAL_REQUEST_COUNT:
        _append(
            "request_count",
            "critical",
            "The page loads a very high number of resources.",
            f"{total_resources} resources were detected.",
            "Reduce request count by bundling or removing non-critical assets.",
        )
    elif total_resources >= _WARNING_REQUEST_COUNT:
        _append(
            "request_count",
            "warning",
            "The page loads many resources.",
            f"{total_resources} resources were detected.",
            "Review request count and consolidate static assets where practical.",
        )

    third_party_bytes = summary["third_party_bytes"]
    third_party_count = summary["third_party_count"]
    if third_party_bytes >= _CRITICAL_THIRD_PARTY_BYTES or third_party_count >= _CRITICAL_THIRD_PARTY_COUNT:
        _append(
            "third_party_weight",
            "critical",
            "Third-party resources contribute significant weight.",
            f"{third_party_count} third-party resource(s), {_format_bytes(third_party_bytes)} total.",
            "Audit off-domain dependencies and remove low-value third-party assets.",
        )
    elif third_party_bytes >= _WARNING_THIRD_PARTY_BYTES or third_party_count >= _WARNING_THIRD_PARTY_COUNT:
        _append(
            "third_party_weight",
            "warning",
            "Third-party resources are adding noticeable overhead.",
            f"{third_party_count} third-party resource(s), {_format_bytes(third_party_bytes)} total.",
            "Reduce third-party dependencies and lazy-load what is not critical.",
        )

    return issues


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


async def _measure_remote_resources(targets: Dict[str, List[str]]) -> tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
    aggregated = {key: 0 for key in targets}
    per_url: Dict[str, Dict[str, int]] = {key: {} for key in targets}
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

    if not url_bucket:
        return aggregated, per_url

    timeout = ClientTimeout(total=_RESOURCE_BYTES_TIMEOUT)
    connector = aiohttp.TCPConnector(ssl=False)
    semaphore = asyncio.Semaphore(6)

    async with aiohttp.ClientSession(connector=connector) as session:
        async def _probe(resource_type: str, url: str) -> tuple[str, str, int]:
            async with semaphore:
                async def _size_via_get() -> int:
                    try:
                        async with session.get(url, allow_redirects=True, timeout=timeout) as resp:
                            length = resp.headers.get("Content-Length")
                            if length is not None:
                                return max(int(length), 0)
                            total = 0
                            async for chunk in resp.content.iter_chunked(16384):
                                total += len(chunk)
                                if total >= _RESOURCE_BODY_SAMPLE:
                                    break
                            return total
                    except Exception:
                        return 0
                    return 0

                try:
                    async with session.head(url, allow_redirects=True, timeout=timeout) as resp:
                        length = resp.headers.get("Content-Length")
                        if length is not None:
                            value = max(int(length), 0)
                            if value:
                                return resource_type, url, value
                except aiohttp.ClientResponseError as exc:
                    if exc.status not in {403, 405}:
                        return resource_type, url, 0
                except Exception:
                    pass
                fallback_size = await _size_via_get()
                if fallback_size:
                    return resource_type, url, fallback_size
                return resource_type, url, 0

        results = await asyncio.gather(*(_probe(r_type, url) for r_type, url in url_bucket))

    for resource_type, url, size in results:
        if size > 0:
            aggregated[resource_type] += size
            per_url.setdefault(resource_type, {})[url] = size
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


async def _collect_performance_metrics(response: Any, soup: Any) -> Dict[str, object]:
    transfer_size = len(response.body.encode("utf-8", errors="ignore"))
    resources: Dict[str, Dict[str, int]] = {
        "css": {"count": 0, "bytes": 0},
        "js": {"count": 0, "bytes": 0},
        "img": {"count": 0, "bytes": 0},
        "font": {"count": 0, "bytes": 0},
        "other": {"count": 0, "bytes": 0},
    }
    fetch_targets: Dict[str, List[str]] = {key: [] for key in resources.keys()}
    resource_entries: Dict[str, List[Dict[str, Any]]] = {key: [] for key in resources.keys()}
    script_stats: Dict[str, Dict[str, int]] = {
        "blocking": {"count": 0, "bytes": 0},
        "async": {"count": 0, "bytes": 0},
    }
    script_entry_map: Dict[str, Dict[str, Any]] = {}
    base_url = response.url

    def _register(resource_type: str, raw_url: str, *, blocking: bool | None = None, label: str | None = None, preset_bytes: int | None = None) -> None:
        bucket = _normalize_resource_type(resource_type)
        url = raw_url.strip()
        if not url or bucket not in resources:
            return
        resources[bucket]["count"] += 1
        if url.startswith("data:"):
            size_val = _data_uri_size(url)
            resources[bucket]["bytes"] += size_val
            entry = {"type": bucket.upper(), "url": label or url[:80], "bytes": size_val, "blocking": bool(blocking)}
            resource_entries[bucket].append(entry)
            if bucket == "js":
                key = "blocking" if blocking else "async"
                script_stats[key]["count"] += 1
                script_stats[key]["bytes"] += size_val
            return
        absolute = urljoin(base_url, url)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"}:
            normalized = urlunparse(parsed)
            fetch_targets[bucket].append(normalized)
            entry = {"type": bucket.upper(), "url": normalized, "bytes": max(preset_bytes or 0, 0), "blocking": bool(blocking)}
            resource_entries[bucket].append(entry)
            if bucket == "js":
                key = "blocking" if blocking else "async"
                script_stats[key]["count"] += 1
                script_entry_map[normalized] = {"kind": key, "entry": entry}

    for link in soup.find_all("link"):
        rel_tokens = {str(token).lower() for token in (link.get("rel") or [])}
        href = str(link.get("href") or "")
        if not href:
            continue
        if "stylesheet" in rel_tokens or str(link.get("type") or "").lower() == "text/css":
            _register("css", href)
            continue
        if "preload" in rel_tokens:
            target = _normalize_resource_type(str(link.get("as") or ""))
            if target in resources:
                _register(target, href)
                continue
        if any("font" in token for token in rel_tokens):
            _register("font", href)

    for script in soup.find_all("script"):
        src = str(script.get("src") or "")
        if src:
            is_blocking = not (script.has_attr("async") or script.has_attr("defer"))
            _register("js", src, blocking=is_blocking)
        else:
            text = script.string or ""
            if text:
                inline_bytes = len(text.encode("utf-8"))
                resources["js"]["count"] += 1
                resources["js"]["bytes"] += inline_bytes
                script_stats["blocking"]["count"] += 1
                script_stats["blocking"]["bytes"] += inline_bytes
                resource_entries["js"].append({"type": "JS", "url": "(inline script)", "bytes": inline_bytes, "blocking": True})

    for img in soup.find_all("img"):
        src = str(img.get("src") or "")
        if src:
            _register("img", src)

    remote_sizes, url_sizes = await _measure_remote_resources(fetch_targets)
    for resource_type, size in remote_sizes.items():
        resources[resource_type]["bytes"] += size
        per_type = url_sizes.get(resource_type, {})
        for entry in resource_entries[resource_type]:
            url = entry.get("url", "")
            if not url:
                continue
            entry_size = per_type.get(url)
            if entry_size is not None:
                entry["bytes"] = entry_size
                if resource_type == "js":
                    script_info = script_entry_map.get(url)
                    if script_info:
                        script_stats[script_info["kind"]]["bytes"] += entry_size

    top_offenders: List[Dict[str, Any]] = []
    for entries in resource_entries.values():
        top_offenders.extend(entries)
    top_offenders.sort(key=lambda item: item.get("bytes", 0), reverse=True)
    top_offenders = top_offenders[:10]

    opportunities: list[str] = []
    opportunity_details: list[Dict[str, str]] = []

    def _add_opportunity(message: str, severity: str) -> None:
        text = message.strip()
        if not text:
            return
        opportunities.append(text)
        opportunity_details.append({"message": text, "severity": severity})

    total_resource_bytes = sum(info.get("bytes", 0) for info in resources.values())
    total_page_weight = transfer_size + total_resource_bytes

    if transfer_size > 800_000:
        _add_opportunity("Main document size exceeds 800 KB; consider compression or trimming inline data.", "critical")
    if total_page_weight > 2_000_000:
        _add_opportunity("Total page weight is above 2 MB; consider deferring or optimizing heavy assets.", "critical")
    if resources["js"]["count"] > 20:
        _add_opportunity("More than 20 external scripts detected; bundle or defer non-critical JS.", "warning")
    if resources["css"]["count"] > 10:
        _add_opportunity("High stylesheet count; inline critical CSS and combine static files.", "warning")
    if script_stats["blocking"]["count"] > 0:
        _add_opportunity(f"{script_stats['blocking']['count']} blocking script(s) detected; add async/defer where possible.", "warning")

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

    resource_breakdown = _build_resource_breakdown(transfer_size, resources)
    summary = _build_performance_summary(base_url, transfer_size, resources, resource_entries)
    issues = _build_performance_issues(resources, script_stats, summary)
    summary_with_meta = _build_performance_summary_metadata(summary, issues)

    return {
        "nav_ttfb_ms": response.ttfb_ms,
        "nav_total_ms": response.total_ms,
        "transfer_size": transfer_size,
        "status": response.status,
        "resource_summary": resources,
        "resource_breakdown": resource_breakdown,
        "summary": summary_with_meta,
        "issues": issues,
        "opportunities": opportunities,
        "top_offenders": top_offenders,
        "scripts": {"blocking": script_stats["blocking"], "async": script_stats["async"]},
        "opportunity_details": opportunity_details,
    }
