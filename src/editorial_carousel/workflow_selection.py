"""Select an immutable workflow identity before loading its checkpoint."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.run_registry import (
    AgentRun,
    RunMode,
    RunRegistryError,
    WORKFLOW_VERSIONS,
    RUN_MODES,
    RunRegistry,
    WorkflowVersion,
)


@dataclass(frozen=True)
class WorkflowContext:
    """The version and execution mode selected for one run."""

    workflow_version: WorkflowVersion
    run_mode: RunMode


GraphFactory = Callable[[], object]
GraphFactories = Mapping[WorkflowVersion, GraphFactory]


def _validate_requested_identity(
    requested_version: WorkflowVersion | None,
    run_mode: RunMode | None,
) -> None:
    if requested_version is not None and requested_version not in WORKFLOW_VERSIONS:
        raise RunRegistryError(f"invalid workflow version: {requested_version!r}")
    if run_mode is not None and run_mode not in RUN_MODES:
        raise RunRegistryError(f"invalid run mode: {run_mode!r}")


def select_workflow_context(
    registry: RunRegistry,
    thread_id: str,
    requested_version: WorkflowVersion | None = None,
    run_mode: RunMode | None = None,
) -> WorkflowContext:
    """Resolve workflow identity without creating or changing a registry row.

    Existing registry metadata is authoritative. Explicit API identity is useful
    for callers creating a new run, but it cannot switch an existing thread to a
    different graph or mode.
    """

    _validate_requested_identity(requested_version, run_mode)
    existing = registry.get_by_thread_id(thread_id)
    if existing is None:
        return WorkflowContext(
            workflow_version=requested_version or "llm_scene_v3",
            run_mode=run_mode or "production",
        )

    if requested_version is not None and requested_version != existing.workflow_version:
        raise RunRegistryError(
            "workflow_version mismatch for existing thread: "
            f"requested {requested_version!r}, persisted {existing.workflow_version!r}"
        )
    if run_mode is not None and run_mode != existing.run_mode:
        raise RunRegistryError(
            "run_mode mismatch for existing thread: "
            f"requested {run_mode!r}, persisted {existing.run_mode!r}"
        )
    return WorkflowContext(existing.workflow_version, existing.run_mode)


def build_graph_for_context(
    context: WorkflowContext,
    *,
    v3_factory: GraphFactory,
    v4_factory: GraphFactory,
) -> object:
    """Build exactly one graph for a previously selected context."""

    if context.workflow_version == "llm_scene_v3":
        return v3_factory()
    if context.workflow_version == "llm_scene_v4":
        return v4_factory()
    raise RunRegistryError(f"unsupported workflow version: {context.workflow_version!r}")


def build_graph_for_run(run: AgentRun, factories: GraphFactories) -> object:
    """Build the graph selected by one immutable registry row."""

    context = WorkflowContext(run.workflow_version, run.run_mode)
    return build_graph_for_context(
        context,
        v3_factory=factories["llm_scene_v3"],
        v4_factory=factories["llm_scene_v4"],
    )
