import asyncio
import pytest
import warnings
import aiohttp  # type: ignore[reportMissingImports]
from aiohttp import web  # type: ignore[reportMissingImports]
from pathlib import Path

from silentfrog import seo_crawler as crawler  # type: ignore[reportMissingImports]
from silentfrog.seo_crawler import analyse, analyse_images  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import CrawlOptions  # type: ignore[reportMissingImports]

# ------------------------------------------------------------------
# Silence third-party warning inside pyRdfa only
# ------------------------------------------------------------------
warnings.filterwarnings(
    "ignore",
    message=r"datetime\.datetime\.utcnow\(\) is deprecated",
    category=DeprecationWarning,
    module=r"pyRdfa\.options",
)

# Silence pyRdfa's deprecated datetime.utcnow() once for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:datetime\\.datetime\\.utcnow\\(\\) is deprecated:DeprecationWarning"
)

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"
HTML = (FIXTURES / "example_page.html").read_text(encoding="utf-8")
ROBOTS_TEXT = (FIXTURES / "robots.txt").read_text(encoding="utf-8")

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00"
    b"\x00\x00\x04\x00\x01\x0b\xe7\x02\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
)
CSS_BYTES = b"body{color:#333;background:#fff;margin:0;}\n"
JS_BYTES = b"console.log('fixture');"
FONT_BYTES = b"wOFF2fixture-font-data"


@pytest.fixture
async def local_server(aiohttp_server):
    """Spin up a minimal aiohttp server that serves the static HTML page."""

    async def _html(_):
        return web.Response(text=HTML, content_type="text/html")

    async def _png(_):
        return web.Response(body=PNG_BYTES, content_type="image/png")

    async def _ico(_):
        return web.Response(body=PNG_BYTES, content_type="image/x-icon")

    async def _robots(_):
        return web.Response(text=ROBOTS_TEXT, content_type="text/plain")

    async def _css(_):
        return web.Response(body=CSS_BYTES, content_type="text/css")

    async def _js(_):
        return web.Response(body=JS_BYTES, content_type="application/javascript")

    async def _font(_):
        return web.Response(body=FONT_BYTES, content_type="font/woff2")

    app = web.Application()
    app.router.add_route("GET", "/", _html)
    app.router.add_route("HEAD", "/", _html)
    app.router.add_get("/logo.png", _png)
    app.router.add_get("/favicon.ico", _ico)
    app.router.add_get("/robots.txt", _robots)
    app.router.add_get("/styles.css", _css)
    app.router.add_get("/app.js", _js)
    app.router.add_get("/font.woff2", _font)

    server = await aiohttp_server(app)
    return str(server.make_url("/"))


