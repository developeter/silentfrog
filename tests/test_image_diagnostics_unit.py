from __future__ import annotations

from silentfrog.image_diagnostics import (
    ACTUAL_HEIGHT_COL,
    ACTUAL_WIDTH_COL,
    CACHE_COL,
    DECLARED_HEIGHT_COL,
    DECLARED_WIDTH_COL,
    DIAGNOSTIC_COL,
    FORMAT_HINT_COL,
    RESPONSIVE_COL,
    SIZES_COL,
    merge_image_row,
    normalize_image_row,
)


def test_normalize_image_row_maps_legacy_shape() -> None:
    row = normalize_image_row(
        ["https://example.com/hero.png", "Hero", "", "image/png", "640", "360", "", "", "Lazy", "High"]
    )

    assert row[DECLARED_WIDTH_COL] == "640"
    assert row[DECLARED_HEIGHT_COL] == "360"
    assert row[ACTUAL_WIDTH_COL] == ""
    assert row[ACTUAL_HEIGHT_COL] == ""
    assert row[FORMAT_HINT_COL] == "Consider WebP or AVIF"
    assert "Missing width/height attributes" not in row[DIAGNOSTIC_COL]


def test_merge_image_row_adds_analysis_diagnostics() -> None:
    current = normalize_image_row(
        [
            "https://example.com/hero.jpg",
            "Hero",
            "",
            "image/jpeg",
            "",
            "",
            "",
            "",
            "Lazy",
            "High",
            "640",
            "360",
            "3 candidates",
            "",
            "",
            "",
        ]
    )

    merged = merge_image_row(current, ["https://example.com/hero.jpg", "1600", "900", "420 KB", "image/jpeg", ""])

    assert merged[ACTUAL_WIDTH_COL] == "1600"
    assert merged[ACTUAL_HEIGHT_COL] == "900"
    assert merged[CACHE_COL] == ""
    assert "Source much larger than declared slot" in merged[DIAGNOSTIC_COL]
    assert "No cache TTL exposed" in merged[DIAGNOSTIC_COL]
    assert "Responsive candidates without sizes" in merged[DIAGNOSTIC_COL]


def test_normalize_image_row_preserves_sizes_and_next_gen_state() -> None:
    row = normalize_image_row(
        [
            "https://example.com/hero.webp",
            "Hero",
            "",
            "image/webp",
            "",
            "",
            "",
            "",
            "Lazy",
            "Auto",
            "640",
            "360",
            "2",
            "(min-width: 1024px) 50vw, 100vw",
            "",
            "",
        ]
    )

    assert row[RESPONSIVE_COL] == "2 candidates"
    assert row[SIZES_COL] == "(min-width: 1024px) 50vw, 100vw"
    assert row[FORMAT_HINT_COL] == "Next-gen format"
    assert row[DIAGNOSTIC_COL] == "OK"
