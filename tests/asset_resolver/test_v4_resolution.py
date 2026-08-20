from __future__ import annotations

from pathlib import Path

import pytest

from src.asset_resolver.v4 import adapt_asset_directive_v4
from src.schemas.v4.direction import AssetDirectiveV4


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

    asset_root = tmp_path / "run" / "candidate" / "revision" / "assets"
    result = resolve_v4_asset_directives(
        directives=(),
        run_id="run",
        transaction_id="revision",
        transaction_directory=asset_root,
        search_provider=object(),
        generation_provider=object(),
    )

    assert result.manifest.items == ()
    assert result.transaction_evidence.run_id == "run"
    assert result.transaction_evidence.transaction_id == "revision"
    assert Path(result.transaction_evidence.transaction_root) == asset_root


def test_v4_resolver_rejects_directory_not_bound_to_run_revision(tmp_path: Path):
    from src.asset_resolver.v4 import resolve_v4_asset_directives

    with pytest.raises(RuntimeError, match="bound"):
        resolve_v4_asset_directives(
            directives=(),
            run_id="run",
            transaction_id="revision",
            transaction_directory=tmp_path / "unrelated",
        )
