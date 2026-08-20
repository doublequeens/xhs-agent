"""Family-neutral ordered step-flow geometry solver."""

from __future__ import annotations

import math

from src.schemas.scene_graph import IconElement, ImageElement, SceneElement
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
            evidence="step support asset region is too small",
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


def solve_step_flow(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    refs = tuple(item.fragment_ref for item in context.program.fragment_placements)
    if not refs:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="sequence",
            evidence="step grammar has no text placements",
        )
    asset_start = 1110.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    elements: list[SceneElement] = [
        context.text_element(
            refs[0],
            x=SAFE_MARGIN_V4,
            y=100.0,
            width=context.width,
            height=170.0,
            region_id="heading",
        )
    ]
    steps = refs[1:]
    if steps:
        flow_top = 330.0
        flow_height = asset_start - flow_top - 24.0
        slot = flow_height / len(steps)
        if slot < 96:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="sequence",
                evidence="ordered steps cannot retain minimum readable density",
            )
        for index, ref in enumerate(steps):
            y = flow_top + index * slot
            icon_id = context._next_id("step", ref)
            icon_box = context._safe_box(
                x=SAFE_MARGIN_V4,
                y=y + 12.0,
                width=44.0,
                height=44.0,
                element_id=icon_id,
                region_id="sequence",
                ref=ref,
            )
            elements.append(
                IconElement(
                    element_id=icon_id,
                    layer=12,
                    box=icon_box,
                    icon="dot",
                    color=context.palette_primary,
                )
            )
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4 + 76.0,
                    y=y,
                    width=context.width - 76.0,
                    height=slot - 16.0,
                    region_id="sequence",
                )
            )
    elements.extend(_assets(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    return tuple(elements)


__all__ = ["solve_step_flow"]
