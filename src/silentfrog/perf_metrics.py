from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse, urlunparse, urljoin

import aiohttp  # type: ignore
from aiohttp import ClientTimeout  # type: ignore

from .perf_guides import PerformanceContext, open_source_hints

_RESOURCE_FETCH_LIMIT = 20
_RESOURCE_BYTES_TIMEOUT = 5
_RESOURCE_BODY_SAMPLE = 512_000


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
        url = raw_url.strip()
        if not url:
            return
        resources[resource_type]["count"] += 1
        if url.startswith("data:"):
            size_val = _data_uri_size(url)
            resources[resource_type]["bytes"] += size_val
            entry = {"type": resource_type.upper(), "url": label or url[:80], "bytes": size_val, "blocking": bool(blocking)}
            resource_entries[resource_type].append(entry)
            if resource_type == "js":
                key = "blocking" if blocking else "async"
                script_stats[key]["count"] += 1
                script_stats[key]["bytes"] += size_val
            return
        absolute = urljoin(base_url, url)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"}:
            normalized = urlunparse(parsed)
            fetch_targets[resource_type].append(normalized)
            entry = {"type": resource_type.upper(), "url": normalized, "bytes": max(preset_bytes or 0, 0), "blocking": bool(blocking)}
            resource_entries[resource_type].append(entry)
            if resource_type == "js":
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
            target = str(link.get("as") or "").lower()
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

    return {
        "nav_ttfb_ms": response.ttfb_ms,
        "nav_total_ms": response.total_ms,
        "transfer_size": transfer_size,
        "status": response.status,
        "resource_summary": resources,
        "opportunities": opportunities,
        "top_offenders": top_offenders,
        "scripts": {"blocking": script_stats["blocking"], "async": script_stats["async"]},
        "opportunity_details": opportunity_details,
    }
