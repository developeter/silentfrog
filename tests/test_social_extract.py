from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

import silentfrog.parsers_meta as parsers  # type: ignore[reportMissingImports]


@pytest.mark.asyncio
async def test_extract_social_cards_basic(monkeypatch):
    html = """
    <html><head>
      <meta property="og:title" content="OG Title">
      <meta property="og:description" content="OG Desc">
      <meta property="og:image" content="/og.png">
      <meta name="twitter:card" content="summary_large_image">
      <meta name="twitter:title" content="TW Title">
      <meta name="twitter:description" content="TW Desc">
    </head><body></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")

    async def fake_fetch(url: str, timeout: int = 5):
        return 1200, 630, 800000, "image/jpeg", ""

    monkeypatch.setattr(parsers, "_fetch_image_details", fake_fetch)

    result = await parsers._extract_social_cards("https://example.com/page", soup, timeout=1)
    og = result["open_graph"]
    tw = result["twitter"]

    assert og["title"] == "OG Title"
    assert og["description"] == "OG Desc"
    assert og["image"].endswith("/og.png")
    assert og["image_bytes"] == 800000
    assert tw["title"] == "TW Title"
    assert tw["card"] == "summary_large_image"
    assert not tw["issues"]


@pytest.mark.asyncio
async def test_extract_social_cards_reports_issues(monkeypatch):
    html = """
    <html><head>
      <meta property="og:title" content="OG Title">
      <meta property="og:image" content="/og.png">
      <meta name="twitter:card" content="unknown">
    </head><body></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")

    async def fake_fetch(url: str, timeout: int = 5):
        return 50, 50, 6_000_000, "image/png", ""

    monkeypatch.setattr(parsers, "_fetch_image_details", fake_fetch)

    result = await parsers._extract_social_cards("https://example.com/page", soup, timeout=1)
    og = result["open_graph"]
    tw = result["twitter"]

    assert any("missing open graph description" in msg.lower() for msg in og["issues"])
    assert any("image over 5" in msg.lower() for msg in og["issues"])
    assert any("very small" in msg.lower() for msg in og["issues"])
    assert any("unsupported twitter:card" in msg.lower() for msg in tw["issues"])
