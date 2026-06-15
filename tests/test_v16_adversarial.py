"""Adversarial V16 tests: RFC 9309 edge cases + hreflang §1.5 invariants.

Independent validation pass for the V16 milestone. Each test targets a
specific risk the Developer's own suites do not already cover. The former
ReDoS case now runs the engine in a hard-timeout subprocess: the linear
two-pointer matcher in ``robots_simulator`` cannot backtrack, so the call
returns promptly and a regression to catastrophic backtracking would fail
the subprocess timeout rather than hang the suite.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from silentfrog.ai_visibility import build_ai_visibility_summary
from silentfrog.crawl_types import AiVisibilityCheck
from silentfrog.hreflang_validator import build_hreflang_checks
from silentfrog.robots_simulator import simulate_robots


def _sim_allowed(body: str, ua: str, url: str) -> bool:
    return simulate_robots(body, ua, url).allowed


# --- Robots: RFC 9309 correctness ---------------------------------------


def test_specific_group_does_not_inherit_star_rules() -> None:
    # RFC 9309: a matching specific group is used EXCLUSIVELY; `*` rules
    # are NOT merged in. Googlebot must not pick up the `*` disallow.
    body = "User-agent: *\nDisallow: /everywhere\n\nUser-agent: googlebot\nAllow: /\n"
    result = simulate_robots(body, "googlebot", "https://e.com/everywhere")
    assert result.matched_group == "googlebot"
    assert result.allowed is True
    assert all(rule.pattern != "/everywhere" for rule in result.candidate_rules)


def test_allow_beats_disallow_regardless_of_order() -> None:
    # §2.2.2 tie-break is order-independent: Allow wins at equal specificity.
    disallow_first = "User-agent: *\nDisallow: /page\nAllow: /page\n"
    allow_first = "User-agent: *\nAllow: /page\nDisallow: /page\n"
    assert _sim_allowed(disallow_first, "bot", "https://e.com/page") is True
    assert _sim_allowed(allow_first, "bot", "https://e.com/page") is True


def test_dollar_sign_mid_pattern_is_literal_not_anchor() -> None:
    # A `$` that is not at pattern end must be escaped, not treated as an anchor.
    body = "User-agent: *\nDisallow: /a$b\n"
    assert _sim_allowed(body, "bot", "https://e.com/a$b/c") is False
    # If `$` were a mid-pattern anchor, /a alone would (wrongly) match.
    assert _sim_allowed(body, "bot", "https://e.com/a") is True


def test_query_string_wildcard_blocks_any_query() -> None:
    body = "User-agent: *\nDisallow: /*?\n"
    assert _sim_allowed(body, "bot", "https://e.com/page?x=1") is False
    assert _sim_allowed(body, "bot", "https://e.com/page") is True


def test_pdf_end_anchor_excludes_query_and_suffix() -> None:
    body = "User-agent: *\nDisallow: /*.pdf$\n"
    assert _sim_allowed(body, "bot", "https://e.com/x.pdf") is False
    assert _sim_allowed(body, "bot", "https://e.com/x.pdf?v=1") is True
    assert _sim_allowed(body, "bot", "https://e.com/x.pdfx") is True


def test_short_ua_does_not_match_longer_group_token() -> None:
    # `goog` is not prefixed by `googlebot`; it must fall back to `*`.
    body = "User-agent: googlebot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    result = simulate_robots(body, "goog", "https://e.com/x")
    assert result.matched_group == "*"
    assert result.allowed is True


def test_percent_encoded_path_does_not_crash_and_matches() -> None:
    body = "User-agent: *\nDisallow: /café\n"
    assert _sim_allowed(body, "bot", "https://e.com/caf%C3%A9") is False


_REDOS_SNIPPET = textwrap.dedent(
    """
    from silentfrog.robots_simulator import simulate_robots
    body = "User-agent: *\\nDisallow: /*a*a*a*a*a*a*a*a*a*a*b\\n"
    url = "https://e.com/" + "a" * 200 + "c"
    simulate_robots(body, "bot", url)
    """
)


def _sim_returns_within(seconds: float) -> bool:
    # Run in a throwaway subprocess so catastrophic backtracking can be hard-
    # killed; an in-process thread cannot be interrupted out of the C regex.
    try:
        subprocess.run([sys.executable, "-c", _REDOS_SNIPPET], timeout=seconds, check=False)
    except subprocess.TimeoutExpired:
        return False
    return True


def test_pathological_wildcard_pattern_is_time_boxed() -> None:
    # The linear two-pointer matcher cannot backtrack, so many `*` against a
    # long non-matching path returns promptly. Time-boxed in a subprocess so a
    # regression to catastrophic backtracking would fail loudly, not hang.
    assert _sim_returns_within(3.0) is True


# --- Hreflang: §1.5 myth rule + integration -----------------------------


def _status_for(checks: list[AiVisibilityCheck], key: str) -> str:
    return next(check.status for check in checks if check.key == key)


def test_missing_x_default_is_info_never_warning() -> None:
    rows = [["en", "https://e.com/en/", "200", "Yes", "Yes"], ["de", "https://e.com/de/", "200", "Yes", "No"]]
    checks = build_hreflang_checks("https://e.com/en/", rows)
    assert _status_for(checks, "hreflang_x_default_present") == "info"


def test_no_cluster_return_tag_is_never_warning() -> None:
    rows = [["en", "https://e.com/en/", "200", "Yes", "No"], ["de", "https://e.com/de/", "200", "Yes", "No"]]
    checks = build_hreflang_checks("https://e.com/en/", rows)
    assert _status_for(checks, "hreflang_return_tag_complete") in {"good", "info"}


def test_empty_rows_produce_no_phantom_checks() -> None:
    assert build_hreflang_checks("https://e.com/en/", []) == []
    assert build_hreflang_checks("https://e.com/en/", None) == []
    assert build_hreflang_checks("https://e.com/en/", "not-a-row") == []


def test_page_url_absent_uses_self_reference_column() -> None:
    rows = [["en", "https://e.com/en/", "200", "Yes", "Yes"], ["de", "https://e.com/de/", "200", "Yes", "No"]]
    checks = build_hreflang_checks("", rows)
    assert _status_for(checks, "hreflang_return_tag_complete") == "good"


def test_info_hreflang_check_does_not_lower_score() -> None:
    good = AiVisibilityCheck(area="Topic clarity", check="x", status="good", details="", recommendation="", key="t")
    info = AiVisibilityCheck(
        area="Hreflang", check="x", status="info", details="", recommendation="r", key="hreflang_x_default_present"
    )
    warn = AiVisibilityCheck(
        area="Hreflang", check="x", status="warning", details="", recommendation="r", key="hreflang_cluster_consistent"
    )
    assert build_ai_visibility_summary([good, info]).score == 100
    assert build_ai_visibility_summary([good, warn]).score == 96
