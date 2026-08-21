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
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="support",
            evidence="step support asset region is too small",
        )
    result: list[ImageElement] = []
    for index, placement in enumerate(placements):
        row, column = divmod(index, columns)
        region_id = placement.region_id
        if region_id == "sequence":
            region_x = SAFE_MARGIN_V4 + 76.0
            region_width = context.width - 76.0
            column = 0
        else:
            region_x = SAFE_MARGIN_V4
            region_width = width
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


def solve_step_flow(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="sequence",
            evidence="step grammar has no text placements",
        )
    asset_start = 1110.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    by_region: dict[str, list[str]] = {"heading": [], "sequence": [], "support": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)
    elements: list[SceneElement] = []
    heading_refs = by_region.get("heading", [])
    heading_top = float(SAFE_MARGIN_V4)
    heading_height = max(120.0, min(180.0 * max(1, len(heading_refs)), 220.0))
    for index, ref in enumerate(heading_refs):
        heading_slot = heading_height / len(heading_refs)
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=heading_top + index * heading_slot,
                width=context.width,
                height=heading_slot - 12.0 if len(heading_refs) > 1 else heading_height,
                region_id="heading",
            )
        )
    steps = by_region.get("sequence", [])
    support_refs = by_region.get("support", [])
    content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    support_height = max(120.0, 132.0 * len(support_refs)) if support_refs else 120.0
    support_top = content_bottom - support_height if support_refs else content_bottom - 120.0
    if context.program.asset_placements:
        support_height = max(
            support_height,
            float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4) - support_top,
        )
    sequence_top = heading_top + heading_height + 44.0
    sequence_bottom = support_top - 32.0 if support_refs else content_bottom
    sequence_height = sequence_bottom - sequence_top
    if steps:
        slot = (sequence_height - 24.0 * (len(steps) - 1)) / len(steps)
        if slot < 96:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="sequence",
                evidence=f"sequence_slot={slot:.3f}; minimum=96.000",
            )
        for index, ref in enumerate(steps):
            y = sequence_top + index * (slot + 24.0)
            text_height = min(slot - 32.0, 360.0)
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
            icon = IconElement(
                element_id=icon_id,
                layer=12,
                box=icon_box,
                icon="dot",
                color=context.palette_primary,
            )
            context.icon_by_fragment_ref[ref] = icon
            elements.append(icon)
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4 + 76.0,
                    y=y,
                    width=context.width - 76.0,
                    height=text_height,
                    region_id="sequence",
                )
            )
    if support_refs:
        support_content_height = content_bottom - support_top
        support_slot = (support_content_height - 24.0 * (len(support_refs) - 1)) / len(support_refs)
        if support_slot < 72.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="support",
                evidence=f"support_slot={support_slot:.3f}; minimum=72.000",
            )
        for index, ref in enumerate(support_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=support_top + index * (support_slot + 24.0),
                    width=context.width,
                    height=support_slot,
                    region_id="support",
                )
            )
    context.register_region_geometry(
        region_id="heading",
        role="primary",
        order=0,
        x=SAFE_MARGIN_V4,
        y=heading_top,
        width=context.width,
        height=heading_height,
    )
    context.register_region_geometry(
        region_id="sequence",
        role="ordered_steps",
        order=1,
        x=SAFE_MARGIN_V4,
        y=sequence_top,
        width=context.width,
        height=max(120.0, sequence_height),
    )
    context.register_region_geometry(
        region_id="support",
        role="supporting",
        order=2,
        x=SAFE_MARGIN_V4,
        y=support_top,
        width=context.width,
        height=support_height,
    )
    elements.extend(_assets(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    by_ref = {
        element.content_ref: element
        for element in elements
        if getattr(element, "kind", None) == "text"
    }
    ordered: list[SceneElement] = []
    for placement in placements:
        if placement.region_id == "sequence":
            ordered.append(context.icon_by_fragment_ref[placement.fragment_ref])
            ordered.append(by_ref[placement.fragment_ref])
        else:
            ordered.append(by_ref[placement.fragment_ref])
    ordered.extend(element for element in elements if getattr(element, "kind", None) == "image")
    return tuple(ordered)


__all__ = ["solve_step_flow"]
