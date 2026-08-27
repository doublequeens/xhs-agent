"""The isolated ``llm_scene_v4`` LangGraph workflow.

Content production is shared verbatim with the frozen v3 graph through
``graph_common``; the visual chain is v4-only:

    assembler -> content_atomizer -> content_lock_builder
      -> semantic_modeling --Q0--> visual_authoring --Q1--> asset_resolver
      -> composition_planning -> layout_compiler -> design_plan_qa --Q2-->
      generic_scene_renderer -> render_qa --Q3--> visual_critic --Q4-->
      review_workspace_builder -> human_review --verified decision-->
      final_policy_guard --run mode--> content_writer | shadow_artifact_writer

Typed revision routing (Task 14) owns every repair re-entry: hard-QA and
aesthetic failures route to ``revision``, which derives the target layer and
re-enters the producing node.  The third occurrence of one fingerprint raises
``VisualExecutionInterrupted`` (candidate exhaustion) — budgets are durable in
checkpointed state and are never reset on resume for v4.

Node functions are resolved through package attributes at build time so
integration tests may monkeypatch any node before ``create_graph_v4``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, StateGraph

from src.editorial_carousel.graph_common import add_content_chain
from src.graph import DEFAULT_CHECKPOINT_PATH, _create_checkpointer
from src.schemas.v4.agent_state import AgentStateV4
from src.schemas.v4.revision import VisualExecutionInterrupted

import src.nodes as nodes
from src.nodes.v4 import assets as v4assets
from src.nodes.v4 import authoring as v4authoring
from src.nodes.v4 import composition as v4composition
from src.nodes.v4 import content as v4content
from src.nodes.v4 import critic as v4critic
from src.nodes.v4 import design_qa as v4design_qa
from src.nodes.v4 import final_guard as v4final_guard
from src.nodes.v4 import human_review as v4human_review
from src.nodes.v4 import layout as v4layout
from src.nodes.v4 import render as v4render
from src.nodes.v4 import revision as v4revision
from src.nodes.v4 import shadow_writer as v4shadow_writer
from src.nodes.v4 import semantic as v4semantic
from src.nodes.v4 import shadow_writer as v4shadow

_V4_GATEWAY: Any = None


def _get_v4_gateway() -> Any:
    """Build the process-wide v4 gateway lazily (first visual node only)."""

    global _V4_GATEWAY
    if _V4_GATEWAY is None:
        from src.visual_ai.factory import get_v4_gateway

        _V4_GATEWAY = get_v4_gateway()
    return _V4_GATEWAY


def _gateway_node(node_fn):
    """Bind a visual node to the lazy default v4 gateway factory."""

    def wrapped(state):
        return node_fn(state, gateway=_get_v4_gateway())

    wrapped.__name__ = getattr(node_fn, "__name__", "v4_gateway_node")
    return wrapped


def _review_workspace_builder_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build the Task 16A review workspace at the review boundary.

    LangGraph persists every channel value through its msgpack serializer,
    which rebuilds pydantic contracts with ``model_construct`` (validators
    skipped, nested models left as raw dicts).  The review boundary requires
    exact, fully validated contracts, so every source contract is first
    revalidated through the same canonical-JSON seam the 16B checkpoint
    loader uses, the canonical instances are written back to state, and only
    then is the workspace built and its external reference persisted —
    before the Human Review interrupt, so interrupt state, checkpoint and
    the local review CLI all agree on the authorization material.
    """

    from src.review.v4_checkpoint import (
        _CONTRACT_CHANNELS,
        _channel,
        _rehydrate_paths,
        _rehydrate_previous_workspace,
        _revalidated,
    )
    from src.review.v4_workspace import (
        ReviewWorkspaceInputsV4,
        build_review_workspace,
    )

    fields: dict[str, Any] = {
        "artifact_paths": _rehydrate_paths(
            _channel(state, "artifact_paths", "asset_transaction_paths")
        )
    }
    patch: dict[str, Any] = {}
    for name, aliases, contract_type, required in _CONTRACT_CHANNELS:
        raw = _channel(state, *aliases)
        if raw is None:
            if required:
                raise ValueError(
                    f"v4 review workspace builder lacks the {aliases[0]} contract"
                )
            fields[name] = None
            continue
        fields[name] = _revalidated(raw, contract_type, aliases[0])
        patch[aliases[0]] = fields[name]
    previous = _channel(
        state, "previous_review_workspace_v4", "previous_review_workspace"
    )
    fields["previous_review_workspace"] = (
        None if previous is None else _rehydrate_previous_workspace(previous)
    )
    patch["artifact_paths"] = fields["artifact_paths"]
    inputs = ReviewWorkspaceInputsV4(**fields)
    workspace = build_review_workspace(inputs)
    patch.update(
        {
            "review_workspace": workspace,
            "review_workspace_v4": workspace,
            "review_workspace_reference": workspace.reference,
            "review_workspace_reference_v4": workspace.reference,
            "current_node": "V4_REVIEW_WORKSPACE_BUILDER",
        }
    )
    return patch


def route_after_asset_resolver_v4(state: Mapping[str, Any]) -> str:
    route = state.get("asset_resolver_route") if isinstance(state, Mapping) else None
    if route not in {"composition_planning", "visual_authoring"}:
        raise ValueError("v4 asset resolver route is missing or invalid")
    return route


def route_after_design_qa_v4(state: Mapping[str, Any]) -> str:
    route = state.get("route") if isinstance(state, Mapping) else None
    if route == "render":
        return "generic_scene_renderer"
    if route == "design_reviser":
        return "revision"
    raise ValueError("v4 design QA route is missing or invalid")


