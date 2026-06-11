"""Internal link graph + sitemap visualisation (v2.0 V9).

Builds the crawl tree (parent = the page that first linked to each URL,
from the store's ``discovered_from`` column, which survives the V3.2
payload stripping), runs an in-tree force-directed layout (no external
graph dependency), and renders it in a QGraphicsView. Sampled to the
top-N nodes by inbound centrality at scale.
"""

from __future__ import annotations

from .graph_model import GraphInput, GraphNode, LinkGraph, build_link_graph
from .layout import layout_positions

__all__ = [
    "GraphInput",
    "GraphNode",
    "LinkGraph",
    "build_link_graph",
    "layout_positions",
]
