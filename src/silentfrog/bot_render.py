"""Per-bot SSR rendering (v2.0 V10).

Renders the audited page once per AI/search bot user-agent through the
V4 :class:`~silentfrog.render_pool.RenderPool` and diffs each bot's
post-JS DOM against the server-rendered HTML. Divergence across bots
means the server varies content by user-agent (UA sniffing, WAF blocks,
bot-specific cloaking) — exactly what the Bot Matrix per-bot SSR column
surfaces.

Off by default (Crawl Settings checkbox), requires the ``geo-render``
extra, and only runs on profiles that render (H4: DEEP). The UA strings
below are Silentfrog's best-effort impersonation of each bot's
documented user-agent (H6: heuristic evidence — vendors change these);
robots-only tokens (Google-Extended, Applebot-Extended) never fetch in
the wild, so a synthetic ``compatible`` UA stands in for them.

The one shared pool keeps browser launches flat across pages: 19 UA
renders reuse a single Chromium, recycled every N pages by the pool.
"""

from __future__ import annotations

import atexit
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from .crawl_types import AiVisibilityCheck
from .parsers_meta import _AI_AGENTS
from .render_diff import compute_render_diff

_CHROME_SUFFIX = "AppleWebKit/537.36 (KHTML, like Gecko)"

# token -> full user-agent string. Keys MUST stay in lockstep with
# ``parsers_meta._AI_AGENTS`` (guard test pins the parity).
BOT_USER_AGENTS: dict[str, str] = {
    "gptbot": f"Mozilla/5.0 {_CHROME_SUFFIX}; compatible; GPTBot/1.2; +https://openai.com/gptbot",
    "chatgpt-user": f"Mozilla/5.0 {_CHROME_SUFFIX}; compatible; ChatGPT-User/1.0; +https://openai.com/bot",
    "oai-searchbot": f"Mozilla/5.0 {_CHROME_SUFFIX}; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot",
    "claudebot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
    ),
    "anthropic-ai": "Mozilla/5.0 (compatible; anthropic-ai/1.0; +https://www.anthropic.com)",
    "claude-web": "Mozilla/5.0 (compatible; Claude-Web/1.0; +https://www.anthropic.com)",
    "claude-user": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Claude-User/1.0; +Claude-User@anthropic.com)"
    ),
    "claude-searchbot": (
        "Mozilla/5.0 AppleWebKit/537.36 "
        "(KHTML, like Gecko; compatible; Claude-SearchBot/1.0; +Claude-SearchBot@anthropic.com)"
    ),
    "perplexitybot": (
        "Mozilla/5.0 AppleWebKit/537.36 "
        "(KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)"
    ),
    "perplexity-user": (
        "Mozilla/5.0 AppleWebKit/537.36 "
        "(KHTML, like Gecko; compatible; Perplexity-User/1.0; +https://perplexity.ai/perplexity-user)"
    ),
    "googlebot": (
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html) Chrome/125.0.0.0 Safari/537.36"
    ),
    "google-extended": "Mozilla/5.0 (compatible; Google-Extended)",
    "applebot-extended": "Mozilla/5.0 (compatible; Applebot-Extended)",
    "amazonbot": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/600.2.5 (KHTML, like Gecko) "
        "Version/8.0.2 Safari/600.2.5 (Amazonbot/0.1; +https://developer.amazon.com/support/amazonbot)"
    ),
    "bytespider": (
        "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)"
    ),
    "ccbot": "CCBot/2.0 (https://commoncrawl.org/faq/)",
    "meta-externalagent": "meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler)",
    "duckassistbot": "Mozilla/5.0 (compatible; DuckAssistBot/1.1; +http://duckduckgo.com/duckassistbot.html)",
    "cohere-ai": "Mozilla/5.0 (compatible; cohere-ai/1.0)",
}

_RENDER_TIMEOUT_SECONDS = 15

# --- shared pool (one Chromium reused across pages and bots) ----------------

_pool_lock = threading.Lock()
_pool: Any = None


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def shared_render_pool() -> Any:
    """Lazily create the process-wide V4 pool used for per-bot renders."""
    global _pool
    with _pool_lock:
        if _pool is None:
            from .render_pool import RenderPool

            _pool = RenderPool()
            atexit.register(close_shared_render_pool)
        return _pool


def close_shared_render_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


