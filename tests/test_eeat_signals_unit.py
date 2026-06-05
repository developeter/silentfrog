from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import silentfrog.eeat_signals as eeat  # type: ignore[reportMissingImports]
from silentfrog.eeat_signals import (  # type: ignore[reportMissingImports]
    EeatPayload,
    _freshness_threshold_days,
    build_eeat_checks,
    extract_eeat_signals,
)
from silentfrog.schema_extractor import _extract_schema_all  # type: ignore[reportMissingImports]

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"
PAGE_URL = "https://example.com/article"


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def _schema(name: str) -> dict:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return _extract_schema_all(html, PAGE_URL)


def _checks(payload: EeatPayload, days: int = 365) -> dict[str, str]:
    return {item.key: item.status for item in build_eeat_checks(payload, freshness_days=days)}


def test_extract_eeat_finds_all_signals_in_full_fixture() -> None:
    payload = extract_eeat_signals(_soup("eeat_full_signals.html"), _schema("eeat_full_signals.html"), PAGE_URL)
    assert payload.byline == "Mario Rossi"
    assert payload.publish_date.startswith("2026-04-12")
    assert payload.update_date.startswith("2026-05-20")
    assert any("linkedin.com/in/mariorossi" in entry for entry in payload.same_as)
    assert payload.author_bio_url.endswith("/authors/mario-rossi")


def test_extract_eeat_anonymous_page_has_no_signals() -> None:
    payload = extract_eeat_signals(_soup("eeat_no_byline.html"), _schema("eeat_no_byline.html"), PAGE_URL)
    assert payload.byline == ""
    assert payload.publish_date == ""
    assert payload.update_date == ""
    assert payload.author_bio_url == ""
    assert payload.same_as == ()


def test_extract_eeat_dates_from_meta_only() -> None:
    payload = extract_eeat_signals(_soup("eeat_stale_dated.html"), _schema("eeat_stale_dated.html"), PAGE_URL)
    assert payload.publish_date.startswith("2018-01-15")
    assert payload.update_date.startswith("2018-06-15")
    assert payload.byline == "Jane Smith"


def test_extract_eeat_external_citations_skip_social_and_internal() -> None:
    payload = extract_eeat_signals(
        _soup("eeat_external_citations.html"),
        _schema("eeat_external_citations.html"),
        PAGE_URL,
    )
    assert "https://twitter.com/example" not in payload.external_citations
    # Three external, non-social citations
    assert len(payload.external_citations) == 3
    assert all("twitter" not in url for url in payload.external_citations)


def test_build_eeat_checks_full_page_is_good() -> None:
    payload = extract_eeat_signals(_soup("eeat_full_signals.html"), _schema("eeat_full_signals.html"), PAGE_URL)
    statuses = _checks(payload, days=365)
    assert statuses["eeat_author_byline"] == "good"
    assert statuses["eeat_publish_date"] == "good"
    assert statuses["eeat_author_bio"] == "good"


def test_build_eeat_checks_anonymous_page_warns_on_eeat_but_info_on_citations() -> None:
    payload = extract_eeat_signals(_soup("eeat_no_byline.html"), _schema("eeat_no_byline.html"), PAGE_URL)
    statuses = _checks(payload, days=365)
    assert statuses["eeat_author_byline"] == "warning"
    assert statuses["eeat_publish_date"] == "warning"
    assert statuses["eeat_author_bio"] == "warning"
    # Myth-flagged citation check: absent => info, never warning.
    assert statuses["eeat_external_citations"] == "info"


def test_build_eeat_checks_stale_dates_warn_freshness() -> None:
    payload = extract_eeat_signals(_soup("eeat_stale_dated.html"), _schema("eeat_stale_dated.html"), PAGE_URL)
    statuses = _checks(payload, days=365)
    assert statuses["eeat_update_freshness"] == "warning"


def test_build_eeat_checks_synthetic_fresh_payload_passes_freshness() -> None:
    fresh = date.today() - timedelta(days=30)
    payload = EeatPayload(
        byline="Mario",
        publish_date=fresh.isoformat(),
        update_date=fresh.isoformat(),
        days_since_update=30,
        author_bio_url="https://example.com/about",
    )
    statuses = _checks(payload, days=365)
    assert statuses["eeat_update_freshness"] == "good"


@pytest.mark.parametrize(
    "myth_key",
    ["eeat_external_citations"],
)
def test_eeat_myth_keys_never_warn_when_absent(myth_key: str) -> None:
    payload = EeatPayload.empty()
    statuses = _checks(payload, days=365)
    assert statuses[myth_key] not in {"warning", "critical"}


def test_eeat_payload_roundtrips_through_dict() -> None:
    payload = EeatPayload(
        byline="A",
        publish_date="2026-01-01",
        update_date="2026-02-01",
        days_since_update=10,
        author_bio_url="https://example.com/about",
        same_as=("https://example.com/social",),
        external_citations=("https://other.com/a",),
    )
    restored = EeatPayload.from_raw(payload.to_dict())
    assert restored == payload


def test_freshness_threshold_reads_env_var(monkeypatch) -> None:
    monkeypatch.setenv("SILENTFROG_EEAT_FRESHNESS_DAYS", "30")
    assert _freshness_threshold_days() == 30
    monkeypatch.setenv("SILENTFROG_EEAT_FRESHNESS_DAYS", "notnumber")
    assert _freshness_threshold_days() == 365  # falls back to default
    monkeypatch.delenv("SILENTFROG_EEAT_FRESHNESS_DAYS", raising=False)
    assert _freshness_threshold_days() == 365


def test_extract_eeat_byline_from_address_block() -> None:
    html = """
    <html><body>
      <article>
        <h1>Title</h1>
        <address>By Bob Editor</address>
        <p>Body content.</p>
      </article>
    </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    payload = extract_eeat_signals(soup, {}, PAGE_URL)
    assert "Bob Editor" in payload.byline
