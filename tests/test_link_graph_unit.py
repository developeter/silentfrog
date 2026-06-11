"""Unit tests for the v2.0 V9 link graph (model + layout + view)."""

from __future__ import annotations

from silentfrog.link_graph import GraphInput, build_link_graph, layout_positions
from silentfrog.link_graph.graph_view import _band_color


def _inputs() -> list[GraphInput]:
    # homepage -> /a, /b ; /a -> /c ; /orphan reached only via sitemap (no parent).
    return [
        GraphInput("https://e.com/", "", 90),
        GraphInput("https://e.com/a", "https://e.com/", 80),
        GraphInput("https://e.com/b", "https://e.com/", 70),
        GraphInput("https://e.com/c", "https://e.com/a", 50),
        GraphInput("https://e.com/orphan", "", 40),
    ]


def test_build_graph_nodes_and_edges() -> None:
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    assert graph.node_count == 5
    assert ("https://e.com/", "https://e.com/a") in graph.edges
    assert ("https://e.com/a", "https://e.com/c") in graph.edges


def test_orphans_are_pages_with_no_internal_inbound() -> None:
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    # /orphan has discovered_from="" and is not the root -> orphan.
    # The root itself is excluded.
    assert "https://e.com/orphan" in graph.orphans
    assert "https://e.com/" not in graph.orphans
    assert "https://e.com/a" not in graph.orphans  # has an inbound edge


def test_inbound_count_is_centrality_proxy() -> None:
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    by_url = {n.url: n for n in graph.nodes}
    assert by_url["https://e.com/a"].inbound == 1
    assert by_url["https://e.com/orphan"].inbound == 0


def test_sampling_caps_nodes_by_centrality() -> None:
    rows = [GraphInput("https://e.com/", "", 90)]
    # 10 children of the homepage; cap at 5 -> sampled.
    rows += [GraphInput(f"https://e.com/{i}", "https://e.com/", 50) for i in range(10)]
    graph = build_link_graph(rows, root_url="https://e.com/", max_nodes=5)
    assert graph.sampled is True
    assert graph.node_count == 5


def test_empty_graph() -> None:
    graph = build_link_graph([], root_url="")
    assert graph.node_count == 0
    assert graph.orphans == ()


def test_layout_positions_cover_all_nodes_and_are_finite() -> None:
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    positions = layout_positions(graph, iterations=20)
    assert set(positions) == {n.url for n in graph.nodes}
    for x, y in positions.values():
        assert isinstance(x, float) and isinstance(y, float)
        assert x == x and y == y  # not NaN


def test_layout_is_deterministic() -> None:
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    a = layout_positions(graph, iterations=20)
    b = layout_positions(graph, iterations=20)
    assert a == b  # seeded RNG → stable across opens


def test_band_color_thresholds() -> None:
    assert _band_color(90).name() == "#2ecc71"  # good
    assert _band_color(70).name() == "#f1c40f"  # warn
    assert _band_color(40).name() == "#e74c3c"  # bad
    assert _band_color(0).name() == "#9aa0a6"  # unknown/grey


def test_graph_view_renders_without_crash(qtbot) -> None:
    from silentfrog.link_graph.graph_view import LinkGraphView

    view = LinkGraphView()
    qtbot.addWidget(view)
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    view.set_graph(graph)
    view.show()
    # Scene has node + edge items.
    assert len(view.scene().items()) >= graph.node_count


def test_graph_view_node_click_emits_url(qtbot) -> None:
    from silentfrog.link_graph.graph_view import LinkGraphView

    view = LinkGraphView()
    qtbot.addWidget(view)
    graph = build_link_graph(_inputs(), root_url="https://e.com/")
    view.set_graph(graph)
    captured: list[str] = []
    view.node_clicked.connect(captured.append)
    # Find a node item and trigger its click callback directly.
    from silentfrog.link_graph.graph_view import _NodeItem

    node_items = [i for i in view.scene().items() if isinstance(i, _NodeItem)]
    assert node_items
    node_items[0]._on_click(node_items[0]._url)
    assert captured and captured[0].startswith("https://e.com/")
