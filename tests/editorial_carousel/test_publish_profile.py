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


def test_export_entry_point_enforces_shared_profile_errors():
    """The publish export entry point delegates to the shared profile boundary."""

    from langgraph.types import StateSnapshot

    from main import export_publish_package

    bad_package = {"domain": "wellness"}  # missing profile_version

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
