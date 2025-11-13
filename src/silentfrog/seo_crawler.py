"""
Motore asincrono per l'analisi SEO di una singola pagina.

"""
from __future__ import annotations
from io import BytesIO
from collections import Counter
from html import unescape
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from nltk.corpus import stopwords
from aiohttp import ClientTimeout, ClientSession  # type: ignore
from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple, cast
from PIL import Image, ImageDraw
from urllib.parse import urljoin, urlparse, urlunparse, unquote
from urllib.robotparser import RobotFileParser
from base64 import b64encode
from textwrap import shorten
from .http_client import fetch_page, head_status, fetch_text, HttpResponse
from .crawl_options import CrawlOptions
from .crawler_utils import _attr, _hr_size
from .crawl_types import CrawlPayload
from .perf_guides import PerformanceContext, open_source_hints

import asyncio
from contextlib import asynccontextmanager
import re
import string
import bs4
import aiohttp  # type: ignore
import email
import json
import os
import html as _html
import logging

Tag = bs4.element.Tag
NavigableString = bs4.element.NavigableString
_RESAMPLING_BASE = getattr(Image, "Resampling", None)
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", getattr(Image, "LANCZOS", 1))

# --- Safe import of extruct (fallback if lxml is broken) ----------------------
try:
    import extruct  # type: ignore
    from w3lib.html import get_base_url  # type: ignore
    USE_EXTRUCT = True
except Exception:                       # ImportError, lxml errors, etc.
    # extruct or lxml is unavailable -> fall back to JSON-LD-only extractor
    USE_EXTRUCT = False

# ------------------------------------------------------------------------------
 
# ------------------------------------------------------------------------------
# Schema debug logger (opt-in via SILENTFROG_DEBUG).  Defined unconditionally,
# so it can never raise NameError even if imported elsewhere.
DEBUG_SCHEMA = os.environ.get("SILENTFROG_DEBUG", "").lower() in ("1", "true", "yes", "y")
_SCHEMA_LOGGER = logging.getLogger("silentfrog.schema")

def _log_schema(msg: str) -> None:
    """Emit debug messages for schema extraction; silent unless env is set."""
    if DEBUG_SCHEMA:
        _SCHEMA_LOGGER.info(msg)

# Carichiamo stop-word per 4 lingue (IT/EN/ES/FR)
STOP = set()
for lang in ("english", "italian", "spanish", "french"):
    try:
        STOP.update(stopwords.words(lang))
    except LookupError:  # prima esecuzione: scarica corpus
        import nltk

        nltk.download("stopwords")
        STOP.update(stopwords.words(lang))


def _keyword_density_threshold() -> float:
    raw = os.environ.get("SILENTFROG_KEYWORD_WARN_DENSITY", "").strip()
    if not raw:
        return 4.0
    try:
        value = float(raw.replace(",", "."))
    except ValueError:
        return 4.0
    return max(value, 0.0)


_ACCEPT_DEFAULT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_LANGUAGE_DEFAULT = "en-US,en;q=0.9"
_HOST_LIMITERS: dict[str, tuple[int, asyncio.Semaphore]] = {}
_HOST_LIMITER_LOCK = asyncio.Lock()
_HOST_DELAYS: dict[str, float] = {}
_BACKOFF_STATUSES = {403, 429}
_BACKOFF_DELAY = 1.5


