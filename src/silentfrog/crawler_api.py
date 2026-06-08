from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import seo_crawler
from .crawl_types import CrawlPayload

__all__ = ["CrawlResult", "ImageAnalysis", "analyse", "analyse_images"]


@dataclass(frozen=True)
class CrawlResult:
    payload: CrawlPayload

    def as_dict(self) -> dict[str, Any]:
        return self.payload.to_mapping()

    def as_payload(self) -> CrawlPayload:
        return self.payload

    def __getitem__(self, key: str) -> Any:
        return self.payload[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)


@dataclass(frozen=True)
class ImageAnalysis:
    rows: list[list[str]]

    def as_rows(self) -> list[list[str]]:
        return [list(row) for row in self.rows]

    def __iter__(self):
        yield from self.rows


async def analyse(url: str, timeout: int = 10) -> CrawlResult:
    data = await seo_crawler.analyse(url, timeout)
    return CrawlResult(payload=data)


async def analyse_images(base: str, rows: list[list[str]], timeout: int = 10) -> ImageAnalysis:
    data = await seo_crawler.analyse_images(base, rows, timeout=timeout)
    return ImageAnalysis(rows=data)
