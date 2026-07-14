from collections.abc import Mapping
from typing import Any


LEGACY_EDITORIAL_CHECKPOINT_KEY = "legacy_editorial_checkpoint"


def hydrate_legacy_content_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Hydrate content contracts read from pre-editorial checkpoints only."""

    hydrated = dict(raw)
    mode = hydrated.get("visual_mode")
    hydrated.setdefault("content_job", "save_and_check")
    hydrated.setdefault("primary_visual_family", "saveable_reference")
    hydrated.setdefault("primary_visual_subject", "checklist")
    hydrated.setdefault(
        "proof_mode",
        "comparison" if mode == "comparison_table" else "diagram",
    )
    hydrated.setdefault("recommended_frame_count", 6)
    return hydrated


def is_legacy_editorial_checkpoint(state: Mapping[str, Any]) -> bool:
    """Return whether state was explicitly hydrated from a pre-editorial run."""

    return state.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True


_LEGACY_CHECKPOINT_NODES = frozenset(
    {
        "carousel_qa",
        "text_card_renderer",
        "human_review",
        "final_policy_guard",
        "content_writer",
    }
)
_MODERN_STORYBOARD_FIELDS = frozenset(
    {"role", "layout", "content_blocks", "visual_slots"}
)


def _has_explicit_legacy_version(values: Mapping[str, Any]) -> bool:
    if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True:
        return True
    legacy_values = {0, 1, "0", "1", "v1", "legacy", "pre-editorial"}
    return any(
        values.get(key) in legacy_values
        for key in ("editorial_workflow_version", "editorial_schema_version")
    )


def _strict_legacy_storyboards(package: Mapping[str, Any]) -> bool:
    storyboards = package.get("storyboards")
    return (
        isinstance(storyboards, list)
        and bool(storyboards)
        and all(
            isinstance(frame, Mapping)
            and isinstance(frame.get("template"), str)
            and bool(frame.get("template"))
            and not _MODERN_STORYBOARD_FIELDS.intersection(frame)
            for frame in storyboards
        )
    )


def hydrate_legacy_editorial_state(
    values: Mapping[str, Any],
    *,
    checkpoint_nodes: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Hydrate only persisted pre-Task-8 states that reached assembly.

    Earlier checkpoints naturally enter the new graph before the editorial seam.
    Modern checkpoints already contain all three manifest slots and are returned
    untouched so their checkpointed successor resumes without re-running downloads.
    """

    package = values.get("publish_package")
    if not isinstance(package, Mapping):
        return {}
    manifest_slots = ("visual_plan", "asset_manifest", "render_manifest")
    modern_storyboard = any(
        isinstance(frame, Mapping)
        and bool(_MODERN_STORYBOARD_FIELDS.intersection(frame))
        for frame in list(package.get("storyboards") or [])
    )
    if modern_storyboard or all(name in values for name in manifest_slots):
        return (
            {LEGACY_EDITORIAL_CHECKPOINT_KEY: False}
            if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True
            else {}
        )
    explicit_legacy = _has_explicit_legacy_version(values)
    shape_and_node_legacy = (
        _strict_legacy_storyboards(package)
        and bool(_LEGACY_CHECKPOINT_NODES.intersection(checkpoint_nodes))
    )
    if not explicit_legacy and not shape_and_node_legacy:
        return {}

    hydrated_package = dict(package)
    raw_contract = hydrated_package.get("content_contract")
    if isinstance(raw_contract, Mapping):
        hydrated_package["content_contract"] = hydrate_legacy_content_contract(
            raw_contract
        )

    return {
        **{name: values.get(name) for name in manifest_slots},
        LEGACY_EDITORIAL_CHECKPOINT_KEY: True,
        "publish_package": hydrated_package,
    }
