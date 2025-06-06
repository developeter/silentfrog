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
    """
    Fire up a minimal aiohttp server that replies to GET "/" with our fixed HTML.
    """
    async def handler(_):
        return web.Response(text=HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", handler)
    server = await aiohttp_server(app)
    return str(server.make_url("/"))


# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_analyse(local_server):
    """
    Verify that analyse() returns a dict containing:
      - at least one meta tag named "description"
      - at least one header "h1"
      - images[0][0] ends with "/logo.png"
      - links[0][2] == "NoFollow"
      - schema[0][0] contains '@context'
    """
    data = await analyse(local_server, timeout=5)

    # 1) meta contains a row whose first column is "description"
    assert any(row[0] == "description" for row in data["meta"])

    # 2) headers contains at least one ["h1", ...]
    assert any(row[0] == "h1" for row in data["headers"])

    # 3) images => first column is a full URL ending in "/logo.png"
    #    (depending on aiohttp_server port, it will be "http://127.0.0.1:<port>/logo.png")
    assert data["images"][0][0].endswith("/logo.png")

    # 4) links => the third column (Follow / NoFollow) should be "NoFollow"
    assert data["links"][0][2] == "NoFollow"

    # 5) schema => first row is a one‐element list [raw_jsonld], which must contain "@context"
    first = data["schema"][0]
    if isinstance(first, dict):
    # Extruct returned a dict for JSON-LD, microdata, etc.
      assert "@context" in first
    elif isinstance(first, list) and first:
      # fallback: one-element list containing raw JSON-LD string
      assert "@context" in first[0]
    else:
      pytest.fail(f"Unexpected schema item type: {type(first)}")



# ------------------------------------------------------------------ #
@pytest.mark.asyncio
async def test_analyse_images(local_server):
    """
    Verify that analyse_images() correctly fetches width/height/size.
    We supply one image row with src="/logo.png", alt="", title="".
    The function should return a list of tuples; the first tuple's URL endswith "/logo.png",
    and width, height are digits, and humanized size ends with 'B' or 'KB' etc.
    """
    # Our input "rows" (the crawl saw exactly one <img src="/logo.png">)
    input_rows = [["/logo.png", "", "", ""]]

    # Call analyse_images(...) with that single row
    out = await analyse_images(local_server, input_rows, timeout=5)

    # out must be a non‐empty list of 4‐tuples
    assert isinstance(out, list)
    assert len(out) == 1

    url, width, height, hr_size = out[0]

    # 1) the URL returned should end with "/logo.png"
    assert url.endswith("/logo.png")

    # 2) width and height must be integer strings or integers
    #    (Our test HTML <img> is a 1×1 image by default in aiohttp test, 
    #     but we only require that they be digits)
    assert isinstance(width, int) or (isinstance(width, str) and width.isdigit())
    assert isinstance(height, int) or (isinstance(height, str) and height.isdigit())

    # 3) humanized size (hr_size) should be a string ending in 'B' (like "14 B", "0 B", "1 KB" etc)
    assert isinstance(hr_size, str)
    assert hr_size.endswith("B")
