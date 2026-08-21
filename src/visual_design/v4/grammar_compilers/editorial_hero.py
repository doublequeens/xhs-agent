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
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="support",
            evidence="asset support region is too small",
        )
    elements: list[ImageElement] = []
    for index, placement in enumerate(placements):
        row, column = divmod(index, columns)
        region_id = placement.region_id
        if region_id == "accent":
            region_x = SAFE_MARGIN_V4 + context.width - 240.0
            region_width = 240.0
        else:
            region_x = SAFE_MARGIN_V4
            region_width = context.width
        region_gap = 24.0
        region_columns = 1 if region_id == "accent" else columns
        region_width = (
            (region_width - region_gap * (region_columns - 1)) / region_columns
        )
        elements.append(
            context.image_element(
                placement.directive_id,
                x=region_x + column * (region_width + region_gap),
                y=start_y + row * (height + gap),
                width=region_width,
                height=height,
                region_id=region_id,
            )
        )
    return elements


def solve_editorial_hero(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="hero",
            evidence="hero grammar has no text placements",
        )
    asset_start = 1080.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    elements: list[SceneElement] = []
    by_region: dict[str, list[str]] = {"hero": [], "support": [], "accent": []}
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)
    hero_refs = by_region.get("hero", [])
    support_refs = by_region.get("support", [])
    accent_refs = by_region.get("accent", [])
    hero_height = 430.0 if support_refs or accent_refs else 520.0
    support_top = 600.0 if not hero_refs else 650.0
    support_top = max(support_top, float(SAFE_MARGIN_V4) + hero_height + 64.0 + 24.0)
    support_text_width = context.width - 264.0 if accent_refs else context.width
    support_region_width = context.width if context.program.asset_placements else support_text_width
    support_height = max(120.0, asset_start - support_top - 24.0)
    if context.program.asset_placements:
        # The support lane includes the deterministic image lane below the
        # text lane; it must contain the actual image box through the safe
        # bottom rather than ending before the image starts.
        support_height = max(support_height, float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4) - support_top)
    accent_top = support_top
    accent_height = max(120.0, min(180.0, (asset_start - accent_top - 24.0) / max(1, len(accent_refs))))
    context.register_region_geometry(
        region_id="hero",
        role="primary",
        order=0,
        x=SAFE_MARGIN_V4,
        y=SAFE_MARGIN_V4,
        width=context.width,
        height=hero_height + 64.0,
    )
    context.register_region_geometry(
        region_id="support",
        role="supporting",
        order=1,
        x=SAFE_MARGIN_V4,
        y=support_top,
        width=support_region_width,
        height=support_height,
    )
    context.register_region_geometry(
        region_id="accent",
        role="accent",
        order=2,
        x=SAFE_MARGIN_V4 + context.width - 240.0,
        y=accent_top,
        width=240.0,
        height=accent_height,
    )
    if hero_refs:
        slot = hero_height / len(hero_refs)
        if slot < 96:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="hero",
                evidence=f"hero_slot={slot:.3f}; minimum=96.000",
            )
        for index, ref in enumerate(hero_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4,
                    y=100.0 + index * slot,
                    width=context.width,
                    height=slot - 16.0 if len(hero_refs) > 1 else hero_height,
                    region_id="hero",
                    align="left",
                )
            )
    if support_refs:
        support_content_bottom = asset_start - 24.0 if context.program.asset_placements else float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
        support_content_height = support_content_bottom - support_top
        slot = support_content_height / len(support_refs)
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
                    width=support_text_width,
                    height=slot - 16.0,
                    region_id="support",
                )
            )
    if accent_refs:
        for index, ref in enumerate(accent_refs):
            elements.append(
                context.text_element(
                    ref,
                    x=SAFE_MARGIN_V4 + context.width - 240.0,
                    y=accent_top + index * accent_height,
                    width=240.0,
                    height=accent_height - 16.0,
                    region_id="accent",
                    align="center",
                )
            )
    elements.extend(_asset_boxes(context, asset_start + 24.0 if context.program.asset_placements else asset_start))
    text_by_ref = {
        element.content_ref: element
        for element in elements
        if getattr(element, "kind", None) == "text"
    }
    ordered_text = [text_by_ref[item.fragment_ref] for item in placements]
    ordered_assets = [element for element in elements if getattr(element, "kind", None) == "image"]
    return tuple([*ordered_text, *ordered_assets])


__all__ = ["solve_editorial_hero"]
