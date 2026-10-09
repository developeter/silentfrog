"""Share one in-flight paid call between concurrent callers (INT-4, INT-5).

A site crawl audits many pages of one host/domain concurrently, and every page
asks the same host-level question (Semrush overview, AI share of voice). The
first caller starts the call; callers that arrive while it is running await the
same task instead of each spending their own paid requests.

Flights are scoped per event loop (a task cannot be awaited from another loop;
single-page and site audits each run under their own ``asyncio.run``) and
dropped as soon as they finish, so a *finished* failure is retried by the next
caller rather than cached.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

_FLIGHTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[Hashable, asyncio.Task[Any]]] = (
    weakref.WeakKeyDictionary()
)


def _retire(flights: dict[Hashable, asyncio.Task[Any]], key: Hashable, task: asyncio.Task[Any]) -> None:
    if flights.get(key) is task:
        del flights[key]
    if not task.cancelled():
        task.exception()  # mark retrieved: every waiter may have been cancelled


async def single_flight[T](key: Hashable, factory: Callable[[], Awaitable[T]]) -> T:
    """Run ``factory()`` once per (running loop, ``key``) at a time; concurrent
    callers share its result. ``asyncio.shield`` keeps one caller's
    cancellation from cancelling the call the others are waiting on."""
    loop = asyncio.get_running_loop()
    flights = _FLIGHTS.setdefault(loop, {})
    task = flights.get(key)
    if task is None:
        task = loop.create_task(factory())  # type: ignore[arg-type]
        flights[key] = task
        task.add_done_callback(lambda done, k=key, f=flights: _retire(f, k, done))
    return await asyncio.shield(task)


__all__ = ["single_flight"]
