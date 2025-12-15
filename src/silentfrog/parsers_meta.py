from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Tuple
from urllib.parse import urljoin, urlparse

import bs4
from bs4 import BeautifulSoup
import aiohttp  # type: ignore[import]  # aiohttp stubs missing
from aiohttp import ClientTimeout  # type: ignore[import]  # aiohttp stubs missing

from .crawler_utils import _attr, _hr_size, normalize_text, safe_attr

Tag = bs4.element.Tag
NavigableString = bs4.element.NavigableString


@dataclass(slots=True)
class ImageInfo:
    src: str
    alt: str
    title: str
    mime: str
    width: str
    height: str
    size: str
    cache: str
    loading: str
    fetchpriority: str

    def to_row(self) -> list[str]:
        return [
            self.src,
            self.alt,
            self.title,
            self.mime,
            self.width,
            self.height,
            self.size,
            self.cache,
            self.loading,
            self.fetchpriority,
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
        src_raw = safe_attr(img, "src") or ""
        src = urljoin(base, src_raw)
        info = ImageInfo(
            src=src,
            alt=safe_attr(img, "alt") or "",
            title=safe_attr(img, "title") or "",
            mime=_guess_image_mime(src),
            width=safe_attr(img, "width") or "",
            height=safe_attr(img, "height") or "",
            size="",
            cache="",
            loading=_normalize_loading(safe_attr(img, "loading") or ""),
            fetchpriority=_normalize_fetchpriority(safe_attr(img, "fetchpriority") or ""),
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


def _link_domain_info(url: str) -> Tuple[str, str]:
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
    for row, status in zip(rows, statuses):
        code = status if isinstance(status, int) else 0
        row[4] = str(code)
        row[5] = _link_status_note(code)


def _meta_robots_value(headers: dict[str, str], soup: BeautifulSoup) -> str:
    header_value = headers.get("X-Robots-Tag", "")
    if header_value:
        return header_value
    return next(
        (
            meta[1]
            for meta in _extract_meta(soup)
            if meta and (meta[0] or "").lower() == "robots"
        ),
        "",
    )


async def _check_canonical(page_url: str, soup: BeautifulSoup, timeout: int = 5) -> tuple[str, bool, bool, str]:
    links: list[str] = []
    for link_tag in soup.find_all("link", rel="canonical", href=True):
        href_val = _attr(link_tag, "href").strip()
        if href_val:
            links.append(href_val)
    has_multiple = len(links) > 1
    canonical_url = urljoin(page_url, links[0]) if links else ""
    is_self = canonical_url.rstrip("/") == page_url.rstrip("/")

    status = ""
    if canonical_url:
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.head(
                    canonical_url,
                    timeout=ClientTimeout(total=timeout),
                    allow_redirects=True,
                ) as r:
                    status = str(r.status)
        except Exception as exc:
            status = f"error {exc.__class__.__name__}"

    return canonical_url, is_self, has_multiple, status


_HREFLANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


async def _extract_hreflang(page_url: str, soup: BeautifulSoup, timeout: int = 5) -> list[list[str]]:
    rows: list[list[str]] = []
    rels: dict[str, str] = {}
    for tag in soup.find_all("link", rel="alternate", hreflang=True, href=True):
        lang_val = _attr(tag, "hreflang").strip()
        href_val = _attr(tag, "href").strip()
        if not lang_val or not href_val:
            continue
        rels[lang_val.lower()] = urljoin(page_url, href_val)

    async with aiohttp.ClientSession() as sess:
        for lang, href in rels.items():
            try:
                async with sess.head(href, allow_redirects=True, timeout=ClientTimeout(total=timeout)) as r:
                    status = str(r.status)
            except Exception as exc:
                status = f"error {exc.__class__.__name__}"

            rows.append([lang, href, status, "Yes" if _HREFLANG_RE.match(lang) else "No", ""])

    for row in rows:
        lang, href = row[0], row[1]
        row[4] = "Yes" if rels.get(lang) == href else "No"

    return rows


_AI_AGENTS = {
    "GPTBot": "gptbot",
    "Google-Extended": "google-extended",
    "Gemini": "google-other",
}


def _ai_crawl_matrix(robots_map: dict[str, list[tuple[str, str]]], meta_robots: str, page_url: str) -> list[list[str]]:
    def _allowed_by_robots(agent_token: str) -> bool:
        disallows = []
        for ua, directives in robots_map.items():
            if ua in ("*", agent_token):
                disallows.extend(path for verb, path in directives if verb.lower() == "disallow")
        return not any(page_url.startswith(urljoin(page_url, d)) for d in disallows)

    out: list[list[str]] = []
    meta_disallow = "noai" in meta_robots.lower() or "noimageai" in meta_robots.lower()
    for pretty, token in _AI_AGENTS.items():
        allowed = _allowed_by_robots(token)
        verdict = "Blocked" if (not allowed or meta_disallow) else "Allowed"
        out.append([pretty, "Yes" if allowed else "No", "Yes" if meta_disallow else "No", verdict])
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
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url, timeout=5) as response:
                if response.status != 200:
                    return img_url
                raw = await response.read()
                from io import BytesIO
                from PIL import Image, ImageDraw  # type: ignore[import]  # pillow stubs missing

                with Image.open(BytesIO(raw)).convert("RGBA") as image:
                    image = image.resize((16, 16), Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
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
