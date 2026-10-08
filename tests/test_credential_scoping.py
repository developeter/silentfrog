"""D1/D4: the user's Cookie / Authorization / custom headers are scoped to the
audited origin (scheme + host + port, exact), and robots.txt fetches honour the
configured User-Agent and those same origin-scoped headers.

Two loopback servers play "the audited site" and "a third party the page links
to"; they differ only by port, which is enough to make them different origins.
"""

from __future__ import annotations

import dataclasses

import pytest
from aiohttp import web  # type: ignore[reportMissingImports]

from silentfrog import crawl_http  # type: ignore[reportMissingImports]
from silentfrog import seo_crawler as crawler
from silentfrog.crawl_mode import CrawlMode  # type: ignore[reportMissingImports]
from silentfrog.crawl_options import AuditProfile, CrawlOptions  # type: ignore[reportMissingImports]
from silentfrog.robots_matcher import RobotsCache  # type: ignore[reportMissingImports]
from silentfrog.site_crawl_types import SiteCrawlConfig, SpiderConfig  # type: ignore[reportMissingImports]
from silentfrog.site_crawler import crawl_site  # type: ignore[reportMissingImports]
from silentfrog.transport import allow_private_network  # type: ignore[reportMissingImports]

SECRET_HEADERS = "Authorization: Token s3cr3t\nX-Api-Key: k-123"
COOKIE = "sid=abc"
PAGE = "<html><head><title>T</title>{head}</head><body><h1>H</h1>{body}</body></html>"


@pytest.fixture(autouse=True)
async def _allow_loopback_test_servers():
    with allow_private_network():
        yield


def _options(**overrides) -> CrawlOptions:
    base = CrawlOptions.from_ui(
        gentle_mode=False,
        max_parallel=4,
        header_text=SECRET_HEADERS,
        cookie_text=COOKIE,
        profile=AuditProfile.DEEP,
    )
    return dataclasses.replace(base, **overrides)


def _credentialed(headers) -> bool:
    return any(headers.get(name) for name in ("Cookie", "Authorization", "X-Api-Key"))


class _Recorder:
    """Records (path, credentialed?, user-agent) for every request a server sees."""

    def __init__(self) -> None:
        self.hits: list[tuple[str, bool, str]] = []

    def note(self, request) -> None:
        self.hits.append((request.path, _credentialed(request.headers), request.headers.get("User-Agent", "")))

    def credentialed_paths(self) -> list[str]:
        return [path for path, credentialed, _ in self.hits if credentialed]

    def paths(self) -> list[str]:
        return [path for path, _, _ in self.hits]


async def _start(aiohttp_server, routes) -> tuple[object, _Recorder]:
    recorder = _Recorder()
    app = web.Application()

    def wrap(handler):
        async def run(request):
            recorder.note(request)
            return await handler(request)

        return run

    for path, handler in routes.items():
        app.router.add_route("*", path, wrap(handler))
    return await aiohttp_server(app), recorder


def _ok(text: str = "ok", content_type: str = "text/plain"):
    async def handler(_request):
        return web.Response(text=text, content_type=content_type)

    return handler


@pytest.mark.asyncio
async def test_probes_never_send_credentials_to_a_third_party(aiohttp_server):
    # Every probe path of one DEEP page audit points at the external server:
    # link status, canonical, hreflang, a robots.txt Sitemap: entry, and
    # origin -> external redirects for canonical and hreflang.
    external, ext_rec = await _start(
        aiohttp_server,
        {
            "/link": _ok(),
            "/canon-final": _ok(),
            "/hl-final": _ok(),
            "/sitemap.xml": _ok("<urlset/>", "application/xml"),
        },
    )
    ext = str(external.make_url("")).rstrip("/")

    def redirect_to(path: str):
        async def handler(_request):
            raise web.HTTPFound(f"{ext}{path}")

        return handler

    async def origin_page(request):
        head = (
            f'<link rel="canonical" href="/canon-redir">'
            f'<link rel="alternate" hreflang="fr-FR" href="/hl-redir">'
            f'<link rel="alternate" hreflang="de-DE" href="{ext}/hl-final">'
        )
        body = f'<a href="{ext}/link">ext</a><a href="/internal">int</a>'
        return web.Response(text=PAGE.format(head=head, body=body), content_type="text/html")

    async def robots(_request):
        return web.Response(text=f"User-agent: *\nAllow: /\nSitemap: {ext}/sitemap.xml\n")

    origin, org_rec = await _start(
        aiohttp_server,
        {
            "/": origin_page,
            "/internal": _ok(),
            "/robots.txt": robots,
            "/canon-redir": redirect_to("/canon-final"),
            "/hl-redir": redirect_to("/hl-final"),
        },
    )

    await crawler.analyse(str(origin.make_url("/")), timeout=5, options=_options())

    # Every kind of probe really reached the third party ...
    assert {"/link", "/canon-final", "/hl-final", "/sitemap.xml"} <= set(ext_rec.paths())
    # ... and none of them carried the user's credentials.
    assert ext_rec.credentialed_paths() == []
    # The audited origin still gets them: page, same-origin link probe, the
    # first hop of the redirecting canonical/hreflang, robots.txt.
    assert {"/", "/internal", "/canon-redir", "/hl-redir", "/robots.txt"} <= set(org_rec.credentialed_paths())


