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


def hydrate_legacy_editorial_state(values: Mapping[str, Any]) -> dict[str, Any]:
    """Hydrate only persisted pre-Task-8 states that reached assembly.

    Earlier checkpoints naturally enter the new graph before the editorial seam.
    Modern checkpoints already contain all three manifest slots and are returned
    untouched so their checkpointed successor resumes without re-running downloads.
    """

    package = values.get("publish_package")
    if not isinstance(package, Mapping):
        return {}
    manifest_slots = ("visual_plan", "asset_manifest", "render_manifest")
    if all(name in values for name in manifest_slots):
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
