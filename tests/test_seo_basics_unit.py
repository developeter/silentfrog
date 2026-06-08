from __future__ import annotations

from bs4 import BeautifulSoup

from silentfrog.seo_basics import (
    SeoBasicsPayload,
    build_seo_basics_checks,
    descriptive_url_slug,
    detect_viewport,
    extract_seo_basics,
)


def _by_key(rows):
    return {r.key: r for r in rows}


def test_detect_viewport_present_and_responsive() -> None:
    soup = BeautifulSoup(
        '<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body/></html>',
        "html.parser",
    )
    present, content = detect_viewport(soup)
    assert present is True
    assert "device-width" in content


def test_detect_viewport_absent() -> None:
    soup = BeautifulSoup("<html><head/><body/></html>", "html.parser")
    present, content = detect_viewport(soup)
    assert present is False
    assert content == ""


def test_descriptive_url_passes_clean_slug() -> None:
    is_desc, path = descriptive_url_slug("https://example.com/docs/getting-started")
    assert is_desc is True
    assert path == "/docs/getting-started"


def test_descriptive_url_flags_uuid() -> None:
    is_desc, _ = descriptive_url_slug("https://example.com/post/0123abcd-4567-89ef-89ab-0123456789ab")
    assert is_desc is False


def test_descriptive_url_flags_long_digit_run() -> None:
    is_desc, _ = descriptive_url_slug("https://example.com/post/12345678")
    assert is_desc is False


def test_descriptive_url_flags_uppercase() -> None:
    is_desc, _ = descriptive_url_slug("https://example.com/Docs/Getting-Started")
    assert is_desc is False


def test_root_url_is_descriptive() -> None:
    is_desc, _ = descriptive_url_slug("https://example.com/")
    assert is_desc is True


def test_extract_seo_basics_combines_both_signals() -> None:
    soup = BeautifulSoup(
        '<html><head><meta name="viewport" content="width=device-width"></head><body/></html>',
        "html.parser",
    )
    payload = extract_seo_basics(soup, "https://example.com/docs/getting-started")
    assert payload.viewport_present is True
    assert payload.descriptive_url is True


def test_build_seo_basics_checks_routes_to_topic_clarity() -> None:
    rows = build_seo_basics_checks(SeoBasicsPayload.empty())
    assert {r.area for r in rows} == {"Topic clarity"}
    assert {r.key for r in rows} == {"seo_viewport_mobile", "seo_descriptive_url"}


def test_build_seo_basics_checks_present_routes_to_good() -> None:
    payload = SeoBasicsPayload(
        viewport_present=True,
        viewport_content="width=device-width",
        descriptive_url=True,
        url_path="/docs/x",
    )
    rows = _by_key(build_seo_basics_checks(payload))
    assert rows["seo_viewport_mobile"].status == "good"
    assert rows["seo_descriptive_url"].status == "good"


def test_seo_basics_never_warn_when_absent() -> None:
    rows = build_seo_basics_checks(SeoBasicsPayload.empty())
    assert all(r.status not in {"warning", "critical"} for r in rows)


def test_seo_basics_payload_roundtrips_through_dict() -> None:
    payload = SeoBasicsPayload(
        viewport_present=True,
        viewport_content="width=device-width, initial-scale=1",
        descriptive_url=False,
        url_path="/post/12345678",
    )
    restored = SeoBasicsPayload.from_raw(payload.to_dict())
    assert restored == payload
