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
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="support",
            evidence="comparison asset region is too small",
        )
    result: list[ImageElement] = []
    for index, placement in enumerate(placements):
        row, column = divmod(index, columns)
        region_id = placement.region_id
        if region_id in {"left", "right"}:
            region_width = (context.width - gap) / 2
            region_x = SAFE_MARGIN_V4 if region_id == "left" else SAFE_MARGIN_V4 + region_width + gap
            column = 0
        else:
            region_width = width
            region_x = SAFE_MARGIN_V4
        result.append(
            context.image_element(
                placement.directive_id,
                x=region_x + column * (region_width + gap),
                y=start_y + row * (height + gap),
                width=region_width,
                height=height,
                region_id=region_id,
            )
        )
    return result


def solve_comparison_grid(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="heading",
            evidence="comparison grammar has no text placements",
        )
    asset_start = 1100.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    by_region: dict[str, list[str]] = {"heading": [], "left": [], "right": [], "support": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)
    elements: list[SceneElement] = []
    heading_refs = by_region.get("heading", [])
    gap = 32.0
    grid_top = 340.0
    rows = max(
        math.ceil(len(by_region.get("left", [])) / 1),
        math.ceil(len(by_region.get("right", [])) / 1),
        1,
    )
    grid_height = min(640.0, asset_start - grid_top - 24.0)
    row_height = max(88.0, (grid_height - gap * (rows - 1)) / rows)
    column_width = (context.width - gap) / 2
    support_top = 1020.0
    support_height = max(80.0, asset_start - support_top - 24.0)
    context.register_region_geometry(
        region_id="heading",
        role="primary",
        order=0,
        x=SAFE_MARGIN_V4,
        y=SAFE_MARGIN_V4,
        width=context.width,
        height=180.0,
    )
    context.register_region_geometry(
        region_id="left",
        role="comparison_primary",
        order=1,
        x=SAFE_MARGIN_V4,
        y=grid_top,
        width=column_width,
        height=row_height * rows + gap * (rows - 1),
    )
    context.register_region_geometry(
        region_id="right",
        role="comparison_secondary",
        order=2,
        x=SAFE_MARGIN_V4 + column_width + gap,
        y=grid_top,
        width=column_width,
        height=row_height * rows + gap * (rows - 1),
    )
    context.register_region_geometry(
        region_id="support",
        role="supporting",
        order=3,
        x=SAFE_MARGIN_V4,
        y=support_top,
        width=context.width,
        height=support_height,
    )
    if heading_refs:
        heading_slot = 180.0 / len(heading_refs)
        for index, ref in enumerate(heading_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=100.0 + index * heading_slot,
                    width=context.width,
                    height=heading_slot - 12.0 if len(heading_refs) > 1 else heading_slot,
                    region_id="heading",
                )
            )
    comparison_refs = by_region.get("left", []) + by_region.get("right", [])
    if comparison_refs:

        if row_height < 88:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="comparison",
                evidence="comparison rows cannot retain minimum readable density",
            )
        for index, ref in enumerate(by_region.get("left", [])):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=grid_top + index * (row_height + gap),
                    width=column_width,
                    height=row_height,
                    region_id="left",
                    align="left",
                )
            )
        for index, ref in enumerate(by_region.get("right", [])):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4 + column_width + gap,
                    y=grid_top + index * (row_height + gap),
                    width=column_width,
                    height=row_height,
                    region_id="right",
                    align="left",
                )
            )
    support_refs = by_region.get("support", [])
    if support_refs:
        slot = support_height / len(support_refs)
        if slot < 72.0:
            raise LayoutCompilationError(
                "INSUFFICIENT_WHITESPACE",
                page_id=context.page_id,
                region_id="support",
                evidence=f"support_slot={slot:.3f}; minimum=72.000",
            )
        for index, ref in enumerate(support_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=support_top + index * slot,
                    width=context.width,
                    height=slot - 12.0,
                    region_id="support",
                )
            )
    elements.extend(_assets(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    text_by_ref = {
        element.content_ref: element
        for element in elements
        if getattr(element, "kind", None) == "text"
    }
    ordered_text = [text_by_ref[item.fragment_ref] for item in placements]
    ordered_assets = [element for element in elements if getattr(element, "kind", None) == "image"]
    return tuple([*ordered_text, *ordered_assets])


__all__ = ["solve_comparison_grid"]
