from __future__ import annotations

from typing import Any, Optional

import bs4
import humanize  # type: ignore[import]  # humanize ships without typing
from bs4.element import Tag


def _attr(tag: Any, key: str) -> str:
    value = tag.get(key)
    return str(value) if value is not None else ""


def _hr_size(num_bytes: int) -> str:
    pretty = humanize.naturalsize(num_bytes, binary=True)
    return pretty.replace("Bytes", "B").replace("Byte", "B")


def safe_attr(node: Any, name: str) -> Optional[str]:
    getter = getattr(node, "get", None)
    if getter is None:
        return None
    value = getter(name)
    return str(value) if value is not None else None


def as_tag(node: Any) -> Optional[Tag]:
    return node if isinstance(node, bs4.element.Tag) else None


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())
