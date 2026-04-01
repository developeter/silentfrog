from __future__ import annotations

import pytest

import silentfrog.parsers_meta as parsers  # type: ignore[reportMissingImports]


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00"
    b"\x00\x00\x04\x00\x01\x0b\xe7\x02\xb5\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeResponse:
    def __init__(self, raw: bytes, headers: dict[str, str]) -> None:
        self._raw = raw
        self.headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self) -> bytes:
        return self._raw


class _FakeSession:
    def __init__(self, raw: bytes, headers: dict[str, str]) -> None:
        self._raw = raw
        self._headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, **kwargs):
        return _FakeResponse(self._raw, self._headers)


@pytest.mark.asyncio
async def test_fetch_image_details_empty_url() -> None:
    assert await parsers._fetch_image_details("", timeout=1) == (0, 0, 0, "-", "")


@pytest.mark.asyncio
async def test_fetch_image_details_image_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        parsers.aiohttp,
        "ClientSession",
        lambda: _FakeSession(PNG_BYTES, {"Content-Type": "image/png"}),
    )

    width, height, size_b, mime, data_uri = await parsers._fetch_image_details("https://example.com/image.png", timeout=1)

    assert width == 1
    assert height == 1
    assert size_b == len(PNG_BYTES)
    assert mime == "image/png"
    assert data_uri.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_fetch_image_details_non_image_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        parsers.aiohttp,
        "ClientSession",
        lambda: _FakeSession(b"plain text body", {"Content-Type": "text/plain"}),
    )

    width, height, size_b, mime, data_uri = await parsers._fetch_image_details("https://example.com/file.txt", timeout=1)

    assert (width, height) == (0, 0)
    assert size_b == len(b"plain text body")
    assert mime == "text/plain"
    assert data_uri == ""


@pytest.mark.asyncio
async def test_fetch_image_details_graceful_failure(monkeypatch) -> None:
    class _BrokenSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(parsers.aiohttp, "ClientSession", lambda: _BrokenSession())

    assert await parsers._fetch_image_details("https://example.com/image.png", timeout=1) == (0, 0, 0, "-", "")
