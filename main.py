import argparse
import sys
import json
import stat
import warnings
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args
from uuid import uuid4

from langgraph.types import Command, StateSnapshot
from memory.memory_manager import XHSMemoryManager
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.domain import DomainContext, DomainName, build_content_policy, get_domain_profile
from src.editorial_carousel.legacy import (
    hydrate_legacy_editorial_state,
    migration_reentry_predecessor,
    persisted_checkpoint_nodes,
)
from src.editorial_carousel.publish_profile import resolve_publish_package_profile
from src.editorial_carousel.workflow_selection import (
    build_graph_for_context,
    build_graph_for_run,
    select_workflow_context,
)
from src.graph import (
    DEFAULT_CHECKPOINT_PATH,
    create_graph,
    delete_all_checkpoints,
    delete_checkpoint_thread,
)
from src.models import set_default_provider
from src.publishing.artifacts import (
    PublishArtifacts,
    _export_verified_state_snapshot,
)
from src.run_registry import (
    AgentRun,
    EXECUTION_TO_LEGACY_STATUS,
    LEGACY_STATUS_TO_EXECUTION,
    RunRegistry,
    RunRegistryError,
    V4_RESUMABLE_EXECUTION_STATES,
    WorkflowVersion,
    exception_summary,
    format_run,
)

SUPPORTED_DOMAINS = get_args(DomainName)
RUN_REGISTRY_PATH = Path("data/agent_runs.sqlite")
PUBLISH_EXPORT_RETRYABLE_ERROR = (
    "Publish package export failed validation; inspect the checkpoint and retry."
)
_LEGACY_DOMAIN_HYDRATION_WARNED = False


def _create_v3_graph():
    """Build the existing production graph without changing its public symbol."""

    return create_graph()


def _create_v4_graph():
    """Import the v4 graph only after a v4 run has been selected."""

    from src.graph_v4 import create_graph_v4

    return create_graph_v4()


def _graph_factories():
    return {
        "llm_scene_v3": _create_v3_graph,
        "llm_scene_v4": _create_v4_graph,
    }


def build_thread_id(explicit_id: str | None, now: datetime | None = None) -> str:
    if explicit_id is not None:
        return explicit_id
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"xhs_conversation_{timestamp}_{uuid4().hex}"


def build_run_config(thread_id: str | None) -> dict:
    return {"configurable": {"thread_id": build_thread_id(thread_id)}}


def hydrate_legacy_domain_state(values: dict) -> dict:
    global _LEGACY_DOMAIN_HYDRATION_WARNED

    domain_context = values.get("domain_context")
    if domain_context is not None:
        return {}

    profile = get_domain_profile("beauty", version="beauty-v1")
    updates = {
        "domain_context": DomainContext(
            domain="beauty",
            subdomain="skincare",
            classification_source="default",
            classification_confidence=1,
            profile_version=profile.version,
            risk_level="low",
        ),
        "content_policy": build_content_policy(profile, risk_level="low"),
    }

    if not _LEGACY_DOMAIN_HYDRATION_WARNED:
        warnings.warn(
            "Hydrating legacy domain checkpoint without domain_context using beauty/skincare defaults.",
            UserWarning,
            stacklevel=2,
        )
        _LEGACY_DOMAIN_HYDRATION_WARNED = True

    return updates


def load_run_state(graph, config: dict, initial_state: dict):
    current_state = graph.get_state(config)
    if current_state.values:
        checkpoint_nodes = persisted_checkpoint_nodes(
            graph,
            config,
            tuple(current_state.next),
        )
        editorial_updates = (
            hydrate_legacy_editorial_state(
                current_state.values,
                checkpoint_nodes=checkpoint_nodes,
            )
            if checkpoint_nodes
            else {}
        )
        hydration_updates = {
            **hydrate_legacy_domain_state(current_state.values),
            **editorial_updates,
        }
        # The generic scene renderer writes carousel PNGs into run_output_dir.
        # Fresh v3 runs carry it from initial_state; migrated checkpoints that
        # predate the slot get it backfilled alongside the editorial hydration
        # so rendering always has a concrete, per-run directory. Clean v3
        # checkpoints are left untouched.
        if hydration_updates and not current_state.values.get("run_output_dir"):
            thread_id = config.get("configurable", {}).get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                hydration_updates.setdefault(
                    "run_output_dir", _resolve_run_output_dir(thread_id)
                )
        if hydration_updates:
            predecessor = migration_reentry_predecessor(
                editorial_updates,
                checkpoint_nodes,
            )
            if predecessor is None:
                graph.update_state(config, hydration_updates)
            else:
                graph.update_state(
                    config,
                    hydration_updates,
                    as_node=predecessor,
                )
            current_state = graph.get_state(config)
    run_input = None if current_state.values else initial_state
    return current_state, run_input


