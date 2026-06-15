"""Tech-stack detection (v2.0 V15).

A curated, in-tree signature set (no vendored Wappalyzer DB — its post-
2023 licence is ambiguous and its ~3000 regexes are a ReDoS surface).
Safe case-insensitive substring matching against the HTML, response
headers, script ``src`` URLs, and the meta-generator tag covers the vast
majority of real-world detections. Pure + typed, zero new deps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CATEGORIES = (
    "CMS",
    "Ecommerce",
    "JS framework",
    "CSS framework",
    "Analytics",
    "Tag manager",
    "CDN",
    "Server",
)


@dataclass(frozen=True)
class TechSignature:
    name: str
    category: str
    html: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    generators: tuple[str, ...] = ()
    headers: tuple[tuple[str, str], ...] = ()  # (header, value-substring; "" = any value)
    cookies: tuple[str, ...] = ()


# Curated, high-signal. Substrings are matched case-insensitively.
_SIGNATURES: tuple[TechSignature, ...] = (
    TechSignature("WordPress", "CMS", html=("/wp-content/", "/wp-includes/"), generators=("wordpress",)),
    TechSignature(
        "Drupal", "CMS", html=("/sites/default/files",), generators=("drupal",), headers=(("X-Generator", "drupal"),)
    ),
    TechSignature("Joomla", "CMS", generators=("joomla",), html=("/media/jui/",)),
    TechSignature("Wix", "CMS", html=("static.wixstatic.com", "wix.com")),
    TechSignature("Squarespace", "CMS", html=("static1.squarespace.com",), generators=("squarespace",)),
    TechSignature("Ghost", "CMS", generators=("ghost",), html=("/ghost/api/",)),
    TechSignature("Shopify", "Ecommerce", html=("cdn.shopify.com", "shopify"), headers=(("X-Shopify-Stage", ""),)),
    TechSignature("WooCommerce", "Ecommerce", html=("/wp-content/plugins/woocommerce",)),
    TechSignature("Magento", "Ecommerce", html=("/static/version", "mage/"), cookies=("X-Magento",)),
    TechSignature("PrestaShop", "Ecommerce", html=("/prestashop",), generators=("prestashop",)),
    TechSignature("BigCommerce", "Ecommerce", html=("cdn11.bigcommerce.com",)),
    TechSignature("React", "JS framework", html=("data-reactroot", "data-reactid"), scripts=("/react.", "react-dom")),
    TechSignature("Vue.js", "JS framework", html=("data-v-", "__vue__"), scripts=("vue.global", "/vue.")),
    TechSignature("Angular", "JS framework", html=("ng-version", "ng-app"), scripts=("/angular",)),
    TechSignature("Next.js", "JS framework", html=("/_next/static", "__NEXT_DATA__")),
    TechSignature("Nuxt.js", "JS framework", html=("/_nuxt/", "__NUXT__")),
    TechSignature("Svelte", "JS framework", html=("svelte-",)),
    TechSignature("jQuery", "JS framework", scripts=("jquery",)),
    TechSignature("Bootstrap", "CSS framework", html=('class="container', "bootstrap.min.css"), scripts=("bootstrap",)),
    TechSignature("Tailwind CSS", "CSS framework", html=("tailwindcss", "tw-")),
    TechSignature(
        "Google Analytics 4", "Analytics", html=("gtag(", "googletagmanager.com/gtag/js"), scripts=("gtag/js",)
    ),
    TechSignature("Universal Analytics", "Analytics", scripts=("google-analytics.com/analytics.js",)),
    TechSignature("Plausible", "Analytics", scripts=("plausible.io/js",)),
    TechSignature("Matomo", "Analytics", html=("matomo.js", "piwik.js")),
    TechSignature("Hotjar", "Analytics", scripts=("static.hotjar.com",)),
    TechSignature("Google Tag Manager", "Tag manager", html=("googletagmanager.com/gtm.js", "GTM-")),
    TechSignature("Cloudflare", "CDN", headers=(("Server", "cloudflare"), ("CF-RAY", "")), cookies=("__cf_bm",)),
    TechSignature("Fastly", "CDN", headers=(("X-Served-By", "cache"), ("Fastly-Debug-Digest", ""))),
    TechSignature("Akamai", "CDN", headers=(("X-Akamai-Transformed", ""), ("Server", "akamai"))),
    TechSignature("Amazon CloudFront", "CDN", headers=(("X-Amz-Cf-Id", ""), ("Via", "cloudfront"))),
    TechSignature("Vercel", "CDN", headers=(("Server", "vercel"), ("X-Vercel-Id", ""))),
    TechSignature("Netlify", "CDN", headers=(("Server", "netlify"), ("X-Nf-Request-Id", ""))),
    TechSignature("Nginx", "Server", headers=(("Server", "nginx"),)),
    TechSignature("Apache", "Server", headers=(("Server", "apache"),)),
    TechSignature("LiteSpeed", "Server", headers=(("Server", "litespeed"),)),
    TechSignature("Microsoft IIS", "Server", headers=(("Server", "iis"), ("X-Powered-By", "asp.net"))),
)


@dataclass(frozen=True)
class TechStackPayload:
    by_category: dict[str, list[str]] = field(default_factory=dict)

    @property
    def all_names(self) -> list[str]:
        return [name for names in self.by_category.values() for name in names]

    def to_dict(self) -> dict[str, Any]:
        return {"by_category": {cat: list(names) for cat, names in self.by_category.items()}}

    @classmethod
    def from_raw(cls, value: Any) -> TechStackPayload:
        raw = value.get("by_category") if isinstance(value, dict) else None
        if not isinstance(raw, dict):
            return cls()
        return cls(by_category={str(k): [str(v) for v in vals] for k, vals in raw.items() if isinstance(vals, list)})


def _haystack(html: str, scripts: list[str]) -> str:
    return (html + " " + " ".join(scripts)).lower()


def _header_match(headers: dict[str, str], wanted: tuple[tuple[str, str], ...]) -> bool:
    lowered = {str(k).lower(): str(v).lower() for k, v in headers.items()}
    for name, needle in wanted:
        value = lowered.get(name.lower())
        if value is None:
            continue
        if not needle or needle.lower() in value:
            return True
    return False


def _signature_matches(sig: TechSignature, hay: str, headers: dict[str, str], generators: str) -> bool:
    if any(token.lower() in hay for token in sig.html):
        return True
    if any(token.lower() in hay for token in sig.scripts):
        return True
    if sig.generators and any(token.lower() in generators.lower() for token in sig.generators):
        return True
    if sig.headers and _header_match(headers, sig.headers):
        return True
    cookie = headers.get("Set-Cookie", "") if isinstance(headers, dict) else ""
    return bool(sig.cookies) and any(token.lower() in cookie.lower() for token in sig.cookies)


def detect_tech(
    html: str,
    headers: dict[str, str] | None = None,
    scripts: list[str] | None = None,
    generator: str = "",
) -> TechStackPayload:
    hay = _haystack(html or "", scripts or [])
    head = headers or {}
    by_category: dict[str, list[str]] = {}
    for sig in _SIGNATURES:
        if _signature_matches(sig, hay, head, generator):
            by_category.setdefault(sig.category, [])
            if sig.name not in by_category[sig.category]:
                by_category[sig.category].append(sig.name)
    return TechStackPayload(by_category=by_category)


__all__ = ["CATEGORIES", "TechSignature", "TechStackPayload", "detect_tech"]