def _host_key(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc or parsed.path or url
    return host.lower()


async def _get_host_semaphore(host: str, limit: int) -> asyncio.Semaphore:
    async with _HOST_LIMITER_LOCK:
        cached = _HOST_LIMITERS.get(host)
        if cached and cached[0] == limit:
            return cached[1]
        semaphore = asyncio.Semaphore(limit)
        _HOST_LIMITERS[host] = (limit, semaphore)
        return semaphore


@asynccontextmanager
async def _throttle_host(host: str, options: CrawlOptions):
    if not options.gentle_mode:
        yield
        return
    semaphore = await _get_host_semaphore(host, max(1, options.max_concurrent_per_host))
    async with semaphore:
        yield


def _headers_from_options(options: CrawlOptions) -> dict[str, str]:
    base = {
        "User-Agent": options.user_agent,
        "Accept": _ACCEPT_DEFAULT,
        "Accept-Language": _ACCEPT_LANGUAGE_DEFAULT,
    }
    if not options.extra_headers:
        return base
    return {**base, **options.extra_headers}


async def _image_info(session: aiohttp.ClientSession, url: str, timeout: int):
    try:
        async with session.get(url, timeout=ClientTimeout(total=timeout)) as r:
            raw = await r.read()

        size_b = len(raw)
        content_type = (r.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        try:
            with Image.open(BytesIO(raw)) as im:
                w, h = im.size
                if not content_type and im.format:
                    content_type = f"image/{im.format.lower()}"
        except Exception:                      # immagine non valida
            w, h = 0, 0

        return url, w, h, _hr_size(size_b), content_type or "-"
    except Exception as exc:                   # es. connessione fallita
        # mantieni "Errore" per il test e per la GUI
        return "Errore", 0, 0, "", "-"


async def _link_status(session: ClientSession, url: str, timeout: int, options: CrawlOptions) -> int:
    host = _host_key(url)
    async with _throttle_host(host, options):
        delay = _HOST_DELAYS.get(host, 0.0) if options.gentle_mode and options.respect_crawl_delay else 0.0
        if delay > 0:
            await asyncio.sleep(delay)
        attempts = 2 if options.gentle_mode else 1
        code = 0
        for attempt in range(attempts):
            code = await head_status(session, url, timeout)
            should_retry = code in _BACKOFF_STATUSES and attempt < attempts - 1
            if not should_retry:
                break
            await asyncio.sleep(_BACKOFF_DELAY)
        return code


def _guess_image_mime(url: str) -> str:
    if not url:
        return "-"
    if url.startswith("data:image/"):
        prefix = url.split(",", 1)[0]
        return prefix[5:]  # remove "data:"
    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path.lower())[1].lstrip(".")
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

# -- robots.txt helper ---------------------------------------------------
async def _fetch_robots(url: str, timeout: int = 5) -> str | None:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    return await fetch_text(robots_url, timeout)


async def _parse_robots(url: str, timeout: int = 5) -> dict[str, list[tuple[str, str]]]:
    """
    Returns a mapping:
        { user_agent: [ (directive, path), ... ] }
    Example:
        { '*': [ ('Disallow', '/admin'), ('Allow', '/') ],
          'Googlebot': [ ('Allow', '/special') ] }
    """
    txt = await _fetch_robots(url, timeout)
    if txt is None:
        return {}

    result: dict[str, list[tuple[str, str]]] = {}
    current_agents: list[str] = ["*"]

    for raw in txt.splitlines():
        line = raw.split("#", 1)[0].strip()     # strip comments
        if not line:
            continue

        if ":" not in line:
            continue
        key, value = (p.strip() for p in line.split(":", 1))
        key_low = key.lower()

        if key_low == "user-agent":
            current_agents = [a.strip() for a in value.split()]
            for ua in current_agents:
                result.setdefault(ua, [])
            continue

        if key_low in ("allow", "disallow"):
            for ua in current_agents:
                result.setdefault(ua, []).append((key.title(), value))
            continue

        # record any other directive verbatim
        for ua in current_agents:
            result.setdefault(ua, []).append((key.title(), value))

    return result


def _crawl_delay_for(options: CrawlOptions, host: str, robots: dict[str, list[tuple[str, str]]]) -> float:
    if not options.gentle_mode or not options.respect_crawl_delay:
        return 0.0
    ua_key = options.user_agent.lower()
    candidates = robots.get(ua_key) or robots.get("*") or []
    for key, value in candidates:
        if key.lower() == "crawl-delay":
            try:
                return max(0.0, float(value.replace(",", ".").strip()))
            except ValueError:
                return 0.0
    return 0.0

# -- canonical helper ----------------------------------------------------------
async def _check_canonical(
    page_url: str,
    soup: BeautifulSoup,
    timeout: int = 5,
) -> tuple[str, bool, bool, str]:
    """
    Returns:
        (canonical_url,
         is_self_referencing,
         has_multiple,
         status_code_or_error)
    """
    links: list[str] = []
    for link_tag in soup.find_all("link", rel="canonical", href=True):
        href_val = _attr(link_tag, "href").strip()
        if href_val:
            links.append(href_val)
    has_multiple = len(links) > 1
    canonical_url = urljoin(page_url, links[0]) if links else ""
    is_self = canonical_url.rstrip("/") == page_url.rstrip("/")

    # HEAD request to see if canonical resolves (optional,  timeout-guarded)
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

# -- hreflang helper ----------------------------------------------------
_HREFLANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")   # e.g. en , fr-FR

async def _extract_hreflang(
    page_url: str,
    soup: BeautifulSoup,
    timeout: int = 5,
) -> list[list[str]]:
    """
    Returns list rows:
        [lang, target_url, status, valid?, return_link?]
    """
    # 1) Collect tags
    rows: list[list[str]] = []
    rels: dict[str, str] = {}          # lang -> url
    for tag in soup.find_all("link", rel="alternate", hreflang=True, href=True):
        lang_val = _attr(tag, "hreflang").strip()
        href_val = _attr(tag, "href").strip()
        if not lang_val or not href_val:
            continue
        rels[lang_val.lower()] = urljoin(page_url, href_val)

    # 2) HEAD-fetch each URL (in serial to keep code short)
    async with aiohttp.ClientSession() as sess:
        for lang, href in rels.items():
            try:
                async with sess.head(
                    href,
                    allow_redirects=True,
                    timeout=ClientTimeout(total=timeout),
                ) as r:
                    status = str(r.status)
            except Exception as exc:
                status = f"error {exc.__class__.__name__}"

            rows.append(
                [
                    lang,
                    href,
                    status,
                    "Yes" if _HREFLANG_RE.match(lang) else "No",
                    "",           # placeholder for return-link
                ]
            )

    # 3) Compute return-link symmetry
    for row in rows:
        lang, href = row[0], row[1]
        # fetch that page's hreflang back to us?
        row[4] = "Yes" if rels.get(lang) == href else "No"

    return rows

# -- AI-crawl helper -----------------------------------------------------
_AI_AGENTS = {
    "GPTBot":      "gptbot",
    "Google-Extended": "google-extended",
    "Gemini":      "google-other",        # Gemini uses generic UA per Google doc
}

def _ai_crawl_matrix(
    robots_map: dict[str, list[tuple[str, str]]],
    meta_robots: str,
    page_url: str,
) -> list[list[str]]:
    """
    Returns rows: [Agent, Robots.txt allowed?, Meta-robots disallow?, Verdict]
    """
    def _allowed_by_robots(agent_token: str) -> bool:
        # Very simple: look for Disallow that matches '*' or our agent
        disallows = []
        for ua, directives in robots_map.items():
            if ua in ("*", agent_token):
                disallows.extend(
                    path for verb, path in directives if verb.lower() == "disallow"
                )
        # If a blanket Disallow: / or path prefix matches URL
        return not any(page_url.startswith(urljoin(page_url, d)) for d in disallows)

    out: list[list[str]] = []
    meta_disallow = "noai" in meta_robots.lower() or "noimageai" in meta_robots.lower()
    for pretty, token in _AI_AGENTS.items():
        allowed = _allowed_by_robots(token)
        verdict = "Blocked" if (not allowed or meta_disallow) else "Allowed"
        out.append([pretty, "Yes" if allowed else "No", "Yes" if meta_disallow else "No", verdict])
    return out


# -- SERP preview helper ------------------------------------------------
def _serp_preview(page_url: str, soup: BeautifulSoup) -> dict[str, str]:
    title = ""
    title_tag = soup.title
    if isinstance(title_tag, Tag):
        title = (title_tag.string or "").strip()
    desc_tag = soup.find("meta", attrs={"name": "description"})
    description = ""
    if isinstance(desc_tag, Tag):
        description = _attr(desc_tag, "content").strip()
    # Google shows ~155 chars on desktop
    description = shorten(description, width=155, placeholder=ELLIPSIS)
    return {
        "title": title,
        "description": description,
        "display_url": urlparse(page_url).netloc.replace("www.", "") + "/" + ELLIPSIS,
    }

# -- 

def _link_status_note(code: int) -> str:
    if code <= 0:
        return "Fetch error"
    bucket = code // 100
    mapping = {
        2: "OK",
        3: "Redirect",
        4: "Client error",
        5: "Server error",
    }
    return mapping.get(bucket, "Unknown")


def _update_link_statuses(rows: list[list[str]], statuses: Iterable[object]) -> None:
    for row, status in zip(rows, statuses):
        code = status if isinstance(status, int) else 0
        row[4] = str(code)
        row[5] = _link_status_note(code)


def _meta_robots_value(headers: Mapping[str, str], soup: BeautifulSoup) -> str:
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


async def _to_data_uri(img_url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url, timeout=5) as response:
                if response.status != 200:
                    return img_url
                raw = await response.read()
                with Image.open(BytesIO(raw)).convert("RGBA") as image:
                    image = image.resize((16, 16), _LANCZOS)
                    mask = Image.new("L", (16, 16), 0)
                    ImageDraw.Draw(mask).ellipse((0, 0, 16, 16), fill=255)
                    image.putalpha(mask)
                    buffer = BytesIO()
                    image.save(buffer, format="PNG")
                    raw = buffer.getvalue()
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
    title = (
        raw_title[: char_limit - 1].rstrip() + ELLIPSIS
        if len(raw_title) > char_limit
        else raw_title
    )

    path_part = unquote(parsed.path.strip("/")).replace("/", " › ")
    breadcrumb = f"{domain} › {path_part}" if path_part else domain

    desc_tag = (
        soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", property="og:description")
    )
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

# --- Title audit helper -------------------------------------------------
_MEAN_PX = 7.2           # average desktop pixel width per glyph
ELLIPSIS = chr(0x2026)

def _title_audit(title: str, headers: list[list[str]]) -> dict[str, str]:
    """Return a dict with all title warning flags."""
    h1_text = next((h[1] for h in headers if h and h[0].lower() == "h1"), "")
    length = len(title)
    pixels = int(length * _MEAN_PX)
    return {
        "too_long":     "Yes" if length > 60 else "No",
        "too_short":    "Yes" if length < 30 else "No",
        "px_over":      "Yes" if pixels > 561 else "No",
        "px_under":     "Yes" if pixels < 200 else "No",
        "equals_h1":    "Yes" if title.strip().lower() == h1_text.strip().lower() else "No",
        "missing":      "Yes" if not title else "No",
        "px_len":       str(pixels),
        "char_len":     str(length),
    }



# -- redirect-chain helper -----------------------------------------------
async def _trace_redirects(url: str, timeout: int = 8) -> tuple[list[str], str, int, bool]:
    """
    Follow HEAD requests (max 6 hops) and return:
        * list of hop URLs  (including start & each Location)
        * final_status      (string)
        * hops              (int)
        * is_loop           (bool)  True if any URL repeats
    """
    max_hops = 6
    hop_urls: list[str] = [url]
    try:
        async with aiohttp.ClientSession() as sess:
            cur = url
            for _ in range(max_hops):
                async with sess.head(
                    cur,
                    allow_redirects=False,
                    timeout=ClientTimeout(total=timeout),
                ) as r:
                    status = r.status
                    if 300 <= status < 400 and "Location" in r.headers:
                        nxt = urljoin(cur, r.headers["Location"])
                        if nxt in hop_urls:
                            # loop detected
                            hop_urls.append(nxt)
                            return hop_urls, str(status), len(hop_urls) - 1, True
                        hop_urls.append(nxt)
                        cur = nxt
                        continue
                    # reached final
                    return hop_urls, str(status), len(hop_urls) - 1, False
        # exceeded max_hops
        return hop_urls, "max-hops", len(hop_urls) - 1, False
    except Exception as exc:
        return hop_urls, f"error {exc.__class__.__name__}", len(hop_urls) - 1, False


# --------------------------------------------------------------------- #
def _extract_meta(soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    title_tag = soup.find("title")
    if isinstance(title_tag, Tag):
        title_text = (title_tag.string or "").strip()
        out.append(["title", title_text, str(len(title_text))])

    for tag in soup.find_all("meta"):
        name = _attr(tag, "name") or _attr(tag, "property") or _attr(tag, "http-equiv")
        content = _attr(tag, "content")
        if not name and tag.has_attr("charset"):
            name = "charset"
            content = tag.get("charset", "")
        out.append([name, content, str(len(content))])
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
    for idx, tag in enumerate(soup.find_all("img")):
        img = cast(bs4.element.Tag, tag)  # typing safe
        src = urljoin(base, _attr(img, "src"))
        alt = _attr(img, "alt")
        title = _attr(img, "title")
        loading_attr = (_attr(img, "loading") or "").lower()
        has_lazy = loading_attr == "lazy"
        mime = _guess_image_mime(src)
        width_attr = _attr(img, "width")
        height_attr = _attr(img, "height")
        size_placeholder = ""
        fetch_priority = _normalize_fetchpriority(_attr(img, "fetchpriority"))
        rows.append(
            [
                src,
                alt,
                title,
                mime,
                width_attr,
                height_attr,
                size_placeholder,
                "Yes" if has_lazy else "No",
                fetch_priority,
            ]
        )
    return rows


def _link_section(tag: Tag) -> str:
    for ancestor in tag.parents:
        if not isinstance(ancestor, Tag):
            continue
        name = ancestor.name.lower()
        role = (ancestor.get("role") or "").lower()
        if name == "nav" or role == "navigation":
            return "Navigation"
        if name == "header":
            return "Header"
        if name == "footer":
            return "Footer"
        if name == "aside":
            return "Aside"
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
        a = cast(bs4.element.Tag, raw)
        href_val = _attr(a, "href")
        href = urljoin(base, href_val)
        rel_val: Any = a.get("rel")                        # ÔåÉ Ôæí default None OK
        rel = rel_val if isinstance(rel_val, list) else [] # lista sicura
        nf  = "nofollow" in rel
        same_host = urlparse(href).netloc == base_host
        typ = "Interno" if same_host else "Esterno"
        anchor_text = " ".join(a.stripped_strings).strip()
        if not anchor_text:
            anchor_text = (_attr(a, "title") or href).strip()
        tokens = [token for token in rel if token]
        if nf and "nofollow" not in tokens:
            tokens.append("nofollow")
        if not nf and "follow" not in tokens:
            tokens.append("follow")
        rel_display = ", ".join(tokens) or "follow"
        section = _link_section(a)
        heading = _link_heading(a)
        _domain, tld = _link_domain_info(href)
        out.append(
            [
                href,
                anchor_text,
                typ,
                rel_display,
                "",
                "",
                section or "",
                heading,
                tld,
            ]
        )
    return out


def _schema_primary_type(value: Any) -> str:
    candidate = ""
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, list):
        for part in value:
            if isinstance(part, str) and part.strip():
                candidate = part
                break
    if not candidate:
        return ""
    text = candidate.strip()
    if not text:
        return ""
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text.strip()


def _schema_block_label(index: int, obj: Dict[str, Any]) -> str:
    type_name = _schema_primary_type(obj.get("@type"))
    via = obj.get("_extracted_via", "")
    label = f"Block #{index}"
    if type_name:
        label += f" ({type_name})"
    if via:
        label += f" via {via}"
    return label


def _schema_normalize_entries(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _schema_validate_breadcrumb(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    entries = obj.get("itemListElement")
    if not entries:
        errors.append("missing itemListElement")
        return errors

    normalized = _schema_normalize_entries(entries)
    for idx, entry in enumerate(normalized, start=1):
        if not isinstance(entry, dict):
            errors.append(f"itemListElement[{idx}] is not an object")
            continue
        target = entry.get("item") or entry.get("itemId") or entry.get("url")
        if isinstance(target, dict):
            target = target.get("@id") or target.get("url")
        if "position" not in entry:
            errors.append(f"itemListElement[{idx}] missing position")
        if not entry.get("name"):
            errors.append(f"itemListElement[{idx}] missing name")
        if not target:
            errors.append(f"itemListElement[{idx}] missing item url")
    return errors


def _schema_validate_product(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not obj.get("name"):
        errors.append("missing name")
    if not obj.get("description"):
        errors.append("missing description")
    image = obj.get("image")
    if not image:
        errors.append("missing image")

    offers = obj.get("offers")
    if not offers:
        errors.append("missing offers")
        return errors

    offers_list = _schema_normalize_entries(offers)
    have_price = False
    have_currency = False
    for offer in offers_list:
        if not isinstance(offer, dict):
            continue
        offer_type = _schema_primary_type(offer.get("@type")).lower()
        price_spec = offer.get("priceSpecification")
        if isinstance(price_spec, dict):
            if price_spec.get("price") or price_spec.get("minPrice") or price_spec.get("lowPrice"):
                have_price = True
            if price_spec.get("priceCurrency"):
                have_currency = True
        price_value = offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
        if price_value:
            have_price = True
        if offer.get("priceCurrency"):
            have_currency = True
        if offer_type == "aggregateoffer":
            if offer.get("lowPrice") or offer.get("highPrice"):
                have_price = True
            if offer.get("priceCurrency"):
                have_currency = True
    if not have_price:
        errors.append("missing offers.price")
    if not have_currency:
        errors.append("missing offers.priceCurrency")
    return errors


_SCHEMA_VALIDATORS: Dict[str, Callable[[Dict[str, Any]], List[str]]] = {
    "breadcrumblist": _schema_validate_breadcrumb,
    "product": _schema_validate_product,
}


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


async def _measure_remote_resources(
    targets: Dict[str, List[str]]
) -> tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
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


async def _collect_performance_metrics(
    response: HttpResponse, soup: BeautifulSoup
) -> dict[str, object]:
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

    def _register(
        resource_type: str,
        raw_url: str,
        *,
        blocking: bool | None = None,
        label: str | None = None,
        preset_bytes: int | None = None,
    ) -> None:
        url = raw_url.strip()
        if not url:
            return
        resources[resource_type]["count"] += 1
        if url.startswith("data:"):
            size_val = _data_uri_size(url)
            resources[resource_type]["bytes"] += size_val
            entry = {
                "type": resource_type.upper(),
                "url": label or url[:80],
                "bytes": size_val,
                "blocking": bool(blocking),
            }
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
            entry = {
                "type": resource_type.upper(),
                "url": normalized,
                "bytes": max(preset_bytes or 0, 0),
                "blocking": bool(blocking),
            }
            resource_entries[resource_type].append(entry)
            if resource_type == "js":
                key = "blocking" if blocking else "async"
                script_stats[key]["count"] += 1
                script_entry_map[normalized] = {"kind": key, "entry": entry}

    for link in soup.find_all("link"):
        rel_tokens = {token.lower() for token in (link.get("rel") or [])}
        href = link.get("href") or ""
        if not href:
            continue
        if "stylesheet" in rel_tokens or (link.get("type") or "").lower() == "text/css":
            _register("css", href)
            continue
        if "preload" in rel_tokens:
            target = (link.get("as") or "").lower()
            if target in resources:
                _register(target, href)
                continue
        if any("font" in token for token in rel_tokens):
            _register("font", href)

    for script in soup.find_all("script"):
        src = script.get("src")
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
                resource_entries["js"].append(
                    {
                        "type": "JS",
                        "url": "(inline script)",
                        "bytes": inline_bytes,
                        "blocking": True,
                    }
                )

    for img in soup.find_all("img"):
        src = img.get("src")
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
        _add_opportunity(
            "Main document size exceeds 800 KB; consider compression or trimming inline data.",
            "critical",
        )
    if total_page_weight > 2_000_000:
        _add_opportunity(
            "Total page weight is above 2 MB; consider deferring or optimizing heavy assets.",
            "critical",
        )
    if resources["js"]["count"] > 20:
        _add_opportunity(
            "More than 20 external scripts detected; bundle or defer non-critical JS.",
            "warning",
        )
    if resources["css"]["count"] > 10:
        _add_opportunity(
            "High stylesheet count; inline critical CSS and combine static files.",
            "warning",
        )
    if script_stats["blocking"]["count"] > 0:
        _add_opportunity(
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

    return {
        "nav_ttfb_ms": response.ttfb_ms,
        "nav_total_ms": response.total_ms,
        "transfer_size": transfer_size,
        "status": response.status,
        "resource_summary": resources,
        "opportunities": opportunities,
        "top_offenders": top_offenders,
        "scripts": {
            "blocking": script_stats["blocking"],
            "async": script_stats["async"],
        },
        "opportunity_details": opportunity_details,
    }

def _extract_schema_all(html_text: str, response_url: str) -> Dict[str, Any]:
    """
    Structured data extraction (robust, logged, still lightweight):
      * JSON-LD manual harvest FIRST (so JSON-LD items stay first in output)
      * extruct pass (lxml) -> retry with html5lib tree if needed
      * Flatten JSON-LD @graph; keep malformed blocks as {"@raw": "..."}
      * Heuristic discovery inside generic JSON (e.g. __NEXT_DATA__, __NUXT__)
      * Provide summary counts by syntax/@type and collect concise error hints
    """
    syntaxes = ["json-ld", "microdata", "opengraph", "microformat", "rdfa"]
    collected: list[Dict[str, Any]] = []
    seen: set[str] = set()
    syntax_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    fallback_raw: list[str] = []

    # --- helpers --------------------------------------------------------------
    def _add_flat(obj: dict, via: str) -> None:
        """Add obj (flattening @graph) with dedup and provenance tag."""
        g = obj.get("@graph")
        if isinstance(g, list) and g:
            for n in g:
                if isinstance(n, dict):
                    _add_flat(n, via)
            return
        sig = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if sig in seen:
            return
        seen.add(sig)
        enriched = dict(obj)
        enriched["_extracted_via"] = via
        collected.append(enriched)
        syntax_counter[via] += 1
        primary_type = _schema_primary_type(enriched.get("@type"))
        if primary_type:
            type_counter[primary_type] += 1

    def _scrub_jsonish(s: str) -> str:
        """Make common broken JSON parseable (BOM, HTML/JS comments, trailing commas)."""
        s = s.lstrip("\ufeff").strip()
        s = re.sub(r"(?s)<!--.*?-->", "", s)           # HTML comments
        s = re.sub(r"(?s)/\*.*?\*/", "", s)            # /* block comments */
        s = re.sub(r"(?m)^\s*//.*$", "", s)            # // line comments
        s = re.sub(r",\s*([}\]])", r"\1", s)           # trailing commas
        return s

    def _safe_load(s: str) -> Any:
        """Try strict JSON, then scrubbed, then HTML-unescaped -> scrubbed."""
        try:
            return json.loads(s)
        except Exception:
            pass
        try:
            return json.loads(_scrub_jsonish(s))
        except Exception:
            pass
        try:
            return json.loads(_scrub_jsonish(_html.unescape(s)))
        except Exception:
            return None

    def _walk_jsonld(obj: Any) -> list[dict]:
        """
        Find JSON-LD dicts anywhere inside a generic JSON structure
        (covers __NEXT_DATA__, __NUXT__, CMS blobs, etc.).
        Also handles stringified JSON-LD nested as values.
        """
        out: list[dict] = []
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if ("@context" in cur) or ("@type" in cur) or ("@graph" in cur):
                    out.append(cur)
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, str) and ("@context" in cur or "@type" in cur):
                loaded = _safe_load(cur)
                if isinstance(loaded, (list, dict)):
                    stack.append(loaded)
        return out

    # -------- minimal BeautifulSoup fallbacks for Microdata / RDFa ----------
    def _is_within_other(scope: bs4.element.Tag, node: bs4.element.Tag, attr: str) -> bool:
        """Return True if *node* is inside a descendant subtree that also has *attr*."""
        p = node.parent
        while p is not None and p is not scope:
            if isinstance(p, bs4.element.Tag) and p.has_attr(attr):
                return True
            p = p.parent
        return False

    def _microdata_bs(soup: BeautifulSoup) -> list[dict]:
        """Very small Microdata scraper (itemscope/itemtype/itemprop)."""
        out: list[dict] = []
        for scope in soup.find_all(attrs={"itemscope": True}):
            if not isinstance(scope, Tag):
                continue
            typ_tokens = _attr(scope, "itemtype").split()
            item_type = typ_tokens[0] if typ_tokens else "Thing"
            item: dict[str, Any] = {"@type": item_type}
            for prop in scope.find_all(attrs={"itemprop": True}):
                if not isinstance(prop, Tag):
                    continue
                if _is_within_other(scope, prop, "itemscope"):
                    continue
                key_tokens = _attr(prop, "itemprop").split()
                raw_content = _attr(prop, "content")
                raw_href = _attr(prop, "href")
                raw_src = _attr(prop, "src")
                value = raw_content or raw_href or raw_src or " ".join(prop.stripped_strings)
                for key in key_tokens:
                    if key:
                        item[key] = value
            out.append(item)
        return out

    def _rdfa_bs(soup: BeautifulSoup) -> list[dict]:
        """Very small RDFa scraper (typeof / property / content|href|src|text)."""
        out: list[dict] = []
        for root in soup.find_all(attrs={"typeof": True}):
            if not isinstance(root, Tag):
                continue
            typ = _attr(root, "typeof").strip()
            vocab = _attr(root, "vocab").strip()
            item: dict[str, Any] = {"@type": typ or (vocab or "Thing")}
            for prop in root.find_all(attrs={"property": True}):
                if not isinstance(prop, Tag):
                    continue
                if _is_within_other(root, prop, "typeof"):
                    continue
                key = _attr(prop, "property").strip()
                raw_content = _attr(prop, "content")
                raw_href = _attr(prop, "href")
                raw_src = _attr(prop, "src")
                value = raw_content or raw_href or raw_src or " ".join(prop.stripped_strings)
                if key:
                    item[key] = value
            out.append(item)
        return out

    # --- 1) Manual JSON-LD first ---------------------------------------------
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        ok = bad = 0
        for node in soup.find_all("script"):
            if not isinstance(node, Tag):
                continue
            tag_type = _attr(node, "type").lower().strip()
            is_ld = "ld+json" in tag_type or tag_type in ("application/jsonld", "application/json+ld")
            ident = _attr(node, "id")
            class_attr = node.get("class") or []
            class_text = " ".join(class_attr) if isinstance(class_attr, (list, tuple)) else str(class_attr)
            hint = "schema" in f"{ident} {class_text}".lower()
            if not (is_ld or hint):
                continue
            raw = (node.string or node.get_text() or "").strip()
            if not raw:
                continue
            parsed = _safe_load(raw)
            if parsed is None:
                collected.append({"@raw": raw, "_extracted_via": "json-ld-raw"}); bad += 1; continue
            if isinstance(parsed, list):
                for obj in parsed:
                    if isinstance(obj, dict):
                        _add_flat(obj, "json-ld")
            elif isinstance(parsed, dict):
                _add_flat(parsed, "json-ld")
            else:
                collected.append({"@raw": raw, "_extracted_via": "json-ld-raw"}); bad += 1; continue
            ok += 1
        _log_schema(f"manual json-ld blocks parsed={ok}, raw_bad={bad}")
    except Exception as e:
        _log_schema(f"manual json-ld error: {e!r}")

    def _find_json_objects(text: str) -> list[str]:
        """
        Extract JSON-looking blocks from arbitrary JS (e.g. `window.__NUXT__ = {...}`).
        We scan for balanced `{...}` blocks (no regex backtracking). Fast and robust.
        """
        out: list[str] = []
        depth = 0
        start = -1
        in_str = ""
        esc = False
        for i, ch in enumerate(text):
            if in_str:
                esc = (ch == "\\" and not esc)
                if ch == in_str and not esc:
                    in_str = ""
                continue
            if ch in ("'", '"'):
                in_str = ch
                esc = False
                continue
            if ch == "{":
                depth += 1
                start = i if depth == 1 else start
                continue
            if ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
        return out

    # --- 1b) Heuristic discovery inside generic JS/JSON blobs -----------------
    try:
        soup2 = BeautifulSoup(html_text, "html.parser")
        hits = 0
        for script in soup2.find_all("script"):
            raw = script.string or script.get_text()
            if not raw:
                continue
            parsed = _safe_load(raw)
            if isinstance(parsed, (list, dict)):
                for item in _walk_jsonld(parsed):
                    _add_flat(item, "json-ld")
                    hits += 1
                continue
            for chunk in _find_json_objects(raw):
                parsed2 = _safe_load(chunk)
                if isinstance(parsed2, (list, dict)):
                    for item in _walk_jsonld(parsed2):
                        _add_flat(item, "json-ld")
                        hits += 1
        if hits:
            _log_schema(f"heuristic nested json-ld nodes found={hits}")
    except Exception as e:
        _log_schema(f"heuristic json-ld error: {e!r}")

    # --- 2) extruct passes (lxml -> html5lib) ---------------------------------
    if USE_EXTRUCT:
        def _extract_lxml() -> dict[str, Any]:
            try:
                data = extruct.extract(html_text, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
                _log_schema("extruct:lxml ok")
                return data
            except Exception as e:
                _log_schema(f"extruct:lxml error: {e!r}")
                return {}
        def _extract_html5lib() -> dict[str, Any]:
            try:
                from extruct.utils import parse_html as _parse_html  # type: ignore
                tree = _parse_html(html_text, treebuilder="html5lib")
                data = extruct.extract(tree, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
                _log_schema("extruct:html5lib ok")
                return data
            except Exception as e:
                _log_schema(f"extruct:html5lib error: {e!r}")
                return {}
        res = _extract_lxml()
        if not any(res.get(k) for k in syntaxes):
            res = _extract_html5lib()
        for syntax in syntaxes:
            items = res.get(syntax) or []
            for it in items:
                if isinstance(it, dict):
                    _add_flat(it, syntax)
            if items:
                _log_schema(f"extruct:{syntax} -> {len(items)} items")

    # --- 2b) Microdata/RDFa BeautifulSoup fallbacks (when extruct gave none) -
    soup_md = BeautifulSoup(html_text, "html.parser")
    have_micro = any(isinstance(o, dict) and o.get("_extracted_via") == "microdata" for o in collected)
    have_rdfa = any(isinstance(o, dict) and o.get("_extracted_via") == "rdfa" for o in collected)
    if not have_micro:
        for item in _microdata_bs(soup_md):
            _add_flat(item, "microdata")
        _log_schema("fallback: microdata added")
    if not have_rdfa:
        for item in _rdfa_bs(soup_md):
            _add_flat(item, "rdfa")
        _log_schema("fallback: rdfa added")

    if not collected:
        soup_fallback = BeautifulSoup(html_text, "html.parser")
        fallback_blocks: list[Dict[str, Any]] = []
        for script in soup_fallback.find_all("script", {"type": "application/ld+json"}):
            raw = script.get_text(strip=True) or ""
            if not raw:
                continue
            fallback_raw.append(raw)
            fallback_blocks.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
        if fallback_blocks:
            collected.extend(fallback_blocks)
            syntax_counter["json-ld-raw"] += len(fallback_blocks)
            _log_schema(f"fallback: raw json-ld captured={len(fallback_blocks)}")

    aggregate: list[str] = []
    for idx, obj in enumerate(collected, start=1):
        if not isinstance(obj, dict):
            continue
        via = str(obj.get("_extracted_via", "")).strip()
        via_lower = via.lower()
        block_issues: List[str] = []
        if via_lower in ("json-ld", "json-ld-raw"):
            checks = [
                ("@raw" in obj, "Unparseable JSON-LD block"),
                ("@context" not in obj and "@raw" not in obj, "JSON-LD missing @context"),
                ("@type" not in obj and "@raw" not in obj, "JSON-LD missing @type"),
            ]
            block_issues.extend(msg for cond, msg in checks if cond)
        if via_lower == "microdata" and "@type" not in obj:
            block_issues.append("Microdata item missing @type")
        if via_lower == "rdfa" and "@type" not in obj:
            block_issues.append("RDFa item missing @type")

        validator_key = _schema_primary_type(obj.get("@type")).lower()
        validator = _SCHEMA_VALIDATORS.get(validator_key)
        if validator:
            block_issues.extend(validator(obj))

        if block_issues:
            unique = sorted(set(block_issues))
            obj["_schema_errors"] = unique
            label = _schema_block_label(idx, obj)
            aggregate.extend(f"{label}: {msg}" for msg in unique)

    summary = {
        "total": int(sum(syntax_counter.values())),
        "by_syntax": {name: syntax_counter[name] for name in sorted(syntax_counter) if syntax_counter[name]},
        "by_type": {name: type_counter[name] for name in sorted(type_counter) if type_counter[name]},
        "errors": sorted(set(aggregate)),
    }
    return {
        "blocks": collected,
        "summary": summary,
        "issues": summary["errors"],
        "fallback_raw": fallback_raw,
    }


def _extract_keywords(soup: BeautifulSoup, text: str, top_n: int = 20) -> list[dict[str, object]]:
    def _tokenize(raw: str) -> list[str]:
        cleaned = unescape(raw.lower())
        cleaned = re.sub(r"[{}]".format(re.escape(string.punctuation)), " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        tokens = []
        for token in cleaned.split():
            if not token or token in STOP or len(token) <= 2:
                continue
            if token.isdigit() or any(ch.isdigit() for ch in token):
                continue
            tokens.append(token)
        return tokens

    def _phrase_set(tokens: list[str], n: int) -> set[str]:
        if len(tokens) < n:
            return set()
        return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}

    def _phrase_counter(tokens: list[str], n: int) -> Counter[str]:
        counter: Counter[str] = Counter()
        if len(tokens) < n:
            return counter
        for i in range(len(tokens) - n + 1):
            counter[" ".join(tokens[i : i + n])] += 1
        return counter

    def _first_positions(tokens: list[str], n: int) -> dict[str, int]:
        positions: dict[str, int] = {}
        if len(tokens) < n:
            return positions
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i : i + n])
            if phrase not in positions:
                positions[phrase] = i
        return positions

    body_tokens = _tokenize(text)
    total_tokens = len(body_tokens)
    if total_tokens == 0:
        return []

    sections = {
        "title": _tokenize(soup.title.get_text(" ", strip=True)) if soup.title else [],
        "description": _tokenize(
            next(
                (meta.get("content", "") for meta in soup.find_all("meta") if str(meta.get("name", "")).lower() == "description"),
                "",
            )
        ),
    }

    heading_tokens: list[list[str]] = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$", re.IGNORECASE)):
        heading_tokens.append(_tokenize(heading.get_text(" ", strip=True)))

    heading_counters = {
        1: Counter[str](),
        2: Counter[str](),
        3: Counter[str](),
    }
    for tokens in heading_tokens:
        for n in (1, 2, 3):
            heading_counters[n].update(_phrase_counter(tokens, n))

    section_phrase_sets = {
        section: {n: _phrase_set(tokens, n) for n in (1, 2, 3)} for section, tokens in sections.items()
    }

    ngram_stats = {}
    for n in (1, 2, 3):
        counts = _phrase_counter(body_tokens, n)
        if not counts:
            counts = Counter()
        positions = _first_positions(body_tokens, n)
        ngram_stats[n] = {"counts": counts, "positions": positions}

    warn_threshold = _keyword_density_threshold()
    results: list[dict[str, object]] = []
    for n in (1, 2, 3):
        counts: Counter[str] = ngram_stats[n]["counts"]
        if not counts:
            continue
        denominator = max(total_tokens - n + 1, 1)
        for term, freq in counts.most_common(top_n):
            density = round((freq / denominator) * 100, 2)
            first_pos = ngram_stats[n]["positions"].get(term)
            density_warning = warn_threshold > 0 and density >= warn_threshold
            entry = {
                "term": term,
                "length": n,
                "frequency": freq,
                "density": density,
                "density_threshold": warn_threshold,
                "density_warning": density_warning,
                "in_title": term in section_phrase_sets["title"][n],
                "in_description": term in section_phrase_sets["description"][n],
                "heading_count": heading_counters[n].get(term, 0),
                "first_position": first_pos if first_pos is not None else -1,
            }
            results.append(entry)

    return results


# --------------------------------------------------------------------- #
_ACCEPT_DEFAULT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_ACCEPT_LANGUAGE_DEFAULT = "en-US,en;q=0.9"


def _headers_from_options(options: CrawlOptions) -> dict[str, str]:
    base = {
        "User-Agent": options.user_agent,
        "Accept": _ACCEPT_DEFAULT,
        "Accept-Language": _ACCEPT_LANGUAGE_DEFAULT,
    }
    if not options.extra_headers:
        return base
    return {**base, **options.extra_headers}


async def analyse(url: str, timeout: int = 10, options: CrawlOptions | None = None) -> CrawlPayload:
    crawl_options = options or CrawlOptions.default()
    host_key = _host_key(url)
    robots_snapshot: dict[str, list[tuple[str, str]]] | None = None
    async with _throttle_host(host_key, crawl_options):
        if crawl_options.respect_crawl_delay:
            robots_snapshot = await _parse_robots(url, timeout=timeout)
        delay_seconds = _crawl_delay_for(crawl_options, host_key, robots_snapshot or {})
        active_delay = delay_seconds if (crawl_options.gentle_mode and crawl_options.respect_crawl_delay) else 0.0
        _HOST_DELAYS[host_key] = active_delay
        if active_delay > 0:
            await asyncio.sleep(active_delay)
        headers = _headers_from_options(crawl_options)
        attempts = 2 if crawl_options.gentle_mode else 1
        resp: HttpResponse | None = None
        for attempt in range(attempts):
            resp = await fetch_page(url, timeout, headers=headers)
            should_retry = resp.status in _BACKOFF_STATUSES and attempt < attempts - 1
            if not should_retry:
                break
            await asyncio.sleep(_BACKOFF_DELAY)
        assert resp is not None
    soup = BeautifulSoup(resp.body, "html.parser")
    structured_data = _extract_schema_all(resp.body, resp.url)
    performance_metrics = await _collect_performance_metrics(resp, soup)
    # rimuovi commenti e script/style per trovare keyword
    for tag in soup.find_all(["script", "style"]):
        tag.extract()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    plain = soup.get_text(separator=" ", strip=True)

    # estrae le righe "grezze" (status ancora vuoto)
    links_rows: list[list[str]] = _extract_links(resp.url, soup)

    # recupera in parallelo gli HTTP status
    connector = aiohttp.TCPConnector(ssl=False)
    link_headers = _headers_from_options(crawl_options)
    async with aiohttp.ClientSession(connector=connector, headers=link_headers) as _sess:
        coros = [_link_status(_sess, row[0], timeout, crawl_options) for row in links_rows]
        statuses = await asyncio.gather(*coros, return_exceptions=True)

    # riempie la 4ª colonna di ogni riga
    _update_link_statuses(links_rows, statuses)

    canonical_url, is_self, many_canon, canon_status = await _check_canonical(
        resp.url, soup, timeout=timeout
    )

    # --- Redirect chain -------------------------------------------------
    hops, final_status, hop_count, is_loop = await _trace_redirects(url)

    hreflang_rows = await _extract_hreflang(resp.url, soup, timeout=timeout)
    
    meta_robots = _meta_robots_value(resp.headers, soup)
    robots_map = robots_snapshot or await _parse_robots(url, timeout=timeout)
    ai_rows = _ai_crawl_matrix(robots_map, meta_robots, resp.url)
    serp_snippet = await _make_serp_snippet(soup, resp.url)
    title_audit = _title_audit(serp_snippet["title"], _extract_headers(soup))

    # costruisce il risultato finale
    raw_payload = {
        "meta": _extract_meta(soup),
        "headers": _extract_headers(soup),
        "images": _extract_images(resp.url, soup),
        "links": links_rows,
        "schema": structured_data,
        "canonical": {
            "target": canonical_url,
            "self": is_self,
            "multiple": many_canon,
            "status": canon_status,
        },
        "redirect": {
            "hops": hop_count,
            "chain": hops,
            "final_status": final_status,
            "loop": is_loop,
        },
        "robots": robots_map,  # full UA map
        "meta_robots": meta_robots,
        "hreflang": hreflang_rows,
        "ai_crawl": ai_rows,
        "serp": serp_snippet,
        "serp_audit": title_audit,
        "keywords": _extract_keywords(soup, plain),
        "performance": performance_metrics,
    }

    return CrawlPayload.from_raw(raw_payload)


async def analyse_images(base: str, rows: list[list[str]], timeout=10):
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        coros = [_image_info(sess, urljoin(base, row[0]), timeout) for row in rows]
        out = await asyncio.gather(*coros, return_exceptions=True)

    result: list[list[str]] = []
    for o in out:
        if isinstance(o, Exception):
            # mantieni l'URL originale se possibile per
            # facilitare il debug: lo ricavo dal messaggio d'errore
            msg = str(o)
            url = msg.split(" ", 1)[0] if "http" in msg else "Errore"
            result.append([url, "", "", "", "-"])
        else:
            url, w, h, hr, ctype = cast(tuple[str, int, int, str, str], o)
            result.append([url, str(w), str(h), hr, ctype])

    return result
