"""Family-neutral image-annotation geometry solver.

A heading, a paired feature/callout band (feature lane left with the page's
approved assets, numbered callout rows right — both regions share one y and
height so the pairing invariant holds), and a support lane.  Without assets
the feature lane keeps its geometry; impossible content fails with
DENSITY_EXCEEDED at the minimum font.
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

_FEATURE_WIDTH = 560.0
_LANE_GAP = 32.0


def _feature_images(
    context: CompilerContextV4, top: float, height: float
) -> list[ImageElement]:
    elements: list[ImageElement] = []
    placements = context.program.asset_placements
    if not placements:
        return elements
    gap = 20.0
    rows = math.ceil(len(placements) / 1)
    # Keep the image ink below the regional density ceiling: the box fills
    # at most ~78% of the feature lane's height.
    box_height = min((height - gap * (rows - 1)) / rows, height * 0.78)
    if box_height < 160.0 or _FEATURE_WIDTH < 160.0:
        raise LayoutCompilationError(
            "DENSITY_EXCEEDED",
            page_id=context.page_id,
            region_id="feature",
            evidence="annotation feature image lane is too small",
        )
    for index, placement in enumerate(placements):
        elements.append(
            context.image_element(
                placement.directive_id,
                x=SAFE_MARGIN_V4,
                y=top + index * (box_height + gap),
                width=_FEATURE_WIDTH,
                height=box_height,
                region_id="feature",
            )
        )
    return elements


_CAPTION_HEIGHT = 88.0


def solve_image_annotation(context: CompilerContextV4) -> tuple[SceneElement, ...]:
    placements = tuple(sorted(context.program.fragment_placements, key=lambda item: item.order))
    if not placements:
        raise LayoutCompilationError(
            "CONTENT_OVERFLOW",
            page_id=context.page_id,
            region_id="callouts",
            evidence="annotation grammar has no text placements",
        )
    by_region: dict[str, list[str]] = {
        "heading": [], "feature": [], "callouts": [], "support": [],
    }
    for placement in placements:
        by_region.setdefault(placement.region_id, []).append(placement.fragment_ref)

    heading_refs = by_region.get("heading", [])
    heading_top = float(SAFE_MARGIN_V4)
    heading_height = max(120.0, min(160.0 * max(1, len(heading_refs)), 200.0))

    support_refs = by_region.get("support", [])
    content_bottom = float(CANVAS_HEIGHT_V4 - SAFE_MARGIN_V4)
    support_height = max(120.0, 92.0 * len(support_refs)) if support_refs else 120.0
    support_top = content_bottom - support_height

    callouts = by_region.get("callouts", [])
    feature_refs = by_region.get("feature", [])
    band_top = heading_top + heading_height + 36.0
    band_bottom = support_top - 32.0
    band_height = max(120.0, band_bottom - band_top)
    # Dense lanes fill the whole page; cap the band so the whitespace floor
    # stays reachable on sparse annotation pages.
    band_height = min(band_height, 640.0)
    band_bottom = band_top + band_height
    callout_width = context.width - _FEATURE_WIDTH - _LANE_GAP

    if callouts:
        row_gap = 18.0
        row_height = (band_height - row_gap * (len(callouts) - 1)) / len(callouts)
        # Cap only the inked text box, not the shared band height: the
        # paired feature lane keeps its geometry for assets and captions.
        text_row_height = min(row_height, 200.0)
        if row_height < 88.0:
            raise LayoutCompilationError(
                "DENSITY_EXCEEDED",
                page_id=context.page_id,
                region_id="callouts",
                evidence=f"callout_row={row_height:.3f}; minimum=88.000",
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
    for index, ref in enumerate(feature_refs):
        slot = band_height / max(1, len(feature_refs))
        # When assets share the feature lane, feature text becomes a caption
        # band pinned to the lane's bottom so text and images never overlap.
        caption_top = band_top + band_height - _CAPTION_HEIGHT if context.program.asset_placements else band_top
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=caption_top + index * (_CAPTION_HEIGHT / max(1, len(feature_refs))),
                width=_FEATURE_WIDTH,
                height=_CAPTION_HEIGHT / max(1, len(feature_refs)) - 12.0,
                region_id="feature",
                align="center",
            )
        )
    row_height = (band_height - 18.0 * (len(callouts) - 1)) / len(callouts) if callouts else band_height
    text_row_height = min(row_height, 200.0) if callouts else band_height
    for index, ref in enumerate(callouts):
        y = band_top + index * (row_height + 18.0)
        icon_id = context._next_id("callout", ref)
        icon_box = context._safe_box(
            x=SAFE_MARGIN_V4 + _FEATURE_WIDTH + _LANE_GAP,
            y=y + 8.0,
            width=36.0,
            height=36.0,
            element_id=icon_id,
            region_id="callouts",
            ref=ref,
        )
        icon = IconElement(
            element_id=icon_id,
            layer=12,
            box=icon_box,
            icon="arrow",
            color=context.palette_primary,
        )
        context.icon_by_fragment_ref[ref] = icon
        elements.append(icon)
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4 + _FEATURE_WIDTH + _LANE_GAP + 48.0,
                y=y,
                width=callout_width - 48.0,
                height=text_row_height - 14.0,
                region_id="callouts",
            )
        )
    for index, ref in enumerate(support_refs):
        elements.append(
            context.text_element(
                ref,
                x=SAFE_MARGIN_V4,
                y=support_top + index * 92.0,
                width=context.width,
                height=92.0,
                region_id="support",
            )
        )

    context.register_region_geometry(
        region_id="heading", role="primary", order=0,
        x=SAFE_MARGIN_V4, y=heading_top, width=context.width, height=heading_height,
    )
    context.register_region_geometry(
        region_id="feature", role="supporting", order=1,
        x=SAFE_MARGIN_V4, y=band_top, width=_FEATURE_WIDTH, height=band_height,
    )
    context.register_region_geometry(
        region_id="callouts", role="annotations", order=2,
        x=SAFE_MARGIN_V4 + _FEATURE_WIDTH + _LANE_GAP, y=band_top,
        width=callout_width, height=band_height,
    )
    context.register_region_geometry(
        region_id="support", role="footnote", order=3,
        x=SAFE_MARGIN_V4, y=support_top, width=context.width,
        height=max(120.0, support_height),
    )
    elements.extend(
        _feature_images(
            context,
            band_top,
            band_height - (_CAPTION_HEIGHT + 16.0 if feature_refs else 0.0),
        )
    )
    by_ref = {
        element.content_ref: element
        for element in elements
        if getattr(element, "kind", None) == "text"
    }
    ordered: list[SceneElement] = []
    for placement in placements:
        if placement.region_id == "callouts":
            ordered.append(context.icon_by_fragment_ref[placement.fragment_ref])
        ordered.append(by_ref[placement.fragment_ref])
    ordered.extend(
        element for element in elements if getattr(element, "kind", None) == "image"
    )
    return tuple(ordered)


__all__ = ["solve_image_annotation"]
