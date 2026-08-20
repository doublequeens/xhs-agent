"""Family-neutral comparison-grid geometry solver."""

from __future__ import annotations

import math

from src.schemas.scene_graph import ImageElement, SceneElement
from src.visual_design.v4.compiler import (
    CANVAS_HEIGHT_V4,
    SAFE_MARGIN_V4,
    CompilerContextV4,
    LayoutCompilationError,
)


def _assets(context: CompilerContextV4, start_y: float) -> list[ImageElement]:
    placements = context.program.asset_placements
    if not placements:
        return []
    columns = min(2, len(placements))
    rows = math.ceil(len(placements) / columns)
    gap = 24.0
    width = (context.width - gap * (columns - 1)) / columns
    available = float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4) - start_y
    height = (available - gap * (rows - 1)) / rows
    if height < 120:
        raise LayoutCompilationError(
            "ASSET_ASPECT_MISMATCH",
            page_id=context.page_id,
            region_id="support",
            evidence="comparison asset region is too small",
        )
    result: list[ImageElement] = []
    for index, placement in enumerate(placements):
        row, column = divmod(index, columns)
        result.append(
            context.image_element(
                placement.directive_id,
                x=SAFE_MARGIN_V4 + column * (width + gap),
                y=start_y + row * (height + gap),
                width=width,
                height=height,
                region_id="support",
            )
        )
    return result


def solve_comparison_grid(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    refs = tuple(item.fragment_ref for item in context.program.fragment_placements)
    if not refs:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="heading",
            evidence="comparison grammar has no text placements",
        )
    asset_start = 1100.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    elements: list[SceneElement] = [
        context.text_element(
            refs[0],
            x=SAFE_MARGIN_V4,
            y=100.0,
            width=context.width,
            height=180.0,
            region_id="heading",
        )
    ]
    comparison_refs = refs[1:]
    if comparison_refs:
        rows = math.ceil(len(comparison_refs) / 2)
        gap = 32.0
        grid_top = 340.0
        grid_height = asset_start - grid_top - 24.0
        row_height = (grid_height - gap * (rows - 1)) / rows
        if row_height < 88:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="comparison",
                evidence="comparison rows cannot retain minimum readable density",
            )
        column_width = (context.width - gap) / 2
        for index, ref in enumerate(comparison_refs):
            row, column = divmod(index, 2)
            if index == len(comparison_refs) - 1 and len(comparison_refs) % 2:
                x, width = SAFE_MARGIN_V4, context.width
            else:
                x, width = SAFE_MARGIN_V4 + column * (column_width + gap), column_width
            elements.append(
                context.text_element(
                    ref,
                    x=x,
                    y=grid_top + row * (row_height + gap),
                    width=width,
                    height=row_height,
                    region_id="comparison",
                    align="left",
                )
            )
    elements.extend(_assets(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    return tuple(elements)


__all__ = ["solve_comparison_grid"]
