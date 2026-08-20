"""Family-neutral editorial-hero geometry solver."""

from __future__ import annotations

import math

from src.schemas.scene_graph import ImageElement, SceneElement
from src.visual_design.v4.compiler import (
    CANVAS_HEIGHT_V4,
    SAFE_MARGIN_V4,
    CompilerContextV4,
    LayoutCompilationError,
)


def _asset_boxes(context: CompilerContextV4, start_y: float) -> list[ImageElement]:
    placements = context.program.asset_placements
    if not placements:
        return []
    columns = min(2, len(placements))
    rows = math.ceil(len(placements) / columns)
    gap = 24.0
    width = (context.width - gap * (columns - 1)) / columns
    available_height = float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4) - start_y
    height = (available_height - gap * (rows - 1)) / rows
    if height < 120 or width < 120:
        raise LayoutCompilationError(
            "ASSET_ASPECT_MISMATCH",
            page_id=context.page_id,
            region_id="support",
            evidence="asset support region is too small",
        )
    elements: list[ImageElement] = []
    for index, placement in enumerate(placements):
        row, column = divmod(index, columns)
        elements.append(
            context.image_element(
                placement.directive_id,
                x=SAFE_MARGIN_V4 + column * (width + gap),
                y=start_y + row * (height + gap),
                width=width,
                height=height,
                region_id="support",
            )
        )
    return elements


def solve_editorial_hero(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    refs = tuple(item.fragment_ref for item in context.program.fragment_placements)
    if not refs:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="hero",
            evidence="hero grammar has no text placements",
        )
    asset_start = 1080.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    elements: list[SceneElement] = []
    hero_height = 430.0 if len(refs) > 1 else 520.0
    elements.append(
        context.text_element(
            refs[0],
            x=SAFE_MARGIN_V4,
            y=100.0,
            width=context.width,
            height=hero_height,
            region_id="hero",
            align="left",
        )
    )
    support_refs = refs[1:]
    if support_refs:
        support_top = 600.0
        support_height = asset_start - support_top - 24.0
        slot = support_height / len(support_refs)
        if slot < 72.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="support",
                evidence="support region cannot retain minimum readable density",
            )
        for index, ref in enumerate(support_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=support_top + index * slot,
                    width=context.width,
                    height=slot - 16.0,
                    region_id="support",
                )
            )
    elements.extend(_asset_boxes(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    return tuple(elements)


__all__ = ["solve_editorial_hero"]
