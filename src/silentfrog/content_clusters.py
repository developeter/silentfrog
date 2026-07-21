"""Content-cluster ("topic map") derivation (v3 G5).

Projects each page's stored topic-embedding vector (``embeddings/topic.py``)
onto 2D via PCA and groups pages into k-means clusters, so pages that drift
onto the same theme show up together on a scatter plot — a local stand-in
for the paid tools' "content cluster" report. Pure derivation, no Qt; the
GUI (``site_crawl_gui.py`` + ``link_graph/cluster_view.py``) renders the
result, cloning the force-directed link graph's (V9) dialog shape.

scikit-learn ships transitively behind ``silentfrog[embeddings]``
(sentence-transformers pulls it in via scipy), so this needs no new
dependency — but the base dev install lacks it, so a missing import must
degrade to ``measured=False`` exactly like the embedder itself degrades
(never raise into the GUI thread).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_MAX_CLUSTERS = 8
_MIN_CLUSTERS = 2
_MIN_USABLE_VECTORS = 3
_RANDOM_STATE = 1234


@dataclass(frozen=True, slots=True)
class ClusterPoint:
    url: str
    title: str
    x: float
    y: float
    cluster: int


@dataclass(frozen=True, slots=True)
class ClusterMap:
    points: tuple[ClusterPoint, ...]
    cluster_count: int
    sampled: bool
    measured: bool
    reason: str = ""


def _unmeasured(reason: str, sampled: bool = False) -> ClusterMap:
    return ClusterMap(points=(), cluster_count=0, sampled=sampled, measured=False, reason=reason)


def _usable_items(
    items: Sequence[tuple[str, str, Sequence[float]]],
) -> list[tuple[str, str, tuple[float, ...]]]:
    return [(url, title, tuple(vector)) for url, title, vector in items if vector]


def _cluster_count(n_points: int) -> int:
    return min(_MAX_CLUSTERS, max(_MIN_CLUSTERS, int(math.sqrt(n_points))))


def build_cluster_map(
    items: Sequence[tuple[str, str, Sequence[float]]],
    *,
    max_points: int = 2000,
) -> ClusterMap:
    """2D topic-cluster projection of every page that has a stored vector.

    ``items`` are ``(url, title, vector)``; entries with an empty vector are
    dropped first. Never raises: too few usable vectors, or a missing
    scikit-learn, degrade to an unmeasured map with a human-readable reason.
    """
    usable = _usable_items(items)
    if len(usable) < _MIN_USABLE_VECTORS:
        return _unmeasured("Not enough pages with a topic-embedding vector to cluster (need at least 3)")
    sampled = len(usable) > max_points
    kept = usable[:max_points] if sampled else usable
    return _fit_cluster_map(kept, sampled)


def _fit_cluster_map(kept: Sequence[tuple[str, str, tuple[float, ...]]], sampled: bool) -> ClusterMap:
    try:
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA
    except ImportError:
        return _unmeasured("Topic map requires silentfrog[embeddings] (scikit-learn)", sampled)
    vectors = [vector for _, _, vector in kept]
    k = _cluster_count(len(vectors))
    try:
        labels = KMeans(n_clusters=k, random_state=_RANDOM_STATE, n_init=10).fit_predict(vectors)
        coords = PCA(n_components=2, random_state=_RANDOM_STATE).fit_transform(vectors)
    except Exception as exc:  # sklearn raises assorted types on odd input; degrade, never crash the GUI
        return _unmeasured(f"Clustering failed: {type(exc).__name__}: {exc}", sampled)
    points = tuple(
        ClusterPoint(url=url, title=title, x=float(coords[i][0]), y=float(coords[i][1]), cluster=int(labels[i]))
        for i, (url, title, _) in enumerate(kept)
    )
    return ClusterMap(points=points, cluster_count=len(set(labels.tolist())), sampled=sampled, measured=True)


__all__ = ["ClusterMap", "ClusterPoint", "build_cluster_map"]
