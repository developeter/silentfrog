"""Crawler fingerprinting from the User-Agent (v2.0 V13; grown for v3 G11).

Identify-by-UA only (no reverse-DNS verification — that's network-bound
and belongs in a separate online check). Covers classic search crawlers
plus the wider AI-agent taxonomy Silentfrog tracks for log analytics.

This module is deliberately separate from ``parsers_meta._AI_AGENTS`` (the
19-bot robots-matrix scope with its own parity guard) — the log-analytics
taxonomy here is free to grow independently and is not rendered anywhere
that guard covers.

_KINDS — the four/five buckets a signature can fall into:
    ai_training  — harvests content to train a foundation model; no live
                   user request behind the fetch (GPTBot, ClaudeBot, CCBot).
    ai_assistant — fetches on behalf of a live, user-triggered chat/agent
                   turn (ChatGPT-User, Claude-User, cohere-ai).
    ai_search    — crawls/retrieves to build or serve an AI-native,
                   RAG-style answer index (OAI-SearchBot, PerplexityBot).
    search       — traditional web-search indexing; no documented AI
                   training/serving role (Googlebot, Bingbot, YandexBot).
    other        — SEO/monitoring/analytics tooling; not a search or AI
                   product (SemrushBot, AhrefsBot, MJ12bot).
"""

from __future__ import annotations

from dataclasses import dataclass

_KIND_AI_TRAINING = "ai_training"
_KIND_AI_ASSISTANT = "ai_assistant"
_KIND_AI_SEARCH = "ai_search"
_KIND_SEARCH = "search"
_KIND_OTHER = "other"

# Kinds that count as "AI agent" traffic for the log-analytics section (G11).
AI_KINDS: frozenset[str] = frozenset({_KIND_AI_TRAINING, _KIND_AI_ASSISTANT, _KIND_AI_SEARCH})


@dataclass(frozen=True)
class BotSignature:
    needle: str
    label: str
    vendor: str
    kind: str


@dataclass(frozen=True)
class BotClassification:
    label: str
    vendor: str
    kind: str


