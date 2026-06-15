"""Custom CSS / XPath / regex extraction (v2.0 V6).

Screaming Frog's flagship power-user feature: define named rules that
pull arbitrary values out of every crawled page (prices, tracking IDs,
schema-not-yet-supported fields…). Zero new deps — CSS via BeautifulSoup,
XPath via lxml, plus regex + attribute extraction.

Sandboxed by construction: no JS eval, no network, no filesystem. XPath
runs against an in-memory lxml tree (lxml disables external entity
resolution by default for HTMLParser). Output is length-capped so a
greedy selector can't blow up memory or the export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from bs4 import BeautifulSoup

MAX_RULES = 10
_MAX_OUTPUT_CHARS = 2048
_MAX_MATCHES = 50


class RuleType(StrEnum):
    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"
    ATTRIBUTE = "attribute"  # CSS selector + an attribute name

    @classmethod
    def from_value(cls, value: Any) -> RuleType:
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.CSS


@dataclass(frozen=True)
class CustomExtractionRule:
    name: str
    type: RuleType = RuleType.CSS
    selector: str = ""
    attribute: str = ""  # used when type == ATTRIBUTE
    post_regex: str = ""  # optional regex applied to each extracted value

    @classmethod
    def from_dict(cls, value: Any) -> CustomExtractionRule:
        if not isinstance(value, dict):
            return cls(name="")
        return cls(
            name=str(value.get("name", "")).strip(),
            type=RuleType.from_value(value.get("type", "css")),
            selector=str(value.get("selector", "")).strip(),
            attribute=str(value.get("attribute", "")).strip(),
            post_regex=str(value.get("post_regex", "")).strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "type": self.type.value,
            "selector": self.selector,
            "attribute": self.attribute,
            "post_regex": self.post_regex,
        }

    @property
    def is_valid(self) -> bool:
        return bool(self.name and (self.selector or self.type is RuleType.REGEX))


@dataclass(frozen=True)
class CustomExtractionConfig:
    rules: tuple[CustomExtractionRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(cls, value: Any) -> CustomExtractionConfig:
        if isinstance(value, CustomExtractionConfig):
            return value
        items = value.get("rules", []) if isinstance(value, dict) else (value or [])
        rules = tuple(CustomExtractionRule.from_dict(item) for item in items)
        valid = tuple(r for r in rules if r.is_valid)[:MAX_RULES]
        return cls(rules=valid)

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [r.to_dict() for r in self.rules]}

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.rules]

    def to_text(self) -> str:
        """Serialise back to the one-rule-per-line text format."""
        lines = []
        for rule in self.rules:
            parts = [rule.name, rule.type.value, rule.selector, rule.attribute, rule.post_regex]
            while len(parts) > 1 and not parts[-1]:
                parts.pop()
            lines.append(" | ".join(parts))
        return "\n".join(lines)


def _clip(value: str) -> str:
    text = value.strip()
    return text if len(text) <= _MAX_OUTPUT_CHARS else text[:_MAX_OUTPUT_CHARS] + "…"


def _apply_post_regex(values: list[str], pattern: str) -> list[str]:
    if not pattern:
        return values
    try:
        compiled = re.compile(pattern)
    except re.error:
        return values
    out: list[str] = []
    for value in values:
        match = compiled.search(value)
        if match:
            out.append(match.group(match.lastindex or 0))
    return out


def _extract_css(soup: BeautifulSoup, selector: str) -> list[str]:
    try:
        nodes = soup.select(selector)
    except Exception:  # noqa: BLE001 — invalid selector degrades to no match
        return []
    return [n.get_text(" ", strip=True) for n in nodes[:_MAX_MATCHES]]


def _extract_attribute(soup: BeautifulSoup, selector: str, attribute: str) -> list[str]:
    try:
        nodes = soup.select(selector)
    except Exception:  # noqa: BLE001
        return []
    values: list[str] = []
    for node in nodes[:_MAX_MATCHES]:
        raw = node.get(attribute)
        if isinstance(raw, list):
            values.append(" ".join(str(v) for v in raw))
        elif raw is not None:
            values.append(str(raw))
    return values


def _extract_xpath(html: str, selector: str) -> list[str]:
    try:
        from lxml import html as lxml_html  # lazy; already a transitive dep

        tree = lxml_html.fromstring(html)
        found = tree.xpath(selector)
    except Exception:  # noqa: BLE001 — invalid xpath / parse error degrades
        return []
    values: list[str] = []
    for item in found[:_MAX_MATCHES]:
        text = item.text_content() if hasattr(item, "text_content") else str(item)
        values.append(str(text))
    return values


def _extract_regex(html: str, pattern: str) -> list[str]:
    try:
        compiled = re.compile(pattern)
    except re.error:
        return []
    out: list[str] = []
    for match in compiled.finditer(html):
        out.append(match.group(match.lastindex or 0))
        if len(out) >= _MAX_MATCHES:
            break
    return out


def _values_css(rule: CustomExtractionRule, soup: BeautifulSoup, html: str) -> list[str]:
    return _extract_css(soup, rule.selector)


def _values_attribute(rule: CustomExtractionRule, soup: BeautifulSoup, html: str) -> list[str]:
    return _extract_attribute(soup, rule.selector, rule.attribute)


def _values_xpath(rule: CustomExtractionRule, soup: BeautifulSoup, html: str) -> list[str]:
    return _extract_xpath(html, rule.selector)


def _values_regex(rule: CustomExtractionRule, soup: BeautifulSoup, html: str) -> list[str]:
    return _extract_regex(html, rule.selector or rule.post_regex)


_EXTRACTORS = {
    RuleType.CSS: _values_css,
    RuleType.ATTRIBUTE: _values_attribute,
    RuleType.XPATH: _values_xpath,
    RuleType.REGEX: _values_regex,
}


def _extract_one(rule: CustomExtractionRule, soup: BeautifulSoup, html: str) -> str:
    extractor = _EXTRACTORS.get(rule.type, _values_css)
    values = extractor(rule, soup, html)
    if rule.type is not RuleType.REGEX:
        values = _apply_post_regex(values, rule.post_regex)
    cleaned = [v for v in (s.strip() for s in values) if v]
    return _clip(" | ".join(cleaned))


def parse_rules_text(text: str) -> CustomExtractionConfig:
    """Parse a simple one-rule-per-line config:

        Name | type | selector | attribute | post_regex

    ``type`` defaults to css; trailing fields are optional. Lines that are
    blank or start with ``#`` are skipped. Invalid rules are dropped.
    """
    rules: list[CustomExtractionRule] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        name = parts[0]
        rule = CustomExtractionRule(
            name=name,
            type=RuleType.from_value(parts[1]) if len(parts) > 1 and parts[1] else RuleType.CSS,
            selector=parts[2] if len(parts) > 2 else "",
            attribute=parts[3] if len(parts) > 3 else "",
            post_regex=parts[4] if len(parts) > 4 else "",
        )
        if rule.is_valid:
            rules.append(rule)
    return CustomExtractionConfig(rules=tuple(rules[:MAX_RULES]))


def extract(html: str, config: CustomExtractionConfig | Any) -> dict[str, str]:
    """Run every rule against the page; return {rule_name: extracted_text}.

    A rule that matches nothing yields "". Never raises.
    """
    resolved = CustomExtractionConfig.from_raw(config)
    if not resolved.rules:
        return {}
    soup = BeautifulSoup(html or "", "html.parser")
    return {rule.name: _extract_one(rule, soup, html or "") for rule in resolved.rules}


__all__ = [
    "MAX_RULES",
    "CustomExtractionConfig",
    "CustomExtractionRule",
    "RuleType",
    "extract",
    "parse_rules_text",
]
