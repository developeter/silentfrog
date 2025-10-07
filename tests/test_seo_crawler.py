import pytest
import textwrap
import warnings
from aiohttp import web

from silentfrog.seo_crawler import analyse, analyse_images

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

HTML = textwrap.dedent(
    """
    <html><head>
      <title>Example page</title>
      <link rel="canonical" href="/" />
      <link rel="alternate" hreflang="en" href="/en" />
      <link rel="icon" href="/favicon.ico" />
      <meta name="description" content="foo bar">
      <meta name="robots" content="index, follow">
      <meta property="og:site_name" content="TestSite" />
      <script type="application/ld+json">{"@context":"https://schema.org"}</script>
    </head><body>
      <h1>Titolo</h1>
      <img src="/logo.png" alt="logo">
      <a href="https://ext.com" rel="nofollow">ext</a>
      <p>Hello world hello analytics keyword focus</p>
    </body></html>
    """
).strip()

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00"
    b"\x00\x00\x04\x00\x01\x0b\xe7\x02\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
        body = "User-agent: *\nDisallow: /tmp\nAllow: /\n"
        return web.Response(text=body, content_type="text/plain")

    app = web.Application()
    app.router.add_route("GET", "/", _html)
    app.router.add_route("HEAD", "/", _html)
    app.router.add_get("/logo.png", _png)
    app.router.add_get("/favicon.ico", _ico)
    app.router.add_get("/robots.txt", _robots)

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

    # Links tab: follow flag and HTTP status populated
    assert payload.links[0][2] == "NoFollow"
    assert payload.links[0][3].isdigit()

    # Schema tab: at least one entry contains @context
    first = payload.schema[0]
    if isinstance(first, dict):
        assert "@context" in first
    elif isinstance(first, list) and first:
        assert "@context" in first[0]
    else:
        pytest.fail(f"Unexpected schema item type: {type(first)}")

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
    assert any(row[0] == "hello" for row in payload.keywords if row[0])


@pytest.mark.asyncio
async def test_analyse_images(local_server):
    input_rows = [["/logo.png", "", "", ""]]
    out = await analyse_images(local_server, input_rows, timeout=5)

    assert isinstance(out, list)
    assert len(out) == 1

    url, width, height, hr_size = out[0]
    assert url.endswith("/logo.png")
    assert isinstance(width, int) or (isinstance(width, str) and width.isdigit())
    assert isinstance(height, int) or (isinstance(height, str) and height.isdigit())
    assert isinstance(hr_size, str) and hr_size.endswith("B")
