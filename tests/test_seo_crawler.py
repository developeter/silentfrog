import pytest
import textwrap
from aiohttp import web

from silentfrog.seo_crawler import analyse, analyse_images

HTML = textwrap.dedent("""
<html><head>
<meta name="description" content="foo bar">
<script type="application/ld+json">{"@context":"https://schema.org"}</script>
</head><body>
<h1>Titolo</h1>
<img src="/logo.png" alt="logo">
<a href="https://ext.com" rel="nofollow">ext</a>
<p>Hello world</p>
</body></html>
""")

# ------------------------------------------------------------------ #
@pytest.fixture
async def local_server(aiohttp_server):
    async def handler(_):
        return web.Response(text=HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    return str(server.make_url("/"))

# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_analyse(local_server):
    data = await analyse(local_server, timeout=5)
    assert any(r[0] == "description" for r in data["meta"])
    assert any(r[0] == "h1" for r in data["headers"])
    assert data["images"][0][0].endswith("/logo.png")
    assert data["links"][0][2] == "NoFollow"
    assert "@context" in data["schema"][0][0]

# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_analyse_images(local_server):
    rows = [["/logo.png", "", "", ""]]
    out = await analyse_images(local_server, rows, timeout=5)
    assert out and out[0][0].endswith("/logo.png")
    assert out[0][1].isdigit() and out[0][2].isdigit()
    assert out[0][3].endswith("B")
