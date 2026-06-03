from __future__ import annotations

import json
import logging
import os
import re
import html as _html
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

import bs4
from bs4 import BeautifulSoup

from .crawler_utils import _attr, as_tag

Tag = bs4.element.Tag

# Safe import of extruct (fallback if lxml is broken). `extruct` is now a
# runtime dep (pyproject), so this guard only fires on a broken install.
try:
    import extruct  # type: ignore[import]  # upstream lacks type hints

    USE_EXTRUCT = True
except Exception:
    USE_EXTRUCT = False

DEBUG_SCHEMA = os.environ.get("SILENTFROG_DEBUG", "").lower() in ("1", "true", "yes", "y")
_SCHEMA_LOGGER = logging.getLogger("silentfrog.schema")
_SCHEMA_ELIGIBILITY_TYPES = [
    ("breadcrumblist", "BreadcrumbList"),
    ("product", "Product"),
    ("article", "Article"),
    ("faqpage", "FAQPage"),
    ("organization", "Organization"),
    ("localbusiness", "LocalBusiness"),
    ("person", "Person"),
    ("howto", "HowTo"),
    ("website", "WebSite"),
]


def _log_schema(msg: str) -> None:
    if DEBUG_SCHEMA:
        _SCHEMA_LOGGER.info(msg)


