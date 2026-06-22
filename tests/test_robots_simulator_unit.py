"""Unit tests for the v2.0 V16 explainable robots.txt simulator."""

from __future__ import annotations

import time

from silentfrog.parsers_meta import _robot_access
from silentfrog.robots_simulator import RobotsSimResult, parse_robots, simulate_robots


def _sim(body: str, ua: str, url: str) -> RobotsSimResult:
    return simulate_robots(body, ua, url)


def test_longest_match_wins() -> None:
    body = "User-agent: *\nDisallow: /a\nAllow: /a/b/c\n"
    blocked = _sim(body, "bot", "https://e.com/a/x")
    allowed = _sim(body, "bot", "https://e.com/a/b/c/page")
    assert blocked.allowed is False
    assert allowed.allowed is True
    assert allowed.winning_rule is not None
    assert allowed.winning_rule.pattern == "/a/b/c"


def test_allow_beats_disallow_at_equal_specificity() -> None:
    body = "User-agent: *\nDisallow: /page\nAllow: /page\n"
    result = _sim(body, "bot", "https://e.com/page")
    assert result.allowed is True
    assert result.winning_rule is not None
    assert result.winning_rule.verb == "allow"


def test_wildcard_blocks_pdf_not_html() -> None:
    body = "User-agent: *\nDisallow: /*.pdf\n"
    assert _sim(body, "bot", "https://e.com/doc.pdf").allowed is False
    assert _sim(body, "bot", "https://e.com/page.html").allowed is True


def test_end_anchor_blocks_exact_extension_only() -> None:
    body = "User-agent: *\nDisallow: /*.php$\n"
    assert _sim(body, "bot", "https://e.com/index.php").allowed is False
    assert _sim(body, "bot", "https://e.com/index.php?x=1").allowed is True


def test_specific_token_group_beats_star() -> None:
    body = "User-agent: googlebot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    google = _sim(body, "Googlebot", "https://e.com/page")
    bing = _sim(body, "bingbot", "https://e.com/page")
    assert google.allowed is False
    assert google.matched_group == "googlebot"
    assert google.group_fallback_to_star is False
    assert bing.allowed is True
    assert bing.matched_group == "*"
    assert bing.group_fallback_to_star is True


def test_user_agent_match_is_case_insensitive() -> None:
    body = "User-agent: GoogleBot\nDisallow: /secret\n"
    result = _sim(body, "googlebot", "https://e.com/secret")
    assert result.allowed is False
    assert result.matched_group == "googlebot"


def test_empty_body_allows_with_no_group() -> None:
    result = _sim("", "bot", "https://e.com/anything")
    assert result.allowed is True
    assert result.winning_rule is None
    assert result.matched_group == ""
    assert result.reason


def test_no_matching_group_allows() -> None:
    body = "User-agent: googlebot\nDisallow: /\n"
    result = _sim(body, "bingbot", "https://e.com/page")
    assert result.allowed is True
    assert result.matched_group == ""
    assert result.winning_rule is None


def test_empty_disallow_value_is_allow_all() -> None:
    body = "User-agent: *\nDisallow:\n"
    result = _sim(body, "bot", "https://e.com/anything")
    assert result.allowed is True
    # The empty-pattern rule exists as a candidate but never matches a path.
    assert result.winning_rule is None
    assert any(rule.pattern == "" and not rule.matched for rule in result.candidate_rules)


def test_candidate_rules_expose_the_chain() -> None:
    body = "User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /other\n"
    result = _sim(body, "bot", "https://e.com/a/b/c")
    matched = [rule for rule in result.candidate_rules if rule.matched]
    assert {rule.pattern for rule in matched} == {"/a", "/a/b"}
    assert all(rule.specificity == len(rule.pattern) for rule in result.candidate_rules)
    other = next(rule for rule in result.candidate_rules if rule.pattern == "/other")
    assert other.matched is False
    assert result.reason


def test_malformed_lines_never_raise() -> None:
    body = "garbage line\n:::\nUser-agent\nDisallow\n# comment only\nUser-agent: *\nDisallow: /x\n"
    result = _sim(body, "bot", "https://e.com/x")
    assert result.allowed is False


def test_to_dict_roundtrips() -> None:
    body = "User-agent: *\nDisallow: /a\n"
    result = _sim(body, "bot", "https://e.com/a")
    data = result.to_dict()
    assert data["allowed"] is False
    assert data["matched_group"] == "*"
    assert data["winning_rule"]["pattern"] == "/a"
    assert isinstance(data["candidate_rules"], list)
    assert data["reason"]


def test_pathological_wildcard_is_linear_in_process() -> None:
    # The two-pointer matcher must stay linear: many `*` against a long non-
    # matching path resolves in milliseconds in-process (no subprocess needed).
    # The path is 5000 'a's + 'c', so `Disallow: /*...*b` (ends in 'b') does
    # NOT match it => the URL is allowed.
    body = "User-agent: *\nDisallow: /*a*a*a*a*a*a*a*a*a*a*b\n"
    url = "https://e.com/" + ("a" * 5000) + "c"
    start = time.perf_counter()
    result = _sim(body, "bot", url)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5
    assert result.allowed is True
    assert result.winning_rule is None


def test_parity_with_parsers_meta_robot_access() -> None:
    # The Bot Matrix gate (_robot_access over RobotsRules) and the one-shot
    # simulator share one engine, so their verdicts must agree.
    cases = [
        ("User-agent: *\nDisallow: /private\n", "https://e.com/private/x"),
        ("User-agent: *\nDisallow: /\n", "https://e.com/page"),
        ("User-agent: *\nDisallow: /a\nAllow: /a/b\n", "https://e.com/a/b/c"),
    ]
    for body, url in cases:
        live_ok, _ = _robot_access(parse_robots(body), "bot", url)
        assert _sim(body, "bot", url).allowed is live_ok


def test_parse_robots_groups_consecutive_user_agents() -> None:
    # F5: consecutive User-agent lines share the following rules (the v1.x
    # parser reset the group on each line, so only the last UA was bound).
    rules = parse_robots("User-agent: a\nUser-agent: b\nDisallow: /x\n")
    assert rules.allows("a", "https://e.com/x") is False
    assert rules.allows("b", "https://e.com/x") is False
    assert rules.allows("c", "https://e.com/x") is True  # no group -> allowed


def test_crawl_delay_selected_by_product_token() -> None:
    # The delay group is chosen by product-token prefix, not an exact full-UA
    # match (the v1.x bug keyed on the whole UA string and never matched).
    rules = parse_robots("User-agent: silentfrog\nCrawl-delay: 3\n")
    assert rules.crawl_delay("SilentFrog/1.0 (+https://example.com)") == 3.0
    assert rules.crawl_delay("OtherBot/2.0") == 0.0  # no matching group, no '*'


def test_parse_robots_collects_sitemaps_and_keeps_directive_map() -> None:
    body = "Sitemap: https://e.com/sitemap.xml\nUser-agent: *\nDisallow: /p\n"
    rules = parse_robots(body)
    assert rules.sitemaps == ("https://e.com/sitemap.xml",)
    directives = rules.directive_map()
    # Sitemap stays in the legacy map so discovery + the Robots sheet still see it.
    assert ("Sitemap", "https://e.com/sitemap.xml") in directives["*"]
    assert ("Disallow", "/p") in directives["*"]
