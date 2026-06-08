"""Google-AI-Optimization-Guide-aligned structure signals (M2 of GEO).

Counts semantic HTML landmarks, internal/external links, and image
alt-text coverage. Feeds three myth-flagged check_keys:

- ``structure_semantic_html`` → Topic clarity area
- ``structure_internal_links`` → Citation readiness area
- ``citation_images_alt`` → Citation readiness area

All three follow the §1.5 rule: absent => "info" (mapped to "good"),
present => "good". They never emit warning or critical.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import bs4
from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

Tag = bs4.element.Tag

_SEMANTIC_TAGS = ("article", "section", "main", "nav", "header", "footer")
_MIN_SEMANTIC_DENSITY = 2  # at least 2 distinct semantic landmark types
_MIN_INTERNAL_LINKS = 3


@dataclass(frozen=True)
class StructurePayload:
    semantic_container_counts: dict[str, int] = field(default_factory=dict)
    internal_link_count: int = 0
    total_link_count: int = 0
    images_with_alt: int = 0
    images_total: int = 0

    @classmethod
    def empty(cls) -> StructurePayload:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_container_counts": dict(self.semantic_container_counts),
            "internal_link_count": self.internal_link_count,
            "total_link_count": self.total_link_count,
            "images_with_alt": self.images_with_alt,
            "images_total": self.images_total,
        }

    @classmethod
    def from_raw(cls, value: Any) -> StructurePayload:
        if not isinstance(value, Mapping):
            return cls.empty()
        counts_raw = value.get("semantic_container_counts", {})
        counts = {str(k): int(v) for k, v in counts_raw.items()} if isinstance(counts_raw, Mapping) else {}
        return cls(
            semantic_container_counts=counts,
            internal_link_count=int(value.get("internal_link_count", 0) or 0),
            total_link_count=int(value.get("total_link_count", 0) or 0),
            images_with_alt=int(value.get("images_with_alt", 0) or 0),
            images_total=int(value.get("images_total", 0) or 0),
        )


def _semantic_counts(soup: BeautifulSoup) -> dict[str, int]:
    return {tag: len(soup.find_all(tag)) for tag in _SEMANTIC_TAGS}


def _link_counts(soup: BeautifulSoup, page_url: str) -> tuple[int, int]:
    page_host = urlparse(page_url).netloc.lower()
    total = 0
    internal = 0
    for link in soup.find_all("a"):
        if not isinstance(link, Tag):
            continue
        href = (link.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        total += 1
        target_host = urlparse(href).netloc.lower()
        if not target_host or target_host == page_host:
            internal += 1
    return internal, total


def _image_alt_counts(soup: BeautifulSoup) -> tuple[int, int]:
    images = [tag for tag in soup.find_all("img") if isinstance(tag, Tag)]
    total = len(images)
    with_alt = sum(1 for img in images if (img.get("alt") or "").strip())
    return with_alt, total


def extract_structure_signals(soup: BeautifulSoup, page_url: str) -> StructurePayload:
    internal_links, total_links = _link_counts(soup, page_url)
    with_alt, total_images = _image_alt_counts(soup)
    return StructurePayload(
        semantic_container_counts=_semantic_counts(soup),
        internal_link_count=internal_links,
        total_link_count=total_links,
        images_with_alt=with_alt,
        images_total=total_images,
    )


def _semantic_density(counts: Mapping[str, int]) -> int:
    return sum(1 for value in counts.values() if value > 0)


def _semantic_status(payload: StructurePayload) -> str:
    # Myth-flagged: never warning. Good if at least _MIN_SEMANTIC_DENSITY
    # distinct landmark tags are present; otherwise info.
    return "good" if _semantic_density(payload.semantic_container_counts) >= _MIN_SEMANTIC_DENSITY else "info"


def _internal_links_status(payload: StructurePayload) -> str:
    return "good" if payload.internal_link_count >= _MIN_INTERNAL_LINKS else "info"


def _images_alt_status(payload: StructurePayload) -> str:
    if payload.images_total == 0:
        return "info"
    ratio = payload.images_with_alt / payload.images_total
    return "good" if ratio >= 0.9 else "info"


_CHECK_TITLES = {
    "structure_semantic_html": (
        "Topic clarity",
        "Page uses semantic HTML landmarks",
        "Structure the page with semantic landmarks (article, section, main, nav, header, footer). "
        "Per Google's AI Optimization Guide, semantic HTML aids machine understanding without any "
        "AI-specific markup.",
    ),
    "structure_internal_links": (
        "Citation readiness",
        "Page links to related internal content",
        "Add a small set of contextual internal links to deeper or related content. "
        "Per Google's AI Optimization Guide, internal architecture that helps crawlers and readers "
        "is part of standard SEO hygiene.",
    ),
    "citation_images_alt": (
        "Citation readiness",
        "Content images carry meaningful alt text",
        "Describe each content image with alt text. Per Google's AI Optimization Guide, image SEO "
        "is part of standard hygiene; the detailed audit lives in the Images tab.",
    ),
}


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    area, title, recommendation = _CHECK_TITLES[key]
    return AiVisibilityCheck(
        area=area,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _semantic_detail(payload: StructurePayload) -> str:
    counts = payload.semantic_container_counts
    parts = [f"{tag}={counts.get(tag, 0)}" for tag in _SEMANTIC_TAGS]
    return f"Landmark counts: {', '.join(parts)}; distinct landmark types: {_semantic_density(counts)}."


def _internal_links_detail(payload: StructurePayload) -> str:
    return (
        f"Internal links: {payload.internal_link_count}; Total links: {payload.total_link_count}; "
        f"Minimum recommended: {_MIN_INTERNAL_LINKS}."
    )


def _images_alt_detail(payload: StructurePayload) -> str:
    if payload.images_total == 0:
        return "No <img> elements detected on the page."
    return (
        f"Images with alt text: {payload.images_with_alt}/{payload.images_total} "
        f"({payload.images_with_alt / payload.images_total:.0%})."
    )


def build_structure_checks(payload: StructurePayload) -> list[AiVisibilityCheck]:
    return [
        _check("structure_semantic_html", _semantic_status(payload), _semantic_detail(payload)),
        _check("structure_internal_links", _internal_links_status(payload), _internal_links_detail(payload)),
        _check("citation_images_alt", _images_alt_status(payload), _images_alt_detail(payload)),
    ]


__all__ = [
    "StructurePayload",
    "build_structure_checks",
    "extract_structure_signals",
]
