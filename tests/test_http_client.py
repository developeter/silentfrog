from __future__ import annotations

import pytest

from silentfrog.http_client import HttpResponse, fetch_page  # type: ignore[reportMissingImports]


@pytest.mark.asyncio
async def test_fetch_page_uses_supplied_headers(monkeypatch):
    captured: dict[str, dict[str, str]] = {}

    class DummySession:
        def __init__(self, *_, headers: dict[str, str] | None = None, **__):
            captured["headers"] = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def fake_fetch(session, url, timeout):
        return HttpResponse("", 200, url, {}, 0.0, 0.0)

    monkeypatch.setattr("silentfrog.http_client.open_crawl_session", DummySession)
    monkeypatch.setattr("silentfrog.http_client.fetch", fake_fetch)

    custom_headers = {
        "User-Agent": "GentleBot/1.0",
        "Accept": "text/html",
        "Accept-Language": "en-US",
    }

    await fetch_page("https://example.com", headers=custom_headers)

    assert captured["headers"] == custom_headers


# --- PR-F2 (D5): the failure cause is classified and named -------------------


def test_classify_fetch_error_unwraps_aiohttp_wrappers() -> None:
    import ssl

    from silentfrog.http_client import classify_fetch_error
    from silentfrog.ssrf import SsrfBlockedError

    class _Wrapper(OSError):  # stands in for aiohttp.ClientConnectorError.os_error
        os_error: BaseException | None = None

    ssrf = _Wrapper("connect failed")
    ssrf.os_error = SsrfBlockedError("blocked")
    tls = _Wrapper("connect failed")
    tls.__cause__ = ssl.SSLCertVerificationError("bad cert")
    assert classify_fetch_error(ssrf) == "ssrf"
    assert classify_fetch_error(tls) == "tls"
    assert classify_fetch_error(ValueError("other")) == ""


@pytest.mark.asyncio
async def test_loopback_with_defaults_tells_the_user_which_box_to_tick(aiohttp_server):
    from aiohttp import web

    from silentfrog import seo_crawler
    from silentfrog.crawl_options import CrawlOptions

    async def _ok(_):
        return web.Response(text="<html></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", _ok)
    server = await aiohttp_server(app)
    url = f"http://127.0.0.1:{server.port}/"
    assert (await fetch_page(url)).error_kind == "ssrf"
    with pytest.raises(RuntimeError, match="Allow private-network targets"):
        await seo_crawler._fetch_analysis_response(url, timeout=5, crawl_options=CrawlOptions.default())


def test_fetch_failure_message_names_the_tls_box_and_falls_back_when_unknown() -> None:
    from silentfrog.seo_crawler import _fetch_failure_message

    assert "Allow insecure TLS" in _fetch_failure_message("https://e.com", "tls")
    assert "Check the URL" in _fetch_failure_message("https://e.com", "")
