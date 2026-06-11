from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Iterable
from typing import Any

from .crawl_options import CrawlOptions
from .seo_crawler import analyse, analyse_images
from .site_crawl_types import SiteCrawlConfig, SiteCrawlReport
from .site_crawler import crawl_site


def run_crawl(
    url: str,
    timeout: int,
    on_success: Callable[[dict], None],
    on_error: Callable[[str], None],
    options: CrawlOptions | None = None,
) -> threading.Thread:
    def _target() -> None:
        try:
            data = asyncio.run(analyse(url, timeout, options=options))
            on_success(data.to_mapping())
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


def run_site_crawl(
    config: SiteCrawlConfig,
    timeout: int,
    on_progress: Callable[[dict[str, Any]], None],
    on_success: Callable[[SiteCrawlReport], None],
    on_error: Callable[[str], None],
    store_path: str | None = None,
) -> tuple[threading.Thread, threading.Event]:
    cancel_event = threading.Event()

    def _target() -> None:
        # The SQLite store must be created AND used on this worker thread
        # (sqlite3 connections are thread-bound). The GUI later opens its
        # own read connection to the same file to load payloads on demand.
        store = _open_store(store_path)
        try:
            report = asyncio.run(
                crawl_site(
                    config,
                    timeout=timeout,
                    on_event=on_progress,
                    cancel_event=cancel_event,
                    store=store,
                )
            )
            on_success(report)
        except Exception as exc:  # noqa: BLE001
            on_error(str(exc))
        finally:
            if store is not None:
                store.close()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    return thread, cancel_event


def _open_store(store_path: str | None) -> Any:
    if not store_path:
        return None
    from .crawl_store import CrawlStore

    try:
        return CrawlStore(store_path)
    except Exception:
        return None