def load_versioned_run(
    graph,
    config: dict | None = None,
    initial_state: dict | None = None,
    *,
    workflow_version: WorkflowVersion = "llm_scene_v3",
):
    """Load a checkpoint using the selected workflow's recovery contract.

    v3 keeps the historical domain/editorial hydration path intact. A v4
    checkpoint is authoritative graph state and is therefore read directly,
    without any v3 migration or state injection.
    """

    effective_config = {} if config is None else config
    effective_initial_state = {} if initial_state is None else initial_state
    if workflow_version == "llm_scene_v3":
        return load_run_state(graph, effective_config, effective_initial_state)
    if workflow_version == "llm_scene_v4":
        current_state = graph.get_state(effective_config)
        run_input = None if current_state.values else effective_initial_state
        return current_state, run_input
    raise RunRegistryError(f"unsupported workflow version: {workflow_version!r}")


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xiaohongshu Agent CLI")
    parser.add_argument("--domain", type=str, choices=SUPPORTED_DOMAINS, help="Explicit domain for routing")
    parser.add_argument("--subdomain", type=str, help="Explicit subdomain for the selected domain")
    run_group = parser.add_mutually_exclusive_group()
    run_group.add_argument("--new", action="store_true", help="Force a new agent run")
    run_group.add_argument("--resume", nargs="?", const="", metavar="RUN", help="Resume by run ID or thread ID")
    run_group.add_argument("--thread-id", type=str, help="Existing conversation thread ID to resume")
    parser.add_argument("--runs", action="store_true", help="List the latest 20 runs and exit")
    parser.add_argument("--verbose", action="store_true", help="Show full IDs in --runs output")
    parser.add_argument("--clear", metavar="RUN", help="Delete a single run (run ID or thread ID) and its checkpoint, then exit")
    parser.add_argument("--clear-all", action="store_true", help="Delete ALL runs and checkpoints, then exit")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt for --clear-all")
    parser.add_argument("--focus_keyword", type=str, help="Focus keyword for the post")
    parser.add_argument("--topic_num", type=int, default=10, help="Topic of the post")
    parser.add_argument("--provider", type=str, help="Model provider (glm, gemini, deepseek)")
    review_group = parser.add_mutually_exclusive_group()
    review_group.add_argument(
        "--review-materialize", metavar="RUN",
        help="Materialize/show an existing local v4 review workspace for RUN",
    )
    review_group.add_argument(
        "--review-show", metavar="RUN",
        help="Show the existing local v4 review workspace for RUN",
    )
    review_group.add_argument(
        "--review-submit", metavar="RUN",
        help="Submit the current local v4 review intent for RUN",
    )
    review_group.add_argument(
        "--review-verify", metavar="RUN",
        help="Verify an existing local v4 review decision for RUN",
    )
    parser.add_argument(
        "--review-intent", metavar="JSON",
        help="JSON file containing an untrusted v4 HumanReviewIntentV4",
    )
    parser.add_argument(
        "--review-reference", metavar="JSON",
        help="JSON file containing an externally persisted v4 decision reference",
    )
    args = parser.parse_args() if argv is None else parser.parse_args(argv)
    # Keep the parser seam backwards-compatible with tests and embedders that
    # provide a pre-review Namespace rather than argparse's full result.
    for review_arg in (
        "review_materialize",
        "review_show",
        "review_submit",
        "review_verify",
        "review_intent",
        "review_reference",
    ):
        if not hasattr(args, review_arg):
            setattr(args, review_arg, None)
    if args.runs and (args.new or args.resume is not None or args.thread_id):
        parser.error("--runs cannot be combined with --new, --resume, or --thread-id")
    clear_flags_active = args.clear is not None or args.clear_all
    if clear_flags_active and (args.new or args.resume is not None or args.thread_id or args.runs):
        parser.error("--clear/--clear-all cannot be combined with --new, --resume, --thread-id, or --runs")
    if args.clear_all and args.clear is not None:
        parser.error("--clear-all cannot be combined with --clear")
    if args.yes and not clear_flags_active:
        parser.error("--yes only applies to --clear-all")
    if args.subdomain and not args.domain:
        parser.error("--subdomain requires --domain")
    if args.focus_keyword is not None and not args.focus_keyword.strip():
        parser.error("--focus_keyword must be non-empty when provided")
    review_run = next(
        (
            value
            for value in (
                args.review_materialize,
                args.review_show,
                args.review_submit,
                args.review_verify,
            )
            if value is not None
        ),
        None,
    )
    review_active = review_run is not None
    if review_active and (
        args.new
        or args.resume is not None
        or args.thread_id
        or args.runs
        or args.verbose
        or args.clear is not None
        or args.clear_all
        or args.yes
        or args.domain
        or args.subdomain
        or args.focus_keyword is not None
        or args.provider
        or args.topic_num != 10
    ):
        parser.error("v4 review operations require only an existing RUN identity")
    if not review_active and (args.review_intent or args.review_reference):
        parser.error("--review-intent/--review-reference require a v4 review operation")
    if args.review_submit and not args.review_intent:
        parser.error("--review-submit requires --review-intent")
    if args.review_verify and not args.review_reference:
        parser.error("--review-verify requires --review-reference")
    if args.review_intent and not args.review_submit:
        parser.error("--review-intent is valid only with --review-submit")
    if args.review_reference and not args.review_verify:
        parser.error("--review-reference is valid only with --review-verify")
    if args.domain and args.subdomain:
        profile = get_domain_profile(args.domain)
        if args.subdomain not in profile.allowed_subdomains:
            parser.error(
                "--subdomain must be one of "
                + ", ".join(profile.allowed_subdomains)
                + f" for domain {args.domain}"
            )
    return args


