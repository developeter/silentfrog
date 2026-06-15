"""Server-log analysis + crawl-budget audit (v2.0 V13).

Parses access logs (Common / Combined Log Format + JSON Apache/Nginx),
fingerprints crawlers, and reports where crawl budget is wasted — the
only ground truth on what Googlebot and the AI bots actually fetch.
Pure + typed, zero new deps.
"""

from __future__ import annotations

from .bot_fingerprint import identify_bot
from .crawl_budget import CrawlBudgetReport, analyse_entries
from .parsers import LogEntry, parse_log_line, parse_log_text

__all__ = [
    "CrawlBudgetReport",
    "LogEntry",
    "analyse_entries",
    "identify_bot",
    "parse_log_line",
    "parse_log_text",
]
