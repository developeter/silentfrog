from __future__ import annotations

import asyncio
import re
from base64 import b64encode
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import bs4
from aiohttp import ClientTimeout  # type: ignore[import]  # aiohttp stubs missing
from bs4 import BeautifulSoup

from .crawl_http import _headers_from_options, _polite_probe_response
from .crawl_options import CrawlOptions
from .crawler_utils import _attr, normalize_text, safe_attr
from .image_diagnostics import INFERRED_SIZES_PREFIX, format_hint_for_mime, responsive_label
from .robots_simulator import RobotsRules
from .transport import open_crawl_session

Tag = bs4.element.Tag
NavigableString = bs4.element.NavigableString
_ALLOWED_TWITTER_CARDS = {"summary", "summary_large_image", "app", "player"}


@dataclass(slots=True)
class ImageInfo:
    src: str
    alt: str
    title: str
    mime: str
    actual_width: str
    actual_height: str
    size: str
    cache: str
    loading: str
    fetchpriority: str
    declared_width: str
    declared_height: str
    responsive: str
    sizes: str
    format_hint: str
    diagnostic: str

    def to_row(self) -> list[str]:
        return [
            self.src,
            self.alt,
            self.title,
            self.mime,
            self.actual_width,
            self.actual_height,
            self.size,
            self.cache,
            self.loading,
            self.fetchpriority,
            self.declared_width,
            self.declared_height,
            self.responsive,
            self.sizes,
            self.format_hint,
            self.diagnostic,
        ]


@dataclass(slots=True)
class LinkInfo:
    href: str
    anchor: str
    kind: str
    rel_display: str
    status: str
    status_note: str
    section: str
    heading: str
    tld: str

    def to_row(self) -> list[str]:
        return [
            self.href,
            self.anchor,
            self.kind,
            self.rel_display,
            self.status,
            self.status_note,
            self.section,
            self.heading,
            self.tld,
        ]


def _guess_image_mime(url: str) -> str:
    if not url:
        return "-"
    if url.startswith("data:image/"):
        prefix = url.split(",", 1)[0]
        return prefix[5:]
    parsed = urlparse(url)
    ext = parsed.path.lower().rsplit(".", 1)[-1] if "." in parsed.path else ""
    mapping = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
        "avif": "image/avif",
        "bmp": "image/bmp",
        "ico": "image/x-icon",
        "heic": "image/heic",
        "heif": "image/heif",
    }
    return mapping.get(ext, "-") if ext else "-"


