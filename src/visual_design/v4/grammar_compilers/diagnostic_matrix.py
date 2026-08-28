"""Family-neutral diagnostic-matrix geometry solver.

A heading plus a two-column matrix of diagnosis cells and a support lane.
Impossible content (text that cannot fit at the minimum font) fails with
DENSITY_EXCEEDED; copy is never truncated or shrunk.
"""

from __future__ import annotations

import math

from src.schemas.scene_graph import SceneElement
from src.visual_design.v4.compiler import (
    CANVAS_HEIGHT_V4,
    SAFE_MARGIN_V4,
    CompilerContextV4,
    LayoutCompilationError,
)


def _support_assets(context: CompilerContextV4, start_y: float) -> list[SceneElement]:
    placements = context.program.asset_placements
    if not placements:
        return []
    gap = 24.0
    columns = min(3, len(placements))
    rows = math.ceil(len(placements) / columns)
    width = (context.width - gap * (columns - 1)) / columns
    height = ((float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4) - start_y) - gap * (rows - 1)) / rows
    if height < 120:
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="support",
            evidence="matrix support asset region is too small",
        )
    return [
        context.image_element(
            placement.directive_id,
            x=SAFE_MARGIN_V4 + column * (width + gap),
            y=start_y + row * (height + gap),
            width=width,
            height=height,
            region_id="support",
        )
        for index, placement in enumerate(placements)
        for row, column in (divmod(index, columns),)
    ]


def solve_diagnostic_matrix(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="matrix",
            evidence="matrix grammar has no text placements",
        )
    by_region: dict[str, list[str]] = {"heading": [], "matrix": [], "support": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)

    heading_refs = by_region.get("heading", [])
    heading_top = float(SAFE_MARGIN_V4)
    heading_height = max(120.0, min(170.0 * max(1, len(heading_refs)), 220.0))

    support_refs = by_region.get("support", [])
    asset_start = 1080.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    support_height = max(120.0, 96.0 * len(support_refs))
    support_top = content_bottom - support_height

    matrix_top = heading_top + heading_height + 44.0
    matrix_bottom = support_top - 32.0 if support_refs else content_bottom
    matrix_height = matrix_bottom - matrix_top
    cells = by_region.get("matrix", [])
    columns = 2
    rows = max(1, math.ceil(len(cells) / columns))
    gap = 24.0
    cell_width = (context.width - gap) / columns
    cell_height = (matrix_height - gap * (rows - 1)) / rows
    if cells and cell_height < 140.0:
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="matrix",
            evidence=f"matrix_cell={cell_height:.3f}; minimum=140.000",
        )

    elements: list[SceneElement] = []
    for index, ref in enumerate(heading_refs):
        slot = heading_height / len(heading_refs)
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=heading_top + index * slot,
                width=context.width,
                height=slot - 12.0 if len(heading_refs) > 1 else heading_height,
                region_id="heading",
            )
        )
    for index, ref in enumerate(cells):
        row, column = divmod(index, columns)
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4 + column * (cell_width + gap),
                y=matrix_top + row * (cell_height + gap),
                width=cell_width - 32.0,
                height=cell_height - 28.0,
                region_id="matrix",
            )
        )
    for index, ref in enumerate(support_refs):
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=support_top + index * 96.0,
                width=context.width,
                height=96.0,
                region_id="support",
            )
        )

    context.register_region_geometry(
        region_id="heading", role="primary", order=0,
        x=SAFE_MARGIN_V4, y=heading_top, width=context.width, height=heading_height,
    )
    context.register_region_geometry(
        region_id="matrix", role="ordered_grid", order=1,
        x=SAFE_MARGIN_V4, y=matrix_top, width=context.width,
        height=max(120.0, matrix_height),
    )
    context.register_region_geometry(
        region_id="support", role="supporting", order=2,
        x=SAFE_MARGIN_V4, y=support_top, width=context.width,
        height=max(120.0, support_height),
    )
    elements.extend(
        _support_assets(
            context, asset_start + 24.0 if context.program.asset_placements else asset_start
        )
    )
    by_ref = {
        element.content_ref: element
        for element in elements
        if getattr(element, "kind", None) == "text"
    }
    ordered = [by_ref[item.fragment_ref] for item in placements]
    ordered.extend(
        element for element in elements if getattr(element, "kind", None) == "image"
    )
    return tuple(ordered)


__all__ = ["solve_diagnostic_matrix"]
