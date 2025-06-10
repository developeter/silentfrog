"""
Motore asincrono per l’analisi SEO di una singola pagina.

"""
from __future__ import annotations
from urllib.parse import urljoin, urlparse
from io import BytesIO
from collections import Counter
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from nltk.corpus import stopwords
from aiohttp import ClientTimeout, ClientSession
from typing import Any, Dict, List, cast
from PIL import Image                     # pillow
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import humanize
import asyncio
import re
import ssl
import string
import bs4
import aiohttp
import email

# ─── Safe import of extruct (fallback if lxml is broken) ──────────────────────
try:
    import extruct
    from w3lib.html import get_base_url
    USE_EXTRUCT = True
except Exception:                       # ImportError, lxml errors, etc.
    # extruct or lxml is unavailable → fall back to JSON-LD-only extractor
    USE_EXTRUCT = False
# ──────────────────────────────────────────────────────────────────────────────


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
async def _check_robots(url: str, timeout: int = 5) -> bool:
    """
    Return True if the URL is allowed for User-agent '*' according to
    the site's robots.txt.  Network errors → assume allowed.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                robots_url,
                timeout=ClientTimeout(total=timeout),   # Pylance-safe
            ) as r:
                txt = await r.text()
    except Exception:
        # Could not fetch robots.txt → be permissive
        return True

    rp = RobotFileParser()
    rp.parse(txt.splitlines())
    return rp.can_fetch("*", url)


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
    links = [l["href"].strip() for l in soup.find_all("link", rel="canonical", href=True)]
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
    If USE_EXTRUCT is True, extract JSON-LD + Microdata + RDFa + OpenGraph via Extruct.
    Otherwise, fall back to looking only for <script type="application/ld+json"> blocks.
    """
    if USE_EXTRUCT:
        # ----- full Extruct-based extraction -----
        base_url = response_url
        results = extruct.extract(
            html_text,
            base_url=base_url,
            syntaxes=["json-ld", "microdata", "rdfa", "opengraph"],
            uniform=True,
        )
        collected: list[dict] = []
        for syntax in ("json-ld", "microdata", "rdfa", "opengraph"):
            items = results.get(syntax) or []
            for item in items:
                item["_extracted_via"] = syntax
                collected.append(item)
        return collected
    else:
        # ----- fallback: only JSON-LD inside <script> tags -----
        soup = BeautifulSoup(html_text, "lxml")
        out: list[list[str]] = []
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            raw = script.get_text(strip=True) or ""
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
        "robots_allowed": await _check_robots(resp.url, timeout=timeout),
        "meta_robots":  resp.headers.get("X-Robots-Tag", "") or
                        next((m[1] for m in _extract_meta(soup)
                            if m[0].lower() == "robots"), ""),
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