def create_initial_state(args: argparse.Namespace) -> dict:
    return {
        "interactive": True,
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain": args.domain,
        "subdomain": args.subdomain,
        "domain_context": None,
        "content_policy": None,
        "memory_context": None,
        "evidence_briefs": {},
        "final_policy_issues": [],
        "trends_num": args.topic_num,
        "focus_keyword": args.focus_keyword if args.focus_keyword is not None else "",
        "focus_keyword_cli_present": args.focus_keyword is not None,
        "topic_signals": [],
        "creative_briefs": [],
        "topic_candidates": [],
        "topic_generation_trace": None,
        "topic_generation_degraded_reason": None,
        "trends": [],
        "angles": [],
        "novelty_check_results": None,
        "scores": [],
        "outlines": [],
        "drafts": [],
        "title_options": [],
        "title_winner": None,
        "current_node": None,
        "decision_output": None,
        "r1_output": None,
        "r2_output": None,
        "final_content": None,
        "hashtags": None,
        # llm_scene_v3 dynamic visual production slots are seeded empty; the
        # pipeline populates them as content_atomizer -> visual_director ->
        # ... -> visual_critic runs.
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
        "publish_package": None,
        "review_status": None,
        "review_feedback": None,
        "review_round": 0,
        "review_route": None,
        "editorial_workflow_version": "llm_scene_v3",
        "legacy_editorial_checkpoint": False,
        "data_writed": None,
    }


def _resolve_run_output_dir(thread_id: str) -> str:
    """Per-run directory where the generic scene renderer writes carousel PNGs."""

    import hashlib

    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    return str(Path("outputs") / "render_runs" / f"{thread_id}-{digest}")


