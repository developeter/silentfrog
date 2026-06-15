"""Crawler fingerprinting from the User-Agent (v2.0 V13).

Identify-by-UA only (no reverse-DNS verification — that's network-bound
and belongs in a separate online check). Covers Googlebot + Bing plus
the AI bots Silentfrog already tracks in the Bot Matrix.
"""

from __future__ import annotations

# Ordered most-specific-first; matched as case-insensitive substrings.
_BOT_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("googlebot-image", "Googlebot-Image"),
    ("googlebot-news", "Googlebot-News"),
    ("googlebot", "Googlebot"),
    ("google-extended", "Google-Extended"),
    ("storebot-google", "Storebot-Google"),
    ("bingbot", "Bingbot"),
    ("gptbot", "GPTBot"),
    ("oai-searchbot", "OAI-SearchBot"),
    ("chatgpt-user", "ChatGPT-User"),
    ("claudebot", "ClaudeBot"),
    ("claude-web", "Claude-Web"),
    ("anthropic-ai", "anthropic-ai"),
    ("perplexitybot", "PerplexityBot"),
    ("amazonbot", "Amazonbot"),
    ("applebot", "Applebot"),
    ("bytespider", "Bytespider"),
    ("ccbot", "CCBot"),
    ("meta-externalagent", "Meta-ExternalAgent"),
    ("duckduckbot", "DuckDuckBot"),
    ("yandexbot", "YandexBot"),
)


def identify_bot(user_agent: str) -> str:
    """Return the normalised bot name for a UA, or "" if it's not a known
    crawler (i.e. likely a human / generic client)."""
    ua = (user_agent or "").lower()
    if not ua:
        return ""
    for needle, label in _BOT_SIGNATURES:
        if needle in ua:
            return label
    return ""


__all__ = ["identify_bot"]
