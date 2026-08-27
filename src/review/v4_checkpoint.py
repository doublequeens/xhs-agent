"""Graph-free checkpoint loading for the local v4 Human Review CLI.

Task 16B boundary: the real ``main()`` review CLI reads one WAITING_HUMAN v4
run's exact review source contracts, the separately persisted external
``ReviewWorkspaceReferenceV4``, and the exact ``publish_package`` from the
production LangGraph SQLite checkpoint.  This module never starts a graph,
memory manager, publisher, network, or browser, and never writes to the
checkpoint database: one connection is opened, the latest channel values for
the thread are read, and the connection is closed on every path.

Trust model
-----------
Everything decoded from the checkpoint is untrusted until it is revalidated
through its strict model boundary.  LangGraph's msgpack layer rebuilds pydantic
blobs with ``model_construct`` (no validators, nested models left as raw
dicts) and plain dataclasses as mappings, so every contract is dumped back to
a canonical JSON payload and revalidated through
``Contract.model_validate_json`` — the same rehydration semantics the reviewed
v4 route-context restore uses.  The workspace is then loaded only through
``load_review_workspace`` with the checkpoint-carried reference; the loader
never derives authorization from the review filesystem.
"""

from __future__ import annotations

import sqlite3
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.review.v4_workspace import (
    ReviewBindingError,
    ReviewWorkspaceInputsV4,
    ReviewWorkspaceV4,
    load_review_workspace,
    validate_review_workspace_inputs,
)
from src.schemas.assets import AssetManifest, AssetResolutionResult
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, canonical_json_v4
from src.schemas.v4.critique import CarouselAestheticEvaluationV4
from src.schemas.v4.direction import (
    CarouselNarrativeV4,
    PageBriefSetV4,
    VisualDirectionPlanV4,
)
from src.schemas.v4.layout import CarouselDesignPlanV4
from src.schemas.v4.quality import DesignPlanQAResultV4
from src.schemas.v4.rendering import RenderManifestV4, RenderQAResultV4
from src.schemas.v4.review import (
    ReviewWorkspaceManifestV4,
    ReviewWorkspaceReferenceV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ArtifactIdentityError,
    ArtifactPaths,
    revalidate_artifact_paths,
    resolve_artifact_paths,
)

# Importing the persisted-state schema tree registers every pydantic class a
# v4 production checkpoint may carry with the shared trusted-schema serializer
# (see ``src/checkpoint_serde.py``).  Without it, earlier-stage channels of a
# real run degrade to plain dicts with deserialization warnings on every read.
import src.schemas.agent_state  # noqa: F401  (schema registration side effect)


__all__ = [
    "V4ReviewCheckpointBundle",
    "V4ReviewCheckpointError",
    "load_v4_review_checkpoint_bundle",
]


class V4ReviewCheckpointError(RuntimeError):
    """A v4 review checkpoint is missing, unreadable, or not exact."""


@dataclass(frozen=True)
class V4ReviewCheckpointBundle:
    """Everything the local review CLI needs from one WAITING_HUMAN run."""

    thread_id: str
    run_id: str
    workspace: ReviewWorkspaceV4
    inputs: ReviewWorkspaceInputsV4
    publish_package: Mapping[str, Any]


_PATH_FIELDS = (
    "base_root",
    "run_root",
    "candidate_root",
    "revision_root",
    "asset_root",
    "render_root",
    "review_root",
    "artifact_root",
)

# (inputs field, checkpoint channel names in priority order, exact type,
#  required).  Mirrors the channel aliases the v4 Human Review node reads so
#  the CLI and the node load exactly the same contracts.
_CONTRACT_CHANNELS: tuple[tuple[str, tuple[str, ...], type, bool], ...] = (
    ("content_lock", ("content_lock",), ContentLock, True),
    ("content_atom_set", ("content_atom_set", "atom_set"), ContentAtomSetV4, True),
    (
        "semantic_content_model",
        ("semantic_content_model", "semantic_model"),
        SemanticContentModelV4,
        True,
    ),
    ("carousel_narrative", ("carousel_narrative",), CarouselNarrativeV4, True),
    ("page_brief_set", ("page_brief_set", "page_briefs"), PageBriefSetV4, True),
    ("visual_direction_plan", ("visual_direction_plan",), VisualDirectionPlanV4, True),
    ("asset_manifest", ("asset_manifest", "assets"), AssetManifest, True),
    (
        "carousel_design_plan",
        ("carousel_design_plan_v4", "carousel_design_plan"),
        CarouselDesignPlanV4,
        True,
    ),
    (
        "design_plan_qa",
        ("design_plan_qa_result_v4", "design_plan_qa_result"),
        DesignPlanQAResultV4,
        True,
    ),
    ("render_manifest", ("render_manifest_v4", "render_manifest"), RenderManifestV4, True),
    ("render_qa", ("render_qa_result_v4", "render_qa_result"), RenderQAResultV4, True),
    (
        "visual_critique",
        ("visual_critique_v4", "visual_critique"),
        CarouselAestheticEvaluationV4,
        True,
    ),
    (
        "asset_resolution_result",
        ("asset_resolution_result_v4", "asset_resolution_result"),
        AssetResolutionResult,
        False,
    ),
)