# --- payload production ------------------------------------------------------


def _diff_entry(baseline_html: str, rendered_html: str, error: str) -> dict[str, Any]:
    if error:
        return {
            "status": "warning",
            "missing_headings": [],
            "missing_main_text_chars": 0,
            "missing_links": 0,
            "reason": f"Render failed: {error}",
        }
    diff = compute_render_diff(baseline_html, rendered_html)
    return {
        "status": diff.status,
        "missing_headings": list(diff.missing_headings),
        "missing_main_text_chars": diff.missing_main_text_chars,
        "missing_links": diff.missing_links,
        "reason": diff.reason,
    }


async def render_for_bots(
    url: str,
    baseline_html: str,
    pool: Any = None,
    tokens: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Render *url* once per bot UA and diff each DOM against the SSR HTML.

    Returns a JSON-native payload: ``{"measured": bool, "reason": str,
    "bots": {token: {status, missing_headings, missing_main_text_chars,
    missing_links, reason}}}``. Never raises; when Playwright is absent
    the payload is unmeasured and the audit is unaffected.
    """
    if pool is None and not _playwright_available():
        return {"measured": False, "reason": "Playwright not installed", "bots": {}}
    active_pool = pool if pool is not None else shared_render_pool()
    bot_tokens = list(tokens) if tokens is not None else [agent.token for agent in _AI_AGENTS]
    bots: dict[str, Any] = {}
    for token in bot_tokens:
        user_agent = BOT_USER_AGENTS.get(token, f"Mozilla/5.0 (compatible; {token})")
        result = await active_pool.render(url, timeout=_RENDER_TIMEOUT_SECONDS, user_agent=user_agent)
        bots[token] = _diff_entry(baseline_html, result.rendered_html, result.error)
    return {"measured": True, "reason": "", "bots": bots}


# --- summary check ------------------------------------------------------------

_CHECK_TITLE = "AI bots receive the same rendered content"
_CHECK_RECOMMENDATION = (
    "Serve the same content to every crawler user-agent. UA-dependent responses (WAF "
    "blocks, cloaking, bot-specific templates) make AI engines see a different page "
    "than users do; the Bot Matrix SSR column shows the per-bot detail."
)


def _divergent_tokens(bots: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Tokens whose render diverges when the bots disagree with each other.

    Uniform statuses (even uniformly non-good) mean every bot sees the same
    thing — that is site-wide SSR parity territory, not per-bot divergence.
    When statuses are mixed, the affected bots are the ones whose render does
    not cleanly match the baseline — never the majority-vote complement, which
    would name the healthy bots once divergence passes 50%.
    """
    statuses = {token: str(entry.get("status", "")) for token, entry in bots.items()}
    if len(set(statuses.values())) <= 1:
        return []
    return sorted(token for token, status in statuses.items() if status != "good")


def build_bot_render_check(payload: Mapping[str, Any] | None) -> AiVisibilityCheck | None:
    """Summary Access check — ``None`` (not emitted) when the feature is off."""
    if not isinstance(payload, Mapping) or not payload.get("measured"):
        return None
    bots = payload.get("bots")
    bots_map = bots if isinstance(bots, Mapping) else {}
    divergent = _divergent_tokens(bots_map)
    failed = sorted(
        token
        for token, entry in bots_map.items()
        if isinstance(entry, Mapping) and str(entry.get("reason", "")).startswith("Render failed")
    )
    problem_tokens = sorted(set(divergent) | set(failed))
    if problem_tokens:
        return AiVisibilityCheck(
            area="Access",
            check=_CHECK_TITLE,
            status="warning",
            details=(
                f"{len(problem_tokens)} of {len(bots_map)} bots diverge from the majority "
                f"rendered view: {', '.join(problem_tokens)}."
            ),
            recommendation=_CHECK_RECOMMENDATION,
            key="access_bot_render",
        )
    return AiVisibilityCheck(
        area="Access",
        check=_CHECK_TITLE,
        status="good",
        details=f"All {len(bots_map)} audited bot user-agents received an equivalent rendered DOM.",
        recommendation=_CHECK_RECOMMENDATION,
        key="access_bot_render",
    )


__all__ = [
    "BOT_USER_AGENTS",
    "build_bot_render_check",
    "close_shared_render_pool",
    "render_for_bots",
    "shared_render_pool",
]
