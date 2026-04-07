from __future__ import annotations

import pytest
import ssl

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

    monkeypatch.setattr("silentfrog.http_client.aiohttp.ClientSession", DummySession)
    monkeypatch.setattr("silentfrog.http_client.fetch", fake_fetch)

    custom_headers = {
        "User-Agent": "GentleBot/1.0",
        "Accept": "text/html",
        "Accept-Language": "en-US",
    }

    await fetch_page("https://example.com", headers=custom_headers)

    assert captured["headers"] == custom_headers


def test_ssl_context_uses_certifi_bundle(monkeypatch):
    captured: dict[str, object] = {}

    class DummyContext:
        def set_ciphers(self, value: str) -> None:
            captured["ciphers"] = value

    def fake_create_default_context(*, cafile=None):
        captured["cafile"] = cafile
        return DummyContext()

    monkeypatch.setattr("silentfrog.http_client.certifi.where", lambda: "/tmp/cacert.pem")
    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)

    from silentfrog.http_client import _ssl_context  # type: ignore[reportMissingImports]

    context = _ssl_context()

    assert isinstance(context, DummyContext)
    assert captured["cafile"] == "/tmp/cacert.pem"
    assert captured["ciphers"] == "DEFAULT:@SECLEVEL=1"
