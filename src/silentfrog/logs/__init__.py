"""Server-log analysis + crawl-budget audit (v2.0 V13).

Parses access logs (Common / Combined Log Format + JSON Apache/Nginx),
fingerprints crawlers, and reports where crawl budget is wasted — the
only ground truth on what Googlebot and the AI bots actually fetch.
Pure + typed, zero new deps.
"""

from __future__ import annotations

from .bot_fingerprint import AI_KINDS, BotClassification, classify_bot, identify_bot, is_google_crawler
from .crawl_budget import CrawlBudgetReport, analyse_entries
from .parsers import LogEntry, parse_log_line, parse_log_text

__all__ = [
    "AI_KINDS",
    "BotClassification",
    "CrawlBudgetReport",
    "LogEntry",
    "analyse_entries",
    "classify_bot",
    "identify_bot",
    "is_google_crawler",
    "parse_log_line",
    "parse_log_text",
]
