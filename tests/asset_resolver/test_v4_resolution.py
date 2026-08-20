from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.asset_resolver.v4 import adapt_asset_directive_v4
from src.asset_resolver.resolver import AssetResolutionError, resolve_asset_directives
from src.schemas.v4.direction import AssetDirectiveV4
from src.schemas.visual_director import AssetDirective
from src.visual_ai.protocols import GeneratedImage
from src.visual_design.model_retry import VisualProductionInterrupted
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
    revalidate_artifact_paths,
)


def test_v4_adapter_maps_only_approved_provider_fields():
    directive = AssetDirectiveV4(
        directive_id="asset-1",
        page_id="page-2",
        role="skin_example",
        purpose="evidence",
        supports_fragment_refs=("fragment-2",),
        required=True,
        preferred_source="search_then_generate",
        fallback_source="none",
        query_or_prompt="text-free irritated skin close-up",
        negative_constraints=("watermark", "logo"),
        orientation="portrait",
        resolution=(1200, 1600),
    )

    adapted = adapt_asset_directive_v4(directive)

    assert adapted.model_dump(mode="python") == {
        "directive_id": "asset-1",
        "page_id": "page-2",
        "role": "skin_example",
        "required": True,
        "preferred_source": "search",
        "fallback_source": "generate",
        "query_or_prompt": "text-free irritated skin close-up",
        "negative_constraints": ("watermark", "logo"),
        "orientation": "portrait",
        "min_width": 1200,
        "min_height": 1600,
    }
    assert "purpose" not in adapted.model_dump()
    assert "supports_fragment_refs" not in adapted.model_dump()


def test_v4_adapter_rejects_unknown_or_non_v4_input():
    with pytest.raises(ValueError):
        adapt_asset_directive_v4({"directive_id": "asset-1", "page_id": "page-1"})


def test_v4_resolver_uses_explicit_asset_directory_without_transaction_id_rewrite(tmp_path: Path):
    from src.asset_resolver.v4 import resolve_v4_asset_directives

    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("run", "candidate", "revision"),
        )
    )
    result = resolve_v4_asset_directives(
        directives=(),
        run_id="run",
        transaction_id="revision",
        artifact_paths=paths,
        search_provider=object(),
        generation_provider=object(),
    )

    assert result.manifest.items == ()
    assert result.transaction_evidence.run_id == "run"
    assert result.transaction_evidence.transaction_id == "revision"
    assert Path(result.transaction_evidence.transaction_root) == paths.asset_root


def test_v4_resolver_rejects_bare_transaction_directory(tmp_path: Path):
    from src.asset_resolver.v4 import resolve_v4_asset_directives

    with pytest.raises(AssetResolutionError, match="artifact_paths|identity"):
        resolve_v4_asset_directives(
            directives=(),
            run_id="run",
            transaction_id="revision",
            transaction_directory=tmp_path / "run" / "candidate" / "revision" / "assets",
        )


def test_shared_resolver_rejects_bare_transaction_directory(tmp_path: Path):
    with pytest.raises(AssetResolutionError, match="artifact_paths|bare"):
        resolve_asset_directives(
            directives=(),
            run_id="run",
            transaction_id="revision",
            transaction_directory=tmp_path / "assets",
        )
    assert not tmp_path.exists() or not tuple(tmp_path.iterdir())


def test_artifact_paths_revalidate_candidate_and_base_identity(tmp_path: Path):
    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("run", "candidate", "revision"),
        )
    )
    assert revalidate_artifact_paths(paths) == paths

    drifted = replace(
        paths,
        identity=ArtifactIdentity("run", "other-candidate", "revision"),
    )
    with pytest.raises(ValueError, match="identity|path"):
        revalidate_artifact_paths(drifted)


def test_legacy_transaction_traversal_has_zero_filesystem_side_effect(tmp_path: Path):
    root = tmp_path / "transactions"
    with pytest.raises(AssetResolutionError, match="transaction_id"):
        resolve_asset_directives(
            directives=(),
            transaction_root=root,
            transaction_id="../escaped",
            run_id="run",
        )
    assert not root.exists()
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize(
    ("source", "preferred", "fallback"),
    [
        ("search_then_generate", "search", "generate"),
        ("generate_then_search", "generate", "search"),
    ],
)
def test_composite_sources_expand_to_deterministic_pairs(source, preferred, fallback):
    directive = AssetDirectiveV4(
        directive_id="asset-1",
        page_id="page-1",
        role="texture",
        purpose="texture",
        supports_fragment_refs=("fragment-1",),
        required=False,
        preferred_source=source,
        fallback_source="none",
        query_or_prompt="texture",
    )
    adapted = adapt_asset_directive_v4(directive)
    assert (adapted.preferred_source, adapted.fallback_source) == (preferred, fallback)


