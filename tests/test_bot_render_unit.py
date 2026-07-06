"""Unit tests for v2.0 V10 per-bot SSR rendering (fake pool — no Chromium)."""

from __future__ import annotations

import pytest

from silentfrog.bot_render import (
    BOT_USER_AGENTS,
    build_bot_render_check,
    render_for_bots,
)
from silentfrog.models.bot_matrix import COL_SSR, build_bot_rows
from silentfrog.parsers_meta import _AI_AGENTS
from silentfrog.render_diff import RenderResult

_BASELINE = "<html><body><h1>Title</h1><p>Server content.</p></body></html>"


class _FakePool:
    """Records the UA per render and serves canned HTML per token marker."""

    def __init__(self, html_for=None, error_for=()) -> None:
        self.user_agents: list[str] = []
        self._html_for = html_for or (lambda ua: _BASELINE)
        self._error_for = set(error_for)

    async def render(self, url: str, timeout: int = 15, user_agent: str = "") -> RenderResult:
        self.user_agents.append(user_agent)
        for marker in self._error_for:
            if marker in user_agent:
                return RenderResult(url=url, rendered_html="", error="HTTP 403")
        return RenderResult(url=url, rendered_html=self._html_for(user_agent))


def test_ua_registry_covers_exactly_the_19_audited_bots() -> None:
    assert set(BOT_USER_AGENTS) == {agent.token for agent in _AI_AGENTS}
    assert len(BOT_USER_AGENTS) == 19
    # Every UA names its bot so server logs stay attributable.
    for token, user_agent in BOT_USER_AGENTS.items():
        assert user_agent.strip(), token


@pytest.mark.asyncio
async def test_render_for_bots_produces_one_entry_per_bot_with_its_ua() -> None:
    pool = _FakePool()
    payload = await render_for_bots("https://e.com/p", _BASELINE, pool=pool)
    assert payload["measured"] is True
    assert set(payload["bots"]) == set(BOT_USER_AGENTS)
    assert sorted(pool.user_agents) == sorted(BOT_USER_AGENTS.values())
    # Identical DOMs -> every bot reads good; values stay JSON-native.
    for entry in payload["bots"].values():
        assert entry["status"] == "good"
        assert isinstance(entry["missing_headings"], list)


@pytest.mark.asyncio
async def test_blocked_bot_reports_render_failure_as_warning() -> None:
    pool = _FakePool(error_for=("GPTBot",))
    payload = await render_for_bots("https://e.com/p", _BASELINE, pool=pool, tokens=["gptbot", "googlebot"])
    assert payload["bots"]["gptbot"]["status"] == "warning"
    assert payload["bots"]["gptbot"]["reason"].startswith("Render failed")
    assert payload["bots"]["googlebot"]["status"] == "good"


@pytest.mark.asyncio
async def test_divergent_bot_render_detected_via_diff() -> None:
    richer = _BASELINE.replace("</body>", "<h2>Only for Googlebot</h2>" + "x" * 600 + "</body>")

    def html_for(user_agent: str) -> str:
        return richer if "Googlebot" in user_agent else _BASELINE

    pool = _FakePool(html_for=html_for)
    payload = await render_for_bots("https://e.com/p", _BASELINE, pool=pool, tokens=["gptbot", "googlebot"])
    # Missing heading + >500 chars crosses render_diff's critical threshold.
    assert payload["bots"]["googlebot"]["status"] == "critical"
    assert payload["bots"]["gptbot"]["status"] == "good"


def test_check_not_emitted_when_unmeasured() -> None:
    assert build_bot_render_check(None) is None
    assert build_bot_render_check({}) is None
    assert build_bot_render_check({"measured": False, "reason": "Playwright not installed", "bots": {}}) is None


def test_check_good_when_all_bots_uniform() -> None:
    payload = {
        "measured": True,
        "reason": "",
        "bots": {token: {"status": "good", "reason": ""} for token in ("gptbot", "googlebot", "claudebot")},
    }
    check = build_bot_render_check(payload)
    assert check is not None
    assert check.key == "access_bot_render"
    assert check.status == "good"


