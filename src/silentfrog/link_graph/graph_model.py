"""Crawl-tree graph model (v2.0 V9).

Each edge is ``discovered_from -> url`` — the page that first linked to a
URL during the crawl. Nodes carry the GEO Score (for colour banding) and
inbound count (centrality proxy). Orphans are pages reached by the seed /
sitemap but never followed from an internal link. Sampled to the top-N
nodes by inbound centrality so a 1M-URL crawl never materialises a full
graph.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

_DEFAULT_MAX_NODES = 2000


@dataclass(frozen=True)
class GraphInput:
    url: str
    discovered_from: str = ""
    geo_score: int = 0


@dataclass(frozen=True)
class GraphNode:
    url: str
    score: int
    inbound: int


@dataclass(frozen=True)
class LinkGraph:
    nodes: tuple[GraphNode, ...] = field(default_factory=tuple)
    edges: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    orphans: tuple[str, ...] = field(default_factory=tuple)
    sampled: bool = False

    @property
    def node_count(self) -> int:
        return len(self.nodes)


def _inbound_counts(rows: Sequence[GraphInput]) -> Counter[str]:
    counts: Counter[str] = Counter()
    present = {r.url for r in rows}
    for row in rows:
        parent = row.discovered_from
        if parent and parent in present:
            counts[row.url] += 1
    return counts


def _orphans(rows: Sequence[GraphInput], inbound: Counter[str], root_url: str) -> list[str]:
    orphans: list[str] = []
    for row in rows:
        if row.url == root_url:
            continue
        if inbound.get(row.url, 0) == 0:
            orphans.append(row.url)
    return sorted(orphans)


def build_link_graph(
    rows: Sequence[GraphInput],
    root_url: str = "",
    max_nodes: int = _DEFAULT_MAX_NODES,
) -> LinkGraph:
    if not rows:
        return LinkGraph()
    inbound = _inbound_counts(rows)
    orphans = tuple(_orphans(rows, inbound, root_url))

    # Sample to the most-central nodes when the crawl is large.
    ranked = sorted(rows, key=lambda r: inbound.get(r.url, 0), reverse=True)
    sampled = len(ranked) > max_nodes
    kept = ranked[:max_nodes] if sampled else ranked
    kept_urls = {r.url for r in kept}

    nodes = tuple(GraphNode(url=r.url, score=r.geo_score, inbound=inbound.get(r.url, 0)) for r in kept)
    edges = tuple((r.discovered_from, r.url) for r in kept if r.discovered_from and r.discovered_from in kept_urls)
    return LinkGraph(nodes=nodes, edges=edges, orphans=orphans, sampled=sampled)


__all__ = ["GraphInput", "GraphNode", "LinkGraph", "build_link_graph"]
