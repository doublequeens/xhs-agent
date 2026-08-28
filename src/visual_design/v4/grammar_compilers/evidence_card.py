"""Family-neutral evidence-card geometry solver.

A heading, a two-column grid of evidence cards (each card carries one
statement with generous interior padding), and a support lane.  Impossible
content fails with DENSITY_EXCEEDED at the minimum font.
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
            evidence="card support asset region is too small",
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


def solve_evidence_card(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="cards",
            evidence="evidence grammar has no text placements",
        )
    by_region: dict[str, list[str]] = {"heading": [], "cards": [], "support": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)

    heading_refs = by_region.get("heading", [])
    heading_top = float(SAFE_MARGIN_V4)
    heading_height = max(120.0, min(160.0 * max(1, len(heading_refs)), 200.0))

    support_refs = by_region.get("support", [])
    asset_start = 1080.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    support_height = max(120.0, 96.0 * len(support_refs))
    support_top = content_bottom - support_height

    cards = by_region.get("cards", [])
    cards_top = heading_top + heading_height + 44.0
    cards_bottom = support_top - 32.0 if support_refs else content_bottom
    cards_height = cards_bottom - cards_top
    columns = 2
    rows = max(1, math.ceil(len(cards) / columns))
    gap = 28.0
    card_width = (context.width - gap) / columns
    card_height = (cards_height - gap * (rows - 1)) / rows
    if cards and card_height < 160.0:
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="cards",
            evidence=f"card_box={card_height:.3f}; minimum=160.000",
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
    for index, ref in enumerate(cards):
        row, column = divmod(index, columns)
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4 + column * (card_width + gap) + 28.0,
                y=cards_top + row * (card_height + gap) + 24.0,
                width=card_width - 56.0,
                height=card_height - 48.0,
                region_id="cards",
                align="center",
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
        region_id="cards", role="data_cards", order=1,
        x=SAFE_MARGIN_V4, y=cards_top, width=context.width,
        height=max(120.0, cards_height),
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


__all__ = ["solve_evidence_card"]
