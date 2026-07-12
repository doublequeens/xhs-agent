from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.domain import get_domain_profile
from src.rendering.text_cards import TextCardRenderError, output_paths, render_text_cards
from src.schemas.agent_state import AgentState
from src.schemas.text_card import TextCardPayload


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_ROOT = REPOSITORY_ROOT / "outputs" / "publish"


def _resolve_publish_package_profile(package: dict):
    domain = package.get("domain")
    profile_version = package.get("profile_version")
    if not domain or not profile_version:
        raise ValueError("publish_package requires valid domain and profile_version metadata")

    try:
        return get_domain_profile(domain, version=profile_version)
    except ValueError as exc:
        raise ValueError(
            f"publish_package requires valid domain and profile_version metadata: {exc}"
        ) from exc


def render_output_directory(package: dict) -> Path:
    """Create a profile-scoped local directory below the publish root."""
    profile = _resolve_publish_package_profile(package)
    domain = package["domain"]
    subdomain = package.get("subdomain") or profile.default_subdomain
    title = package.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError("publish_package requires a non-empty title for local rendering")

    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    root = PUBLISH_ROOT.resolve()
    output_dir = (root / f"{date_str}-{domain}-{subdomain}-{title}" / "images").resolve()
    if not output_dir.is_relative_to(root):
        raise ValueError("render output path must remain inside outputs/publish")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def text_card_renderer_node(state: AgentState) -> dict:
    package = state.get("publish_package")
    if not isinstance(package, dict):
        raise ValueError("text_card_renderer_node requires publish_package as a dict.")

    package = dict(package)
    payload = TextCardPayload.model_validate({"storyboards": package.get("storyboards")})
    output_dir = render_output_directory(package)
    try:
        paths = render_text_cards(payload, output_dir)
    except TextCardRenderError as exc:
        package["rendered_image_paths"] = []
        package["render_error"] = str(exc)
    else:
        package["rendered_image_paths"] = [str(path) for path in paths]
        package.pop("render_error", None)
    return {"publish_package": package, "current_node": "TEXT_CARD_RENDERER"}
