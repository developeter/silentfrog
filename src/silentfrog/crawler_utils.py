from __future__ import annotations
from typing import Any

import humanize  # type: ignore


def _attr(tag: Any, key: str) -> str:
    value = tag.get(key)
    return str(value) if value is not None else ""


def _hr_size(num_bytes: int) -> str:
    pretty = humanize.naturalsize(num_bytes, binary=True)
    return pretty.replace("Bytes", "B").replace("Byte", "B")