def _schema_primary_type(value: Any) -> str:
    candidate = ""
    if isinstance(value, str):
        candidate = value
    elif isinstance(value, list):
        for part in value:
            if isinstance(part, str) and part.strip():
                candidate = part
                break
    if not candidate:
        return ""
    text = candidate.strip()
    if not text:
        return ""
    for sep in ("#", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[-1]
    return text.strip()


def _schema_block_label(index: int, obj: Dict[str, Any]) -> str:
    type_name = _schema_primary_type(obj.get("@type"))
    via = obj.get("_extracted_via", "")
    label = f"Block #{index}"
    if type_name:
        label += f" ({type_name})"
    if via:
        label += f" via {via}"
    return label


def _schema_normalize_entries(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _schema_validate_breadcrumb(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    entries = obj.get("itemListElement")
    if not entries:
        errors.append("missing itemListElement")
        return errors

    normalized = _schema_normalize_entries(entries)
    for idx, entry in enumerate(normalized, start=1):
        if not isinstance(entry, dict):
            errors.append(f"itemListElement[{idx}] is not an object")
            continue
        target = entry.get("item") or entry.get("itemId") or entry.get("url")
        if isinstance(target, dict):
            target = target.get("@id") or target.get("url")
        if "position" not in entry:
            errors.append(f"itemListElement[{idx}] missing position")
        if not entry.get("name"):
            errors.append(f"itemListElement[{idx}] missing name")
        if not target:
            errors.append(f"itemListElement[{idx}] missing item url")
    return errors


def _schema_validate_product(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not obj.get("name"):
        errors.append("missing name")
    if not obj.get("description"):
        errors.append("missing description")
    if not obj.get("image"):
        errors.append("missing image")

    offers = obj.get("offers")
    if not offers:
        errors.append("missing offers")
        return errors

    have_price, have_currency = _schema_offer_flags(_schema_normalize_entries(offers))
    if not have_price:
        errors.append("missing offers.price")
    if not have_currency:
        errors.append("missing offers.priceCurrency")
    return errors


def _schema_offer_flags(offers: List[Any]) -> tuple[bool, bool]:
    have_price = False
    have_currency = False
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        price_spec = offer.get("priceSpecification")
        if isinstance(price_spec, dict):
            if price_spec.get("price") or price_spec.get("minPrice") or price_spec.get("lowPrice"):
                have_price = True
            if price_spec.get("priceCurrency"):
                have_currency = True
        if offer.get("price") or offer.get("lowPrice") or offer.get("highPrice"):
            have_price = True
        if offer.get("priceCurrency"):
            have_currency = True
    return have_price, have_currency


def _schema_validate_article(obj: Dict[str, Any]) -> List[str]:
    checks = [
        (not obj.get("headline"), "missing headline"),
        (not obj.get("image"), "missing image"),
        (not obj.get("datePublished"), "missing datePublished"),
        (not obj.get("author"), "missing author"),
    ]
    return [message for failed, message in checks if failed]


def _schema_validate_faq_page(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    entries = _schema_normalize_entries(obj.get("mainEntity"))
    if not entries:
        return ["missing mainEntity"]

    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            errors.append(f"mainEntity[{idx}] is not an object")
            continue
        if not entry.get("name"):
            errors.append(f"mainEntity[{idx}] missing name")
        answer = entry.get("acceptedAnswer")
        if not isinstance(answer, dict):
            errors.append(f"mainEntity[{idx}] missing acceptedAnswer")
            continue
        if not (answer.get("text") or answer.get("answerExplanation")):
            errors.append(f"mainEntity[{idx}] missing acceptedAnswer.text")
    return errors


def _schema_validate_organization(obj: Dict[str, Any]) -> List[str]:
    checks = [
        (not obj.get("name"), "missing name"),
        (not obj.get("url"), "missing url"),
        (not obj.get("logo"), "missing logo"),
    ]
    return [message for failed, message in checks if failed]


def _schema_validate_local_business(obj: Dict[str, Any]) -> List[str]:
    checks = [
        (not obj.get("name"), "missing name"),
        (not obj.get("address"), "missing address"),
        (not obj.get("telephone"), "missing telephone"),
    ]
    return [message for failed, message in checks if failed]


def _schema_validate_person(obj: Dict[str, Any]) -> List[str]:
    checks = [
        (not obj.get("name"), "missing name"),
    ]
    return [message for failed, message in checks if failed]


def _schema_validate_how_to_step(idx: int, step: Any) -> List[str]:
    if not isinstance(step, dict):
        return [f"step[{idx}] is not an object"]
    if step.get("text") or step.get("name") or step.get("itemListElement"):
        return []
    return [f"step[{idx}] missing text or name"]


def _schema_validate_how_to(obj: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not obj.get("name"):
        errors.append("missing name")
    steps = _schema_normalize_entries(obj.get("step"))
    if not steps:
        errors.append("missing step")
        return errors
    for idx, step in enumerate(steps, start=1):
        errors.extend(_schema_validate_how_to_step(idx, step))
    return errors


def _schema_validate_website(obj: Dict[str, Any]) -> List[str]:
    checks = [
        (not obj.get("name"), "missing name"),
        (not obj.get("url"), "missing url"),
    ]
    return [message for failed, message in checks if failed]


_SCHEMA_VALIDATORS: Dict[str, Any] = {
    "breadcrumblist": _schema_validate_breadcrumb,
    "product": _schema_validate_product,
    "article": _schema_validate_article,
    "faqpage": _schema_validate_faq_page,
    "organization": _schema_validate_organization,
    "localbusiness": _schema_validate_local_business,
    "person": _schema_validate_person,
    "howto": _schema_validate_how_to,
    "website": _schema_validate_website,
}


@dataclass
class _SchemaState:
    collected: list[Dict[str, Any]] = field(default_factory=list)
    seen: set[str] = field(default_factory=set)
    syntax_counter: Counter[str] = field(default_factory=Counter)
    type_counter: Counter[str] = field(default_factory=Counter)
    fallback_raw: list[str] = field(default_factory=list)


def _unique_text(values: List[str]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        ordered.append(text)
        seen.add(text)
    return ordered


def _schema_build_eligibility(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    indexed: Dict[str, List[Dict[str, Any]]] = {key: [] for key, _ in _SCHEMA_ELIGIBILITY_TYPES}
    for block in blocks:
        schema_type = _schema_primary_type(block.get("@type")).lower()
        if schema_type in indexed:
            indexed[schema_type].append(block)

    rows: List[Dict[str, Any]] = []
    for key, label in _SCHEMA_ELIGIBILITY_TYPES:
        matches = indexed[key]
        if not matches:
            rows.append(
                {
                    "type": label,
                    "detected": False,
                    "count": 0,
                    "eligibility": "Not detected",
                    "missing_fields": [],
                    "warnings": [],
                }
            )
            continue

        valid_blocks = sum(1 for block in matches if not block.get("_schema_errors"))
        missing_fields = _unique_text([error for block in matches for error in block.get("_schema_errors", [])])
        warnings: List[str] = []
        if len(matches) > 1:
            warnings.append(f"{len(matches)} blocks detected")
        if valid_blocks and valid_blocks < len(matches):
            warnings.append(f"{len(matches) - valid_blocks} block(s) need fixes")
        if not valid_blocks and missing_fields:
            warnings.append("Missing required fields")

        rows.append(
            {
                "type": label,
                "detected": True,
                "count": len(matches),
                "eligibility": "Eligible" if valid_blocks else "Incomplete",
                "missing_fields": missing_fields,
                "warnings": _unique_text(warnings),
            }
        )
    return rows


def _schema_add_flat(state: _SchemaState, obj: Dict[str, Any], via: str) -> None:
    graph = obj.get("@graph")
    if isinstance(graph, list) and graph:
        for node in graph:
            if isinstance(node, dict):
                _schema_add_flat(state, node, via)
        return
    signature = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    if signature in state.seen:
        return
    state.seen.add(signature)
    enriched = dict(obj)
    enriched["_extracted_via"] = via
    state.collected.append(enriched)
    state.syntax_counter[via] += 1
    primary_type = _schema_primary_type(enriched.get("@type"))
    if primary_type:
        state.type_counter[primary_type] += 1


def _scrub_jsonish(text: str) -> str:
    cleaned = text.lstrip("\ufeff").strip()
    cleaned = re.sub(r"(?s)<!--.*?-->", "", cleaned)
    cleaned = re.sub(r"(?s)/\*.*?\*/", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*//.*$", "", cleaned)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def _safe_load_json(text: str) -> Any:
    variants = (text, _scrub_jsonish(text), _scrub_jsonish(_html.unescape(text)))
    for candidate in variants:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _walk_jsonld(obj: Any) -> list[dict]:
    out: list[dict] = []
    stack = [obj]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if any(key in current for key in ("@context", "@type", "@graph")):
                out.append(current)
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            stack.extend(current)
            continue
        if not isinstance(current, str) or ("@context" not in current and "@type" not in current):
            continue
        loaded = _safe_load_json(current)
        if isinstance(loaded, (list, dict)):
            stack.append(loaded)
    return out


def _find_json_objects(text: str) -> list[str]:
    out: list[str] = []
    depth = 0
    start = -1
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if quote:
            escaped = char == "\\" and not escaped
            if char == quote and not escaped:
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
            escaped = False
            continue
        if char == "{":
            depth += 1
            if depth == 1:
                start = index
            continue
        if char != "}":
            continue
        depth -= 1
        if depth == 0 and start >= 0:
            out.append(text[start : index + 1])
    return out


def _is_schema_jsonld_script(node: Tag) -> bool:
    tag_type = _attr(node, "type").lower().strip()
    if "ld+json" in tag_type or tag_type in ("application/jsonld", "application/json+ld"):
        return True
    ident = _attr(node, "id")
    class_attr = node.get("class") or []
    class_text = " ".join(class_attr) if isinstance(class_attr, (list, tuple)) else str(class_attr)
    return "schema" in f"{ident} {class_text}".lower()


def _is_within_other(scope: Tag, node: Tag, attr: str) -> bool:
    parent = node.parent
    while isinstance(parent, Tag) and parent is not scope:
        if parent.has_attr(attr):
            return True
        parent = parent.parent
    return False


def _microdata_bs(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for scope in soup.find_all(attrs={"itemscope": True}):
        if not isinstance(scope, Tag):
            continue
        type_tokens = _attr(scope, "itemtype").split()
        item: dict[str, Any] = {"@type": type_tokens[0] if type_tokens else "Thing"}
        for prop in scope.find_all(attrs={"itemprop": True}):
            if not isinstance(prop, Tag) or _is_within_other(scope, prop, "itemscope"):
                continue
            value = _attr(prop, "content") or _attr(prop, "href") or _attr(prop, "src") or " ".join(prop.stripped_strings)
            for key in _attr(prop, "itemprop").split():
                if key:
                    item[key] = value
        out.append(item)
    return out


def _rdfa_bs(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for root in soup.find_all(attrs={"typeof": True}):
        if not isinstance(root, Tag):
            continue
        schema_type = _attr(root, "typeof").strip() or _attr(root, "vocab").strip() or "Thing"
        item: dict[str, Any] = {"@type": schema_type}
        for prop in root.find_all(attrs={"property": True}):
            if not isinstance(prop, Tag) or _is_within_other(root, prop, "typeof"):
                continue
            key = _attr(prop, "property").strip()
            if not key:
                continue
            value = _attr(prop, "content") or _attr(prop, "href") or _attr(prop, "src") or " ".join(prop.stripped_strings)
            item[key] = value
        out.append(item)
    return out


def _collect_manual_jsonld(state: _SchemaState, html_text: str) -> None:
    soup = BeautifulSoup(html_text, "html.parser")
    parsed_count = 0
    raw_bad = 0
    for node in soup.find_all("script"):
        if not isinstance(node, Tag) or not _is_schema_jsonld_script(node):
            continue
        raw = (node.string or node.get_text() or "").strip()
        if not raw:
            continue
        parsed = _safe_load_json(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    _schema_add_flat(state, item, "json-ld")
            parsed_count += 1
            continue
        if isinstance(parsed, dict):
            _schema_add_flat(state, parsed, "json-ld")
            parsed_count += 1
            continue
        state.collected.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
        raw_bad += 1
    _log_schema(f"manual json-ld blocks parsed={parsed_count}, raw_bad={raw_bad}")


def _collect_heuristic_jsonld(state: _SchemaState, html_text: str) -> None:
    soup = BeautifulSoup(html_text, "html.parser")
    hits = 0
    for script_node in soup.find_all("script"):
        script = as_tag(script_node)
        raw = str(getattr(script, "string", None) or script.get_text() or "") if script else ""
        if not raw:
            continue
        parsed = _safe_load_json(raw)
        if isinstance(parsed, (list, dict)):
            for item in _walk_jsonld(parsed):
                _schema_add_flat(state, item, "json-ld")
                hits += 1
            continue
        for chunk in _find_json_objects(raw):
            parsed_chunk = _safe_load_json(chunk)
            if not isinstance(parsed_chunk, (list, dict)):
                continue
            for item in _walk_jsonld(parsed_chunk):
                _schema_add_flat(state, item, "json-ld")
                hits += 1
    if hits:
        _log_schema(f"heuristic nested json-ld nodes found={hits}")


def _extract_extruct(html_text: str, response_url: str, syntaxes: List[str]) -> dict[str, Any]:
    def _extract_lxml() -> dict[str, Any]:
        data = extruct.extract(html_text, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
        _log_schema("extruct:lxml ok")
        return data

    def _extract_html5lib() -> dict[str, Any]:
        from extruct.utils import parse_html as _parse_html  # type: ignore[import]

        tree = _parse_html(html_text, treebuilder="html5lib")
        data = extruct.extract(tree, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
        _log_schema("extruct:html5lib ok")
        return data

    try:
        data = _extract_lxml()
    except Exception as exc:
        _log_schema(f"extruct:lxml error: {exc!r}")
        data = {}
    if any(data.get(key) for key in syntaxes):
        return data
    try:
        return _extract_html5lib()
    except Exception as exc:
        _log_schema(f"extruct:html5lib error: {exc!r}")
        return {}


def _collect_extruct_items(state: _SchemaState, html_text: str, response_url: str, syntaxes: List[str]) -> None:
    if not USE_EXTRUCT:
        return
    data = _extract_extruct(html_text, response_url, syntaxes)
    for syntax in syntaxes:
        items = data.get(syntax) or []
        for item in items:
            if isinstance(item, dict):
                _schema_add_flat(state, item, syntax)
        if items:
            _log_schema(f"extruct:{syntax} -> {len(items)} items")


def _collect_bs_fallbacks(state: _SchemaState, html_text: str) -> None:
    soup = BeautifulSoup(html_text, "html.parser")
    if not any(obj.get("_extracted_via") == "microdata" for obj in state.collected if isinstance(obj, dict)):
        for item in _microdata_bs(soup):
            _schema_add_flat(state, item, "microdata")
        _log_schema("fallback: microdata added")
    if not any(obj.get("_extracted_via") == "rdfa" for obj in state.collected if isinstance(obj, dict)):
        for item in _rdfa_bs(soup):
            _schema_add_flat(state, item, "rdfa")
        _log_schema("fallback: rdfa added")


def _collect_raw_jsonld_fallback(state: _SchemaState, html_text: str) -> None:
    if state.collected:
        return
    soup = BeautifulSoup(html_text, "html.parser")
    fallback_blocks: list[Dict[str, Any]] = []
    for script in soup.find_all("script", {"type": "application/ld+json"}):
        raw = script.get_text(strip=True) or ""
        if not raw:
            continue
        state.fallback_raw.append(raw)
        fallback_blocks.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
    if not fallback_blocks:
        return
    state.collected.extend(fallback_blocks)
    state.syntax_counter["json-ld-raw"] += len(fallback_blocks)
    _log_schema(f"fallback: raw json-ld captured={len(fallback_blocks)}")


def _schema_block_issues(obj: Dict[str, Any]) -> List[str]:
    via_lower = str(obj.get("_extracted_via", "")).strip().lower()
    issues: List[str] = []
    if via_lower in {"json-ld", "json-ld-raw"}:
        checks = [
            ("@raw" in obj, "Unparseable JSON-LD block"),
            ("@type" not in obj and "@raw" not in obj, "JSON-LD missing @type"),
        ]
        issues.extend(message for condition, message in checks if condition)
    if via_lower == "microdata" and "@type" not in obj:
        issues.append("Microdata item missing @type")
    if via_lower == "rdfa" and "@type" not in obj:
        issues.append("RDFa item missing @type")
    validator = _SCHEMA_VALIDATORS.get(_schema_primary_type(obj.get("@type")).lower())
    if validator:
        issues.extend(validator(obj))
    return sorted(set(issues))


def _annotate_schema_blocks(blocks: List[Dict[str, Any]]) -> List[str]:
    aggregate: List[str] = []
    for index, obj in enumerate(blocks, start=1):
        issues = _schema_block_issues(obj)
        if not issues:
            continue
        obj["_schema_errors"] = issues
        label = _schema_block_label(index, obj)
        aggregate.extend(f"{label}: {message}" for message in issues)
    return aggregate


def _schema_summary(state: _SchemaState, aggregate: List[str]) -> Dict[str, Any]:
    return {
        "total": int(sum(state.syntax_counter.values())),
        "by_syntax": {
            name: state.syntax_counter[name]
            for name in sorted(state.syntax_counter)
            if state.syntax_counter[name]
        },
        "by_type": {
            name: state.type_counter[name]
            for name in sorted(state.type_counter)
            if state.type_counter[name]
        },
        "errors": sorted(set(aggregate)),
    }


def _extract_schema_all(html_text: str, response_url: str) -> Dict[str, Any]:
    syntaxes = ["json-ld", "microdata", "opengraph", "microformat", "rdfa"]
    state = _SchemaState()
    try:
        _collect_manual_jsonld(state, html_text)
    except Exception as exc:
        _log_schema(f"manual json-ld error: {exc!r}")

    try:
        _collect_heuristic_jsonld(state, html_text)
    except Exception as exc:
        _log_schema(f"heuristic json-ld error: {exc!r}")

    _collect_extruct_items(state, html_text, response_url, syntaxes)
    _collect_bs_fallbacks(state, html_text)
    _collect_raw_jsonld_fallback(state, html_text)

    aggregate = _annotate_schema_blocks([obj for obj in state.collected if isinstance(obj, dict)])
    eligibility = _schema_build_eligibility([obj for obj in state.collected if isinstance(obj, dict)])
    summary = _schema_summary(state, aggregate)
    return {
        "blocks": state.collected,
        "summary": summary,
        "eligibility": eligibility,
        "issues": summary["errors"],
        "fallback_raw": state.fallback_raw,
    }
