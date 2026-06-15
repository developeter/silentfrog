"""Explainable robots.txt evaluator (v2.0 V16).

An RFC 9309 engine that reports not just allow/deny but *why*: which
User-agent group matched, whether it fell back to ``*``, and which rule
won the longest-match contest. It is built for a future Settings->Tools
robots simulator dialog that renders ``RobotsSimResult.to_dict()``; the
dialog itself is deferred.

This does NOT replace ``robots_matcher.py`` or ``parsers_meta._robot_access``
(the live crawl path stays on those). It is a standalone, pure engine that
parses a raw robots body string and never raises — malformed input simply
yields the permissive default (allowed) that RFC 9309 mandates.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class RobotsRule:
    verb: str  # "allow" | "disallow", lowercased
    pattern: str
    specificity: int  # len(pattern) — RFC 9309 longest-match key
    matched: bool


@dataclass(frozen=True)
class RobotsSimResult:
    allowed: bool
    user_agent_query: str
    matched_group: str  # the group token, "*" fallback, or "" when no group
    group_fallback_to_star: bool
    winning_rule: RobotsRule | None
    candidate_rules: tuple[RobotsRule, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "user_agent_query": self.user_agent_query,
            "matched_group": self.matched_group,
            "group_fallback_to_star": self.group_fallback_to_star,
            "winning_rule": _rule_to_dict(self.winning_rule),
            "candidate_rules": [_rule_to_dict(rule) for rule in self.candidate_rules],
            "reason": self.reason,
        }


def _rule_to_dict(rule: RobotsRule | None) -> dict[str, object] | None:
    if rule is None:
        return None
    return {
        "verb": rule.verb,
        "pattern": rule.pattern,
        "specificity": rule.specificity,
        "matched": rule.matched,
    }


# Group selection and outcome reasons are keyed by an outcome token so the
# control flow stays a table lookup rather than an if/elif ladder.
_REASON_TEMPLATES = {
    "no_group": "No matching User-agent group for '{ua}'; allowed by RFC 9309 default.",
    "no_match": "Group '{group}' has no path rule matching '{path}'; allowed by default.",
    "allow_wins": "Group '{group}': Allow '{pattern}' wins by longest match ({spec} chars).",
    "disallow_wins": "Group '{group}': Disallow '{pattern}' wins by longest match ({spec} chars).",
}


def _strip_comment(raw: str) -> str:
    return raw.split("#", 1)[0].strip()


def _split_directive(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, _sep, value = line.partition(":")
    return key.strip().lower(), value.strip()


def _is_agent_line(key: str) -> bool:
    return key == "user-agent"


def _rule_from(key: str, value: str) -> RobotsRule:
    # Empty "Disallow:" is a rule that matches nothing (allow-all); an empty
    # pattern never matches a path, so specificity 0 keeps it out of contention.
    return RobotsRule(verb=key, pattern=value, specificity=len(value), matched=False)


def _parse_groups(body: str) -> dict[str, list[RobotsRule]]:
    """Group consecutive User-agent lines and their allow/disallow rules.

    Returns ``{ua_lowercased: [RobotsRule, ...]}``. Non-rule directives
    (Sitemap, Crawl-delay, ...) are ignored. Never raises.
    """
    groups: dict[str, list[RobotsRule]] = {}
    current: list[str] = []
    expecting_agent = True
    for raw in str(body or "").splitlines():
        directive = _split_directive(_strip_comment(raw))
        if directive is None:
            continue
        key, value = directive
        current, expecting_agent = _consume_directive(groups, current, expecting_agent, key, value)
    return groups


def _consume_directive(
    groups: dict[str, list[RobotsRule]],
    current: list[str],
    expecting_agent: bool,
    key: str,
    value: str,
) -> tuple[list[str], bool]:
    """Fold one directive into the group map; return the new agent buffer state."""
    if _is_agent_line(key):
        fresh = [] if not expecting_agent else current
        fresh.append(value.lower())
        groups.setdefault(value.lower(), [])
        return fresh, True
    if key in {"allow", "disallow"}:
        rule = _rule_from(key, value)
        for token in current or ["*"]:
            groups.setdefault(token, []).append(rule)
    return current, False


def _select_group(groups: dict[str, list[RobotsRule]], ua_lower: str) -> tuple[str, bool]:
    """Pick the group key for ``ua_lower`` and report whether ``*`` was used.

    RFC 9309 precedence: exact token, else the longest token that is a prefix
    of the UA, else ``*``, else "" (no group => caller allows). Uses max-by-
    length rather than ranked branches.
    """
    if ua_lower in groups:
        return ua_lower, False
    prefixes = [token for token in groups if token and token != "*" and ua_lower.startswith(token)]
    if prefixes:
        return max(prefixes, key=len), False
    if "*" in groups:
        return "*", True
    return "", False


def _url_path(url: str) -> str:
    parsed = urlparse(str(url or ""))
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    # Percent-decode so "/caf%C3%A9" and "/café" compare identically.
    return unquote(path)


@lru_cache(maxsize=512)
def _parse_pattern(pattern: str) -> tuple[tuple[str, ...], bool]:
    """Split an RFC 9309 path pattern into literal segments around each ``*``.

    Returns ``(segments, anchored)`` where a single trailing ``$`` is stripped
    and recorded as ``anchored``. Every other character — including ``.``,
    ``?``, mid-pattern ``$`` — stays literal. ``segments`` is the text between
    consecutive ``*``; empty strings mark a leading/trailing/back-to-back ``*``.
    """
    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    return tuple(core.split("*")), anchored


def _wildcard_match(pattern: str, path: str) -> bool:
    """Linear two-pointer glob match (RFC 9309 §2.2.3); never backtracks.

    ``*`` matches any run; the pattern is start-anchored; a trailing ``$``
    end-anchors. Literal segments are located with ``str.find`` (no regex), so
    worst case is O(path * pattern) — never the exponential blow-up that a
    backtracking ``.*`` regex suffers on a long non-matching path.
    """
    segments, anchored = _parse_pattern(pattern)
    if segments == ("",):
        return False  # empty pattern (no ``*``) matches nothing, per _rule_matches
    head, *rest = segments
    if not path.startswith(head):  # first segment is start-anchored at index 0
        return False
    return _match_segments(rest, path, len(head), anchored)


def _match_segments(rest: list[str], path: str, pos: int, anchored: bool) -> bool:
    """Advance through the inner/trailing segments left of any final ``*``."""
    if not rest:  # pattern had no ``*``: prefix match already proven by the head
        return path[:pos] == path if anchored else True
    *middle, tail = rest
    for seg in middle:
        found = path.find(seg, pos)
        if found < 0:
            return False
        pos = found + len(seg)
    return _match_tail(tail, path, pos, anchored)


def _match_tail(tail: str, path: str, pos: int, anchored: bool) -> bool:
    """Resolve the segment after the last ``*``; ``tail == ""`` means a free trailing ``*``."""
    if tail == "":  # pattern ends with ``*``: remainder is unconstrained
        return True
    if anchored:  # trailing ``$``: the last segment must land exactly at the end
        return path.endswith(tail) and path.find(tail, pos) >= 0
    return path.find(tail, pos) >= 0


def _rule_matches(rule: RobotsRule, path: str) -> bool:
    if not rule.pattern:
        return False
    return _wildcard_match(rule.pattern, path)


def _allow_priority(rule: RobotsRule) -> int:
    # Allow outranks Disallow at equal specificity (RFC 9309 §2.2.2).
    return 1 if rule.verb == "allow" else 0


def _winning_rule(matched_rules: list[RobotsRule]) -> RobotsRule | None:
    if not matched_rules:
        return None
    return max(matched_rules, key=lambda rule: (rule.specificity, _allow_priority(rule)))


def _reason_for(outcome: str, *, ua: str, group: str, path: str, rule: RobotsRule | None) -> str:
    pattern = rule.pattern if rule else ""
    spec = rule.specificity if rule else 0
    return _REASON_TEMPLATES[outcome].format(ua=ua, group=group, path=path, pattern=pattern, spec=spec)


def _evaluated_candidates(rules: list[RobotsRule], path: str) -> tuple[RobotsRule, ...]:
    return tuple(
        RobotsRule(
            verb=rule.verb, pattern=rule.pattern, specificity=rule.specificity, matched=_rule_matches(rule, path)
        )
        for rule in rules
    )


def _no_group_result(user_agent: str) -> RobotsSimResult:
    return RobotsSimResult(
        allowed=True,
        user_agent_query=user_agent,
        matched_group="",
        group_fallback_to_star=False,
        winning_rule=None,
        candidate_rules=(),
        reason=_reason_for("no_group", ua=user_agent, group="", path="", rule=None),
    )


def simulate_robots(robots_body: str, user_agent: str, url: str) -> RobotsSimResult:
    """Evaluate ``url`` for ``user_agent`` against a raw robots.txt body.

    Returns an explainable verdict; never raises. With no matching group or
    no matching rule the URL is allowed, per RFC 9309's permissive default.
    """
    groups = _parse_groups(robots_body)
    ua_lower = str(user_agent or "").strip().lower()
    group_key, used_star = _select_group(groups, ua_lower)
    if not group_key:
        return _no_group_result(user_agent)

    path = _url_path(url)
    candidates = _evaluated_candidates(groups.get(group_key, []), path)
    winner = _winning_rule([rule for rule in candidates if rule.matched])
    allowed = winner is None or winner.verb == "allow"
    outcome = _outcome_token(winner)
    return RobotsSimResult(
        allowed=allowed,
        user_agent_query=user_agent,
        matched_group=group_key,
        group_fallback_to_star=used_star,
        winning_rule=winner,
        candidate_rules=candidates,
        reason=_reason_for(outcome, ua=user_agent, group=group_key, path=path, rule=winner),
    )


def _outcome_token(winner: RobotsRule | None) -> str:
    if winner is None:
        return "no_match"
    return "allow_wins" if winner.verb == "allow" else "disallow_wins"


__all__ = ["RobotsRule", "RobotsSimResult", "simulate_robots"]
