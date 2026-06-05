"""E-E-A-T signal extraction for the GEO roadmap (M2).

Extracts author byline, publish/update dates, author bio links, and
external citations from the page DOM and JSON-LD schema. Feeds the
``E-E-A-T`` area of the AI Visibility tab.

The myth-flagged check ``eeat_external_citations`` follows the §1.5
rule (absent => info, never warning) — see ``docs/geo_roadmap.md``.
The other four E-E-A-T checks may warn because they reflect concrete
best practices, not Google "not required" myths.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import bs4
from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

Tag = bs4.element.Tag

_DEFAULT_FRESHNESS_DAYS = 365
_BIO_PATH_HINTS = ("/about", "/author", "/team", "/staff", "/profile", "/chi-siamo")
_SOCIAL_HOSTS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
)


def _freshness_threshold_days() -> int:
    raw = os.environ.get("SILENTFROG_EEAT_FRESHNESS_DAYS", "").strip()
    if not raw:
        return _DEFAULT_FRESHNESS_DAYS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_FRESHNESS_DAYS
    return max(value, 1)


@dataclass(frozen=True)
class EeatPayload:
    byline: str = ""
    publish_date: str = ""
    update_date: str = ""
    days_since_update: int = -1
    author_bio_url: str = ""
    same_as: tuple[str, ...] = ()
    external_citations: tuple[str, ...] = ()

    @classmethod
    def empty(cls) -> "EeatPayload":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "byline": self.byline,
            "publish_date": self.publish_date,
            "update_date": self.update_date,
            "days_since_update": self.days_since_update,
            "author_bio_url": self.author_bio_url,
            "same_as": list(self.same_as),
            "external_citations": list(self.external_citations),
        }

    @classmethod
    def from_raw(cls, value: Any) -> "EeatPayload":
        if not isinstance(value, Mapping):
            return cls.empty()
        same_as = tuple(_string_tuple(value.get("same_as")))
        citations = tuple(_string_tuple(value.get("external_citations")))
        return cls(
            byline=str(value.get("byline", "")),
            publish_date=str(value.get("publish_date", "")),
            update_date=str(value.get("update_date", "")),
            days_since_update=int(value.get("days_since_update", -1) or -1),
            author_bio_url=str(value.get("author_bio_url", "")),
            same_as=same_as,
            external_citations=citations,
        )


def _string_tuple(value: Any) -> Iterable[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _article_blocks(schema: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(schema, Mapping):
        return []
    blocks = schema.get("blocks", [])
    if not isinstance(blocks, Iterable):
        return []
    out: list[Mapping[str, Any]] = []
    article_types = {"article", "newsarticle", "blogposting"}
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        raw_type = block.get("@type", "")
        if isinstance(raw_type, list):
            primary = str(raw_type[0]) if raw_type else ""
        else:
            primary = str(raw_type)
        if primary.casefold() in article_types:
            out.append(block)
    return out


def _person_blocks(schema: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(schema, Mapping):
        return []
    blocks = schema.get("blocks", [])
    if not isinstance(blocks, Iterable):
        return []
    out: list[Mapping[str, Any]] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        raw_type = block.get("@type", "")
        primary = str(raw_type[0]) if isinstance(raw_type, list) and raw_type else str(raw_type)
        if primary.casefold() == "person":
            out.append(block)
    return out


def _byline_from_schema(article_blocks: Iterable[Mapping[str, Any]]) -> str:
    for block in article_blocks:
        author = block.get("author")
        name = _author_name(author)
        if name:
            return name
    return ""


def _author_name(author: Any) -> str:
    if isinstance(author, Mapping):
        return str(author.get("name", "")).strip()
    if isinstance(author, list):
        for item in author:
            name = _author_name(item)
            if name:
                return name
    if isinstance(author, str):
        return author.strip()
    return ""


def _byline_from_dom(soup: BeautifulSoup) -> str:
    # rel="author" link
    author_link = soup.find("a", attrs={"rel": "author"})
    if isinstance(author_link, Tag):
        text = (author_link.get_text() or "").strip()
        if text:
            return text
    # itemprop="author"
    itemprop = soup.find(attrs={"itemprop": "author"})
    if isinstance(itemprop, Tag):
        name = itemprop.find(attrs={"itemprop": "name"})
        if isinstance(name, Tag):
            text = (name.get_text() or "").strip()
            if text:
                return text
        text = (itemprop.get_text() or "").strip()
        if text:
            return text
    # <address> element inside <article>
    address = soup.find("address")
    if isinstance(address, Tag):
        text = (address.get_text() or "").strip()
        if text:
            return text
    return ""


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: name})
            if isinstance(tag, Tag):
                value = (tag.get("content") or "").strip()
                if value:
                    return str(value)
    return ""


def _time_attr(soup: BeautifulSoup, kind: str) -> str:
    for time_tag in soup.find_all("time"):
        if not isinstance(time_tag, Tag):
            continue
        itemprop = (time_tag.get("itemprop") or "").lower()
        klass = " ".join(time_tag.get("class") or []).lower()
        if kind == "published" and ("published" in itemprop or "publish" in klass or "datepublished" in itemprop):
            return str(time_tag.get("datetime") or "").strip()
        if kind == "modified" and ("modified" in itemprop or "updated" in klass or "datemodified" in itemprop):
            return str(time_tag.get("datetime") or "").strip()
    return ""


def _publish_date(soup: BeautifulSoup, article_blocks: Iterable[Mapping[str, Any]]) -> str:
    for block in article_blocks:
        value = str(block.get("datePublished") or "").strip()
        if value:
            return value
    meta_value = _meta_content(soup, "article:published_time", "datePublished", "publish_date")
    if meta_value:
        return meta_value
    return _time_attr(soup, "published")


def _update_date(soup: BeautifulSoup, article_blocks: Iterable[Mapping[str, Any]]) -> str:
    for block in article_blocks:
        value = str(block.get("dateModified") or "").strip()
        if value:
            return value
    meta_value = _meta_content(soup, "article:modified_time", "dateModified", "last_modified")
    if meta_value:
        return meta_value
    return _time_attr(soup, "modified")


def _days_since(value: str) -> int:
    if not value:
        return -1
    parsed = _parse_iso_date(value)
    if parsed is None:
        return -1
    today = date.today()
    delta = (today - parsed).days
    return max(delta, 0)


def _parse_iso_date(value: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    # Try full ISO datetime first
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _bio_url_from_schema(person_blocks: Iterable[Mapping[str, Any]]) -> str:
    for person in person_blocks:
        url = str(person.get("url") or "").strip()
        if url:
            return url
    return ""


def _bio_url_from_dom(soup: BeautifulSoup) -> str:
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = (link.get("href") or "").strip()
        if not href:
            continue
        path = urlparse(href).path.lower()
        rel = " ".join(link.get("rel") or []).lower()
        if rel == "author":
            return href
        if any(hint in path for hint in _BIO_PATH_HINTS):
            return href
    return ""


def _same_as(person_blocks: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for person in person_blocks:
        same_as = person.get("sameAs")
        if isinstance(same_as, str):
            entries = [same_as]
        elif isinstance(same_as, Iterable):
            entries = [str(item) for item in same_as if isinstance(item, str)]
        else:
            entries = []
        for entry in entries:
            stripped = entry.strip()
            if stripped and stripped not in seen:
                out.append(stripped)
                seen.add(stripped)
    return tuple(out)


def _external_citations(soup: BeautifulSoup, page_url: str) -> tuple[str, ...]:
    page_host = urlparse(page_url).netloc.lower()
    if not page_host:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = (link.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:"):
            continue
        target_host = urlparse(href).netloc.lower()
        if not target_host or target_host == page_host:
            continue
        if any(social in target_host for social in _SOCIAL_HOSTS):
            continue
        if href in seen:
            continue
        out.append(href)
        seen.add(href)
    return tuple(out)


def extract_eeat_signals(
    soup: BeautifulSoup,
    schema: Mapping[str, Any] | None,
    page_url: str = "",
) -> EeatPayload:
    article_blocks = _article_blocks(schema)
    person_blocks = _person_blocks(schema)
    publish = _publish_date(soup, article_blocks)
    update = _update_date(soup, article_blocks) or publish
    byline = _byline_from_schema(article_blocks) or _byline_from_dom(soup)
    bio_url = _bio_url_from_schema(person_blocks) or _bio_url_from_dom(soup)
    return EeatPayload(
        byline=byline,
        publish_date=publish,
        update_date=update,
        days_since_update=_days_since(update),
        author_bio_url=bio_url,
        same_as=_same_as(person_blocks),
        external_citations=_external_citations(soup, page_url),
    )


_CHECK_META = {
    "eeat_author_byline": (
        "Author byline is visible on the page",
        "Show an author name near the title and link it to a stable profile.",
    ),
    "eeat_publish_date": (
        "A publication date is exposed",
        "Expose datePublished (or a visible publish date) so AI engines can attribute the page.",
    ),
    "eeat_update_freshness": (
        "Content was updated within the freshness window",
        "Refresh evergreen pages within SILENTFROG_EEAT_FRESHNESS_DAYS and expose dateModified.",
    ),
    "eeat_author_bio": (
        "Author bio or sameAs link is discoverable",
        "Link the byline to an /about page, a Person schema with sameAs, or a stable external profile.",
    ),
    "eeat_external_citations": (
        "Page cites named external sources",
        "Link to a small set of authoritative external sources where relevant. Per Google's AI Optimization Guide, "
        "QUALITY matters more than quantity; manufactured mentions do NOT help.",
    ),
}


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    title, recommendation = _CHECK_META[key]
    return AiVisibilityCheck(
        area="E-E-A-T",
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _byline_status(byline: str) -> str:
    return "good" if byline else "warning"


def _publish_status(value: str) -> str:
    return "good" if value else "warning"


def _freshness_status(days: int, threshold: int) -> str:
    if days < 0:
        return "warning"
    return "good" if days <= threshold else "warning"


def _bio_status(bio_url: str, same_as: tuple[str, ...]) -> str:
    return "good" if (bio_url or same_as) else "warning"


def _citations_status(citations: tuple[str, ...]) -> str:
    # Myth-flagged: absence => info, never warning. Presence => good.
    return "good" if citations else "info"


def build_eeat_checks(payload: EeatPayload, freshness_days: int | None = None) -> list[AiVisibilityCheck]:
    threshold = freshness_days if freshness_days is not None else _freshness_threshold_days()
    return [
        _check("eeat_author_byline", _byline_status(payload.byline), f"Byline: {payload.byline or '-'}."),
        _check(
            "eeat_publish_date",
            _publish_status(payload.publish_date),
            f"datePublished: {payload.publish_date or '-'}.",
        ),
        _check(
            "eeat_update_freshness",
            _freshness_status(payload.days_since_update, threshold),
            (
                f"dateModified: {payload.update_date or '-'}; Days since update: "
                f"{payload.days_since_update if payload.days_since_update >= 0 else '-'}; "
                f"Threshold: {threshold} days."
            ),
        ),
        _check(
            "eeat_author_bio",
            _bio_status(payload.author_bio_url, payload.same_as),
            f"Bio URL: {payload.author_bio_url or '-'}; sameAs count: {len(payload.same_as)}.",
        ),
        _check(
            "eeat_external_citations",
            _citations_status(payload.external_citations),
            f"External non-social citations: {len(payload.external_citations)}.",
        ),
    ]


__all__ = [
    "EeatPayload",
    "build_eeat_checks",
    "extract_eeat_signals",
]