_REVISION_REENTRY = {
    "semantic_reviser": "semantic_modeling",
    "authoring_reviser": "visual_authoring",
    "asset_resolver": "asset_resolver",
    "composition_reviser": "composition_planning",
    "layout_reviser": "layout_compiler",
    "render": "generic_scene_renderer",
    "visual_critic": "visual_critic",
}


def route_after_revision_v4(state: Mapping[str, Any]) -> str:
    route = state.get("revision_route") if isinstance(state, Mapping) else None
    if route not in _REVISION_REENTRY:
        raise ValueError("v4 revision route is missing or invalid")
    return route


def route_after_final_guard_v4(state: Mapping[str, Any]) -> str:
    run_mode = state.get("run_mode") if isinstance(state, Mapping) else None
    if run_mode == "shadow":
        return "shadow_artifact_writer"
    if run_mode == "production":
        return "content_writer"
    raise ValueError("v4 final guard route requires an exact run mode")


def create_graph_v4(checkpointer=None, checkpoint_path=DEFAULT_CHECKPOINT_PATH):
    """Build the ``llm_scene_v4`` workflow with v4-only visual routing."""

    builder = StateGraph(AgentStateV4)
    # Shared content chain (domain routing through assembler), identical to v3.
    add_content_chain(builder)

    # --- v4 visual production nodes ---
    builder.add_node("content_atomizer", v4content.content_atomizer_node)
    builder.add_node("content_lock_builder", v4content.content_lock_builder_node)
    builder.add_node(
        "semantic_modeling",
        _gateway_node(v4semantic.semantic_modeling_node),
    )
    builder.add_node(
        "visual_authoring",
        _gateway_node(v4authoring.visual_authoring_node),
    )
    builder.add_node("asset_resolver", v4assets.asset_resolver_node)
    builder.add_node(
        "composition_planning", v4composition.composition_planning_node
    )
    builder.add_node("layout_compiler", v4layout.layout_node)
    builder.add_node("design_plan_qa", v4design_qa.design_qa_node)
    builder.add_node("generic_scene_renderer", v4render.render_node)
    builder.add_node("render_qa", v4render.render_qa_node)
    builder.add_node(
        "visual_critic", _gateway_node(v4critic.aesthetic_critic_node)
    )
    builder.add_node("review_workspace_builder", _review_workspace_builder_node)
    builder.add_node("human_review", v4human_review.human_review_node)
    builder.add_node("final_policy_guard", v4final_guard.final_policy_guard_v4_node)
    builder.add_node("revision", v4revision.revision_node)
    # Terminal writers: production reuses the v3 memory writer; shadow writes
    # an isolated evaluation bundle and never reaches content_writer.
    builder.add_node("content_writer", nodes.content_writer_node)
    builder.add_node("shadow_artifact_writer", v4shadow_writer.shadow_writer_node)

    # --- v4 visual production chain ---
    builder.add_edge("assembler", "content_atomizer")
    builder.add_edge("content_atomizer", "content_lock_builder")
    builder.add_edge("content_lock_builder", "semantic_modeling")
    builder.add_conditional_edges(
        "semantic_modeling",
        v4semantic.route_after_semantic_qa,
        {"visual_authoring": "visual_authoring", "semantic_modeling": "revision"},
    )
    builder.add_conditional_edges(
        "visual_authoring",
        v4authoring.route_after_authoring_qa,
        {"asset_resolver": "asset_resolver", "visual_authoring": "revision"},
    )
    builder.add_conditional_edges(
        "asset_resolver",
        route_after_asset_resolver_v4,
        {
            "composition_planning": "composition_planning",
            "visual_authoring": "visual_authoring",
        },
    )
    builder.add_edge("composition_planning", "layout_compiler")
    builder.add_edge("layout_compiler", "design_plan_qa")
    builder.add_conditional_edges(
        "design_plan_qa",
        route_after_design_qa_v4,
        {
            "generic_scene_renderer": "generic_scene_renderer",
            "revision": "revision",
        },
    )
    builder.add_edge("generic_scene_renderer", "render_qa")
    builder.add_conditional_edges(
        "render_qa",
        v4render.route_after_render_qa,
        {"visual_critic": "visual_critic", "design_reviser": "revision"},
    )
    builder.add_conditional_edges(
        "visual_critic",
        v4critic.route_after_aesthetic_critic,
        {"human_review": "review_workspace_builder", "revision": "revision"},
    )
    builder.add_edge("review_workspace_builder", "human_review")
    builder.add_conditional_edges(
        "human_review",
        v4human_review.route_after_human_review_v4,
        {
            "final_policy_guard": "final_policy_guard",
            "revision": "revision",
            "asset_resolver": "asset_resolver",
            "r2_compliance": "r2_compliance",
        },
    )
    builder.add_conditional_edges(
        "revision",
        route_after_revision_v4,
        {route: node for route, node in _REVISION_REENTRY.items()},
    )
    builder.add_conditional_edges(
        "final_policy_guard",
        route_after_final_guard_v4,
        {
            "content_writer": "content_writer",
            "shadow_artifact_writer": "shadow_artifact_writer",
        },
    )
    builder.add_edge("content_writer", END)
    builder.add_edge("shadow_artifact_writer", END)

    if checkpointer is None:
        checkpointer = _create_checkpointer(checkpoint_path)
    return builder.compile(checkpointer=checkpointer)


__all__ = [
    "VisualExecutionInterrupted",
    "create_graph_v4",
    "route_after_asset_resolver_v4",
    "route_after_design_qa_v4",
    "route_after_final_guard_v4",
    "route_after_revision_v4",
]
