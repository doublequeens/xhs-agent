from __future__ import annotations

import hashlib
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
