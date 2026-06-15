"""Crawl-budget audit over parsed log entries (v2.0 V13).

Surfaces where bots waste fetches: 404s, redirect chains, and server
errors they hit, plus what Googlebot actually crawls. Pure + typed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from .bot_fingerprint import identify_bot
from .parsers import LogEntry


@dataclass(frozen=True)
class CrawlBudgetReport:
    total_requests: int = 0
    bot_requests: int = 0
    by_bot: dict[str, int] = field(default_factory=dict)
    by_status_class: dict[str, int] = field(default_factory=dict)
    wasted_404: int = 0
    wasted_redirect: int = 0
    server_error: int = 0
    top_404_paths: list[tuple[str, int]] = field(default_factory=list)
    googlebot_top_paths: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "total_requests": self.total_requests,
            "bot_requests": self.bot_requests,
            "by_bot": dict(self.by_bot),
            "by_status_class": dict(self.by_status_class),
            "wasted_404": self.wasted_404,
            "wasted_redirect": self.wasted_redirect,
            "server_error": self.server_error,
            "top_404_paths": [list(item) for item in self.top_404_paths],
            "googlebot_top_paths": [list(item) for item in self.googlebot_top_paths],
        }


def _status_class(status: int) -> str:
    if status <= 0:
        return "other"
    return f"{status // 100}xx"


def analyse_entries(entries: Sequence[LogEntry], top_n: int = 10) -> CrawlBudgetReport:
    by_bot: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    not_found: Counter[str] = Counter()
    googlebot_paths: Counter[str] = Counter()
    bot_requests = 0

    for entry in entries:
        bot = identify_bot(entry.user_agent)
        if bot:
            by_bot[bot] += 1
            bot_requests += 1
        status_class = _status_class(entry.status)
        by_class[status_class] += 1
        # Counts per class are derived from by_class below; here we only
        # capture the per-path detail that the class counter can't.
        if status_class == "4xx":
            not_found[entry.path] += 1
        if bot.startswith("Googlebot"):
            googlebot_paths[entry.path] += 1

    return CrawlBudgetReport(
        total_requests=len(entries),
        bot_requests=bot_requests,
        by_bot=dict(by_bot.most_common()),
        by_status_class=dict(sorted(by_class.items())),
        wasted_404=by_class.get("4xx", 0),
        wasted_redirect=by_class.get("3xx", 0),
        server_error=by_class.get("5xx", 0),
        top_404_paths=not_found.most_common(top_n),
        googlebot_top_paths=googlebot_paths.most_common(top_n),
    )


__all__ = ["CrawlBudgetReport", "analyse_entries"]