@pytest.mark.asyncio
async def test_redirect_trace_drops_credentials_on_the_cross_origin_hop(aiohttp_server):
    external, ext_rec = await _start(aiohttp_server, {"/landed": _ok()})
    ext = str(external.make_url("")).rstrip("/")

    async def hop(_request):
        raise web.HTTPFound(f"{ext}/landed")

    origin, org_rec = await _start(aiohttp_server, {"/start": hop})

    url = str(origin.make_url("/start"))
    hops, status, count, _loop = await crawl_http._trace_redirects(url, timeout=5, options=_options())

    assert (count, status) == (1, "200")
    assert hops[-1] == f"{ext}/landed"
    assert ext_rec.paths() == ["/landed"]
    assert ext_rec.credentialed_paths() == []
    assert org_rec.credentialed_paths() == ["/start"]


@pytest.mark.asyncio
async def test_page_fetch_redirect_to_third_party_drops_credentials(aiohttp_server):
    # The audited URL itself redirects off-site. aiohttp alone would keep a
    # custom X-Api-Key on that hop; the transport guard must drop it.
    external, ext_rec = await _start(
        aiohttp_server, {"/final": _ok(PAGE.format(head="", body=""), "text/html"), "/robots.txt": _ok("")}
    )
    ext = str(external.make_url("")).rstrip("/")

    async def jump(_request):
        raise web.HTTPFound(f"{ext}/final")

    origin, org_rec = await _start(aiohttp_server, {"/jump": jump, "/robots.txt": _ok("")})

    await crawler.analyse(str(origin.make_url("/jump")), timeout=5, options=_options())

    assert "/final" in ext_rec.paths()
    assert ext_rec.credentialed_paths() == []
    assert "/jump" in org_rec.credentialed_paths()


@pytest.mark.parametrize(
    ("origin", "target", "expected"),
    [
        ("https://a.test/x", "https://a.test/y", True),
        ("https://a.test", "https://A.TEST:443/y", True),  # case + default port
        ("https://a.test", "https://sub.a.test/y", False),  # subdomain is a different origin
        ("https://a.test", "http://a.test/y", False),  # scheme
        ("https://a.test", "https://a.test:8443/y", False),  # port
        ("", "https://a.test/y", False),  # fail closed
        ("https://a.test", "not a url", False),
    ],
)
def test_scoped_extra_headers_is_exact_origin(origin: str, target: str, expected: bool) -> None:
    scoped = crawl_http._scoped_extra_headers(_options(), origin, target)
    assert bool(scoped) is expected
    if expected:
        assert scoped["Cookie"] == COOKIE
        assert scoped["X-Api-Key"] == "k-123"


@pytest.mark.asyncio
async def test_site_crawl_honours_a_cookie_gated_robots_txt(aiohttp_server):
    # robots.txt only discloses "Disallow: /secret" to a request that carries
    # the cookie. If the robots fetch ignored the user's headers (D4) the
    # crawler would see a 404, treat everything as allowed and crawl /secret.
    async def robots(request):
        if request.cookies.get("sid") != "abc":
            return web.Response(status=404)
        return web.Response(text="User-agent: *\nDisallow: /secret\n")

    async def home(_request):
        body = '<a href="/secret">s</a><a href="/open">o</a>'
        return web.Response(text=PAGE.format(head="", body=body), content_type="text/html")

    page = _ok(PAGE.format(head="", body=""), "text/html")
    server, rec = await _start(aiohttp_server, {"/": home, "/robots.txt": robots, "/secret": page, "/open": page})
    config = SiteCrawlConfig.from_text(
        base_url=str(server.make_url("/")),
        crawl_options=_options(profile=AuditProfile.LIGHTWEIGHT),
        spider=SpiderConfig(mode=CrawlMode.SPIDER, politeness_delay_ms=0, max_urls=10),
    )

    report = await crawl_site(config, timeout=5)

    crawled = {urlpath for urlpath in rec.paths() if urlpath in {"/secret", "/open"}}
    assert "/open" in crawled
    assert "/secret" not in crawled
    assert report.discovered_count >= 1


@pytest.mark.asyncio
async def test_robots_fetches_send_the_configured_user_agent(aiohttp_server):
    server, rec = await _start(aiohttp_server, {"/robots.txt": _ok("User-agent: *\nDisallow: /nope\n")})
    base = str(server.make_url("/page"))
    options = _options(user_agent="AcmeAudit/9.9")

    # Single-page audit path (http_client.fetch_text).
    rules = await crawl_http._parse_robots(base, timeout=5, options=options)
    assert not rules.allows("*", base.replace("/page", "/nope"))
    # Site-crawl path (robots_matcher.fetch_robots_matcher via RobotsCache).
    cache = RobotsCache(options.user_agent, 5, options=options, origin=base)
    assert not await cache.allows(base.replace("/page", "/nope"))

    robots_hits = [hit for hit in rec.hits if hit[0] == "/robots.txt"]
    assert len(robots_hits) == 2
    assert {ua for _, _, ua in robots_hits} == {"AcmeAudit/9.9"}
    assert all(credentialed for _, credentialed, _ in robots_hits)  # same origin -> headers kept


@pytest.mark.asyncio
async def test_robots_cache_does_not_send_credentials_to_another_origin(aiohttp_server):
    server, rec = await _start(aiohttp_server, {"/robots.txt": _ok("User-agent: *\nAllow: /\n")})
    cache = RobotsCache("AcmeAudit/9.9", 5, options=_options(), origin="https://audited.example/")
    await cache.allows(str(server.make_url("/page")))

    assert rec.paths() == ["/robots.txt"]
    assert rec.credentialed_paths() == []
