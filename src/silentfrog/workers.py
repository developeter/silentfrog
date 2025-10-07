from __future__ import annotations
from typing import Callable, Iterable
import asyncio
import threading

from .seo_crawler import analyse, analyse_images


def run_crawl(
    url: str,
    timeout: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
) -> threading.Thread:
    def _target() -> None:
        try:
            data = asyncio.run(analyse(url, timeout))
            on_success(data)
        except Exception as exc:  # noqa: BLE001
            on_error(str(exc))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread


def run_image_analysis(
    base: str,
    rows: Iterable[Iterable[str]],
    timeout: int,
    on_success: Callable[[list[list[str]]], None],
    on_error: Callable[[str], None],
) -> threading.Thread:
    rows_list = [list(row) for row in rows]

    def _target() -> None:
        try:
            result = asyncio.run(analyse_images(base, rows_list, timeout=timeout))
            on_success(result)
        except Exception as exc:  # noqa: BLE001
            on_error(str(exc))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread
