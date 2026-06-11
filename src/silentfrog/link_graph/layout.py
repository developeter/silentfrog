"""In-tree Fruchterman-Reingold force-directed layout (v2.0 V9).

No external graph dependency — ~80 LoC of the classic algorithm:
repulsion between every pair, attraction along edges, cooling per
iteration. Deterministic (seeded) so positions are stable across opens
and the unit test can assert convergence.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from .graph_model import LinkGraph

_AREA = 1.0
_ITERATIONS = 60
_SEED = 1234


def _initial_positions(urls: Sequence[str], rng: random.Random) -> dict[str, list[float]]:
    return {url: [rng.uniform(0, _AREA), rng.uniform(0, _AREA)] for url in urls}


def _repulse(positions: dict[str, list[float]], k: float, disp: dict[str, list[float]]) -> None:
    urls = list(positions)
    for i, a in enumerate(urls):
        for b in urls[i + 1 :]:
            dx = positions[a][0] - positions[b][0]
            dy = positions[a][1] - positions[b][1]
            dist = math.hypot(dx, dy) or 0.01
            force = (k * k) / dist
            ux, uy = dx / dist, dy / dist
            disp[a][0] += ux * force
            disp[a][1] += uy * force
            disp[b][0] -= ux * force
            disp[b][1] -= uy * force


def _attract(
    edges: Sequence[tuple[str, str]],
    positions: dict[str, list[float]],
    k: float,
    disp: dict[str, list[float]],
) -> None:
    for parent, child in edges:
        if parent not in positions or child not in positions:
            continue
        dx = positions[parent][0] - positions[child][0]
        dy = positions[parent][1] - positions[child][1]
        dist = math.hypot(dx, dy) or 0.01
        force = (dist * dist) / k
        ux, uy = dx / dist, dy / dist
        disp[parent][0] -= ux * force
        disp[parent][1] -= uy * force
        disp[child][0] += ux * force
        disp[child][1] += uy * force


def layout_positions(graph: LinkGraph, iterations: int = _ITERATIONS) -> dict[str, tuple[float, float]]:
    urls = [n.url for n in graph.nodes]
    if not urls:
        return {}
    rng = random.Random(_SEED)
    positions = _initial_positions(urls, rng)
    k = math.sqrt(_AREA / len(urls))
    temperature = _AREA / 10.0
    cooling = temperature / (iterations + 1)
    for _ in range(iterations):
        disp = {url: [0.0, 0.0] for url in urls}
        _repulse(positions, k, disp)
        _attract(graph.edges, positions, k, disp)
        for url in urls:
            dx, dy = disp[url]
            length = math.hypot(dx, dy) or 0.01
            positions[url][0] += (dx / length) * min(length, temperature)
            positions[url][1] += (dy / length) * min(length, temperature)
        temperature = max(0.0, temperature - cooling)
    return {url: (pos[0], pos[1]) for url, pos in positions.items()}


__all__ = ["layout_positions"]
