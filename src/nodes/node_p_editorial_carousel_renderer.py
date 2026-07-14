from __future__ import annotations

from src.editorial_carousel.legacy import is_legacy_editorial_checkpoint
from src.nodes.node_p_text_card_renderer import (
    render_output_directory,
    text_card_renderer_node,
)
from src.rendering.editorial import render_carousel
from src.schemas import AgentState, AssetManifest, CarouselPayload, VisualPlan


def editorial_carousel_renderer_node(state: AgentState) -> dict:
    """Validate graph state and delegate one render to the deep renderer."""

    if is_legacy_editorial_checkpoint(state) and state.get("visual_plan") is None:
        result = text_card_renderer_node(state)
        return {**result, "current_node": "EDITORIAL_CAROUSEL_RENDERER"}

    package = state.get("publish_package")
    if not isinstance(package, dict):
        raise ValueError(
            "editorial_carousel_renderer_node requires publish_package as a dict."
        )
    plan = VisualPlan.model_validate(state.get("visual_plan"))
    storyboard = CarouselPayload.model_validate(
        {"storyboards": package.get("storyboards")}
    )
    assets = AssetManifest.model_validate(state.get("asset_manifest"))
    output_dir = render_output_directory(package)
    manifest = render_carousel(plan, storyboard, assets, output_dir)

    updated_package = dict(package)
    updated_package["rendered_image_paths"] = [
        page.path for page in manifest.pages
    ]
    updated_package.pop("render_error", None)
    return {
        "publish_package": updated_package,
        "render_manifest": manifest,
        "current_node": "EDITORIAL_CAROUSEL_RENDERER",
    }
