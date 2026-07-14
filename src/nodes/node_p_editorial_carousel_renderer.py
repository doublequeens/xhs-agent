from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.editorial_carousel.publish_profile import resolve_publish_package_profile
from src.rendering.editorial import render_carousel
from src.schemas import AgentState, AssetManifest, CarouselPayload, VisualPlan


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_ROOT = REPOSITORY_ROOT / "outputs" / "publish"


def render_output_directory(package: dict) -> Path:
    """Create a profile-scoped directory below the modern publish root."""

    profile = resolve_publish_package_profile(package)
    domain = package["domain"]
    subdomain = package.get("subdomain") or profile.default_subdomain
    title = package.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError(
            "publish_package requires a non-empty title for local rendering"
        )
    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    root = PUBLISH_ROOT.resolve()
    output_dir = (
        root / f"{date_str}-{domain}-{subdomain}-{title}" / "images"
    ).resolve()
    if not output_dir.is_relative_to(root):
        raise ValueError("render output path must remain inside outputs/publish")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def editorial_carousel_renderer_node(state: AgentState) -> dict:
    """Validate graph state and delegate one render to the deep renderer."""

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