def _value(item, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def extract_run_updates(values: dict, last_node: str | None = None) -> dict[str, str]:
    context = values.get("domain_context")
    package = values.get("publish_package") or {}
    trends = values.get("trends") or []
    candidate = _value(trends[0], "topic") if trends else None
    fields = {
        "domain": _value(context, "domain") or values.get("domain"),
        "subdomain": _value(context, "subdomain") or values.get("subdomain"),
        "title": _value(package, "title"),
        "topic_summary": _value(package, "topic") or candidate,
        "last_node": values.get("current_node") or last_node,
    }
    return {name: value for name, value in fields.items() if isinstance(value, str) and value}


def _update_run_lifecycle(
    registry: RunRegistry,
    thread_id: str,
    *,
    status: str | None = None,
    execution_state: str | None = None,
    **updates,
):
    """Write lifecycle state through the authoritative versioned field."""

    run = registry.get_by_thread_id(thread_id)
    if run is None:
        raise RunRegistryError(f"unknown thread ID: {thread_id}")
    if run.workflow_version == "llm_scene_v4":
        if execution_state is None:
            if status is None:
                raise ValueError("v4 lifecycle update requires execution_state")
            execution_state = LEGACY_STATUS_TO_EXECUTION[status]
        return registry.update_run(
            thread_id,
            execution_state=execution_state,
            **updates,
        )
    if status is None:
        if execution_state is None:
            raise ValueError("v3 lifecycle update requires status")
        status = EXECUTION_TO_LEGACY_STATUS[execution_state]
    return registry.update_run(thread_id, status=status, **updates)


def _is_missing_selected_v4_graph(error: BaseException) -> bool:
    """Identify the specific lazy-import failure for the selected v4 graph."""

    return isinstance(error, ModuleNotFoundError) and (
        getattr(error, "name", None) == "src.graph_v4"
        or "No module named 'src.graph_v4'" in str(error)
    )


def _prepare_run_for_resume(registry: RunRegistry, run: AgentRun) -> AgentRun:
    """Validate and mark an explicitly selected run without losing v4 state."""

    if run.workflow_version == "llm_scene_v4":
        if run.execution_state not in V4_RESUMABLE_EXECUTION_STATES:
            raise RunRegistryError(
                f"v4 run {run.thread_id!r} in state {run.execution_state} cannot be resumed"
            )
        state = (
            "WAITING_HUMAN"
            if run.execution_state == "WAITING_HUMAN"
            else "RUNNING"
        )
        return _update_run_lifecycle(
            registry,
            run.thread_id,
            execution_state=state,
            error_summary=None,
        )
    return _update_run_lifecycle(
        registry,
        run.thread_id,
        status="running",
        error_summary=None,
    )


def _mark_loaded_run_running(
    registry: RunRegistry,
    thread_id: str,
    **updates,
) -> AgentRun:
    """Mark a loaded run active while retaining a pending human review."""

    run = registry.get_by_thread_id(thread_id)
    if run is None:
        raise RunRegistryError(f"unknown thread ID: {thread_id}")
    if run.workflow_version == "llm_scene_v4":
        state = (
            "WAITING_HUMAN"
            if run.execution_state == "WAITING_HUMAN"
            else "RUNNING"
        )
        return _update_run_lifecycle(
            registry,
            thread_id,
            execution_state=state,
            error_summary=None,
            **updates,
        )
    return _update_run_lifecycle(
        registry,
        thread_id,
        status="running",
        error_summary=None,
        **updates,
    )


def _record_publish_export_failure(
    registry: RunRegistry,
    thread_id: str,
) -> AgentRun:
    """Persist a failed terminal export without creating a false v4 review wait."""

    run = registry.get_by_thread_id(thread_id)
    if run is None:
        raise RunRegistryError(f"unknown thread ID: {thread_id}")
    if run.workflow_version == "llm_scene_v4":
        return _update_run_lifecycle(
            registry,
            thread_id,
            execution_state="INTERRUPTED_RETRYABLE",
            error_summary=PUBLISH_EXPORT_RETRYABLE_ERROR,
        )
    return _update_run_lifecycle(
        registry,
        thread_id,
        status="awaiting_review",
    )


def _print_run_choices(runs: list[AgentRun], output_fn=print) -> None:
    output_fn("\n可恢复的任务：")
    for run in runs:
        output_fn(format_run(run))
    output_fn("输入任务编号恢复；输入 n 新建任务；输入 q 退出。")


def select_run(registry: RunRegistry, args: argparse.Namespace, input_fn=input, output_fn=print):
    if args.new:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    if args.thread_id:
        existing = registry.get_by_thread_id(args.thread_id)
        if existing is not None:
            _prepare_run_for_resume(registry, existing)
        return args.thread_id, False
    if args.resume not in (None, ""):
        run = registry.get_by_thread_id(args.resume)
        if run is None and args.resume.isdigit():
            run = registry.get_by_run_id(int(args.resume))
        if run is None:
            raise RunRegistryError(f"找不到要恢复的任务：{args.resume}")
        _prepare_run_for_resume(registry, run)
        return run.thread_id, False
    runs = registry.list_resumable()
    if not runs:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    _print_run_choices(runs, output_fn)
    while True:
        choice = input_fn("请选择：").strip().lower()
        if choice == "n":
            thread_id = build_thread_id(None)
            registry.create_run(thread_id, args.focus_keyword)
            return thread_id, True
        if choice == "q":
            return None
        if choice.isdigit():
            run = registry.get_by_run_id(int(choice))
            if run in runs:
                _prepare_run_for_resume(registry, run)
                return run.thread_id, False
        output_fn("无效选择，请输入列表中的任务编号、n 或 q。")


def _resolve_run(registry: RunRegistry, ref: str) -> AgentRun | None:
    run = registry.get_by_thread_id(ref)
    if run is None and ref.isdigit():
        run = registry.get_by_run_id(int(ref))
    return run


def run_v4_review_cli(
    args: argparse.Namespace,
    registry: RunRegistry,
    *,
    workspace_loader=None,
    inputs_loader=None,
    package_loader=None,
    submitter=None,
    verifier=None,
    decision_loader=None,
    output_fn=print,
):
    """Run one additive, local-only v4 review operation.

    Task 18 owns graph/checkpoint orchestration.  Until then the loaders are
    explicit dependencies: the CLI refuses to guess a graph, checkpoint,
    workspace, or source contract from an arbitrary filesystem path.
    """

    from src.review.v4_decisions import (
        read_human_review_decision,
        submit_human_review_intent,
        verify_human_review_decision,
    )
    from src.review.v4_workspace import (
        read_review_intent,
    )
    from src.schemas.v4.review import HumanReviewDecisionReferenceV4

    def call_with_optional_package(function, *positional, package):
        """Keep dependency-injected test seams compatible with lean fakes."""

        import inspect

        try:
            parameters = inspect.signature(function).parameters.values()
        except (TypeError, ValueError):
            parameters = ()
        accepts_keyword = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            or parameter.name == "current_package"
            for parameter in parameters
        )
        if accepts_keyword:
            return function(*positional, current_package=package)
        return function(*positional)

    operation_values = {
        "materialize": args.review_materialize,
        "show": args.review_show,
        "submit": args.review_submit,
        "verify": args.review_verify,
    }
    active = tuple((name, value) for name, value in operation_values.items() if value is not None)
    if len(active) != 1:
        raise RunRegistryError("exactly one local v4 review operation is required")
    operation, run_ref = active[0]
    run = _resolve_run(registry, run_ref)
    if run is None:
        raise RunRegistryError(f"找不到 v4 review 任务：{run_ref}")
    if run.workflow_version != "llm_scene_v4":
        raise RunRegistryError("local review operations require workflow_version=llm_scene_v4")
    if run.run_mode != "production":
        raise RunRegistryError("local review operations do not accept shadow runs")
    if run.execution_state != "WAITING_HUMAN" or run.status != "awaiting_review":
        raise RunRegistryError(
            "local v4 review operations require an exact WAITING_HUMAN/awaiting_review run"
        )
    if workspace_loader is None:
        raise RunRegistryError(
            "v4 review workspace loader is not configured; refusing to start a graph or guess checkpoint state"
        )
    try:
        loaded = workspace_loader(run)
    except Exception as error:
        raise RunRegistryError("v4 review workspace checkpoint is unavailable") from error
    if isinstance(loaded, tuple) and len(loaded) == 2:
        workspace, inputs = loaded
    else:
        workspace = loaded
        inputs = None
        if inputs_loader is not None:
            try:
                inputs = inputs_loader(run, workspace)
            except Exception as error:
                raise RunRegistryError("v4 review source-contract checkpoint is unavailable") from error

    if workspace is None or not hasattr(workspace, "root"):
        raise RunRegistryError("v4 review checkpoint lacks a workspace handle")
    # A production loader returns the exact Task 16A handle.  Keep the
    # dependency-injected test seam permissive, but verify real handles before
    # exposing an index or accepting mutable intake.
    try:
        from src.review.v4_workspace import ReviewWorkspaceV4, verify_review_workspace

        if type(workspace) is ReviewWorkspaceV4:
            verify_review_workspace(workspace)
    except Exception as error:
        if isinstance(error, RunRegistryError):
            raise
        raise RunRegistryError("v4 review workspace is stale or unauthorized") from error

    if operation in {"materialize", "show"}:
        index = workspace.root / "index.html"
        try:
            index_info = index.lstat()
        except OSError as error:
            raise RunRegistryError("v4 review workspace index is missing") from error
        if stat.S_ISLNK(index_info.st_mode) or not stat.S_ISREG(index_info.st_mode):
            raise RunRegistryError("v4 review workspace index is missing")
        try:
            uri = index.as_uri()
        except ValueError as error:
            raise RunRegistryError("v4 review workspace index is not an absolute local file") from error
        output_fn(uri)
        return workspace

    if operation == "submit":
        if inputs is None:
            raise RunRegistryError("v4 review source-contract loader is not configured")
        if args.review_intent:
            try:
                intent = json.loads(Path(args.review_intent).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as error:
                raise RunRegistryError("v4 review intent file is unreadable or malformed") from error
        else:
            intent = read_review_intent(workspace)
        package = package_loader(run, workspace, inputs) if package_loader is not None else None
        submit = submitter or submit_human_review_intent
        try:
            result = call_with_optional_package(
                submit, workspace, inputs, intent, package=package
            )
            reference_value = result.reference
        except Exception as error:
            raise RunRegistryError("v4 review intent was rejected by the decision boundary") from error
        output_fn(
            json.dumps(
                reference_value.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return result

    try:
        reference_payload = json.loads(
            Path(args.review_reference).read_text(encoding="utf-8")
        )
        reference = HumanReviewDecisionReferenceV4.model_validate(reference_payload)
    except (OSError, UnicodeError, ValueError) as error:
        raise RunRegistryError("v4 review decision reference is unreadable or malformed") from error
    load_decision = decision_loader or read_human_review_decision
    if inputs is None:
        raise RunRegistryError("v4 review source-contract loader is not configured")
    try:
        decision = load_decision(workspace, reference)
    except Exception as error:
        raise RunRegistryError("v4 review decision record is missing or stale") from error
    package = package_loader(run, workspace, inputs) if package_loader is not None else None
    check = verifier or verify_human_review_decision
    try:
        checked = call_with_optional_package(
            check, decision, reference, workspace, inputs, package=package
        )
    except Exception as error:
        raise RunRegistryError("v4 review decision failed source and byte verification") from error
    output_fn(
        json.dumps(
            {
                "workflow_version": "llm_scene_v4",
                "run_id": checked.run_id,
                "candidate_id": checked.candidate_id,
                "revision_id": checked.revision_id,
                "decision_id": checked.decision_id,
                "decision_canonical_sha256": checked.canonical_sha256,
                "action": checked.action,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return checked


def clear_runs(
    registry: RunRegistry,
    args: argparse.Namespace,
    *,
    checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
    input_fn=input,
    output_fn=print,
) -> int:
    """Delete runs + their LangGraph checkpoints, then exit.

    ``--clear RUN`` deletes a single run (no confirmation: the run is named
    explicitly). ``--clear-all`` wipes every run and asks for confirmation unless
    ``--yes`` is set. Registry rows and checkpoint blobs are both cleared
    best-effort. Returns the number of registry rows removed.
    """
    if args.clear_all:
        runs = registry.list_recent()
        if not runs:
            output_fn("没有可清除的任务。")
            return 0
        output_fn(f"将清除全部 {len(runs)} 个任务及其 checkpoint：")
        for run in runs:
            output_fn(format_run(run, verbose=args.verbose))
        if not args.yes:
            answer = input_fn("确认清除全部？此操作不可撤销 [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                output_fn("已取消。")
                return 0
        for run in runs:
            try:
                delete_checkpoint_thread(run.thread_id, checkpoint_path)
            except Exception as exc:  # noqa: BLE001 - report and continue
                output_fn(f"checkpoint 清除失败 ({run.thread_id}): {exc}")
        deleted = registry.delete_all()
        output_fn(f"已清除 {deleted} 个任务。")
        return deleted

    run = _resolve_run(registry, args.clear)
    if run is None:
        raise RunRegistryError(f"找不到要清除的任务：{args.clear}")
    output_fn("将清除该任务及其 checkpoint：")
    output_fn(format_run(run, verbose=args.verbose))
    try:
        delete_checkpoint_thread(run.thread_id, checkpoint_path)
    except Exception as exc:  # noqa: BLE001 - report but still drop the registry row
        output_fn(f"checkpoint 清除失败: {exc}")
    deleted = registry.delete_run(run.thread_id)
    output_fn("已清除。" if deleted else "注册表无此任务（仅清除了 checkpoint）。")
    return 1 if deleted else 0


def backfill_legacy_run(registry: RunRegistry, thread_id: str, current_state) -> None:
    values = getattr(current_state, "values", None) or {}
    if not values or registry.get_by_thread_id(thread_id) is not None:
        return
    registry.upsert_run(thread_id, status="running", **extract_run_updates(values))

def export_publish_package(completed_state: StateSnapshot) -> PublishArtifacts:
    """Validate and export one immutable terminal graph checkpoint."""
    if type(completed_state) is not StateSnapshot:
        raise TypeError("final export requires a real langgraph.types.StateSnapshot")
    values = completed_state.values
    if not isinstance(values, Mapping):
        raise TypeError("final export requires completed graph state")
    publish_package = values.get("publish_package")
    if not isinstance(publish_package, Mapping):
        raise ValueError("completed graph state requires publish_package")
    resolve_publish_package_profile(publish_package)
    return _export_verified_state_snapshot(completed_state)


def read_multiline_json() -> dict:
    print("请粘贴完整 JSON，输入单独一行 END 结束：")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    return json.loads("\n".join(lines))


def collect_human_review(interrupt_value: dict) -> dict:
    publish_package = interrupt_value["publish_package"]
    pending_assets = list(interrupt_value.get("pending_assets") or [])
    asset_decisions = {}
    print("\n===== Human Review Required =====")
    print(interrupt_value["message"])
    print(json.dumps(publish_package, ensure_ascii=False, indent=2))

    for asset in pending_assets:
        decision_id = asset.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("Pending review asset is missing decision_id.")
        print(
            json.dumps(
                {
                    "slot_id": asset.get("slot_id"),
                    "provider": asset.get("provider"),
                    "provider_asset_id": asset.get("provider_asset_id"),
                    "source_url": asset.get("source_url"),
                    "author": asset.get("author"),
                    "license": asset.get("license"),
                    "license_terms_url": asset.get("license_terms_url"),
                    "sha256": asset.get("sha256"),
                    "metadata_path": asset.get("metadata_path"),
                    "unresolved_safety_checks": asset.get(
                        "unresolved_safety_checks"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        while True:
            decision = input(
                f"资产 {decision_id} ({asset.get('provider') or 'external'})："
                "输入 approved 或 rejected: "
            ).strip().lower()
            if decision in {"approved", "rejected"}:
                break
            print("无效输入，请输入 approved / rejected。")
        safety_decisions = {}
        if decision == "approved":
            for safety_check in list(asset.get("unresolved_safety_checks") or []):
                expected = safety_check == "allowed_for_publishing"
                while True:
                    answer = input(
                        f"安全项 {safety_check}：输入 yes 或 no: "
                    ).strip().lower()
                    if answer in {"yes", "no"}:
                        safety_decisions[safety_check] = answer == "yes"
                        break
                    print("无效输入，请输入 yes / no。")
                if safety_decisions[safety_check] is not expected:
                    raise ValueError(
                        f"Asset {decision_id} did not receive a safe publishing decision."
                    )
        asset_decisions[decision_id] = {
            "decision": decision,
            "binding": dict(asset.get("decision_binding") or {}),
            "safety_decisions": safety_decisions,
        }

    while True:
        action = input("\n输入 yes 继续；输入 edit 修改 JSON；输入 no 提建议并继续 review: ").strip().lower()

        if action == "yes":
            response = {
                "approved": True,
                "edited_publish_package": None,
                "feedback": "approved by user",
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        if action == "edit":
            try:
                edited_publish_package = read_multiline_json()
            except json.JSONDecodeError as exc:
                print(f"JSON 解析失败：{exc}")
                continue

            approve = input("修改后是否批准继续？输入 yes 或 no: ").strip().lower()
            feedback = input("可选：补充一点 review 建议，直接回车可跳过: ").strip()
            response = {
                "approved": approve == "yes",
                "edited_publish_package": edited_publish_package,
                "feedback": feedback or "edited by user",
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        if action == "no":
            feedback = input("请输入 review 建议: ").strip()
            response = {
                "approved": False,
                "edited_publish_package": None,
                "feedback": feedback,
            }
            if asset_decisions:
                response["asset_decisions"] = asset_decisions
            return response

        print("无效输入，请输入 yes / edit / no。")


def collect_domain_confirmation(interrupt_value: dict) -> dict:
    context = interrupt_value["context"]
    allowed_domains = tuple(interrupt_value.get("allowed_domains", SUPPORTED_DOMAINS))
    profile_subdomains = interrupt_value.get("allowed_subdomains")
    print("\n===== Domain Confirmation Required =====")
    print(interrupt_value["message"])
    print(json.dumps(context, ensure_ascii=False, indent=2))

    while True:
        selected_domain = (
            input(
                f"请输入 domain {allowed_domains}，直接回车使用当前值 {context['domain']}: "
            ).strip()
            or context["domain"]
        )
        if selected_domain not in allowed_domains:
            print("无效 domain，请重新输入。")
            continue

        if profile_subdomains is not None:
            allowed_subdomains = tuple(profile_subdomains)
            default_subdomain = (
                context["subdomain"]
                if selected_domain == context["domain"]
                and context["subdomain"] in allowed_subdomains
                else allowed_subdomains[0]
            )
        else:
            profile = get_domain_profile(selected_domain)
            allowed_subdomains = profile.allowed_subdomains
            default_subdomain = (
                context["subdomain"]
                if selected_domain == context["domain"]
                else profile.default_subdomain
            )
        print(f"可选 subdomain: {', '.join(allowed_subdomains)}")
        selected_subdomain = (
            input(f"请输入 subdomain，直接回车使用 {default_subdomain}: ").strip()
            or default_subdomain
        )
        if selected_subdomain not in allowed_subdomains:
            print("无效 subdomain，请重新输入。")
            continue

        return {"domain": selected_domain, "subdomain": selected_subdomain}


def collect_interrupt_response(interrupt_value: dict) -> dict:
    kind = interrupt_value.get("kind")
    if kind == "domain_confirmation":
        return collect_domain_confirmation(interrupt_value)
    if kind in {None, "publish_review"}:
        return collect_human_review(interrupt_value)
    raise ValueError(f"Unsupported interrupt kind: {kind}")


def export_completed_publish_package(graph, config) -> bool:
    """Export only from a completed, final-policy-clean graph checkpoint."""
    if not hasattr(graph, "get_state"):
        return False
    completed_state = graph.get_state(config)
    try:
        publish_package = completed_state.values["publish_package"]
        print("The final publish package title is:")
        print(publish_package["title"])
        resolve_publish_package_profile(publish_package)
        _export_verified_state_snapshot(completed_state)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def sync_run_from_graph(
    registry: RunRegistry,
    graph,
    config: dict,
    thread_id: str,
    last_node: str | None,
) -> None:
    state = graph.get_state(config)
    values = getattr(state, "values", None) or {}
    _update_run_lifecycle(
        registry,
        thread_id,
        status="running",
        error_summary=None,
        **extract_run_updates(values, last_node),
    )


def stream_graph_until_stop(
    graph,
    run_input,
    config,
    *,
    registry: RunRegistry | None = None,
    thread_id: str | None = None,
    review_input_state: dict[str, bool] | None = None,
) -> bool:
    next_input = run_input

    while True:
        interrupted = False
        for output in graph.stream(next_input, config=config):
            for key, value in output.items():
                if key == "__interrupt__":
                    interrupted = True
                    interrupt_event = value[0]
                    payload = interrupt_event.value
                    if not isinstance(payload, dict):
                        raise ValueError("Interrupt payload must be a dict.")
                    if registry is not None and thread_id is not None:
                        _update_run_lifecycle(
                            registry,
                            thread_id,
                            status="awaiting_review",
                        )
                    if review_input_state is not None:
                        review_input_state["bound"] = True
                    response = collect_interrupt_response(payload)
                    if review_input_state is not None:
                        review_input_state["bound"] = False
                    next_input = Command(resume=response)
                    if registry is not None and thread_id is not None:
                        _update_run_lifecycle(
                            registry,
                            thread_id,
                            status="running",
                            error_summary=None,
                        )
                    break

                print(f"Finished processing node: {key}")
                if registry is not None and thread_id is not None:
                    sync_run_from_graph(registry, graph, config, thread_id, key)
            if interrupted:
                break

        if not interrupted:
            return export_completed_publish_package(graph, config)


def main():
    args = parse_cli_args()
    try:
        registry = RunRegistry(RUN_REGISTRY_PATH)
    except RunRegistryError as exc:
        print(f"本地运行注册表错误：{exc}", file=sys.stderr)
        sys.exit(1)

    thread_id = None
    graph_ready = False
    checkpoint_loaded = False
    review_input_state = {"bound": False}
    try:
        if args.runs:
            for run in registry.list_recent(20):
                print(format_run(run, verbose=args.verbose))
            return

        if args.clear_all or args.clear is not None:
            clear_runs(registry, args)
            return

        if any(
            value is not None
            for value in (
                args.review_materialize,
                args.review_show,
                args.review_submit,
                args.review_verify,
            )
        ):
            run_v4_review_cli(args, registry)
            return

        selection = select_run(registry, args)
        if selection is None:
            return
        thread_id, is_new = selection

        init_message = "Starting Xiaohongshu Agent"
        if args.provider:
            init_message += f" with default model: {args.provider},"
        if args.focus_keyword:
            init_message += f" with topic focus keyword: {args.focus_keyword},"
        if args.domain:
            init_message += f" with domain: {args.domain},"
        if args.subdomain:
            init_message += f" with subdomain: {args.subdomain},"
        if args.topic_num:
            init_message += f" with topic number: {args.topic_num}."
        print(init_message)

        if args.provider:
            set_default_provider(args.provider)

        persisted_run = registry.get_by_thread_id(thread_id)
        workflow_context = select_workflow_context(
            registry,
            thread_id,
            requested_version=None,
            run_mode=None,
        )
        if persisted_run is None:
            graph = build_graph_for_context(
                workflow_context,
                v3_factory=_create_v3_graph,
                v4_factory=_create_v4_graph,
            )
        else:
            graph = build_graph_for_run(persisted_run, _graph_factories())
        graph_ready = True

        database = XHSMemoryManager("data/xhs_memory.db")
        database.init_db("memory/schema.sql")
        initial_state = create_initial_state(args)
        initial_state["run_output_dir"] = _resolve_run_output_dir(thread_id)
        config = build_run_config(thread_id)
        current_state, run_input = load_versioned_run(
            graph,
            config,
            initial_state,
            workflow_version=workflow_context.workflow_version,
        )
        checkpoint_loaded = True

        if args.thread_id:
            backfill_legacy_run(registry, thread_id, current_state)
        if not current_state.values:
            if not is_new and args.resume is not None:
                raise RunRegistryError("所选任务的 LangGraph checkpoint 不存在，请使用 --new 创建新任务")
            if registry.get_by_thread_id(thread_id) is None:
                registry.create_run(thread_id, args.focus_keyword)
            print("No existing state found, starting a new run...")
        else:
            _mark_loaded_run_running(
                registry,
                thread_id,
                **extract_run_updates(current_state.values),
            )
            print("Found existing state, resuming from the latest checkpoint...")
            # A resumed run gets a fresh design/render QA loop budget. The
            # failure counters persist across attempts, so a run interrupted
            # after two QA strikes would otherwise resume with only one strike
            # left before the hard gate interrupts again. Resetting the counters
            # on resume gives the (human-supervised) retry a full 3-strike
            # window without ever force-passing the hard gates. A real compiled
            # graph always has update_state; the guard keeps the CLI testable
            # with minimal fakes.
            if workflow_context.workflow_version == "llm_scene_v3" and hasattr(
                graph, "update_state"
            ):
                graph.update_state(
                    config,
                    {"design_plan_qa_failures": 0, "render_qa_failures": 0},
                )

        if current_state.values and not current_state.next:
            if export_completed_publish_package(graph, config):
                _update_run_lifecycle(
                    registry,
                    thread_id,
                    status="completed",
                    error_summary=None,
                )
            else:
                _record_publish_export_failure(registry, thread_id)
            return

        exported = stream_graph_until_stop(
            graph,
            run_input,
            config,
            registry=registry,
            thread_id=thread_id,
            review_input_state=review_input_state,
        )
        if exported:
            _update_run_lifecycle(
                registry,
                thread_id,
                status="completed",
                error_summary=None,
            )
        else:
            _record_publish_export_failure(registry, thread_id)
    except Exception as exc:
        if thread_id is not None:
            try:
                run = registry.get_by_thread_id(thread_id)
                if run is not None:
                    if run.workflow_version == "llm_scene_v4":
                        review_input_failure = (
                            checkpoint_loaded and review_input_state["bound"]
                        )
                        if review_input_failure:
                            failure_state = "WAITING_HUMAN"
                        else:
                            failure_state = (
                                "FAILED_FATAL"
                                if not graph_ready
                                and _is_missing_selected_v4_graph(exc)
                                else "INTERRUPTED_RETRYABLE"
                            )
                        _update_run_lifecycle(
                            registry,
                            thread_id,
                            execution_state=failure_state,
                            error_summary=exception_summary(exc),
                        )
                    else:
                        _update_run_lifecycle(
                            registry,
                            thread_id,
                            status="interrupted",
                            error_summary=exception_summary(exc),
                        )
            except RunRegistryError as registry_exc:
                print(f"本地运行注册表错误：{registry_exc}", file=sys.stderr)
        print(f"Error running agent: {exc}")
        sys.exit(1)
    finally:
        registry.close()

if __name__ == "__main__":
    main()
