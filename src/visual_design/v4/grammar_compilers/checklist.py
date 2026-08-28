"""Family-neutral checklist geometry solver.

A heading, full-width checkbox rows in reading order, and a support lane.
Impossible content fails with DENSITY_EXCEEDED at the minimum font; no
truncation, no shrinking.
"""

from __future__ import annotations

import math

from src.schemas.scene_graph import IconElement, ImageElement, SceneElement
from src.visual_design.v4.compiler import (
    CANVAS_HEIGHT_V4,
    SAFE_MARGIN_V4,
    CompilerContextV4,
    LayoutCompilationError,
)


def _support_assets(context: CompilerContextV4, start_y: float) -> list[ImageElement]:
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
            evidence="checklist support asset region is too small",
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


def solve_checklist(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="items",
            evidence="checklist grammar has no text placements",
        )
    by_region: dict[str, list[str]] = {"heading": [], "items": [], "support": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)

    heading_refs = by_region.get("heading", [])
    heading_top = float(SAFE_MARGIN_V4)
    heading_height = max(120.0, min(160.0 * max(1, len(heading_refs)), 200.0))

    support_refs = by_region.get("support", [])
    asset_start = 1110.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    support_height = max(120.0, 92.0 * len(support_refs))
    support_top = content_bottom - support_height

    items = by_region.get("items", [])
    items_top = heading_top + heading_height + 40.0
    items_bottom = support_top - 32.0 if support_refs else content_bottom
    items_height = items_bottom - items_top
    elements: list[SceneElement] = []
    if items:
        row_gap = 20.0
        row_height = (items_height - row_gap * (len(items) - 1)) / len(items)
        # Sparse pages (one short item) must not stretch a single row across
        # the whole region: cap each row so whitespace floors stay reachable.
        row_height = min(row_height, 240.0)
        items_height = row_height * len(items) + row_gap * (len(items) - 1)
        if row_height < 92.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="items",
                evidence=f"checklist_row={row_height:.3f}; minimum=92.000",
            )
        for index, ref in enumerate(items):
            y = items_top + index * (row_height + row_gap)
            icon_id = context._next_id("check", ref)
            icon_box = context._safe_box(
                x=SAFE_MARGIN_V4,
                y=y + 12.0,
                width=44.0,
                height=44.0,
                element_id=icon_id,
                region_id="items",
                ref=ref,
            )
            icon = IconElement(
                element_id=icon_id,
                layer=12,
                box=icon_box,
                icon="check",
                color=context.palette_primary,
            )
            context.icon_by_fragment_ref[ref] = icon
            elements.append(icon)
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4 + 68.0,
                    y=y,
                    width=context.width - 68.0,
                    height=row_height - 16.0,
                    region_id="items",
                )
            )
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
    for index, ref in enumerate(support_refs):
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=support_top + index * 80.0,
                width=context.width,
                height=76.0,
                region_id="support",
            )
        )

    context.register_region_geometry(
        region_id="heading", role="primary", order=0,
        x=SAFE_MARGIN_V4, y=heading_top, width=context.width, height=heading_height,
    )
    context.register_region_geometry(
        region_id="items", role="checklist_rows", order=1,
        x=SAFE_MARGIN_V4, y=items_top, width=context.width,
        height=max(120.0, items_height),
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
    ordered: list[SceneElement] = []
    for placement in placements:
        if placement.region_id == "items":
            ordered.append(context.icon_by_fragment_ref[placement.fragment_ref])
        ordered.append(by_ref[placement.fragment_ref])
    ordered.extend(
        element for element in elements if getattr(element, "kind", None) == "image"
    )
    return tuple(ordered)


__all__ = ["solve_checklist"]
