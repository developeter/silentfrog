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


def test_ai_agents_matrix_lists_at_least_eighteen_bots() -> None:
    # M1 of docs/geo_roadmap.md: ≥ 18 AI/search agent rows in the matrix.
    assert len(parsers._AI_AGENTS) >= 18


def test_ai_agents_matrix_covers_named_engines() -> None:
    tokens = {agent.token for agent in parsers._AI_AGENTS}
    # Anthropic family, OpenAI family, Perplexity, Google, Apple, Amazon,
    # ByteDance, Common Crawl, Meta, DuckDuckGo, Cohere.
    expected = {
        "gptbot", "chatgpt-user", "oai-searchbot",
        "claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot",
        "perplexitybot", "perplexity-user",
        "googlebot", "google-extended",
        "applebot-extended", "amazonbot", "bytespider", "ccbot",
        "meta-externalagent", "duckassistbot", "cohere-ai",
    }
    missing = expected - tokens
    assert missing == set(), f"missing AI agent tokens: {missing}"


def test_only_googlebot_applies_google_search_controls() -> None:
    google_flagged = [
        agent for agent in parsers._AI_AGENTS if agent.applies_google_search_controls
    ]
    assert [agent.token for agent in google_flagged] == ["googlebot"]


def test_ai_agent_labels_are_unique() -> None:
    labels = [agent.label for agent in parsers._AI_AGENTS]
    assert len(labels) == len(set(labels)), "duplicate label in _AI_AGENTS"
