from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from silentfrog.structure_signals import (  # type: ignore[reportMissingImports]
    StructurePayload,
    build_structure_checks,
    extract_structure_signals,
)

FIXTURES = Path(__file__).resolve().parents[1] / "docs" / "tests" / "fixtures"
PAGE_URL = "https://example.com/page"


def _soup(name: str) -> BeautifulSoup:
    return BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")


def _statuses(payload: StructurePayload) -> dict[str, str]:
    return {item.key: item.status for item in build_structure_checks(payload)}


def test_semantic_full_fixture_has_many_landmark_types() -> None:
    payload = extract_structure_signals(_soup("structure_semantic_full.html"), PAGE_URL)
    counts = payload.semantic_container_counts
    assert counts["main"] >= 1
    assert counts["article"] >= 1
    assert counts["nav"] >= 1
    assert counts["header"] >= 1
    assert counts["footer"] >= 1


def test_divsoup_fixture_has_no_semantic_landmarks() -> None:
    payload = extract_structure_signals(_soup("structure_divsoup.html"), PAGE_URL)
    counts = payload.semantic_container_counts
    assert sum(counts.values()) == 0


def test_internal_link_partition() -> None:
    payload = extract_structure_signals(_soup("structure_internal_links_rich.html"), PAGE_URL)
    assert payload.internal_link_count >= 4
    # One external link (example.org)
    assert payload.total_link_count - payload.internal_link_count == 1


def test_images_alt_mixed_partition() -> None:
    payload = extract_structure_signals(_soup("structure_images_alt_mixed.html"), PAGE_URL)
    assert payload.images_total == 3
    assert payload.images_with_alt == 2


def test_build_structure_checks_semantic_full_is_good() -> None:
    payload = extract_structure_signals(_soup("structure_semantic_full.html"), PAGE_URL)
    assert _statuses(payload)["structure_semantic_html"] == "good"


def test_build_structure_checks_divsoup_is_info_not_warning() -> None:
    payload = extract_structure_signals(_soup("structure_divsoup.html"), PAGE_URL)
    statuses = _statuses(payload)
    assert statuses["structure_semantic_html"] == "info"
    assert statuses["structure_internal_links"] == "info"
    assert statuses["citation_images_alt"] == "info"


def test_build_structure_checks_internal_link_rich_is_good() -> None:
    payload = extract_structure_signals(_soup("structure_internal_links_rich.html"), PAGE_URL)
    assert _statuses(payload)["structure_internal_links"] == "good"


def test_build_structure_checks_mixed_alt_below_threshold_is_info() -> None:
    payload = extract_structure_signals(_soup("structure_images_alt_mixed.html"), PAGE_URL)
    # 2/3 = ~66% < 90% threshold
    assert _statuses(payload)["citation_images_alt"] == "info"


@pytest.mark.parametrize(
    "myth_key",
    ["structure_semantic_html", "structure_internal_links", "citation_images_alt"],
)
def test_structure_myth_keys_never_warn(myth_key: str) -> None:
    payload = StructurePayload.empty()
    statuses = _statuses(payload)
    assert statuses[myth_key] not in {"warning", "critical"}


def test_structure_payload_roundtrips_through_dict() -> None:
    payload = StructurePayload(
        semantic_container_counts={"article": 1, "main": 1},
        internal_link_count=5,
        total_link_count=8,
        images_with_alt=4,
        images_total=4,
    )
    restored = StructurePayload.from_raw(payload.to_dict())
    assert restored == payload