@pytest.mark.asyncio
async def test_analyse(local_server):
    payload = await analyse(local_server, timeout=5)

    # Meta tab: description + robots row, meta robots string
    assert any(row[0] == "description" for row in payload.meta)
    assert any(row[0] == "robots" and "index" in row[1].lower() for row in payload.meta)
    assert payload.meta_robots.lower() == "index, follow"

    # Headers tab: one H1 with expected content
    assert any(row[0] == "h1" and "Titolo" in row[1] for row in payload.headers)

    # Images tab: absolute URL, alt preserved
    assert payload.images[0][0].endswith("/logo.png")
    assert payload.images[0][1] == "logo"
    assert payload.images[0][8] == ""

    # Links tab: rel + status populated with context
    rel_value = payload.links[0][3].lower()
    assert "follow" in rel_value or "nofollow" in rel_value
    assert payload.links[0][4].isdigit()
    assert payload.links[0][6]  # section label

    # Schema tab: at least one entry contains @context
    schema_report = payload.schema
    assert schema_report.summary.total >= 1
    assert schema_report.blocks, "expected at least one structured data block"
    first = schema_report.blocks[0]
    assert isinstance(first, dict)
    assert "@context" in first

    # Canonical tab: self-referencing to requested URL
    canon = payload.canonical
    assert canon.is_self is True and canon.target.rstrip("/") == local_server.rstrip("/")

    # Redirect tab: no hops, final status reported, chain starts with URL
    redir = payload.redirect
    assert redir.hops == 0
    assert redir.final_status
    assert redir.chain[0].rstrip("/") == local_server.rstrip("/")

    # Robots tab: parsed robots.txt directives available
    robots_map = payload.robots
    assert "*" in robots_map
    assert ("Disallow", "/tmp") in robots_map["*"]
    assert ("Allow", "/") in robots_map["*"]

    # Hreflang tab: expected alternate link surfaced
    langs = [row[0] for row in payload.hreflang]
    assert "en" in langs
    target = next(row[1] for row in payload.hreflang if row[0] == "en")
    assert target.endswith("/en")

    # AI tab: GPTBot row shows allowed crawl (robots + meta)
    assert payload.ai_crawl[0] == ["GPTBot", "Yes", "No", "Allowed"]

    # SERP tab: preview and audit payloads populated
    serp = payload.serp
    assert serp.title
    expected_crumb = serp.url.split("//", 1)[1].rstrip("/")
    assert serp.breadcrumb == expected_crumb or serp.breadcrumb.startswith(expected_crumb)
    assert serp.site_name == "TestSite"
    assert serp.favicon and serp.favicon.startswith("http")

    audit = payload.serp_audit
    assert {
        "too_long",
        "too_short",
        "px_over",
        "px_under",
        "equals_h1",
        "missing",
        "px_len",
        "char_len",
    } == set(audit.to_dict())
    assert audit.char_len.isdigit()
    assert audit.px_len.isdigit()
    assert audit.missing == "No"

    # Keywords tab: extracted tokens include hello (appears twice in body)
    assert any(entry.term == "hello" for entry in payload.keywords)

    perf = payload.performance
    assert perf.transfer_size >= 0
    summary = perf.resource_summary
    assert summary["css"]["count"] >= 1
    assert summary["css"]["bytes"] >= len(CSS_BYTES)
    assert summary["js"]["count"] >= 1
    assert summary["js"]["bytes"] >= len(JS_BYTES)
    assert summary["img"]["bytes"] >= len(PNG_BYTES)
    assert summary["font"]["bytes"] >= len(FONT_BYTES)
    assert perf.scripts.blocking_count >= 0
    assert perf.scripts.async_count >= 0
    assert perf.scripts.blocking_bytes >= 0
    assert perf.scripts.async_bytes >= 0
    assert perf.top_offenders, "expected top offenders list to be populated"
    assert any(off.resource_type.upper() == "JS" for off in perf.top_offenders)
    assert all(off.bytes >= 0 for off in perf.top_offenders)
    assert isinstance(perf.opportunity_details, list)

@pytest.mark.asyncio
async def test_analyse_images(local_server):
    input_rows = [["/logo.png", "", "", "-", "", "", "", "No", ""]]
    out = await analyse_images(local_server, input_rows, timeout=5)

    assert isinstance(out, list)
    assert len(out) == 1

    url, width, height, hr_size, content_type = out[0]
    assert url.endswith("/logo.png")
    assert isinstance(width, str) and width.isdigit()
    assert isinstance(height, str) and height.isdigit()
    assert isinstance(hr_size, str) and hr_size.endswith("B")
    assert content_type == "image/png"


@pytest.mark.asyncio
async def test_host_throttle_limits_concurrency(aiohttp_server):
    crawler._HOST_DELAYS.clear()
    tracker = {"current": 0, "max": 0}

    async def head_handler(request):
        tracker["current"] += 1
        tracker["max"] = max(tracker["max"], tracker["current"])
        await asyncio.sleep(0.05)
        tracker["current"] -= 1
        return web.Response(status=200)

    app = web.Application()
    app.router.add_route("HEAD", "/", head_handler)
    server = await aiohttp_server(app)
    url = str(server.make_url("/"))
    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(
            *[crawler._link_status(session, url, 5, options) for _ in range(6)]
        )
    assert tracker["max"] <= 2


