"""Unit tests for the v2.0 V16 hreflang depth validator."""

from __future__ import annotations

from silentfrog.hreflang_validator import (
    HreflangValidation,
    build_hreflang_checks,
    parse_hreflang_entries,
    validate_hreflang,
)

_PAGE = "https://e.com/en/"


def _row(lang: str, href: str, valid: str = "Yes", self_ref: str = "No") -> list[str]:
    return [lang, href, "200", valid, self_ref]


def _status_for(checks: list, key: str) -> str:
    return next(check.status for check in checks if check.key == key)


def test_no_hreflang_returns_no_checks() -> None:
    assert build_hreflang_checks(_PAGE, []) == []
    assert build_hreflang_checks(_PAGE, None) == []


def test_x_default_present_multi_is_good() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
        _row("x-default", "https://e.com/"),
    ]
    checks = build_hreflang_checks(_PAGE, rows)
    assert _status_for(checks, "hreflang_x_default_present") == "good"


def test_x_default_missing_multi_is_info_not_warning() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
    ]
    checks = build_hreflang_checks(_PAGE, rows)
    status = _status_for(checks, "hreflang_x_default_present")
    assert status == "info"
    assert status != "warning"


def test_single_language_x_default_is_good() -> None:
    rows = [_row("en", "https://e.com/en/", self_ref="Yes")]
    checks = build_hreflang_checks(_PAGE, rows)
    assert _status_for(checks, "hreflang_x_default_present") == "good"


def test_return_tag_self_page_no_cluster_never_warns() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
    ]
    checks = build_hreflang_checks(_PAGE, rows)
    status = _status_for(checks, "hreflang_return_tag_complete")
    assert status in {"good", "info"}
    assert status != "warning"


def test_return_tag_no_self_reference_no_cluster_is_info() -> None:
    rows = [_row("en", "https://e.com/en/"), _row("de", "https://e.com/de/")]
    checks = build_hreflang_checks(_PAGE, rows)
    assert _status_for(checks, "hreflang_return_tag_complete") == "info"


def test_return_tag_broken_with_cluster_warns_and_lists_missing() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
    ]
    # The German alternate does NOT link back to the English page.
    cluster = {"https://e.com/de/": [_row("de", "https://e.com/de/", self_ref="Yes")]}
    result = validate_hreflang(_PAGE, rows, cluster)
    assert result.return_tag_complete is False
    assert "de" in result.missing_return_langs
    checks = build_hreflang_checks(_PAGE, rows, cluster)
    assert _status_for(checks, "hreflang_return_tag_complete") == "warning"


def test_return_tag_complete_with_cluster_is_good() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
    ]
    cluster = {
        "https://e.com/de/": [
            _row("en", "https://e.com/en/"),
            _row("de", "https://e.com/de/", self_ref="Yes"),
        ]
    }
    checks = build_hreflang_checks(_PAGE, rows, cluster)
    assert _status_for(checks, "hreflang_return_tag_complete") == "good"


def test_cluster_consistent_is_good_and_divergent_warns() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
    ]
    good_cluster = {
        "https://e.com/de/": [_row("en", "https://e.com/en/"), _row("de", "https://e.com/de/", self_ref="Yes")]
    }
    bad_cluster = {"https://e.com/de/": [_row("de", "https://e.com/de/", self_ref="Yes")]}
    good = build_hreflang_checks(_PAGE, rows, good_cluster)
    bad = build_hreflang_checks(_PAGE, rows, bad_cluster)
    assert _status_for(good, "hreflang_cluster_consistent") == "good"
    assert _status_for(bad, "hreflang_cluster_consistent") == "warning"


def test_duplicate_lang_codes_warn_on_cluster_consistency() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("en", "https://e.com/en-2/"),
    ]
    checks = build_hreflang_checks(_PAGE, rows)
    assert _status_for(checks, "hreflang_cluster_consistent") == "warning"


def test_malformed_lang_warns_on_cluster_consistency() -> None:
    rows = [_row("english", "https://e.com/en/", valid="No", self_ref="Yes")]
    checks = build_hreflang_checks(_PAGE, rows)
    assert _status_for(checks, "hreflang_cluster_consistent") == "warning"


def test_parse_hreflang_entries_tolerates_ragged_rows() -> None:
    rows = [["en"], ["de", "https://e.com/de/"], "not-a-row", ["fr", "https://e.com/fr/", "200", "Yes", "Yes"]]
    entries = parse_hreflang_entries(rows)
    assert len(entries) == 3
    assert entries[0].lang == "en"
    assert entries[0].href == ""
    assert entries[2].self_ref is True


def test_validation_to_dict_roundtrips() -> None:
    rows = [_row("en", "https://e.com/en/", self_ref="Yes"), _row("de", "https://e.com/de/")]
    result = validate_hreflang(_PAGE, rows)
    data = result.to_dict()
    assert data["entry_count"] == 2
    assert "en" in data["distinct_langs"]
    assert data["multiple_languages"] is True
    restored = HreflangValidation(
        **{
            **result.to_dict(),
            "distinct_langs": result.distinct_langs,
            "missing_return_langs": result.missing_return_langs,
        }
    )
    assert restored.entry_count == result.entry_count


def test_every_built_check_has_valid_status_and_area() -> None:
    rows = [
        _row("en", "https://e.com/en/", self_ref="Yes"),
        _row("de", "https://e.com/de/"),
        _row("x-default", "https://e.com/"),
    ]
    checks = build_hreflang_checks(_PAGE, rows)
    assert len(checks) == 3
    for check in checks:
        assert check.status in {"good", "warning", "info"}
        assert check.area == "Hreflang"
