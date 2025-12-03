from __future__ import annotations

import json
import logging
import os
import re
import html as _html
from collections import Counter
from typing import Any, Dict, List, cast

import bs4
from bs4 import BeautifulSoup

from .crawler_utils import _attr

Tag = bs4.element.Tag

# Safe import of extruct (fallback if lxml is broken)
try:
    import extruct  # type: ignore
    from w3lib.html import get_base_url  # type: ignore

    USE_EXTRUCT = True
except Exception:
    USE_EXTRUCT = False

DEBUG_SCHEMA = os.environ.get("SILENTFROG_DEBUG", "").lower() in ("1", "true", "yes", "y")
_SCHEMA_LOGGER = logging.getLogger("silentfrog.schema")


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
    image = obj.get("image")
    if not image:
        errors.append("missing image")

    offers = obj.get("offers")
    if not offers:
        errors.append("missing offers")
        return errors

    offers_list = _schema_normalize_entries(offers)
    have_price = False
    have_currency = False
    for offer in offers_list:
        if not isinstance(offer, dict):
            continue
        offer_type = _schema_primary_type(offer.get("@type")).lower()
        price_spec = offer.get("priceSpecification")
        if isinstance(price_spec, dict):
            if price_spec.get("price") or price_spec.get("minPrice") or price_spec.get("lowPrice"):
                have_price = True
            if price_spec.get("priceCurrency"):
                have_currency = True
        price_value = offer.get("price") or offer.get("lowPrice") or offer.get("highPrice")
        if price_value:
            have_price = True
        if offer.get("priceCurrency"):
            have_currency = True
        if offer_type == "aggregateoffer":
            if offer.get("lowPrice") or offer.get("highPrice"):
                have_price = True
            if offer.get("priceCurrency"):
                have_currency = True
    if not have_price:
        errors.append("missing offers.price")
    if not have_currency:
        errors.append("missing offers.priceCurrency")
    return errors


_SCHEMA_VALIDATORS: Dict[str, Any] = {
    "breadcrumblist": _schema_validate_breadcrumb,
    "product": _schema_validate_product,
}


