from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.asset_resolver.resolver import AssetSafetyDecision
from src.schemas.v4.direction import AssetDirectiveDraftV4, VisualAuthoringDraftV4
from src.visual_ai.protocols import GeneratedImage
from src.visual_design.model_retry import VisualProductionInterrupted


class ProviderMustNotBeCalled:
    def __init__(self):
        self.calls = 0

    def search(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("stale Q1 must fail before provider invocation")

    def generate(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("stale Q1 must fail before provider invocation")


def test_asset_node_routes_stale_or_missing_q1_before_filesystem_or_provider(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    provider = ProviderMustNotBeCalled()
    result = asset_resolver_node(
        {
            "run_id": "run-1",
            "run_mode": "shadow",
            "candidate_id": "candidate-1",
            "revision_id": "revision-1",
        },
        search_provider=provider,
        generation_provider=provider,
        base_root=tmp_path,
    )

    assert result["route"] == "visual_authoring"
    assert provider.calls == 0
    assert not tmp_path.exists() or not tuple(tmp_path.iterdir())


def _authored_state(*, required: bool = True):
    from tests.nodes.v4.test_authoring import RecordingGateway, _draft, _state
    from src.nodes.v4.authoring import visual_authoring_node

    draft = _draft()
    directive = AssetDirectiveDraftV4(
        directive_id="asset-1",
        page_id="page-1",
        role="skin_example",
        purpose="evidence",
        supports_fragment_refs=("fragment-0",),
        required=required,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt="text-free skin texture",
        negative_constraints=("watermark",),
        orientation="portrait",
    )
    first = draft.page_brief_set.pages[0].model_copy(
        update={"asset_directives": (directive,)}
    )
    changed = draft.page_brief_set.model_copy(
        update={"pages": (first, *draft.page_brief_set.pages[1:])}
    )
    authored = visual_authoring_node(
        _state(),
        gateway=RecordingGateway(
            VisualAuthoringDraftV4(narrative=draft.narrative, page_brief_set=changed), []
        ),
    )
    assert authored["route"] == "asset_resolver"
    return {**_state(), **authored}


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (300, 400), (180, 130, 120)).save(output, format="PNG")
    return output.getvalue()


class GenerationProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, request, transaction_dir):
        self.calls += 1
        raw = _image_bytes()
        transaction_dir.mkdir(parents=True, exist_ok=True)
        path = transaction_dir / "generated.png"
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        return GeneratedImage(
            path=path,
            mime_type="image/png",
            sha256=digest,
            provider="gemini",
            model="gemini-3.1-flash-image",
            prompt_sha256=request.prompt_sha256,
            response_sha256=digest,
            generated_at="2026-08-20T00:00:00+00:00",
        )


class SafeChecker:
    def check(self, path, directive):
        return AssetSafetyDecision(approved=True)


class AncestorSwappingChecker:
    def __init__(self, final_dir: Path, outside_dir: Path):
        self.final_dir = final_dir
        self.outside_dir = outside_dir
        self.seen: bytes | None = None

    def check(self, path, directive):
        leaf = self.final_dir / Path(path).name
        self.outside_dir.mkdir(parents=True, exist_ok=True)
        (self.outside_dir / leaf.name).write_bytes(b"outside-bytes")
        moved = self.final_dir.with_name(self.final_dir.name + "-moved")
        self.final_dir.rename(moved)
        self.final_dir.symlink_to(self.outside_dir, target_is_directory=True)
        try:
            self.seen = Path(path).read_bytes()
        finally:
            self.final_dir.unlink()
            moved.rename(self.final_dir)
        return AssetSafetyDecision(approved=True)


def test_safety_checker_legacy_path_adapter_reads_pinned_bytes_during_ancestor_swap(
    tmp_path: Path,
):
    from src.nodes.v4.assets import asset_resolver_node

    checker = AncestorSwappingChecker(
        tmp_path / "run-1" / "candidate-1" / "revision-1" / "assets" / "generated",
        tmp_path / "outside",
    )
    result = asset_resolver_node(
        _authored_state(),
        generation_provider=GenerationProvider(),
        safety_checker=checker,
        base_root=tmp_path,
    )

    final_path = Path(result["asset_manifest"].items[0].local_path)
    assert checker.seen == final_path.read_bytes()
    assert checker.seen != b"outside-bytes"
    assert result["asset_manifest"].items[0].security_status == "approved"


class StagingAwareGenerationProvider(GenerationProvider):
    def generate(self, request, transaction_dir):
        assert ".staging" in transaction_dir.name
        return super().generate(request, transaction_dir)


def test_asset_node_resolves_directives_once_under_revision_identity(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    provider = GenerationProvider()
    result = asset_resolver_node(
        _authored_state(),
        generation_provider=provider,
        safety_checker=SafeChecker(),
        base_root=tmp_path,
    )

    assert provider.calls == 1
    item = result["asset_manifest"].items[0]
    assert item.security_status == "approved"
    assert item.human_decision == "pending"
    assert item.run_id == "run-1"
    assert item.transaction_id == "revision-1"
    assert Path(item.local_path).parent.name == "generated"
    assert result["artifact_paths"].asset_root == tmp_path / "run-1" / "candidate-1" / "revision-1" / "assets"
    assert Path(result["asset_transaction_evidence"].transaction_root) == result["artifact_paths"].asset_root
    assert result["route"] == "composition_planning"


def test_asset_node_required_failure_preserves_revision_journal(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    with pytest.raises(VisualProductionInterrupted):
        asset_resolver_node(
            _authored_state(required=True),
            generation_provider=None,
            safety_checker=SafeChecker(),
            base_root=tmp_path,
        )

    journal = tmp_path / "run-1" / "candidate-1" / "revision-1" / "assets" / "recovery.json"
    assert journal.is_file()
    assert '"transaction_id":"revision-1"' in journal.read_text(encoding="utf-8")


def test_asset_node_optional_failure_is_unresolved_without_fake_approval(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    state = _authored_state(required=False)
    # The fixture's directive prefers generation, so no provider is a
    # deterministic offline failure.
    result = asset_resolver_node(
        state,
        generation_provider=None,
        safety_checker=SafeChecker(),
        base_root=tmp_path,
    )

    assert result["asset_manifest"].items == ()
    assert result["unresolved_optional_assets"][0].directive_id == "asset-1"
    assert result["route"] == "composition_planning"


def test_generated_provider_writes_staging_and_manifest_points_to_final_copy(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    provider = StagingAwareGenerationProvider()
    result = asset_resolver_node(
        _authored_state(),
        generation_provider=provider,
        safety_checker=SafeChecker(),
        base_root=tmp_path,
    )

    item = result["asset_manifest"].items[0]
    assert Path(item.local_path).parent.name == "generated"
    assert ".staging" not in item.local_path
    assert Path(item.local_path).read_bytes()


class MutatingSafetyChecker:
    def check(self, path, directive):
        path.write_bytes(b"mutated-after-snapshot")
        return AssetSafetyDecision(approved=True)


def test_generated_safety_mutation_cannot_leave_stale_manifest_hash(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    with pytest.raises(VisualProductionInterrupted, match="asset_resolver"):
        asset_resolver_node(
            _authored_state(),
            generation_provider=GenerationProvider(),
            safety_checker=MutatingSafetyChecker(),
            base_root=tmp_path,
        )


class MalformedProvenanceGeneratedImage(GeneratedImage):
    @property
    def internal_provenance(self):
        return None


class MalformedGenerationProvider(GenerationProvider):
    def __init__(self, field: str):
        super().__init__()
        self.field = field

    def generate(self, request, transaction_dir):
        generated = super().generate(request, transaction_dir)
        if self.field == "provenance":
            return MalformedProvenanceGeneratedImage(
                path=generated.path,
                mime_type=generated.mime_type,
                sha256=generated.sha256,
                provider=generated.provider,
                model=generated.model,
                prompt_sha256=generated.prompt_sha256,
                response_sha256=generated.response_sha256,
                generated_at=generated.generated_at,
            )
        return replace(generated, **{self.field: None})


@pytest.mark.parametrize("field", ["path", "sha256", "provider", "mime_type", "provenance"])
def test_malformed_generated_image_is_normalized_to_required_vpi_with_journal(
    tmp_path: Path, field: str
):
    from src.nodes.v4.assets import asset_resolver_node

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        asset_resolver_node(
            _authored_state(required=True),
            generation_provider=MalformedGenerationProvider(field),
            safety_checker=SafeChecker(),
            base_root=tmp_path,
        )

    assert all("AttributeError" not in error and "TypeError" not in error for error in exc_info.value.errors)
    assert (tmp_path / "run-1" / "candidate-1" / "revision-1" / "assets" / "recovery.json").is_file()


def test_generated_final_collision_never_overwrites_existing_revision_asset(tmp_path: Path):
    from src.nodes.v4.assets import asset_resolver_node

    first = asset_resolver_node(
        _authored_state(),
        generation_provider=GenerationProvider(),
        safety_checker=SafeChecker(),
        base_root=tmp_path,
    )
    final_path = Path(first["asset_manifest"].items[0].local_path)
    original = final_path.read_bytes()

    with pytest.raises(VisualProductionInterrupted, match="asset_resolver"):
        asset_resolver_node(
            _authored_state(),
            generation_provider=GenerationProvider(),
            safety_checker=SafeChecker(),
            base_root=tmp_path,
        )

    assert final_path.read_bytes() == original
