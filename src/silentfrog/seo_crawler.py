"""
Motore asincrono per l’analisi SEO di una singola pagina.
Ritorna un dict con chiavi:
  meta, headers, images, links, schema, keywords
Tutte le funzioni sono pure e testabili.
"""

from __future__ import annotations
from urllib.parse import urljoin, urlparse

from io import BytesIO
from typing import Any, Dict, List, cast
from aiohttp import ClientTimeout
from collections import Counter
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from bs4 import BeautifulSoup, Comment
from nltk.corpus import stopwords

from typing import Any, Dict, List, cast
from PIL import Image                     # pillow
import humanize

import asyncio

import re
import ssl
import string

import bs4                      

import aiohttp


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
    body: str
    status: int
    url: str


# --------------------------------------------------------------------- #

# helper: ritorna sempre str ed evita errori di typing con Pylance
def _attr(tag: Any, key: str) -> str:   # noqa: ANN401 (bs4 non ha stub preciso)
    val = tag.get(key)
    return str(val) if val is not None else ""

# humanize produce "14 Bytes": converte in "14 B" per i test
def _hr_size(num_bytes: int) -> str:
    s = humanize.naturalsize(num_bytes, binary=True)
    return s.replace("Bytes", "B")       # es. "14 Bytes" → "14 B"


async def _fetch(session: aiohttp.ClientSession, url: str, timeout: int) -> HttpResponse:
    try:
        async with session.get(
            url,
            timeout=ClientTimeout(total=timeout),
            allow_redirects=True,
        ) as r:
            text = await r.text("utf-8", errors="ignore")
            return HttpResponse(text, r.status, str(r.url))
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


def _extract_schema(soup: BeautifulSoup) -> list[list[str]]:
    out: list[list[str]] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.get_text(strip=True)            # -> sempre str
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
async def analyse(url: str, timeout: int = 10) -> Dict[str, List[List[str]]]:
    resp = await fetch_page(url, timeout)
    soup = BeautifulSoup(resp.body, "html.parser")
    schema_rows = _extract_schema(soup)
    # rimuovi commenti e script/style per trovare keyword
    for tag in soup.find_all(["script", "style"]):
        tag.extract()
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        c.extract()
    plain = soup.get_text(separator=" ", strip=True)

    return {
        "meta": _extract_meta(soup),
        "headers": _extract_headers(soup),
        "images": _extract_images(resp.url, soup),
        "links": _extract_links(resp.url, soup),
        "schema": schema_rows,
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

    return result            # <-- assicurati che la funzione ritorni SEMPRE
