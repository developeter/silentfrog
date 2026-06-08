from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import silentfrog.discovery_files as discovery_files  # type: ignore[reportMissingImports]
from silentfrog.discovery_files import (  # type: ignore[reportMissingImports]
    DiscoveryEntry,
    DiscoveryPayload,
    build_discovery_checks,
    fetch_discovery_files,
)

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class _DummyResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> _DummyResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def text(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self._body


class _DummySession:
    """Routes GET by URL path to a precomputed (status, body) map.

    Mirrors the DummySession pattern from tests/test_http_client.py:13
    so the test never touches a live socket.
    """

    def __init__(self, routes: Mapping[str, tuple[int, str]], **_: Any) -> None:
        self._routes = dict(routes)
        self.calls: list[str] = []

    async def __aenter__(self) -> _DummySession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def get(self, url: str, **_: Any) -> _DummyResponse:
        self.calls.append(url)
        status, body = self._routes.get(url, (404, ""))
        return _DummyResponse(status, body)


def _install_session(monkeypatch, routes: Mapping[str, tuple[int, str]]) -> _DummySession:
    session_holder: dict[str, _DummySession] = {}

    def _factory(**kwargs: Any) -> _DummySession:
        session = _DummySession(routes, **kwargs)
        session_holder["session"] = session
        return session

    monkeypatch.setattr(discovery_files.aiohttp, "ClientSession", _factory)
    return session_holder.setdefault("session", _DummySession(routes))


@pytest.mark.asyncio
async def test_fetch_discovery_files_all_present(monkeypatch) -> None:
    routes = {
        "https://example.com/llms.txt": (200, _load("llms_txt_allow.txt")),
        "https://example.com/llms-full.txt": (200, _load("llms_full_txt_minimal.txt")),
        "https://example.com/.well-known/ai.json": (200, _load("well_known_ai_allow.json")),
        "https://example.com/sitemap.xml": (200, _load("sitemap_at_root.xml")),
    }
    _install_session(monkeypatch, routes)

    payload = await fetch_discovery_files("https://example.com/some/page")

    assert payload.llms_txt.present is True
    assert payload.llms_txt.parsed.get("title") == "Example Knowledge Base"
    assert payload.llms_full_txt.present is True
    assert payload.well_known_ai_json.present is True
    assert payload.well_known_ai_json.parsed.get("policy") == "allow"
    assert payload.sitemap.present is True
    assert payload.sitemap.source == "root-sitemap"


@pytest.mark.asyncio
async def test_fetch_discovery_files_llms_blocking_variant_is_still_present(monkeypatch) -> None:
    routes = {
        "https://example.com/llms.txt": (200, _load("llms_txt_block.txt")),
        "https://example.com/llms-full.txt": (404, ""),
        "https://example.com/.well-known/ai.json": (200, _load("well_known_ai_block.json")),
        "https://example.com/sitemap.xml": (404, ""),
    }
    _install_session(monkeypatch, routes)

    payload = await fetch_discovery_files("https://example.com/")

    # A block-style llms.txt is still "present" — we report presence,
    # not policy. The user reads policy from the body excerpt.
    assert payload.llms_txt.present is True
    assert "NOT permitted" in payload.llms_txt.body_excerpt
    assert payload.well_known_ai_json.parsed.get("policy") == "deny"
    assert payload.llms_full_txt.present is False
    assert payload.sitemap.present is False


@pytest.mark.asyncio
async def test_fetch_discovery_files_all_missing(monkeypatch) -> None:
    routes: dict[str, tuple[int, str]] = {}
    _install_session(monkeypatch, routes)

    payload = await fetch_discovery_files("https://example.com/")

    assert payload.llms_txt.present is False
    assert payload.llms_full_txt.present is False
    assert payload.well_known_ai_json.present is False
    assert payload.sitemap.present is False


@pytest.mark.asyncio
async def test_fetch_discovery_files_uses_robots_sitemap_directive(monkeypatch) -> None:
    routes = {
        "https://example.com/llms.txt": (404, ""),
        "https://example.com/llms-full.txt": (404, ""),
        "https://example.com/.well-known/ai.json": (404, ""),
        "https://example.com/sitemap.xml": (200, _load("sitemap_at_root.xml")),
        "https://example.com/news-sitemap.xml": (200, _load("sitemap_at_root.xml")),
    }
    _install_session(monkeypatch, routes)
    robots_map = {
        "*": [("Allow", "/"), ("Sitemap", "https://example.com/sitemap.xml")],
        "GPTBot": [("Disallow", "/private/"), ("Sitemap", "https://example.com/news-sitemap.xml")],
    }

    payload = await fetch_discovery_files("https://example.com/", robots_map=robots_map)

    assert payload.sitemap.present is True
    assert payload.sitemap.source == "robots-sitemap"
    assert payload.sitemap.url == "https://example.com/sitemap.xml"
    assert payload.sitemap.parsed.get("robots_sitemap_count") == 2


@pytest.mark.asyncio
async def test_fetch_discovery_files_unparseable_base_url_returns_empty() -> None:
    payload = await fetch_discovery_files("not-a-url")
    assert payload == DiscoveryPayload.empty()


@pytest.mark.asyncio
async def test_fetch_discovery_files_swallows_network_errors(monkeypatch) -> None:
    class _BoomSession:
        def __init__(self, **_: Any) -> None:
            pass

        async def __aenter__(self) -> _BoomSession:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, url: str, **_: Any) -> _DummyResponse:
            class _Broken:
                async def __aenter__(self_inner):
                    raise RuntimeError("boom")

                async def __aexit__(self_inner, exc_type, exc, tb):
                    return False

            return _Broken()  # type: ignore[return-value]

    monkeypatch.setattr(discovery_files.aiohttp, "ClientSession", _BoomSession)

    payload = await fetch_discovery_files("https://example.com/")
    # Errors collapse to absent entries; nothing is raised.
    assert payload.llms_txt.present is False
    assert payload.sitemap.present is False


