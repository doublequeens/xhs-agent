from collections.abc import Mapping
from typing import Any


LEGACY_EDITORIAL_CHECKPOINT_KEY = "legacy_editorial_checkpoint"
EDITORIAL_WORKFLOW_VERSION_KEY = "editorial_workflow_version"
LEGACY_EDITORIAL_V1 = "legacy_v1"
MODERN_EDITORIAL_V2 = "modern_v2"


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

    return (
        state.get(EDITORIAL_WORKFLOW_VERSION_KEY) == LEGACY_EDITORIAL_V1
        or state.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True
    )


def modern_editorial_transition_updates() -> dict[str, Any]:
    """Return the typed transition that retires all legacy-only routing."""

    return {
        EDITORIAL_WORKFLOW_VERSION_KEY: MODERN_EDITORIAL_V2,
        LEGACY_EDITORIAL_CHECKPOINT_KEY: False,
        "asset_manifest": None,
        "render_manifest": None,
        "carousel_qa_result": None,
        "render_qa_result": None,
    }


def route_after_storyboard_generation(state: Mapping[str, Any]) -> str:
    if is_legacy_editorial_checkpoint(state) and state.get("visual_plan") is None:
        return "carousel_qa"
    return "asset_resolver"


_LEGACY_CHECKPOINT_NODES = frozenset(
    {
        "carousel_qa",
        "storyboard_generator",
        "text_card_renderer",
        "render_qa",
        "human_review",
        "final_policy_guard",
        "content_writer",
    }
)
LEGACY_RESUME_PREDECESSOR_BY_SUCCESSOR = {
    "storyboard_generator": "visual_strategy_planner",
    "carousel_qa": "asset_resolver",
    "render_qa": "text_card_renderer",
    "human_review": "render_qa",
    "final_policy_guard": "human_review",
    "content_writer": "final_policy_guard",
}
_MODERN_STORYBOARD_FIELDS = frozenset(
    {"role", "layout", "content_blocks", "visual_slots"}
)


def _has_explicit_legacy_version(values: Mapping[str, Any]) -> bool:
    if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True:
        return True
    legacy_values = {
        0,
        1,
        "0",
        "1",
        "v1",
        "legacy",
        "pre-editorial",
        LEGACY_EDITORIAL_V1,
    }
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
            {
                LEGACY_EDITORIAL_CHECKPOINT_KEY: False,
                EDITORIAL_WORKFLOW_VERSION_KEY: MODERN_EDITORIAL_V2,
            }
            if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is True
            or values.get(EDITORIAL_WORKFLOW_VERSION_KEY) == LEGACY_EDITORIAL_V1
            else {}
        )
    explicit_legacy = _has_explicit_legacy_version(values)
    shape_and_node_legacy = (
        _strict_legacy_storyboards(package)
        and bool(_LEGACY_CHECKPOINT_NODES.intersection(checkpoint_nodes))
    )
    raw_contract = package.get("content_contract")
    old_contract_before_storyboard = (
        "storyboard_generator" in checkpoint_nodes
        and isinstance(raw_contract, Mapping)
        and "visual_mode" in raw_contract
        and not {
            "content_job",
            "primary_visual_family",
            "primary_visual_subject",
            "proof_mode",
            "recommended_frame_count",
        }.intersection(raw_contract)
    )
    if not explicit_legacy and not shape_and_node_legacy and not old_contract_before_storyboard:
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
        EDITORIAL_WORKFLOW_VERSION_KEY: LEGACY_EDITORIAL_V1,
        "publish_package": hydrated_package,
    }
