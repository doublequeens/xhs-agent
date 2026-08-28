"""Family-neutral summary-closing geometry solver.

A tall closing headline, stacked takeaway rows, and a narrow closing-note
lane on the lower right.  Impossible content fails with DENSITY_EXCEEDED at
the minimum font; copy is never truncated.
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
            region_id="note",
            evidence="closing note asset region is too small",
        )
    return [
        context.image_element(
            placement.directive_id,
            x=SAFE_MARGIN_V4 + column * (width + gap),
            y=start_y + row * (height + gap),
            width=width,
            height=height,
            region_id="note",
        )
        for index, placement in enumerate(placements)
        for row, column in (divmod(index, columns),)
    ]


def solve_summary_closing(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="headline",
            evidence="closing grammar has no text placements",
        )
    by_region: dict[str, list[str]] = {"headline": [], "takeaways": [], "note": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)

    headline_refs = by_region.get("headline", [])
    takeaways = by_region.get("takeaways", [])
    note_refs = by_region.get("note", [])

    headline_top = float(SAFE_MARGIN_V4)
    headline_height = min(400.0 if takeaways else 520.0, 160.0 * max(1, len(headline_refs)))
    headline_height = max(160.0, headline_height)
    note_width = 280.0 if note_refs else 0.0
    asset_start = 1090.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    note_height = max(120.0, min(200.0, 92.0 * len(note_refs)))
    note_top = content_bottom - note_height

    takeaways_top = headline_top + headline_height + 48.0
    takeaways_bottom = note_top - 32.0 if note_refs else content_bottom
    takeaways_height = takeaways_bottom - takeaways_top
    if takeaways:
        row_gap = 24.0
        row_height = (takeaways_height - row_gap * (len(takeaways) - 1)) / len(takeaways)
        row_height = min(row_height, 220.0)
        takeaways_height = row_height * len(takeaways) + row_gap * (len(takeaways) - 1)
        if row_height < 96.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="takeaways",
                evidence=f"takeaway_row={row_height:.3f}; minimum=96.000",
            )

    elements: list[SceneElement] = []
    if headline_refs:
        slot = headline_height / len(headline_refs)
        if slot < 160.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="headline",
                evidence=f"headline_slot={slot:.3f}; minimum=160.000",
            )
        for index, ref in enumerate(headline_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=headline_top + index * slot,
                    width=context.width,
                    height=slot - 20.0 if len(headline_refs) > 1 else headline_height,
                    region_id="headline",
                )
            )
    for index, ref in enumerate(takeaways):
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=takeaways_top + index * (row_height + 24.0),
                width=context.width - note_width,
                height=row_height - 16.0,
                region_id="takeaways",
            )
        )
    for index, ref in enumerate(note_refs):
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4 + (context.width - note_width) + 24.0,
                y=note_top + index * 92.0,
                width=note_width - 24.0,
                height=92.0,
                region_id="note",
                align="center",
            )
        )

    context.register_region_geometry(
        region_id="headline", role="primary", order=0,
        x=SAFE_MARGIN_V4, y=headline_top, width=context.width, height=headline_height,
    )
    context.register_region_geometry(
        region_id="takeaways", role="key_points", order=1,
        x=SAFE_MARGIN_V4, y=takeaways_top, width=context.width - note_width,
        height=max(120.0, takeaways_height),
    )
    context.register_region_geometry(
        region_id="note", role="closing_note", order=2,
        x=SAFE_MARGIN_V4 + (context.width - note_width) if note_refs else SAFE_MARGIN_V4,
        y=note_top,
        width=note_width if note_refs else context.width,
        height=max(120.0, note_height),
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


__all__ = ["solve_summary_closing"]