def test_llms_txt_parser_extracts_title_and_headings() -> None:
    text = _load("llms_txt_allow.txt")
    parsed = discovery_files._parse_llms_txt(text)
    assert parsed["title"] == "Example Knowledge Base"
    assert "Documentation" in parsed["headings"]
    assert "Contact" in parsed["headings"]


def test_well_known_ai_json_parser_returns_mapping() -> None:
    parsed = discovery_files._parse_body(_load("well_known_ai_allow.json"), parser="json")
    assert parsed["policy"] == "allow"
    assert parsed["agents"]["GPTBot"] == "allow"


def test_sitemap_urls_from_robots_dedupes_and_orders() -> None:
    robots = {
        "*": [
            ("Allow", "/"),
            ("Sitemap", "https://example.com/a.xml"),
            ("Sitemap", "https://example.com/b.xml"),
        ],
        "GPTBot": [
            ("Disallow", "/x"),
            ("Sitemap", "https://example.com/a.xml"),
        ],
    }
    assert discovery_files._sitemap_urls_from_robots(robots) == [
        "https://example.com/a.xml",
        "https://example.com/b.xml",
    ]


def test_build_discovery_checks_all_present_are_good() -> None:
    payload = DiscoveryPayload(
        llms_txt=DiscoveryEntry(
            url="https://example.com/llms.txt",
            status=200,
            present=True,
            body_excerpt="# x",
            parsed={"title": "x"},
            source="fetch",
        ),
        llms_full_txt=DiscoveryEntry(
            url="https://example.com/llms-full.txt",
            status=200,
            present=True,
            body_excerpt="# y",
            parsed={},
            source="fetch",
        ),
        well_known_ai_json=DiscoveryEntry(
            url="https://example.com/.well-known/ai.json",
            status=200,
            present=True,
            body_excerpt="{}",
            parsed={"policy": "allow"},
            source="fetch",
        ),
        sitemap=DiscoveryEntry(
            url="https://example.com/sitemap.xml",
            status=200,
            present=True,
            body_excerpt="<urlset/>",
            parsed={"robots_sitemap_count": 1},
            source="robots-sitemap",
        ),
    )
    checks = {item.key: item for item in build_discovery_checks(payload)}
    assert set(checks) == {
        "access_llms_txt",
        "access_llms_full_txt",
        "access_well_known_ai_json",
        "access_sitemap",
    }
    for check in checks.values():
        assert check.status == "good"
        assert check.area == "Access"


def test_build_discovery_checks_all_absent_are_info_mapped_to_good() -> None:
    payload = DiscoveryPayload.empty()
    checks = build_discovery_checks(payload)
    # _STATUS_ALIASES (ai_visibility.py:27) maps "info" -> "good".
    # We rely on AiVisibilityCheck's status field already being normalised
    # by the consumer; here we just confirm we never emit warning/critical.
    assert all(check.status in {"good", "info"} for check in checks)
    assert all(check.status != "warning" for check in checks)
    assert all(check.status != "critical" for check in checks)


def test_discovery_payload_roundtrips_through_dict() -> None:
    entry = DiscoveryEntry(
        url="https://example.com/llms.txt",
        status=200,
        present=True,
        body_excerpt="# Example",
        parsed={"title": "Example"},
        source="fetch",
    )
    payload = DiscoveryPayload(llms_txt=entry)
    restored = DiscoveryPayload.from_raw(payload.to_dict())
    assert restored.llms_txt.url == entry.url
    assert restored.llms_txt.parsed["title"] == "Example"
    assert restored.llms_txt.present is True
