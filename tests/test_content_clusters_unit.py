"""Unit tests for the v3 G5 content-cluster ("topic map") derivation.

The base dev install has no scikit-learn (it ships transitively behind
``silentfrog[embeddings]``), so the happy path and sampling tests are
skipped there and only exercised when the extra is installed. The unmeasured
paths (too few vectors, sklearn missing) run unconditionally — the "sklearn
missing" test IS the no-extra path this dev environment actually exercises.
"""

from __future__ import annotations

import pytest

from silentfrog.content_clusters import build_cluster_map

try:
    import sklearn  # noqa: F401

    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

_SKIP_REASON = "requires silentfrog[embeddings] (scikit-learn)"


def _grouped_items(n: int, dim: int = 8) -> list[tuple[str, str, list[float]]]:
    """n vectors in two obviously separated groups (even index near the
    origin, odd index far away in every dimension) so k-means/PCA have a
    clean signal to recover, deterministically."""
    items = []
    for i in range(n):
        base = 0.0 if i % 2 == 0 else 10.0
        vector = [base + i * 0.01] * dim
        items.append((f"https://e.com/{i}", f"Page {i}", vector))
    return items


def test_too_few_usable_vectors_is_unmeasured() -> None:
    items = [
        ("https://e.com/a", "A", ()),  # empty vector -> filtered out
        ("https://e.com/b", "B", [1.0, 2.0]),
        ("https://e.com/c", "C", [3.0, 4.0]),
    ]
    cluster_map = build_cluster_map(items)
    assert cluster_map.measured is False
    assert cluster_map.points == ()
    assert cluster_map.cluster_count == 0
    assert "at least 3" in cluster_map.reason


def test_unmeasured_with_install_hint_when_sklearn_missing() -> None:
    if _SKLEARN_AVAILABLE:
        pytest.skip("scikit-learn installed; the no-extra degrade path is not exercised")
    cluster_map = build_cluster_map(_grouped_items(10))
    assert cluster_map.measured is False
    assert "silentfrog[embeddings]" in cluster_map.reason


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason=_SKIP_REASON)
def test_happy_path_clusters_two_obvious_groups() -> None:
    items = _grouped_items(10)
    first = build_cluster_map(items)
    second = build_cluster_map(items)

    assert first.measured is True
    assert first.cluster_count >= 2
    assert len(first.points) == 10
    for point in first.points:
        assert point.x == point.x  # not NaN
        assert point.y == point.y
    assert first == second  # fixed random_state -> deterministic across calls


@pytest.mark.skipif(not _SKLEARN_AVAILABLE, reason=_SKIP_REASON)
def test_max_points_sampling_keeps_first_n_in_input_order() -> None:
    items = _grouped_items(20)
    cluster_map = build_cluster_map(items, max_points=5)

    assert cluster_map.sampled is True
    assert len(cluster_map.points) == 5
    assert [p.url for p in cluster_map.points] == [url for url, _, _ in items[:5]]