def test_composite_source_with_explicit_different_fallback_is_rejected():
    directive = AssetDirectiveV4(
        directive_id="asset-1",
        page_id="page-1",
        role="texture",
        purpose="texture",
        supports_fragment_refs=("fragment-1",),
        required=False,
        preferred_source="search_then_generate",
        fallback_source="search",
        query_or_prompt="texture",
    )
    with pytest.raises(ValueError, match="ambiguous"):
        adapt_asset_directive_v4(directive)


def test_v4_resolver_rejects_evidence_identity_drift(tmp_path: Path):
    from src.asset_resolver.v4 import resolve_v4_asset_directives

    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path,
            ArtifactIdentity("run", "candidate", "revision"),
        )
    )
    with pytest.raises(RuntimeError, match="identity"):
        resolve_v4_asset_directives(
            directives=(),
            run_id="other-run",
            transaction_id="revision",
            artifact_paths=paths,
        )


def test_required_journal_close_failure_preserves_primary_errors(tmp_path: Path, monkeypatch):
    from src.asset_resolver import resolver as module

    directive = AssetDirective(
        directive_id="asset-1",
        page_id="page-1",
        role="texture",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt="texture",
        orientation="any",
        min_width=1080,
        min_height=1440,
    )
    original_close = module.os.close
    calls: list[int] = []

    def fail_close(fd: int):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError("journal close sentinel")
        return original_close(fd)

    monkeypatch.setattr(module.os, "close", fail_close)
    with pytest.raises(VisualProductionInterrupted) as exc_info:
        resolve_asset_directives(
            directives=(directive,),
            transaction_root=tmp_path / "transactions",
            transaction_id="tx-1",
            run_id="run-1",
        )
    assert exc_info.value.errors == (
        "generate source requested without a generation provider",
    )
    assert isinstance(exc_info.value.__cause__, AssetResolutionError)
    assert len(calls) == len(set(calls))


def test_legacy_transaction_reentry_replaces_final_after_existing_journal(tmp_path: Path):
    class Provider:
        def generate(self, request, transaction_dir):
            transaction_dir.mkdir(parents=True, exist_ok=True)
            output = BytesIO()
            Image.new("RGB", (300, 400), (180, 130, 120)).save(output, format="PNG")
            raw = output.getvalue()
            path = transaction_dir / "generated.png"
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            return GeneratedImage(
                path=path,
                mime_type="image/png",
                sha256=digest,
                provider="gemini",
                model="offline-test",
                prompt_sha256=request.prompt_sha256,
                response_sha256=digest,
                generated_at="2026-08-20T00:00:00+00:00",
            )

    class SafeChecker:
        def check(self, path, directive):
            from src.asset_resolver.resolver import AssetSafetyDecision

            return AssetSafetyDecision(approved=True)

    directive = AssetDirective(
        directive_id="asset-1",
        page_id="page-1",
        role="texture",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt="texture",
        orientation="portrait",
        min_width=300,
        min_height=400,
    )
    root = tmp_path / "transactions"
    first = resolve_asset_directives(
        directives=(directive,),
        run_id="run-1",
        transaction_root=root,
        transaction_id="tx-1",
        generation_provider=Provider(),
        safety_checker=SafeChecker(),
    )
    final_path = Path(first.manifest.items[0].local_path)
    original = final_path.read_bytes()
    (root / "tx-1" / "recovery.json").write_text("stale recovery", encoding="utf-8")

    second = resolve_asset_directives(
        directives=(directive,),
        run_id="run-1",
        transaction_root=root,
        transaction_id="tx-1",
        generation_provider=Provider(),
        safety_checker=SafeChecker(),
    )

    assert second.manifest.items[0].sha256 == first.manifest.items[0].sha256
    assert final_path.read_bytes() == original
    assert (root / "tx-1" / "recovery.json").read_text(encoding="utf-8") == "stale recovery"
