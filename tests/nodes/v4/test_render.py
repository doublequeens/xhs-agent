"""Task 13 RED/GREEN tests for the v4 render node."""

from __future__ import annotations

from src.nodes.v4.render import render_node, v4_render_node


def test_v4_render_node_public_names_are_available():
    assert callable(render_node)
    assert v4_render_node is render_node
