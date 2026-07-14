import pytest

from src.editorial_carousel.publish_profile import resolve_publish_package_profile


def test_resolve_publish_package_profile_is_the_shared_modern_boundary():
    profile = resolve_publish_package_profile(
        {"domain": "wellness", "profile_version": "wellness-v1"}
    )

    assert profile.domain == "wellness"
    assert profile.version == "wellness-v1"


@pytest.mark.parametrize(
    "package",
    [
        {},
        {"domain": "wellness"},
        {"domain": "wellness", "profile_version": "wellness-v999"},
        {"domain": "unknown-domain", "profile_version": "wellness-v1"},
    ],
)
def test_resolve_publish_package_profile_rejects_missing_or_invalid_metadata(package):
    with pytest.raises(ValueError, match="valid domain and profile_version"):
        resolve_publish_package_profile(package)


def test_renderer_and_export_entry_points_enforce_shared_profile_errors():
    """Both the render and export entry points delegate to the shared boundary."""

    from langgraph.types import StateSnapshot

    from main import export_publish_package
    from src.nodes.node_p_editorial_carousel_renderer import (
        render_output_directory,
    )

    bad_package = {"domain": "wellness"}  # missing profile_version

    with pytest.raises(ValueError, match="valid domain and profile_version"):
        render_output_directory(bad_package)

    completed_state = StateSnapshot(
        values={"publish_package": bad_package},
        next=(),
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=(),
        interrupts=(),
    )
    with pytest.raises(ValueError, match="valid domain and profile_version"):
        export_publish_package(completed_state)
