"""
Motore asincrono per l’analisi SEO di una singola pagina.

"""
from __future__ import annotations
from io import BytesIO
from collections import Counter
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from nltk.corpus import stopwords
from aiohttp import ClientTimeout, ClientSession  # type: ignore
from typing import Any, Dict, List, cast
from PIL import Image, ImageDraw
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from base64 import b64encode
from textwrap import shorten

import humanize  # type: ignore
import asyncio
import re
import ssl
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

# ─── Safe import of extruct (fallback if lxml is broken) ──────────────────────
try:
    import extruct  # type: ignore
    from w3lib.html import get_base_url  # type: ignore
    USE_EXTRUCT = True
except Exception:                       # ImportError, lxml errors, etc.
    # extruct or lxml is unavailable → fall back to JSON-LD-only extractor
    USE_EXTRUCT = False

# ──────────────────────────────────────────────────────────────────────────────
 
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


@dataclass
class HttpResponse:
    """Lightweight container returned by fetch_page()."""

    def __init__(
        self,
        body: str,
        status: int,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.url = url
        self.headers = headers or {}

# helper: ritorna sempre str ed evita errori di typing con Pylance
def _attr(tag: Any, key: str) -> str:   # noqa: ANN401 (bs4 non ha stub preciso)
    val = tag.get(key)
    return str(val) if val is not None else ""

# humanize produce "14 Bytes": converte in "14 B" per i test
def _hr_size(num_bytes: int) -> str:
    """Restituisce una stringa breve (es. 14 B, 16.2 KB, 2.1 MB)."""
    s = humanize.naturalsize(num_bytes, binary=True)
    return s.replace("Bytes", "B").replace("Byte", "B")


async def _fetch(session: aiohttp.ClientSession, url: str, timeout: int) -> HttpResponse:
    try:
        async with session.get(
            url,
            timeout=ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as r:
            text = await r.text("utf-8", errors="ignore")
            return HttpResponse(
                body=text,
                status=r.status,
                url=str(r.url),
                headers=dict(r.headers),
            )
    except Exception:
        return HttpResponse("", 0, url)


async def fetch_page(url: str, timeout: int = 10) -> HttpResponse:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        headers = {"User-Agent": "SilentFrog/1.0 (+https://example.com)"}
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        async with aiohttp.ClientSession(headers=headers, connector=connector) as sess:
            return await _fetch(sess, url, timeout)


async def _image_info(session: aiohttp.ClientSession, url: str, timeout: int):
    try:
        async with session.get(url, timeout=ClientTimeout(total=timeout)) as r:
            raw = await r.read()

        size_b = len(raw)
        try:
            w, h = Image.open(BytesIO(raw)).size
        except Exception:                      # immagine non valida
            w, h = 0, 0

        return url, w, h, _hr_size(size_b)
    except Exception as exc:                   # es. connessione fallita
        # mantieni “Errore” per il test e per la GUI
        return "Errore", 0, 0, ""


async def _link_status(session: ClientSession, url: str, timeout: int) -> int:
    try:
        async with session.head(url, timeout=ClientTimeout(total=timeout)) as r:
            return r.status
    except Exception:
        return 0

# ── robots.txt helper ───────────────────────────────────────────────────
async def _fetch_robots(url: str, timeout: int = 5) -> str | None:
    """Return robots.txt text or None on network failure."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                robots_url,
                timeout=ClientTimeout(total=timeout),
            ) as r:
                return await r.text()
    except Exception:
        return None


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

# ── canonical helper ──────────────────────────────────────────────────────────
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

# ── hreflang helper ────────────────────────────────────────────────────
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
    rels: dict[str, str] = {}          # lang → url
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

# ── AI-crawl helper ─────────────────────────────────────────────────────
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


# ── SERP preview helper ────────────────────────────────────────────────
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
    description = shorten(description, width=155, placeholder="…")
    return {
        "title": title,
        "description": description,
        "display_url": urlparse(page_url).netloc.replace("www.", "") + "/…",
    }

# ── Title audit helper ──────────────────────────────────────────────────
_MEAN_PX = 7.2           # average desktop pixel width per glyph

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



# ── redirect-chain helper ───────────────────────────────────────────────
async def _trace_redirects(url: str, timeout: int = 8) -> tuple[list[str], str, int, bool]:
    """
    Follow HEAD requests (max 6 hops) and return:
        • list of hop URLs  (including start & each Location)
        • final_status      (string)
        • hops              (int)
        • is_loop           (bool)  True if any URL repeats
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
    for tag in soup.find_all("meta"):
        name = _attr(tag, "name") or _attr(tag, "property")
        content = _attr(tag, "content")
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
    for tag in soup.find_all("img"):
        img = cast(bs4.element.Tag, tag)          # typing safe
        src   = urljoin(base, _attr(img, "src"))
        alt   = _attr(img, "alt")
        title = _attr(img, "title")
        rows.append([src, alt, title, "", "", ""])   # peso/size TBD
    return rows


def _extract_links(base: str, soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    for raw in soup.find_all("a", href=True):
        a = cast(bs4.element.Tag, raw)
        href_val = _attr(a, "href")
        href = urljoin(base, href_val)
        rel_val: Any = a.get("rel")                        # ← ② default None OK
        rel = rel_val if isinstance(rel_val, list) else [] # lista sicura
        nf  = "nofollow" in rel
        same_host = urlparse(href).netloc == urlparse(base).netloc
        typ = "Interno" if same_host else "Esterno"
        
        out.append([href, typ, "NoFollow" if nf else "Follow", ""])  # status later
    return out


def _extract_schema_all(html_text: str, response_url: str) -> list[Any]:
    """
    Schema.org extraction (robust, logged, still lightweight):
      • JSON-LD manual harvest FIRST (so JSON-LD items stay first in output)
      • extruct pass (lxml) → retry with html5lib tree if needed
      • Flatten JSON-LD @graph; keep malformed blocks as {"@raw": "..."}
      • Heuristic discovery inside generic JSON (e.g. __NEXT_DATA__, __NUXT__)
      • Append {"_schema_issues":[...]} with concise hints
    RDFa intentionally excluded.
    """
    # Ask extruct for every lightweight syntax, including RDFa.
    syntaxes = ["json-ld", "microdata", "opengraph", "microformat", "rdfa"]
    collected: list[dict] = []
    seen: set[str] = set()

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
        o = dict(obj); o["_extracted_via"] = via
        collected.append(o)

    def _scrub_jsonish(s: str) -> str:
        """Make common broken JSON parseable (BOM, HTML/JS comments, trailing commas)."""
        s = s.lstrip("\ufeff").strip()
        s = re.sub(r"(?s)<!--.*?-->", "", s)           # HTML comments
        s = re.sub(r"(?s)/\*.*?\*/", "", s)            # /* block comments */
        s = re.sub(r"(?m)^\s*//.*$", "", s)            # // line comments
        s = re.sub(r",\s*([}\]])", r"\1", s)           # trailing commas
        return s

    def _safe_load(s: str) -> Any:
        """Try strict JSON, then scrubbed, then HTML-unescaped → scrubbed."""
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
    # Covers __NEXT_DATA__, window.__NUXT__ = {...}, CMS blobs, etc.
    try:
        soup2 = BeautifulSoup(html_text, "html.parser")
        hits = 0
        for node in soup2.find_all("script"):
            if not isinstance(node, Tag):
                continue
            raw = (node.string or node.get_text() or "").strip()
            if not raw or ("@context" not in raw and "@type" not in raw):
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

    # --- 2) extruct passes (lxml → html5lib) ---------------------------------
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
    have_rdfa  = any(isinstance(o, dict) and o.get("_extracted_via") == "rdfa"      for o in collected)
    if not have_micro:
        for item in _microdata_bs(soup_md):
            _add_flat(item, "microdata")
        _log_schema("fallback: microdata added")
    if not have_rdfa:
        for item in _rdfa_bs(soup_md):
            _add_flat(item, "rdfa")
        _log_schema("fallback: rdfa added")


    # --- 3) Issue summary (explicit; no Pylance “unused expression”) ----------
    issues: list[str] = []
    for obj in collected:
        via = str(obj.get("_extracted_via", ""))
        if via in ("json-ld", "json-ld-raw"):
            checks = [
                ("@raw" in obj, "Unparseable JSON-LD block"),
                ("@context" not in obj and "@raw" not in obj, "JSON-LD missing @context"),
                ("@type" not in obj and "@raw" not in obj, "JSON-LD missing @type"),
            ]
            issues.extend([msg for cond, msg in checks if cond])
        if via == "microdata" and "@type" not in obj:
            issues.append("Microdata item missing @type")
        if via == "rdfa" and "@type" not in obj:
            issues.append("RDFa item missing @type")
    if issues:
        collected.append({"_schema_issues": sorted(set(issues))})

    # --- 4) Last resort: raw JSON-LD scripts if everything else failed --------
    if collected:
        return collected
    soup = BeautifulSoup(html_text, "html.parser")
    out: list[list[str]] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.get_text(strip=True) or ""
        if raw:
            out.append([raw])
    return out


def _extract_keywords(text: str, top_n: int = 30) -> list[list[str]]:
    text = unescape(text.lower())
    text = re.sub(r"[{}]".format(re.escape(string.punctuation)), " ", text)
    tokens = [t for t in text.split() if t not in STOP and len(t) > 2]

    def ngram(n: int) -> list[list[str]]:
        counts = Counter(" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1))
        return [[k, str(v)] for k, v in counts.most_common(top_n)]

    return ngram(1) + [["", ""]] + ngram(2) + [["", ""]] + ngram(3)


# --------------------------------------------------------------------- #
async def analyse(url: str, timeout: int = 10) -> dict[str, Any]:
    resp = await fetch_page(url, timeout)
    soup = BeautifulSoup(resp.body, "html.parser")
    schema_rows = _extract_schema_all(resp.body, resp.url)
    # rimuovi commenti e script/style per trovare keyword
    for tag in soup.find_all(["script", "style"]):
        tag.extract()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    plain = soup.get_text(separator=" ", strip=True)
    
    # estrae le righe “grezze” (status ancora vuoto)
    links_rows: list[list[str]] = _extract_links(resp.url, soup)

    # recupera in parallelo gli HTTP status
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as _sess:
        coros = [_link_status(_sess, row[0], timeout) for row in links_rows]
        statuses = await asyncio.gather(*coros, return_exceptions=True)

    # riempie la 4ª colonna di ogni riga
    for row, st in zip(links_rows, statuses):
        row[3] = str(st if isinstance(st, int) else 0)

    canonical_url, is_self, many_canon, canon_status = await _check_canonical(
    resp.url, soup, timeout=timeout
    )

    # --- Redirect chain -------------------------------------------------
    hops, final_status, hop_count, is_loop = await _trace_redirects(url)

    hreflang_rows = await _extract_hreflang(resp.url, soup, timeout=timeout)
    
    meta_robots = resp.headers.get("X-Robots-Tag", "") or next(
        (m[1] for m in _extract_meta(soup) if m[0].lower() == "robots"), ""
    )

    robots_map = await _parse_robots(url, timeout=timeout)
    ai_rows = _ai_crawl_matrix(robots_map, meta_robots, resp.url)
    serp_preview = _serp_preview(resp.url, soup)
    title_audit = _title_audit(serp_preview["title"], _extract_headers(soup))

    # -- SERP helper ----------------------------------------------------------------
    from urllib.parse import urlparse, unquote

    async def _make_serp_snippet(soup: BeautifulSoup, page_url: str) -> dict[str, str]:
            async def _to_data_uri(img_url: str) -> str:
                """Download *img_url* and return a data-URI.
                Falls back to the original URL on error."""
                try:
                    async with aiohttp.ClientSession() as _s:
                        async with _s.get(img_url, timeout=5) as _r:
                            if _r.status == 200:
                                raw = await _r.read()
                                with Image.open(BytesIO(raw)).convert("RGBA") as im:
                                    im = im.resize((16, 16), _LANCZOS)
                                    mask = Image.new("L", (16, 16), 0)
                                    ImageDraw.Draw(mask).ellipse((0, 0, 16, 16), fill=255)
                                    im.putalpha(mask)
                                    buf = BytesIO()
                                    im.save(buf, format="PNG")
                                    raw = buf.getvalue()
                                return f"data:image/png;base64,{b64encode(raw).decode()}"
                except Exception:
                    pass
                return img_url

            parsed = urlparse(page_url)
            domain = parsed.netloc

            site_name = ""
            og_site = soup.find("meta", property="og:site_name")
            if isinstance(og_site, Tag):
                site_name = _attr(og_site, "content").strip()
            if not site_name and domain:
                parts = domain.split(".")
                site_name = parts[-2].capitalize() if len(parts) >= 2 else domain.capitalize()

            title_tag = soup.title
            raw_title = ""
            if isinstance(title_tag, Tag):
                raw_title = (title_tag.string or "").strip()

            _MAX_PX = 600
            _CHAR_LIMIT = int(_MAX_PX / _MEAN_PX)
            title = (
                raw_title[: _CHAR_LIMIT - 1].rstrip() + "…"
                if len(raw_title) > _CHAR_LIMIT
                else raw_title
            )

            path = unquote(parsed.path.strip("/")).replace("/", " › ")
            breadcrumb = f"{domain} › {path}" if path else domain

            desc_tag = (
                soup.find("meta", attrs={"name": "description"})
                or soup.find("meta", property="og:description")
            )
            raw_desc = ""
            if isinstance(desc_tag, Tag):
                raw_desc = _attr(desc_tag, "content").strip()
            description = (raw_desc[:157] + "…") if len(raw_desc) > 160 else raw_desc

            favicon_tag = soup.find("link", rel=lambda val: isinstance(val, str) and "icon" in val.lower())
            favicon = f"https://www.google.com/s2/favicons?sz=48&domain={domain}"
            if isinstance(favicon_tag, Tag):
                href_val = _attr(favicon_tag, "href").strip()
                if href_val:
                    favicon = urljoin(page_url, href_val)

            return {
                "title": title,
                "description": (description[:157] + "…") if len(description) > 160 else description,
                "url": page_url,
                "site_name": site_name,
                "favicon": await _to_data_uri(favicon),
                "breadcrumb": breadcrumb,
            }

    # costruisce il risultato finale
    return {
        "meta":     _extract_meta(soup),
        "headers":  _extract_headers(soup),
        "images":   _extract_images(resp.url, soup),
        "links":    links_rows,
        "schema":   schema_rows,
        "canonical": {
            "target": canonical_url,
            "self":   is_self,
            "multiple": many_canon,
            "status": canon_status,
        },
        "redirect": {
            "hops": hop_count,
            "chain": hops,
            "final_status": final_status,
            "loop": is_loop,
        },
        "robots":  await _parse_robots(resp.url, timeout=timeout),   # full UA map
        "meta_robots":  resp.headers.get("X-Robots-Tag", "") or
                        next((m[1] for m in _extract_meta(soup)
                            if m[0].lower() == "robots"), ""),
        "hreflang": hreflang_rows,
        "ai_crawl": ai_rows,
        "serp":      await _make_serp_snippet(soup, resp.url),
        "serp_audit": title_audit,
        "keywords": _extract_keywords(plain),
  
    }


async def analyse_images(base: str, rows: list[list[str]], timeout=10):
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        coros = [
            _image_info(sess, urljoin(base, row[0]), timeout)   # <-- fix
            for row in rows
        ]
        out = await asyncio.gather(*coros, return_exceptions=True)

    result: list[list[str]] = []
    for o in out:
        if isinstance(o, Exception):
            # mantieni l’URL originale se possibile per
            # facilitare il debug: lo ricavo dal messaggio d’errore
            msg = str(o)
            url = msg.split(" ", 1)[0] if "http" in msg else "Errore"
            result.append([url, "", "", ""])
        else:
            url, w, h, hr = cast(tuple[str, int, int, str], o)
            result.append([url, str(w), str(h), hr])

    return result