def _extract_schema_all(html_text: str, response_url: str) -> Dict[str, Any]:
    syntaxes = ["json-ld", "microdata", "opengraph", "microformat", "rdfa"]
    collected: list[Dict[str, Any]] = []
    seen: set[str] = set()
    syntax_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    fallback_raw: list[str] = []

    def _add_flat(obj: dict, via: str) -> None:
        g = obj.get("@graph")
        if isinstance(g, list) and g:
            for n in g:
                if isinstance(n, dict):
                    _add_flat(n, via)
            return
        sig = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if sig in seen:
            return
        seen.add(sig)
        enriched = dict(obj)
        enriched["_extracted_via"] = via
        collected.append(enriched)
        syntax_counter[via] += 1
        primary_type = _schema_primary_type(enriched.get("@type"))
        if primary_type:
            type_counter[primary_type] += 1

    def _scrub_jsonish(s: str) -> str:
        s = s.lstrip("\ufeff").strip()
        s = re.sub(r"(?s)<!--.*?-->", "", s)
        s = re.sub(r"(?s)/\*.*?\*/", "", s)
        s = re.sub(r"(?m)^\s*//.*$", "", s)
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    def _safe_load(s: str) -> Any:
        try:
            return json.loads(s)
        except Exception:
            pass
        try:
            return json.loads(_scrub_jsonish(s))
        except Exception:
            pass
        try:
            return json.loads(_scrub_jsonish(_html.unescape(s)))
        except Exception:
            return None

    def _walk_jsonld(obj: Any) -> list[dict]:
        out: list[dict] = []
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                if ("@context" in cur) or ("@type" in cur) or ("@graph" in cur):
                    out.append(cur)
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, str) and ("@context" in cur or "@type" in cur):
                loaded = _safe_load(cur)
                if isinstance(loaded, (list, dict)):
                    stack.append(loaded)
        return out

    def _is_within_other(scope: bs4.element.Tag, node: bs4.element.Tag, attr: str) -> bool:
        p = node.parent
        while isinstance(p, bs4.element.Tag) and p is not scope:
            if p.has_attr(attr):
                return True
            p = p.parent
        return False

    def _microdata_bs(soup: BeautifulSoup) -> list[dict]:
        out: list[dict] = []
        for scope in soup.find_all(attrs={"itemscope": True}):
            if not isinstance(scope, Tag):
                continue
            typ_tokens = _attr(scope, "itemtype").split()
            item_type = typ_tokens[0] if typ_tokens else "Thing"
            item: dict[str, Any] = {"@type": item_type}
            for prop in scope.find_all(attrs={"itemprop": True}):
                if not isinstance(prop, Tag):
                    continue
                if _is_within_other(scope, prop, "itemscope"):
                    continue
                key_tokens = _attr(prop, "itemprop").split()
                raw_content = _attr(prop, "content")
                raw_href = _attr(prop, "href")
                raw_src = _attr(prop, "src")
                value = raw_content or raw_href or raw_src or " ".join(prop.stripped_strings)
                for key in key_tokens:
                    if key:
                        item[key] = value
            out.append(item)
        return out

    def _rdfa_bs(soup: BeautifulSoup) -> list[dict]:
        out: list[dict] = []
        for root in soup.find_all(attrs={"typeof": True}):
            if not isinstance(root, Tag):
                continue
            typ = _attr(root, "typeof").strip()
            vocab = _attr(root, "vocab").strip()
            item: dict[str, Any] = {"@type": typ or (vocab or "Thing")}
            for prop in root.find_all(attrs={"property": True}):
                if not isinstance(prop, Tag):
                    continue
                if _is_within_other(root, prop, "typeof"):
                    continue
                key = _attr(prop, "property").strip()
                raw_content = _attr(prop, "content")
                raw_href = _attr(prop, "href")
                raw_src = _attr(prop, "src")
                value = raw_content or raw_href or raw_src or " ".join(prop.stripped_strings)
                if key:
                    item[key] = value
            out.append(item)
        return out

    try:
        soup = BeautifulSoup(html_text, "html.parser")
        ok = bad = 0
        for node in soup.find_all("script"):
            if not isinstance(node, Tag):
                continue
            tag_type = _attr(node, "type").lower().strip()
            is_ld = "ld+json" in tag_type or tag_type in ("application/jsonld", "application/json+ld")
            ident = _attr(node, "id")
            class_attr = node.get("class") or []
            class_text = " ".join(class_attr) if isinstance(class_attr, (list, tuple)) else str(class_attr)
            hint = "schema" in f"{ident} {class_text}".lower()
            if not (is_ld or hint):
                continue
            raw = (node.string or node.get_text() or "").strip()
            if not raw:
                continue
            parsed = _safe_load(raw)
            if parsed is None:
                collected.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
                bad += 1
                continue
            if isinstance(parsed, list):
                for obj in parsed:
                    if isinstance(obj, dict):
                        _add_flat(obj, "json-ld")
            elif isinstance(parsed, dict):
                _add_flat(parsed, "json-ld")
            else:
                collected.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
                bad += 1
                continue
            ok += 1
        _log_schema(f"manual json-ld blocks parsed={ok}, raw_bad={bad}")
    except Exception as e:
        _log_schema(f"manual json-ld error: {e!r}")

    def _find_json_objects(text: str) -> list[str]:
        out: list[str] = []
        depth = 0
        start = -1
        in_str = ""
        esc = False
        for i, ch in enumerate(text):
            if in_str:
                esc = ch == "\\" and not esc
                if ch == in_str and not esc:
                    in_str = ""
                continue
            if ch in ("'", '"'):
                in_str = ch
                esc = False
                continue
            if ch == "{":
                depth += 1
                start = i if depth == 1 else start
                continue
            if ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start : i + 1])
        return out

    try:
        soup2 = BeautifulSoup(html_text, "html.parser")
        hits = 0
        for script_node in soup2.find_all("script"):
            script = cast(Tag, script_node)
            raw = str(getattr(script, "string", None) or script.get_text() or "")
            if not raw:
                continue
            parsed = _safe_load(raw)
            if isinstance(parsed, (list, dict)):
                for item in _walk_jsonld(parsed):
                    _add_flat(item, "json-ld")
                    hits += 1
                continue
            for chunk in _find_json_objects(raw):
                parsed2 = _safe_load(chunk)
                if isinstance(parsed2, (list, dict)):
                    for item in _walk_jsonld(parsed2):
                        _add_flat(item, "json-ld")
                        hits += 1
        if hits:
            _log_schema(f"heuristic nested json-ld nodes found={hits}")
    except Exception as e:
        _log_schema(f"heuristic json-ld error: {e!r}")

    if USE_EXTRUCT:
        def _extract_lxml() -> dict[str, Any]:
            try:
                data = extruct.extract(html_text, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
                _log_schema("extruct:lxml ok")
                return data
            except Exception as e:
                _log_schema(f"extruct:lxml error: {e!r}")
                return {}

        def _extract_html5lib() -> dict[str, Any]:
            try:
                from extruct.utils import parse_html as _parse_html  # type: ignore

                tree = _parse_html(html_text, treebuilder="html5lib")
                data = extruct.extract(tree, base_url=response_url, syntaxes=syntaxes, uniform=True)  # type: ignore[arg-type]
                _log_schema("extruct:html5lib ok")
                return data
            except Exception as e:
                _log_schema(f"extruct:html5lib error: {e!r}")
                return {}

        res = _extract_lxml()
        if not any(res.get(k) for k in syntaxes):
            res = _extract_html5lib()
        for syntax in syntaxes:
            items = res.get(syntax) or []
            for it in items:
                if isinstance(it, dict):
                    _add_flat(it, syntax)
            if items:
                _log_schema(f"extruct:{syntax} -> {len(items)} items")

    soup_md = BeautifulSoup(html_text, "html.parser")
    have_micro = any(isinstance(o, dict) and o.get("_extracted_via") == "microdata" for o in collected)
    have_rdfa = any(isinstance(o, dict) and o.get("_extracted_via") == "rdfa" for o in collected)
    if not have_micro:
        for item in _microdata_bs(soup_md):
            _add_flat(item, "microdata")
        _log_schema("fallback: microdata added")
    if not have_rdfa:
        for item in _rdfa_bs(soup_md):
            _add_flat(item, "rdfa")
        _log_schema("fallback: rdfa added")

    if not collected:
        soup_fallback = BeautifulSoup(html_text, "html.parser")
        fallback_blocks: list[Dict[str, Any]] = []
        for script in soup_fallback.find_all("script", {"type": "application/ld+json"}):
            raw = script.get_text(strip=True) or ""
            if not raw:
                continue
            fallback_raw.append(raw)
            fallback_blocks.append({"@raw": raw, "_extracted_via": "json-ld-raw"})
        if fallback_blocks:
            collected.extend(fallback_blocks)
            syntax_counter["json-ld-raw"] += len(fallback_blocks)
            _log_schema(f"fallback: raw json-ld captured={len(fallback_blocks)}")

    aggregate: list[str] = []
    for idx, obj in enumerate(collected, start=1):
        if not isinstance(obj, dict):
            continue
        via = str(obj.get("_extracted_via", "")).strip()
        via_lower = via.lower()
        block_issues: List[str] = []
        if via_lower in ("json-ld", "json-ld-raw"):
            checks = [
                ("@raw" in obj, "Unparseable JSON-LD block"),
                ("@context" not in obj and "@raw" not in obj, "JSON-LD missing @context"),
                ("@type" not in obj and "@raw" not in obj, "JSON-LD missing @type"),
            ]
            block_issues.extend(msg for cond, msg in checks if cond)
        if via_lower == "microdata" and "@type" not in obj:
            block_issues.append("Microdata item missing @type")
        if via_lower == "rdfa" and "@type" not in obj:
            block_issues.append("RDFa item missing @type")

        validator_key = _schema_primary_type(obj.get("@type")).lower()
        validator = _SCHEMA_VALIDATORS.get(validator_key)
        if validator:
            block_issues.extend(validator(obj))

        if block_issues:
            unique = sorted(set(block_issues))
            obj["_schema_errors"] = unique
            label = _schema_block_label(idx, obj)
            aggregate.extend(f"{label}: {msg}" for msg in unique)

    summary = {
        "total": int(sum(syntax_counter.values())),
        "by_syntax": {name: syntax_counter[name] for name in sorted(syntax_counter) if syntax_counter[name]},
        "by_type": {name: type_counter[name] for name in sorted(type_counter) if type_counter[name]},
        "errors": sorted(set(aggregate)),
    }
    return {
        "blocks": collected,
        "summary": summary,
        "issues": summary["errors"],
        "fallback_raw": fallback_raw,
    }