def test_check_warns_and_names_the_divergent_bots() -> None:
    payload = {
        "measured": True,
        "reason": "",
        "bots": {
            "gptbot": {"status": "warning", "reason": "Render failed: HTTP 403"},
            "googlebot": {"status": "good", "reason": ""},
            "claudebot": {"status": "good", "reason": ""},
        },
    }
    check = build_bot_render_check(payload)
    assert check is not None
    assert check.status == "warning"
    assert "gptbot" in check.details


def test_check_names_the_divergent_bots_even_when_they_are_the_majority() -> None:
    # Regression: majority-vote naming used to list the healthy bots once
    # divergence passed 50%.
    payload = {
        "measured": True,
        "reason": "",
        "bots": {
            "gptbot": {"status": "critical", "reason": ""},
            "claudebot": {"status": "critical", "reason": ""},
            "bytespider": {"status": "critical", "reason": ""},
            "googlebot": {"status": "good", "reason": ""},
            "duckassistbot": {"status": "good", "reason": ""},
        },
    }
    check = build_bot_render_check(payload)
    assert check is not None
    assert check.status == "warning"
    for divergent in ("gptbot", "claudebot", "bytespider"):
        assert divergent in check.details
    assert "googlebot" not in check.details


def test_check_good_when_bots_uniformly_gain_content_from_js() -> None:
    # Uniform non-good statuses = every bot sees the same thing (a site-wide
    # SSR parity concern, not per-bot divergence).
    payload = {
        "measured": True,
        "reason": "",
        "bots": {token: {"status": "warning", "reason": ""} for token in ("gptbot", "googlebot")},
    }
    check = build_bot_render_check(payload)
    assert check is not None
    assert check.status == "good"


def test_bot_matrix_ssr_column_uses_per_bot_diff_with_site_wide_fallback() -> None:
    ai_rows = [
        ["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "-"],
        ["Googlebot", "googlebot", "Yes", "-", "-", "Allowed", "-"],
        ["ClaudeBot", "claudebot", "Yes", "-", "-", "Allowed", "-"],
    ]
    site_render = {"status": "good", "reason": ""}
    bot_render = {
        "measured": True,
        "reason": "",
        # claudebot intentionally absent -> falls back to the site-wide cell.
        "bots": {
            "gptbot": {"status": "critical", "reason": "Render failed: HTTP 403"},
            "googlebot": {"status": "good", "reason": ""},
        },
    }
    rows = build_bot_rows(ai_rows, discovery=None, render=site_render, bot_render=bot_render)
    ssr_by_label = {row.label: row.statuses[COL_SSR - 1] for row in rows}
    assert ssr_by_label == {"GPTBot": "critical", "Googlebot": "good", "ClaudeBot": "good"}
    tips_by_label = {row.label: row.tooltips[COL_SSR - 1] for row in rows}
    assert "Per-bot render" in tips_by_label["GPTBot"]
    assert "site-wide" in tips_by_label["ClaudeBot"].lower() or "match" in tips_by_label["ClaudeBot"].lower()


def test_bot_matrix_ignores_unmeasured_bot_render() -> None:
    ai_rows = [["GPTBot", "gptbot", "Yes", "-", "-", "Allowed", "-"]]
    rows = build_bot_rows(
        ai_rows,
        discovery=None,
        render=None,
        bot_render={"measured": False, "reason": "off", "bots": {"gptbot": {"status": "critical"}}},
    )
    # Feature off -> per-bot data ignored, grey site-wide fallback.
    assert rows[0].statuses[COL_SSR - 1] == "info"


@pytest.mark.asyncio
async def test_render_for_bots_unknown_token_gets_synthetic_ua() -> None:
    pool = _FakePool()
    await render_for_bots("https://e.com/p", _BASELINE, pool=pool, tokens=["somebot-x"])
    assert pool.user_agents == ["Mozilla/5.0 (compatible; somebot-x)"]