def _channel(channels: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = channels.get(name)
        if value is not None:
            return value
    return None


def _revalidated(value: Any, contract_type: type, label: str) -> Any:
    """Revalidate one contract through its strict model boundary.

    A checkpoint round-trip can return either a ``model_construct`` instance
    whose nested models are still raw dicts or a plain mapping.  Both forms
    are dumped to a canonical JSON payload and revalidated, so a coordinated
    rehash still has to satisfy every validator (including canonical hash
    self-checks) before the value is trusted.
    """

    if not (isinstance(value, contract_type) or isinstance(value, Mapping)):
        raise V4ReviewCheckpointError(
            f"v4 review checkpoint {label} is missing or malformed"
        )
    try:
        with warnings.catch_warnings():
            # Dumping a construct-only instance with dict-typed nested fields
            # emits pydantic serializer warnings; the strict revalidation
            # below is the actual gate, so the transient noise is suppressed.
            warnings.simplefilter("ignore", UserWarning)
            payload = (
                value.model_dump(mode="json")
                if isinstance(value, contract_type)
                else dict(value)
            )
        restored = contract_type.model_validate_json(
            canonical_json_v4(payload).encode("utf-8")
        )
    except Exception as error:
        raise V4ReviewCheckpointError(
            f"v4 review checkpoint {label} is not an exact contract"
        ) from error
    if type(restored) is not contract_type:
        raise V4ReviewCheckpointError(
            f"v4 review checkpoint {label} is not an exact contract"
        )
    return restored


def _paths_payload_from_instance(paths: ArtifactPaths) -> dict[str, Any]:
    return {
        "base_root": str(paths.base_root),
        "identity": {
            "run_id": paths.identity.run_id,
            "candidate_id": paths.identity.candidate_id,
            "revision_id": paths.identity.revision_id,
        },
        **{field: str(getattr(paths, field)) for field in _PATH_FIELDS[1:]},
        "trusted_base_identity": (
            None
            if paths.trusted_base_identity is None
            else list(paths.trusted_base_identity)
        ),
    }


def _rehydrate_paths(value: Any) -> ArtifactPaths:
    """Strictly rebuild ``ArtifactPaths``; a degraded mapping is expected."""

    if type(value) is ArtifactPaths:
        payload = _paths_payload_from_instance(value)
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint lacks exact ArtifactPaths"
        )
    identity_payload = payload.get("identity")
    if not isinstance(identity_payload, Mapping):
        raise V4ReviewCheckpointError(
            "v4 review checkpoint ArtifactPaths identity is missing"
        )
    try:
        identity = ArtifactIdentity(
            run_id=identity_payload["run_id"],
            candidate_id=identity_payload["candidate_id"],
            revision_id=identity_payload["revision_id"],
        )
        base_root = payload.get("base_root")
        if not isinstance(base_root, (str, Path)):
            raise V4ReviewCheckpointError(
                "v4 review checkpoint ArtifactPaths base root is malformed"
            )
        expected = resolve_artifact_paths(str(base_root), identity)
    except V4ReviewCheckpointError:
        raise
    except (KeyError, TypeError, ValueError, ArtifactIdentityError, OSError) as error:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint ArtifactPaths are unsafe or malformed"
        ) from error
    for field in _PATH_FIELDS:
        raw = payload.get(field)
        if not isinstance(raw, (str, Path)) or Path(raw) != getattr(expected, field):
            raise V4ReviewCheckpointError(
                "v4 review checkpoint ArtifactPaths drifted"
            )
    trusted = payload.get("trusted_base_identity")
    if not isinstance(trusted, (tuple, list)) or tuple(trusted) != (
        expected.trusted_base_identity or ()
    ):
        raise V4ReviewCheckpointError(
            "v4 review checkpoint ArtifactPaths base identity drifted"
        )
    try:
        return revalidate_artifact_paths(expected)
    except (ArtifactIdentityError, OSError) as error:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint ArtifactPaths are stale or unsafe"
        ) from error


def _rehydrate_previous_workspace(value: Any) -> ReviewWorkspaceV4:
    """Strictly rebuild the optional previous-revision workspace handle."""

    if type(value) is ReviewWorkspaceV4:
        payload = {
            "root": value.root,
            "manifest": value.manifest,
            "artifact_paths": value.artifact_paths,
            "manifest_raw": value.manifest_raw,
            "reference": value.reference,
        }
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint previous workspace is not exact"
        )
    paths = _rehydrate_paths(payload.get("artifact_paths"))
    manifest = _revalidated(
        payload.get("manifest"),
        ReviewWorkspaceManifestV4,
        "previous workspace manifest",
    )
    reference = _revalidated(
        payload.get("reference"),
        ReviewWorkspaceReferenceV4,
        "previous workspace reference",
    )
    root = payload.get("root")
    if not isinstance(root, (str, Path)) or Path(root) != paths.review_root:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint previous workspace root drifted"
        )
    raw = payload.get("manifest_raw")
    if not isinstance(raw, (bytes, bytearray)):
        raise V4ReviewCheckpointError(
            "v4 review checkpoint previous workspace manifest bytes are missing"
        )
    raw = bytes(raw)
    if raw != canonical_json_v4(manifest.model_dump(mode="json")).encode("utf-8"):
        raise V4ReviewCheckpointError(
            "v4 review checkpoint previous workspace manifest bytes are stale"
        )
    return ReviewWorkspaceV4(
        Path(root), manifest, paths, manifest_raw=raw, reference=reference
    )