def _normalize_fetchpriority(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    mapping = {"high": "High", "low": "Low", "auto": "Auto"}
    if lowered in mapping:
        return mapping[lowered]
    truthy = {"true", "1", "yes"}
    falsy = {"false", "0", "no"}
    if lowered in truthy:
        return "True"
    if lowered in falsy:
        return "False"
    return text


def _normalize_loading(value: str) -> str:
    text = (value or "").strip().lower()
    mapping = {"lazy": "Lazy", "eager": "Eager", "auto": "Auto"}
    if not text:
        return ""
    return mapping.get(text, value.strip().title())


def _parse_dimension(value: str | None) -> int:
    text = (value or "").strip()
    return int(text) if text.isdigit() else 0


def _non_empty_attr(tag: Tag, *names: str) -> str:
    for name in names:
        value = (safe_attr(tag, name) or "").strip()
        if value:
            return value
    return ""


def _srcset_url(srcset: str, target_width: int = 0) -> str:
    candidates = _srcset_candidates(srcset)
    if not candidates:
        return ""
    if target_width:
        width_candidates = [candidate for candidate in candidates if candidate[1]]
        if width_candidates:
            return min(width_candidates, key=lambda item: abs(item[1] - target_width))[0]
    return candidates[-1][0]


def _srcset_entries(srcset: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for chunk in srcset.split(","):
        parts = chunk.strip().split()
        if not parts:
            continue
        url = parts[0].strip()
        descriptor = parts[1].strip().lower() if len(parts) > 1 else ""
        entries.append((url, descriptor))
    return entries


def _srcset_candidates(srcset: str) -> list[tuple[str, int]]:
    return [
        (url, int(descriptor[:-1]) if descriptor.endswith("w") and descriptor[:-1].isdigit() else 0)
        for url, descriptor in _srcset_entries(srcset)
    ]


def _srcset_descriptors(srcset: str) -> list[str]:
    return [descriptor for _url, descriptor in _srcset_entries(srcset) if descriptor]


def _picture_source_url(img: Tag, target_width: int) -> str:
    parent = img.parent
    if not isinstance(parent, Tag) or parent.name.lower() != "picture":
        return ""
    sources = [source for source in parent.find_all("source", recursive=False) if isinstance(source, Tag)]
    ordered = [source for source in sources if not _non_empty_attr(source, "media")]
    ordered.extend(source for source in sources if _non_empty_attr(source, "media"))
    for source in ordered:
        raw = _non_empty_attr(source, "srcset", "src", "data-srcset", "data-src")
        resolved = _srcset_url(raw, target_width)
        if resolved:
            return resolved
    return ""


def _picture_sources(img: Tag) -> list[Tag]:
    parent = img.parent
    if not isinstance(parent, Tag) or parent.name.lower() != "picture":
        return []
    return [source for source in parent.find_all("source", recursive=False) if isinstance(source, Tag)]


def _responsive_candidates(img: Tag) -> int:
    seen: set[str] = set()
    raw_values = [
        _non_empty_attr(img, "srcset"),
        _non_empty_attr(img, "data-srcset"),
    ]
    raw_values.extend(_non_empty_attr(source, "srcset", "data-srcset") for source in _picture_sources(img))
    for raw in raw_values:
        for candidate, _ in _srcset_candidates(raw):
            if candidate:
                seen.add(candidate)
    return len(seen)


def _image_sizes(img: Tag) -> str:
    sizes = _non_empty_attr(img, "sizes")
    if sizes:
        return sizes
    sources = _picture_sources(img)
    for source in sources:
        sizes = _non_empty_attr(source, "sizes")
        if sizes:
            return sizes
    media_values = [_non_empty_attr(source, "media") for source in sources]
    media_values = [value for value in media_values if value]
    if media_values:
        preview = "; ".join(media_values[:2])
        suffix = "; ..." if len(media_values) > 2 else ""
        return f"{INFERRED_SIZES_PREFIX}picture media ({preview}{suffix})"
    descriptor_values: list[str] = []
    raw_values = [
        _non_empty_attr(img, "srcset"),
        _non_empty_attr(img, "data-srcset"),
    ]
    raw_values.extend(_non_empty_attr(source, "srcset", "data-srcset") for source in sources)
    for raw in raw_values:
        descriptor_values.extend(_srcset_descriptors(raw))
    unique_descriptors = list(dict.fromkeys(descriptor_values))
    width_descriptors = [descriptor for descriptor in unique_descriptors if descriptor.endswith("w")]
    density_descriptors = [descriptor for descriptor in unique_descriptors if descriptor.endswith("x")]
    if width_descriptors:
        preview = ", ".join(width_descriptors[:3])
        suffix = ", ..." if len(width_descriptors) > 3 else ""
        return f"{INFERRED_SIZES_PREFIX}srcset widths ({preview}{suffix})"
    if density_descriptors:
        preview = ", ".join(density_descriptors[:3])
        suffix = ", ..." if len(density_descriptors) > 3 else ""
        return f"{INFERRED_SIZES_PREFIX}srcset densities ({preview}{suffix})"
    if _responsive_candidates(img) > 1:
        return f"{INFERRED_SIZES_PREFIX}multiple responsive candidates"
    return ""


def _image_src(base: str, img: Tag) -> str:
    target_width = _parse_dimension(safe_attr(img, "width"))
    candidates = (
        _non_empty_attr(img, "src"),
        _non_empty_attr(img, "data-src"),
        _non_empty_attr(img, "data-original"),
        _non_empty_attr(img, "data-lazy-src"),
        _non_empty_attr(img, "data-srcset"),
        _non_empty_attr(img, "srcset"),
        _picture_source_url(img, target_width),
    )
    for candidate in candidates:
        resolved = _srcset_url(candidate, target_width)
        if resolved:
            return urljoin(base, resolved)
    return ""


def _extract_meta(soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    title_tag = soup.find("title")
    if title_tag is not None:
        title_text = str(title_tag.string or "").strip()
        out.append(["title", title_text, str(len(title_text))])

    for raw_tag in soup.find_all("meta"):
        tag = raw_tag
        name = _attr(tag, "name") or _attr(tag, "property") or _attr(tag, "http-equiv")
        content_str = str(_attr(tag, "content"))
        if not name:
            charset = safe_attr(tag, "charset")
            if charset:
                name = "charset"
                content_str = charset
        out.append([name, content_str, str(len(content_str))])
    return out


def _extract_headers(soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = " ".join(tag.stripped_strings)
            out.append([f"h{level}", text])
    return out


def _extract_images(base: str, soup: BeautifulSoup) -> list[list[str]]:
    rows: list[list[str]] = []
    for tag in soup.find_all("img"):
        img = tag
        src = _image_src(base, img)
        if not src:
            continue
        mime = _guess_image_mime(src)
        info = ImageInfo(
            src=src,
            alt=safe_attr(img, "alt") or "",
            title=safe_attr(img, "title") or "",
            mime=mime,
            actual_width="",
            actual_height="",
            size="",
            cache="",
            loading=_normalize_loading(safe_attr(img, "loading") or ""),
            fetchpriority=_normalize_fetchpriority(safe_attr(img, "fetchpriority") or ""),
            declared_width=safe_attr(img, "width") or "",
            declared_height=safe_attr(img, "height") or "",
            responsive=responsive_label(_responsive_candidates(img)),
            sizes=_image_sizes(img),
            format_hint=format_hint_for_mime(mime),
            diagnostic="",
        )
        rows.append(info.to_row())
    return rows


def _link_section(tag: Tag) -> str:
    role_labels = {"navigation": "Navigation"}
    name_labels = {"nav": "Navigation", "header": "Header", "footer": "Footer", "aside": "Aside"}
    for ancestor in tag.parents:
        if not isinstance(ancestor, Tag):
            continue
        name = ancestor.name.lower()
        role = str(ancestor.get("role") or "").lower()
        label = role_labels.get(role) or name_labels.get(name)
        if label:
            return label
    return "Body"


def _link_heading(tag: Tag) -> str:
    heading = tag.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    if isinstance(heading, Tag):
        return heading.get_text(" ", strip=True)
    return ""


def _content_type(headers: Any) -> str:
    return str(headers.get("Content-Type") or "").split(";", 1)[0].lower()


def _image_data_uri(raw: bytes, content_type: str) -> str:
    if not raw or len(raw) > 200_000 or not content_type.startswith("image/"):
        return ""
    return f"data:{content_type};base64,{b64encode(raw).decode()}"


def _decode_image_size(raw: bytes, content_type: str) -> tuple[int, int, str]:
    try:
        from io import BytesIO

        from PIL import Image  # type: ignore

        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
            if content_type or not image.format:
                return int(width or 0), int(height or 0), content_type
            return int(width or 0), int(height or 0), f"image/{image.format.lower()}"
    except Exception:
        return 0, 0, content_type


async def _download_image(url: str, timeout: int) -> tuple[bytes, str]:
    async with open_crawl_session() as session:
        async with session.get(url, timeout=ClientTimeout(total=timeout)) as response:
            raw = await response.read()
            return raw, _content_type(response.headers)


async def _fetch_image_details(url: str, timeout: int = 5) -> tuple[int, int, int, str, str]:
    if not url:
        return 0, 0, 0, "-", ""
    try:
        raw, content_type = await _download_image(url, timeout)
        width, height, mime = _decode_image_size(raw, content_type)
        size_b = int(len(raw) or 0)
        return width, height, size_b, mime or "-", _image_data_uri(raw, mime or content_type)
    except Exception:
        return 0, 0, 0, "-", ""


def _social_issues(card: dict[str, Any], kind: str) -> list[str]:
    issues: list[str] = []
    required = ["title", "description", "image"]
    for key in required:
        if not card.get(key):
            issues.append(f"Missing {kind} {key}")

    if kind == "twitter":
        card_type = str(card.get("card") or "").lower()
        if card_type and card_type not in _ALLOWED_TWITTER_CARDS:
            issues.append(f"Unsupported twitter:card '{card_type}'")

    img_bytes = int(card.get("image_bytes") or 0)
    if img_bytes > 5 * 1024 * 1024:
        issues.append(f"{kind.title()} image over 5MB")
    width = int(card.get("image_width") or 0)
    height = int(card.get("image_height") or 0)
    if (width and width < 120) or (height and height < 120):
        issues.append(f"{kind.title()} image very small")
    return issues


async def _extract_social_cards(
    base: str, soup: BeautifulSoup, timeout: int = 5, *, download_images: bool = True
) -> dict[str, dict[str, Any]]:
    # OG/Twitter tags are parsed locally in every profile (H4); ``download_images``
    # gates only the extra HTTP requests that size the card images.
    def _tag_value(names: tuple[str, ...]) -> str:
        for tag in soup.find_all("meta"):
            prop = _attr(tag, "property").lower()
            name = _attr(tag, "name").lower()
            if prop in names or name in names:
                content = _attr(tag, "content").strip()
                if content:
                    return content
        return ""

    og_image = _tag_value(("og:image",))
    tw_image = _tag_value(("twitter:image", "twitter:image:src"))

    og = {
        "title": _tag_value(("og:title",)),
        "description": _tag_value(("og:description",)),
        "image": urljoin(base, og_image) if og_image else "",
        "site_name": _tag_value(("og:site_name",)),
        "url": _tag_value(("og:url",)) or base,
    }
    twitter = {
        "title": _tag_value(("twitter:title",)) or og["title"],
        "description": _tag_value(("twitter:description",)) or og["description"],
        "image": urljoin(base, tw_image) if tw_image else og["image"],
        "site_name": _tag_value(("twitter:site", "twitter:creator")),
        "card": _tag_value(("twitter:card",)),
        "url": base,
    }

    async def _enrich(card: dict[str, Any]) -> None:
        if not card.get("image"):
            card.update({"image_width": 0, "image_height": 0, "image_bytes": 0, "image_type": "-"})
            return
        w, h, size_b, ctype, data_uri = await _fetch_image_details(card["image"], timeout=timeout)
        card.update(
            {
                "image_width": w,
                "image_height": h,
                "image_bytes": size_b,
                "image_type": ctype,
                "image_data": data_uri,
            }
        )

    if download_images:
        await asyncio.gather(_enrich(og), _enrich(twitter))
    else:
        for card in (og, twitter):
            card.update({"image_width": 0, "image_height": 0, "image_bytes": 0, "image_type": "-"})
    og["issues"] = _social_issues(og, "open graph")
    twitter["issues"] = _social_issues(twitter, "twitter")
    return {"open_graph": og, "twitter": twitter}


def _link_domain_info(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if not domain:
        return "", ""
    parts = domain.split(".")
    tld = parts[-1] if parts else ""
    return domain, tld


def _extract_links(base: str, soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    base_host = urlparse(base).netloc
    for raw in soup.find_all("a", href=True):
        a = raw
        href_val = safe_attr(a, "href") or ""
        href = urljoin(base, href_val)
        rel_val: Any = a.get("rel")
        rel_tokens = [str(token) for token in rel_val] if isinstance(rel_val, list) else []
        nf = "nofollow" in rel_tokens
        same_host = urlparse(href).netloc == base_host
        typ = "Interno" if same_host else "Esterno"
        anchor_text = normalize_text(" ".join(a.stripped_strings))
        if not anchor_text:
            anchor_text = (safe_attr(a, "title") or href).strip()
        tokens = [token for token in rel_tokens if token]
        if nf and "nofollow" not in tokens:
            tokens.append("nofollow")
        if not nf and "follow" not in tokens:
            tokens.append("follow")
        rel_display = ", ".join(tokens) or "follow"
        section = _link_section(a)
        heading = _link_heading(a)
        _domain, tld = _link_domain_info(href)
        info = LinkInfo(
            href=href,
            anchor=anchor_text,
            kind=typ,
            rel_display=rel_display,
            status="",
            status_note="",
            section=section or "",
            heading=heading,
            tld=tld,
        )
        out.append(info.to_row())
    return out


def _link_status_note(code: int) -> str:
    if code <= 0:
        return "Fetch error"
    bucket = code // 100
    mapping = {2: "OK", 3: "Redirect", 4: "Client error", 5: "Server error"}
    return mapping.get(bucket, "Unknown")


def _update_link_statuses(rows: list[list[str]], statuses: Any) -> None:
    for row, status in zip(rows, statuses, strict=False):
        code = status if isinstance(status, int) else 0
        row[4] = str(code)
        row[5] = _link_status_note(code)


def _meta_robots_value(headers: dict[str, str], soup: BeautifulSoup) -> str:
    header_value = headers.get("X-Robots-Tag", "")
    if header_value:
        return header_value
    return next(
        (meta[1] for meta in _extract_meta(soup) if meta and (meta[0] or "").lower() == "robots"),
        "",
    )


async def _check_canonical(
    page_url: str,
    soup: BeautifulSoup,
    timeout: int = 5,
    crawl_options: CrawlOptions | None = None,
    *,
    probe: bool = True,
) -> tuple[str, bool, bool, str]:
    # The canonical tag is parsed locally in every profile (H4); ``probe`` gates
    # only the extra HTTP request that resolves the canonical target's status.
    links: list[str] = []
    for link_tag in soup.find_all("link", rel="canonical", href=True):
        href_val = _attr(link_tag, "href").strip()
        if href_val:
            links.append(href_val)
    has_multiple = len(links) > 1
    canonical_url = urljoin(page_url, links[0]) if links else ""
    is_self = canonical_url.rstrip("/") == page_url.rstrip("/")

    status = ""
    if canonical_url and probe:
        options = crawl_options or CrawlOptions.default()
        async with open_crawl_session(headers=_headers_from_options(options)) as sess:
            response = await _polite_probe_response(
                sess,
                canonical_url,
                timeout,
                options,
                allow_redirects=True,
            )
            status = str(response.status)

    return canonical_url, is_self, has_multiple, status


_HREFLANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


async def _extract_hreflang(
    page_url: str,
    soup: BeautifulSoup,
    timeout: int = 5,
    crawl_options: CrawlOptions | None = None,
    *,
    probe: bool = True,
) -> list[list[str]]:
    # hreflang tags are parsed locally in every profile (H4); ``probe`` gates the
    # per-alternate HTTP status check (parse-only profiles report status "-").
    rows: list[list[str]] = []
    rels: dict[str, str] = {}
    for tag in soup.find_all("link", rel="alternate", hreflang=True, href=True):
        lang_val = _attr(tag, "hreflang").strip()
        href_val = _attr(tag, "href").strip()
        if not lang_val or not href_val:
            continue
        rels[lang_val.lower()] = urljoin(page_url, href_val)

    if probe:
        rows = await _probe_hreflang_rows(rels, timeout, crawl_options)
    else:
        rows = [[lang, href, "-", "Yes" if _HREFLANG_RE.match(lang) else "No", ""] for lang, href in rels.items()]

    for row in rows:
        lang, href = row[0], row[1]
        row[4] = "Yes" if rels.get(lang) == href else "No"

    return rows


async def _probe_hreflang_rows(
    rels: dict[str, str], timeout: int, crawl_options: CrawlOptions | None
) -> list[list[str]]:
    rows: list[list[str]] = []
    options = crawl_options or CrawlOptions.default()
    async with open_crawl_session(headers=_headers_from_options(options)) as sess:
        for lang, href in rels.items():
            response = await _polite_probe_response(sess, href, timeout, options, allow_redirects=True)
            rows.append([lang, href, str(response.status), "Yes" if _HREFLANG_RE.match(lang) else "No", ""])
    return rows


@dataclass(frozen=True, slots=True)
class AiAuditAgent:
    label: str
    token: str
    applies_google_search_controls: bool = False


_AI_AGENTS = (
    AiAuditAgent("GPTBot", "gptbot"),
    AiAuditAgent("ChatGPT-User", "chatgpt-user"),
    AiAuditAgent("OAI-SearchBot", "oai-searchbot"),
    AiAuditAgent("ClaudeBot", "claudebot"),
    AiAuditAgent("anthropic-ai", "anthropic-ai"),
    AiAuditAgent("Claude-Web", "claude-web"),
    AiAuditAgent("Claude-User", "claude-user"),
    AiAuditAgent("Claude-SearchBot", "claude-searchbot"),
    AiAuditAgent("PerplexityBot", "perplexitybot"),
    AiAuditAgent("Perplexity-User", "perplexity-user"),
    AiAuditAgent("Googlebot", "googlebot", applies_google_search_controls=True),
    AiAuditAgent("Google-Extended", "google-extended"),
    AiAuditAgent("Applebot-Extended", "applebot-extended"),
    AiAuditAgent("Amazonbot", "amazonbot"),
    AiAuditAgent("Bytespider", "bytespider"),
    AiAuditAgent("CCBot", "ccbot"),
    AiAuditAgent("Meta-ExternalAgent", "meta-externalagent"),
    AiAuditAgent("DuckAssistBot", "duckassistbot"),
    AiAuditAgent("cohere-ai", "cohere-ai"),
)

_AI_NONSTANDARD_DIRECTIVES = {"noai", "noimageai"}
_GOOGLE_SEARCH_CONTROLS = {"noindex", "nosnippet"}


def _meta_directives(meta_robots: str) -> set[str]:
    return {directive.strip().lower() for directive in str(meta_robots or "").split(",") if directive.strip()}


def _robot_access(rules: RobotsRules, agent_token: str, page_url: str) -> tuple[bool, list[str]]:
    """Per-agent robots verdict via the single live engine (H3). Returns
    ``(allowed, [blocking pattern] | [])`` — the pattern feeds the Bot Matrix
    notes. RFC 9309 wildcards/anchors + longest-match now apply, where the
    v1.x prefix matcher silently missed ``*``/``$`` rules."""
    result = rules.evaluate(agent_token, page_url)
    if result.allowed:
        return True, []
    pattern = result.winning_rule.pattern if result.winning_rule else ""
    return False, ([pattern] if pattern else [])


def _ai_nonstandard_directives(directives: set[str]) -> list[str]:
    return [directive for directive in sorted(directives) if directive in _AI_NONSTANDARD_DIRECTIVES]


def _parse_max_snippet_limit(directive: str) -> int | None:
    key, _sep, value = directive.partition(":")
    if key != "max-snippet":
        return None
    normalized_value = value.strip()
    if normalized_value == "-1":
        return None
    return int(normalized_value) if normalized_value.lstrip("-").isdigit() else None


def _google_search_controls(directives: set[str]) -> list[str]:
    controls = [directive for directive in sorted(directives) if directive in _GOOGLE_SEARCH_CONTROLS]
    snippet_controls = [
        directive
        for directive in sorted(directives)
        if (limit := _parse_max_snippet_limit(directive)) is not None and limit >= 0
    ]
    if "none" in directives:
        controls.append("none")
    return list(dict.fromkeys(controls + snippet_controls))


def _ai_verdict(robots_ok: bool, controls: list[str]) -> str:
    if not robots_ok:
        return "Blocked"
    if controls:
        return "Limited"
    return "Allowed"


def _ai_notes(
    robots_ok: bool,
    disallows: list[str],
    nonstandard_directives: list[str],
    controls: list[str],
) -> str:
    notes: list[str] = []
    if not robots_ok and disallows:
        notes.append(f"Blocked by robots.txt: {', '.join(disallows)}")
    if nonstandard_directives:
        notes.append(f"Nonstandard directives detected: {', '.join(nonstandard_directives)}")
    if controls:
        notes.append(f"Google search controls: {', '.join(controls)}")
    return "; ".join(notes) or "No explicit AI restrictions detected"


def _ai_crawl_matrix(rules: RobotsRules, meta_robots: str, page_url: str) -> list[list[str]]:
    directives = _meta_directives(meta_robots)
    nonstandard_directives = _ai_nonstandard_directives(directives)
    google_controls = _google_search_controls(directives)
    ai_directive_text = ", ".join(nonstandard_directives) or "-"
    out: list[list[str]] = []
    for agent in _AI_AGENTS:
        disallows: list[str]
        robots_ok, disallows = _robot_access(rules, agent.token, page_url)
        controls = google_controls if agent.applies_google_search_controls else []
        search_control_text = ", ".join(controls) or "-"
        verdict = _ai_verdict(robots_ok, controls)
        out.append(
            [
                agent.label,
                agent.token,
                "Yes" if robots_ok else "No",
                ai_directive_text,
                search_control_text,
                verdict,
                _ai_notes(robots_ok, disallows, nonstandard_directives, controls),
            ]
        )
    return out


ELLIPSIS = chr(0x2026)
_MEAN_PX = 7.2


def _serp_preview(page_url: str, soup: BeautifulSoup) -> dict[str, str]:
    title = ""
    title_tag = soup.title
    if isinstance(title_tag, Tag):
        title = (title_tag.string or "").strip()
    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = ""
    if isinstance(desc_tag, Tag):
        description = _attr(desc_tag, "content").strip()
    description = description[:155]  # simple desktop-length trim
    return {
        "title": title,
        "description": description,
        "display_url": urlparse(page_url).netloc.replace("www.", "") + "/" + ELLIPSIS,
    }


async def _to_data_uri(img_url: str) -> str:
    try:
        async with open_crawl_session() as session:
            async with session.get(img_url, timeout=5) as response:
                if response.status != 200:
                    return img_url
                raw = await response.read()
                from io import BytesIO

                from PIL import Image, ImageDraw  # type: ignore[import]  # pillow stubs missing

                with Image.open(BytesIO(raw)).convert("RGBA") as image:
                    image = image.resize(
                        (16, 16), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                    )
                    mask = Image.new("L", (16, 16), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 16, 16), fill=255)
                    image.putalpha(mask)
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    raw = buffer.getvalue()
                from base64 import b64encode

                return f"data:image/png;base64,{b64encode(raw).decode()}"
    except Exception:
        return img_url


async def _make_serp_snippet(soup: BeautifulSoup, page_url: str) -> dict[str, str]:
    parsed = urlparse(page_url)
    domain = parsed.netloc

    site_name = ""
    og_site = soup.find("meta", property="og:site_name")
    if isinstance(og_site, Tag):
        site_name = _attr(og_site, "content").strip()
    if not site_name and domain:
        parts = domain.split(".")
        site_name = parts[-2].capitalize() if len(parts) >= 2 else domain.capitalize()

    raw_title = ""
    title_tag = soup.title
    if isinstance(title_tag, Tag):
        raw_title = (title_tag.string or "").strip()

    max_px = 600
    char_limit = int(max_px / _MEAN_PX)
    title = raw_title[: char_limit - 1].rstrip() + ELLIPSIS if len(raw_title) > char_limit else raw_title

    path_part = parsed.path.strip("/").replace("/", " • ")
    breadcrumb = f"{domain} • {path_part}" if path_part else domain

    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    raw_desc = ""
    if isinstance(desc_tag, Tag):
        raw_desc = _attr(desc_tag, "content").strip()
    description = (raw_desc[:157] + ELLIPSIS) if len(raw_desc) > 160 else raw_desc

    favicon = f"https://www.google.com/s2/favicons?sz=48&domain={domain}"
    favicon_tag = soup.find("link", rel=lambda val: isinstance(val, str) and "icon" in val.lower())
    if isinstance(favicon_tag, Tag):
        href_val = _attr(favicon_tag, "href").strip()
        if href_val:
            favicon = urljoin(page_url, href_val)

    return {
        "title": title,
        "description": (description[:157] + ELLIPSIS) if len(description) > 160 else description,
        "url": page_url,
        "site_name": site_name,
        "favicon": await _to_data_uri(favicon),
        "breadcrumb": breadcrumb,
    }


def _title_audit(title: str, headers: list[list[str]]) -> dict[str, str]:
    h1_text = next((h[1] for h in headers if h and h[0].lower() == "h1"), "")
    length = len(title)
    pixels = int(length * _MEAN_PX)
    return {
        "too_long": "Yes" if length > 60 else "No",
        "too_short": "Yes" if length < 30 else "No",
        "px_over": "Yes" if pixels > 561 else "No",
        "px_under": "Yes" if pixels < 200 else "No",
        "equals_h1": "Yes" if title.strip().lower() == h1_text.strip().lower() else "No",
        "missing": "Yes" if not title else "No",
        "px_len": str(pixels),
        "char_len": str(length),
    }
