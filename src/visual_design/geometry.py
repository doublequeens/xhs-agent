"""Shared box geometry for the design-plan and render QA gates."""

from __future__ import annotations

from src.schemas.scene_graph import Box

_EPS = 1e-9


def box_right(box: Box) -> float:
    return box.x + box.width


def box_bottom(box: Box) -> float:
    return box.y + box.height


def boxes_intersect(a: Box, b: Box) -> bool:
    # Touching edges (<=) do not count as an overlap.
    return not (
        box_right(a) <= b.x + _EPS
        or box_right(b) <= a.x + _EPS
        or box_bottom(a) <= b.y + _EPS
        or box_bottom(b) <= a.y + _EPS
    )