def load_v4_review_checkpoint_bundle(
    thread_id: str,
    *,
    checkpoint_path: str | Path,
) -> V4ReviewCheckpointBundle:
    """Load one WAITING_HUMAN v4 review bundle from the SQLite checkpoint.

    The database is opened with a controlled read-only-use connection (no
    ``setup()``, no cached checkpointer) and closed on every path.  The
    registry thread id, the persisted state ``run_id``, and the artifact
    identity must all agree: Task 18 aligns the v4 graph's run id with the
    registry thread id, and this loader fails closed until they match.
    """

    if type(thread_id) is not str or not thread_id:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint requires an exact thread id"
        )
    path = Path(checkpoint_path).expanduser()
    if not path.is_file():
        raise V4ReviewCheckpointError("v4 review checkpoint database is missing")
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ModuleNotFoundError as error:  # pragma: no cover - dependency guard
        raise V4ReviewCheckpointError(
            "langgraph SQLite checkpoint support is unavailable"
        ) from error
    from src.checkpoint_serde import checkpoint_serializer

    # mode=ro: a default read-write connection would checkpoint a leftover
    # WAL into the main database and delete the sidecars on close — silently
    # mutating exactly the crash evidence a review CLI must preserve.  A
    # read-only connection ignores uncommitted frames and leaves every
    # database/write-ahead-log byte untouched.
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        checkpointer = SqliteSaver(conn, serde=checkpoint_serializer())
        try:
            checkpoint_tuple = checkpointer.get_tuple(
                {"configurable": {"thread_id": thread_id}}
            )
        except sqlite3.Error as error:
            raise V4ReviewCheckpointError(
                "v4 review checkpoint database is unreadable"
            ) from error
        checkpoint = (
            getattr(checkpoint_tuple, "checkpoint", None)
            if checkpoint_tuple is not None
            else None
        )
        if not isinstance(checkpoint, Mapping):
            raise V4ReviewCheckpointError(
                "v4 review checkpoint has no checkpoint for this thread"
            )
        channels = checkpoint.get("channel_values")
        if not isinstance(channels, Mapping):
            raise V4ReviewCheckpointError(
                "v4 review checkpoint has no channel values"
            )
    finally:
        conn.close()

    run_id = channels.get("run_id")
    if type(run_id) is not str or not run_id:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint lacks an exact state run id"
        )
    if run_id != thread_id:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint run id differs from the registry thread id"
        )

    fields: dict[str, Any] = {
        "artifact_paths": _rehydrate_paths(
            _channel(channels, "artifact_paths", "asset_transaction_paths")
        ),
    }
    for name, aliases, contract_type, required in _CONTRACT_CHANNELS:
        raw = _channel(channels, *aliases)
        if raw is None:
            if required:
                raise V4ReviewCheckpointError(
                    f"v4 review checkpoint lacks the {aliases[0]} contract"
                )
            fields[name] = None
            continue
        fields[name] = _revalidated(raw, contract_type, aliases[0])
    previous = _channel(
        channels, "previous_review_workspace_v4", "previous_review_workspace"
    )
    fields["previous_review_workspace"] = (
        None if previous is None else _rehydrate_previous_workspace(previous)
    )
    reference = _revalidated(
        _channel(
            channels, "review_workspace_reference", "review_workspace_reference_v4"
        ),
        ReviewWorkspaceReferenceV4,
        "review workspace reference",
    )
    package = channels.get("publish_package")
    if not isinstance(package, Mapping):
        raise V4ReviewCheckpointError(
            "v4 review checkpoint lacks an exact publish package"
        )
    try:
        inputs = ReviewWorkspaceInputsV4(**fields)
    except Exception as error:
        raise V4ReviewCheckpointError(
            "v4 review checkpoint source contracts are malformed"
        ) from error
    if inputs.artifact_paths.identity.run_id != run_id:
        raise V4ReviewCheckpointError(
            "v4 review artifact identity differs from the state run id"
        )
    try:
        workspace = load_review_workspace(inputs.artifact_paths, reference)
        validate_review_workspace_inputs(inputs)
    except (ReviewBindingError, ArtifactIdentityError, OSError) as error:
        raise V4ReviewCheckpointError(
            "v4 review workspace is stale or unauthorized"
        ) from error
    return V4ReviewCheckpointBundle(
        thread_id=thread_id,
        run_id=run_id,
        workspace=workspace,
        inputs=inputs,
        publish_package=package,
    )