# Ordered most-specific-first; matched as case-insensitive substrings.
# Rule: if needle A contains needle B, A must sit before B (else B's match
# would shadow A's more specific UA) — pinned by
# test_bot_signature_ordering_is_specific_first.
_BOT_SIGNATURES: tuple[BotSignature, ...] = (
    BotSignature("googlebot-image", "Googlebot-Image", "Google", _KIND_SEARCH),
    BotSignature("googlebot-news", "Googlebot-News", "Google", _KIND_SEARCH),
    BotSignature("google-cloudvertexbot", "Google-CloudVertexBot", "Google", _KIND_AI_ASSISTANT),
    BotSignature("googlebot", "Googlebot", "Google", _KIND_SEARCH),
    BotSignature("google-extended", "Google-Extended", "Google", _KIND_AI_TRAINING),
    BotSignature("googleother", "GoogleOther", "Google", _KIND_SEARCH),
    BotSignature("storebot-google", "Storebot-Google", "Google", _KIND_SEARCH),
    BotSignature("bingbot", "Bingbot", "Microsoft", _KIND_SEARCH),
    BotSignature("gptbot", "GPTBot", "OpenAI", _KIND_AI_TRAINING),
    BotSignature("oai-searchbot", "OAI-SearchBot", "OpenAI", _KIND_AI_SEARCH),
    BotSignature("chatgpt-user", "ChatGPT-User", "OpenAI", _KIND_AI_ASSISTANT),
    BotSignature("claude-searchbot", "Claude-SearchBot", "Anthropic", _KIND_AI_SEARCH),
    BotSignature("claude-user", "Claude-User", "Anthropic", _KIND_AI_ASSISTANT),
    BotSignature("claudebot", "ClaudeBot", "Anthropic", _KIND_AI_TRAINING),
    BotSignature("claude-web", "Claude-Web", "Anthropic", _KIND_AI_ASSISTANT),
    BotSignature("anthropic-ai", "anthropic-ai", "Anthropic", _KIND_AI_TRAINING),
    BotSignature("perplexity-user", "Perplexity-User", "Perplexity", _KIND_AI_ASSISTANT),
    BotSignature("perplexitybot", "PerplexityBot", "Perplexity", _KIND_AI_SEARCH),
    BotSignature("amazonbot", "Amazonbot", "Amazon", _KIND_SEARCH),
    BotSignature("applebot-extended", "Applebot-Extended", "Apple", _KIND_AI_TRAINING),
    BotSignature("applebot", "Applebot", "Apple", _KIND_SEARCH),
    BotSignature("bytespider", "Bytespider", "ByteDance", _KIND_AI_TRAINING),
    BotSignature("ccbot", "CCBot", "Common Crawl", _KIND_AI_TRAINING),
    BotSignature("meta-externalfetcher", "Meta-ExternalFetcher", "Meta", _KIND_AI_ASSISTANT),
    BotSignature("meta-externalagent", "Meta-ExternalAgent", "Meta", _KIND_AI_TRAINING),
    BotSignature("facebookbot", "FacebookBot", "Meta", _KIND_OTHER),
    BotSignature("duckassistbot", "DuckAssistBot", "DuckDuckGo", _KIND_AI_ASSISTANT),
    BotSignature("duckduckbot", "DuckDuckBot", "DuckDuckGo", _KIND_SEARCH),
    BotSignature("yandexgpt", "YandexGPT", "Yandex", _KIND_AI_ASSISTANT),
    BotSignature("yandexbot", "YandexBot", "Yandex", _KIND_SEARCH),
    BotSignature("cohere-training-data-crawler", "cohere-training-data-crawler", "Cohere", _KIND_AI_TRAINING),
    BotSignature("cohere-ai", "cohere-ai", "Cohere", _KIND_AI_ASSISTANT),
    BotSignature("diffbot", "Diffbot", "Diffbot", _KIND_AI_TRAINING),
    BotSignature("youbot", "YouBot", "You.com", _KIND_AI_SEARCH),
    BotSignature("timpibot", "Timpibot", "Timpi", _KIND_AI_TRAINING),
    BotSignature("imagesiftbot", "ImagesiftBot", "Imagesift", _KIND_AI_TRAINING),
    BotSignature("petalbot", "PetalBot", "Huawei", _KIND_SEARCH),
    BotSignature("ai2bot", "AI2Bot", "Allen Institute for AI", _KIND_AI_TRAINING),
    BotSignature("omgilibot", "omgilibot", "Webz.io", _KIND_AI_TRAINING),
    BotSignature("omgili", "omgili", "Webz.io", _KIND_AI_TRAINING),
    BotSignature("webzio-extended", "Webzio-Extended", "Webz.io", _KIND_AI_TRAINING),
    BotSignature("magpie-crawler", "magpie-crawler", "Brightedge", _KIND_OTHER),
    BotSignature("awario", "Awario", "Awario", _KIND_OTHER),
    BotSignature("kangaroo bot", "Kangaroo Bot", "Kangaroo LLM", _KIND_AI_TRAINING),
    BotSignature("semrushbot", "SemrushBot", "Semrush", _KIND_OTHER),
    BotSignature("ahrefsbot", "AhrefsBot", "Ahrefs", _KIND_OTHER),
    BotSignature("mj12bot", "MJ12bot", "Majestic", _KIND_OTHER),
    BotSignature("dataforseobot", "DataForSeoBot", "DataForSEO", _KIND_OTHER),
)


def _match(user_agent: str) -> BotSignature | None:
    ua = (user_agent or "").lower()
    if not ua:
        return None
    for signature in _BOT_SIGNATURES:
        if signature.needle in ua:
            return signature
    return None


def identify_bot(user_agent: str) -> str:
    """Return the normalised bot name for a UA, or "" if it's not a known
    crawler (i.e. likely a human / generic client)."""
    match = _match(user_agent)
    return match.label if match else ""


def classify_bot(user_agent: str) -> BotClassification | None:
    """Return the (label, vendor, kind) classification for a UA, or None if
    it's not a known crawler."""
    match = _match(user_agent)
    if match is None:
        return None
    return BotClassification(label=match.label, vendor=match.vendor, kind=match.kind)


__all__ = ["AI_KINDS", "BotClassification", "BotSignature", "classify_bot", "identify_bot"]
