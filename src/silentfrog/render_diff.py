"""SSR / JS render parity check for the GEO roadmap (M4).

Optional integration: requires the ``geo-render`` extra
(``pip install silentfrog[geo-render]``) plus ``playwright install
chromium``. When Playwright is not importable the check reports
``not_measured`` and does NOT down-weight the AI Visibility summary.

Only the I/O helper (``render_with_playwright``) talks to Playwright.
``compute_render_diff`` is pure and is what the tests exercise; the
fixture pair under ``docs/tests/fixtures/render_diff_*.html`` is enough
to cover the verdict logic without ever installing Chromium.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from bs4 import BeautifulSoup

from .crawl_types import AiVisibilityCheck

try:  # optional dep, gated behind the silentfrog[geo-render] extra
    from playwright.sync_api import sync_playwright  # type: ignore[import]
except Exception:  # pragma: no cover - exercised by setattr in tests
    sync_playwright = None  # type: ignore[assignment]


@dataclass(frozen=True)
class RenderResult:
    url: str
    rendered_html: str
    error: str = ""
    # v1.1 N1: when collect_vitals=True was passed, this carries the
    # raw CDP-derived CWV payload (a dict suitable for
    # ``perf_vitals.WebVitals.from_raw``). ``None`` means CWV were
    # not requested.
    vitals_payload: dict[str, Any] | None = None
    # v3 G4: return value of an ``evaluate_js`` expression passed to
    # ``RenderPool.render`` (e.g. the axe-core scan result). ``None`` means
    # no script was requested, or it failed/returned nothing.
    script_result: Any = None


RenderStatus = Literal["good", "warning", "critical", "not_measured"]


@dataclass(frozen=True)
class RenderDiff:
    status: RenderStatus
    missing_headings: tuple[str, ...] = ()
    missing_main_text_chars: int = 0
    missing_links: int = 0
    reason: str = ""


def render_with_playwright(
    url: str,
    timeout_seconds: int = 15,
    collect_vitals: bool = False,
) -> RenderResult | None:
    """Render *url* with Chromium and return the post-JS DOM.

    Returns ``None`` when Playwright is not installed (gated on the
    optional ``geo-render`` extra). Returns a ``RenderResult`` whose
    ``error`` field is populated on any other failure (network,
    timeout, browser launch). Never raises.

    When ``collect_vitals`` is True, the same browser session also
    drives a CDP ``Performance.getMetrics`` call after navigation and
    stores the parsed CWV payload on ``RenderResult.vitals_payload``.
    Sharing the session keeps the per-URL cost flat at one browser
    launch.
    """
    if sync_playwright is None:
        return None
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(url, timeout=timeout_seconds * 1000, wait_until="networkidle")
                vitals_payload = _collect_cdp_vitals(page) if collect_vitals else None
                return RenderResult(
                    url=url,
                    rendered_html=page.content(),
                    vitals_payload=vitals_payload,
                )
            finally:
                browser.close()
    except Exception as exc:  # pragma: no cover - real Chromium failures
        return RenderResult(url=url, rendered_html="", error=f"{type(exc).__name__}: {exc}")


def _collect_cdp_vitals(page: Any) -> dict[str, Any]:
    """Drive CDP to capture lab Core Web Vitals from the open page.

    Returns the raw payload (a dict suitable for
    ``WebVitals.from_raw``). Any failure mode produces a dict with a
    populated ``reason`` and otherwise ``None`` metric fields.
    """
    try:
        cdp = page.context.new_cdp_session(page)
    except Exception as exc:  # pragma: no cover - real CDP failures
        return {"reason": f"CDP unavailable: {type(exc).__name__}: {exc}"}
    try:
        cdp.send("Performance.enable")
    except Exception as exc:  # pragma: no cover - real CDP failures
        return {"reason": f"Performance.enable failed: {type(exc).__name__}: {exc}"}
    try:
        page.keyboard.press("Tab", timeout=2000)
    except Exception:
        # Non-fatal: some pages don't accept keyboard input; LCP/CLS
        # still measurable.
        pass
    try:
        metrics_response = cdp.send("Performance.getMetrics")
    except Exception as exc:  # pragma: no cover - real CDP failures
        return {"reason": f"Performance.getMetrics failed: {type(exc).__name__}: {exc}"}
    return _vitals_dict_from_cdp(metrics_response)


_CDP_VITALS_NAME_MAP = {
    "LargestContentfulPaint": "lcp_ms",
    "FirstContentfulPaint": "fcp_ms",
    "CumulativeLayoutShift": "cls",
    "InteractionToNextPaint": "inp_ms",
    "TotalBlockingTime": "tbt_ms",
    "SpeedIndex": "speed_index_ms",
}


def _vitals_dict_from_cdp(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"reason": "getMetrics returned non-dict"}
    metrics = response.get("metrics") or []
    if not isinstance(metrics, list):
        return {"reason": "metrics field not a list"}
    parsed: dict[str, Any] = {}
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name", ""))
        if name not in _CDP_VITALS_NAME_MAP:
            continue
        try:
            parsed[_CDP_VITALS_NAME_MAP[name]] = float(metric.get("value"))
        except (TypeError, ValueError):
            parsed[_CDP_VITALS_NAME_MAP[name]] = None
    return parsed


def _normalised_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.extract()
    return soup.get_text(separator=" ", strip=True)


def _headings(html: str) -> set[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    return {tag.get_text(strip=True) for tag in soup.find_all(["h1", "h2", "h3"]) if tag.get_text(strip=True)}


def _link_count(html: str) -> int:
    soup = BeautifulSoup(html or "", "html.parser")
    return sum(1 for tag in soup.find_all("a") if (tag.get("href") or "").strip())


_CRITICAL_TEXT_DELTA = 500
_WARNING_TEXT_DELTA = 200
_CRITICAL_LINK_DELTA = 5
_WARNING_LINK_DELTA = 2


def _diff_status(missing_headings: tuple[str, ...], text_delta: int, link_delta: int) -> RenderStatus:
    if missing_headings and (text_delta > _CRITICAL_TEXT_DELTA or link_delta > _CRITICAL_LINK_DELTA):
        return "critical"
    if missing_headings or text_delta > _WARNING_TEXT_DELTA or link_delta > _WARNING_LINK_DELTA:
        return "warning"
    return "good"


def compute_render_diff(plain_html: str, rendered_html: str) -> RenderDiff:
    """Compare the SSR DOM with the post-JS DOM.

    Pure function — no Playwright dependency. Returns ``status="critical"``
    when the rendered DOM is empty (engine fetched nothing or the page
    is JS-gated). Returns ``status="good"`` when the SSR DOM covers the
    headings, ~the same body length, and the same link count.
    """
    if not (rendered_html or "").strip():
        return RenderDiff(status="critical", reason="Rendered HTML is empty")
    plain_headings = _headings(plain_html)
    rendered_headings = _headings(rendered_html)
    missing_headings = tuple(sorted(rendered_headings - plain_headings))
    plain_text = _normalised_text(plain_html)
    rendered_text = _normalised_text(rendered_html)
    text_delta = max(0, len(rendered_text) - len(plain_text))
    plain_links = _link_count(plain_html)
    rendered_links = _link_count(rendered_html)
    link_delta = max(0, rendered_links - plain_links)
    return RenderDiff(
        status=_diff_status(missing_headings, text_delta, link_delta),
        missing_headings=missing_headings,
        missing_main_text_chars=text_delta,
        missing_links=link_delta,
    )


def _status_for_check(diff_status: RenderStatus) -> str:
    """Translate RenderDiff.status into an AiVisibilityCheck status.

    ``not_measured`` collapses to ``info`` so the GEO Score and the
    verdict logic never penalise an opt-in check the user did not enable.
    """
    return "info" if diff_status == "not_measured" else diff_status


_CHECK_TITLE = "Server-rendered DOM matches the JS-rendered DOM"
_CHECK_RECOMMENDATION = (
    "Render critical content server-side; AI crawlers commonly fetch without executing JavaScript. "
    "When Playwright is not installed this check reports 'not measured' and does not affect the verdict."
)


def build_render_diff_check(diff: RenderDiff | None) -> AiVisibilityCheck:
    if diff is None:
        return AiVisibilityCheck(
            area="Access",
            check=_CHECK_TITLE,
            status="info",
            details=(
                "Render parity not measured. Install `silentfrog[geo-render]` and enable "
                "'Run SSR parity check' in Crawl settings to surface this row."
            ),
            recommendation=_CHECK_RECOMMENDATION,
            key="access_ssr_parity",
        )
    detail = (
        f"Status: {diff.status}; Missing headings: {len(diff.missing_headings)}; "
        f"Missing main text chars: {diff.missing_main_text_chars}; "
        f"Missing links: {diff.missing_links}."
    )
    if diff.reason:
        detail = f"{detail} Reason: {diff.reason}."
    return AiVisibilityCheck(
        area="Access",
        check=_CHECK_TITLE,
        status=_status_for_check(diff.status),
        details=detail,
        recommendation=_CHECK_RECOMMENDATION,
        key="access_ssr_parity",
    )


__all__ = [
    "RenderDiff",
    "RenderResult",
    "build_render_diff_check",
    "compute_render_diff",
    "render_with_playwright",
]