@pytest.mark.asyncio
async def test_crawl_delay_respected(monkeypatch, aiohttp_server):
    crawler._HOST_DELAYS.clear()
    sleep_calls: list[float] = []

    async def fake_sleep(duration: float):
        sleep_calls.append(duration)

    async def fake_parse(url: str, timeout: int = 5):
        return {"*": [("Crawl-delay", "2")]}

    monkeypatch.setattr(crawler, "_parse_robots", fake_parse)
    monkeypatch.setattr(crawler.asyncio, "sleep", fake_sleep)

    async def html_handler(request):
        return web.Response(text="<html><body>Hello</body></html>")

    app = web.Application()
    app.router.add_get("/", html_handler)
    server = await aiohttp_server(app)
    url = str(server.make_url("/"))

    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=2)
    await crawler.analyse(url, timeout=5, options=options)

    assert sleep_calls, "expected crawl-delay to trigger sleep"
    assert all(pytest.approx(2.0, rel=0.05) == value for value in sleep_calls)


@pytest.mark.asyncio
async def test_backoff_retries_on_429(monkeypatch, aiohttp_server):
    crawler._HOST_DELAYS.clear()
    call_count = {"value": 0}

    async def handler(request):
        call_count["value"] += 1
        status = 429 if call_count["value"] == 1 else 200
        return web.Response(status=status, text="<html><head><title>X</title></head><body></body></html>")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    url = str(server.make_url("/"))

    sleep_durations: list[float] = []

    async def fake_sleep(duration: float):
        sleep_durations.append(duration)

    monkeypatch.setattr(crawler, "_BACKOFF_DELAY", 0.01)
    monkeypatch.setattr(crawler.asyncio, "sleep", fake_sleep)

    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=1, respect_crawl_delay=False)
    payload = await crawler.analyse(url, timeout=5, options=options)

    assert payload.meta, "expected crawl to succeed after retry"
    assert call_count["value"] >= 2
    assert sleep_durations and pytest.approx(0.01, rel=0.1) == sleep_durations[0]


@pytest.mark.asyncio
async def test_custom_header_forwarded(aiohttp_server):
    crawler._HOST_DELAYS.clear()
    seen: list[str | None] = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return web.Response(text="<html><head><title>X</title></head><body></body></html>")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    url = str(server.make_url("/"))

    options = CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=4,
        header_text="Authorization: Token 123",
    )
    payload = await crawler.analyse(url, timeout=5, options=options)
    assert payload.meta
    assert "Token 123" in seen


@pytest.mark.asyncio
async def test_gentle_mode_toggles_backoff_behavior(monkeypatch, aiohttp_server):
    crawler._HOST_DELAYS.clear()
    call_log: list[str] = []

    async def handler(request):
        call_log.append(request.headers.get("User-Agent", ""))
        status = 429 if len(call_log) == 1 else 200
        return web.Response(status=status, text="<html><head><title>X</title></head><body></body></html>")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    url = str(server.make_url("/"))

    sleep_calls: list[float] = []

    async def fake_sleep(duration: float):
        sleep_calls.append(duration)

    monkeypatch.setattr(crawler, "_BACKOFF_DELAY", 0.01)
    monkeypatch.setattr(crawler.asyncio, "sleep", fake_sleep)

    options = CrawlOptions.from_ui(gentle_mode=True, max_parallel=1)
    await crawler.analyse(url, timeout=5, options=options)
    assert len(sleep_calls) >= 1
    call_log.clear()
    sleep_calls.clear()

    fast_options = CrawlOptions.from_ui(gentle_mode=False, max_parallel=4)
    await crawler.analyse(url, timeout=5, options=fast_options)
    assert not sleep_calls  # no backoff when gentle mode is off
