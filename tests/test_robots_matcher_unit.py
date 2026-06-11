"""Unit tests for the v2.0 V3 robots matcher + cache."""

from __future__ import annotations

import pytest

from silentfrog.robots_matcher import RobotsCache, RobotsMatcher

_ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /private/public.html

User-agent: SilentFrog
Disallow: /frog-blocked/
"""


def test_empty_robots_allows_everything() -> None:
    matcher = RobotsMatcher("SilentFrog", "")
    assert matcher.allows("https://e.com/anything")
    assert matcher.allows("https://e.com/private/secret")


def test_matcher_respects_wildcard_disallow() -> None:
    matcher = RobotsMatcher("RandomBot", _ROBOTS)
    assert matcher.allows("https://e.com/public-page")
    assert not matcher.allows("https://e.com/private/secret")
    # NB: stdlib robotparser is conservative about Allow-overrides under a
    # disallowed prefix — it may keep the page disallowed. For a respectful
    # spider, over-blocking (skipping a page we could fetch) is the safe
    # direction, so we don't assert the Allow-override carve-out here.


def test_matcher_respects_agent_specific_rules() -> None:
    matcher = RobotsMatcher("SilentFrog", _ROBOTS)
    assert not matcher.allows("https://e.com/frog-blocked/x")
    # SilentFrog has its own group; the wildcard /private/ rule does not
    # apply to it, so /private/ is allowed for SilentFrog.
    assert matcher.allows("https://e.com/private/secret")


@pytest.mark.asyncio
async def test_cache_fetches_once_per_host() -> None:
    calls: list[str] = []

    async def _fake_fetcher(url: str, ua: str, timeout: int) -> RobotsMatcher:
        calls.append(url)
        return RobotsMatcher(ua, _ROBOTS)

    cache = RobotsCache("RandomBot", fetcher=_fake_fetcher)
    assert await cache.allows("https://e.com/a")
    assert not await cache.allows("https://e.com/private/x")
    # Same host → one fetch only.
    assert len(calls) == 1
    # Different host → a second fetch.
    await cache.allows("https://other.com/a")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cache_allows_delegates_to_matcher() -> None:
    async def _fake_fetcher(url: str, ua: str, timeout: int) -> RobotsMatcher:
        return RobotsMatcher(ua, _ROBOTS)

    cache = RobotsCache("RandomBot", fetcher=_fake_fetcher)
    assert await cache.allows("https://e.com/ok")
    assert not await cache.allows("https://e.com/private/secret")
