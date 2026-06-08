"""SEO-basics signals (v1.1 N2) sourced from the `seo` Claude skill.

Adds two new check_keys:

- ``seo_viewport_mobile`` — `<meta name="viewport" content="...width=device-width...">`
- ``seo_descriptive_url`` — heuristic on the URL slug shape

Both follow the v1.1 §1.5 myth pattern (absent → info, never warning).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import bs4
from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

Tag = bs4.element.Tag

# Slug heuristics: lowercase, no UUIDs, no ≥ 4 consecutive digits, no
# query strings dominating the path, length cap.
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_FOUR_DIGIT_RE = re.compile(r"\d{4,}")


@dataclass(frozen=True)
class SeoBasicsPayload:
    viewport_present: bool = False
    viewport_content: str = ""
    descriptive_url: bool = False
    url_path: str = ""

    @classmethod
    def empty(cls) -> SeoBasicsPayload:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "viewport_present": self.viewport_present,
            "viewport_content": self.viewport_content,
            "descriptive_url": self.descriptive_url,
            "url_path": self.url_path,
        }

    @classmethod
    def from_raw(cls, value: Any) -> SeoBasicsPayload:
        if not isinstance(value, dict):
            return cls.empty()
        return cls(
            viewport_present=bool(value.get("viewport_present", False)),
            viewport_content=str(value.get("viewport_content", "")),
            descriptive_url=bool(value.get("descriptive_url", False)),
            url_path=str(value.get("url_path", "")),
        )


def detect_viewport(soup: BeautifulSoup) -> tuple[bool, str]:
    """Return (present, content) for the viewport meta tag."""
    tag = soup.find("meta", attrs={"name": "viewport"})
    if not isinstance(tag, Tag):
        return False, ""
    content = (tag.get("content") or "").strip()
    if not content:
        return False, ""
    is_responsive = "width=device-width" in content.replace(" ", "").lower()
    return is_responsive, content


def descriptive_url_slug(page_url: str) -> tuple[bool, str]:
    """Heuristic: a slug is descriptive when lowercase, no UUIDs,
    no ≥ 4 consecutive digit runs (1234567 looks like an ID), and
    no longer than 80 chars.

    Returns ``(is_descriptive, path)``.
    """
    parsed = urlparse(page_url)
    path = parsed.path or "/"
    if path == "/" or len(path) <= 1:
        return True, path  # root URL — trivially descriptive
    if len(path) > 80:
        return False, path
    if _UUID_RE.search(path):
        return False, path
    if _FOUR_DIGIT_RE.search(path):
        return False, path
    if path != path.lower():
        return False, path
    return True, path


def extract_seo_basics(soup: BeautifulSoup, page_url: str) -> SeoBasicsPayload:
    present, content = detect_viewport(soup)
    descriptive, path = descriptive_url_slug(page_url)
    return SeoBasicsPayload(
        viewport_present=present,
        viewport_content=content,
        descriptive_url=descriptive,
        url_path=path,
    )


_CHECK_META: dict[str, tuple[str, str, str]] = {
    "seo_viewport_mobile": (
        "Topic clarity",
        "Page declares a mobile-responsive viewport",
        'Add `<meta name="viewport" content="width=device-width, initial-scale=1">` in '
        "<head>. Per Google Search Central, this is a Lighthouse high-priority SEO check.",
    ),
    "seo_descriptive_url": (
        "Topic clarity",
        "URL slug looks descriptive (no UUIDs, lowercase, no long digit runs)",
        "Use lowercase, hyphen-separated slugs that describe the content. Per the Addy Osmani "
        "web-quality SEO checklist, descriptive URLs sit in the 'high' tier of technical SEO.",
    ),
}


def _check(key: str, status: str, detail: str) -> AiVisibilityCheck:
    area, title, recommendation = _CHECK_META[key]
    return AiVisibilityCheck(
        area=area,
        check=title,
        status=status,
        details=detail,
        recommendation=recommendation,
        key=key,
    )


def _viewport_status(payload: SeoBasicsPayload) -> tuple[str, str]:
    if payload.viewport_present:
        return "good", f"viewport content: {payload.viewport_content}"
    return "info", "No mobile-responsive viewport meta tag detected."


def _slug_status(payload: SeoBasicsPayload) -> tuple[str, str]:
    if payload.descriptive_url:
        return "good", f"URL slug: {payload.url_path}"
    return "info", f"URL slug: {payload.url_path} — contains a UUID, long digit run, or uppercase."


def build_seo_basics_checks(payload: SeoBasicsPayload) -> list[AiVisibilityCheck]:
    rows: list[AiVisibilityCheck] = []
    for key, status_fn in (
        ("seo_viewport_mobile", _viewport_status),
        ("seo_descriptive_url", _slug_status),
    ):
        status, detail = status_fn(payload)
        rows.append(_check(key, status, detail))
    return rows


__all__ = [
    "SeoBasicsPayload",
    "build_seo_basics_checks",
    "descriptive_url_slug",
    "detect_viewport",
    "extract_seo_basics",
]
