from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.schemas.content_atoms import ContentFragment
from src.schemas.visual_director import AssetDirective, PageDirection, VisualDirectionPlan
from src.visual_ai.protocols import GeneratedImage


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (300, 400), (180, 130, 120)).save(output, format="PNG")
    return output.getvalue()


class Generator:
    def generate(self, request, transaction_dir):
        raw = _image_bytes()
        transaction_dir.mkdir(parents=True, exist_ok=True)
        path = transaction_dir / "image.png"
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
            generated_at="2026-07-31T12:00:00+00:00",
        )


class Safe:
    def check(self, path, directive):
        from src.asset_resolver.resolver import AssetSafetyDecision

        return AssetSafetyDecision(approved=True, unwanted_text=False)


def _plan() -> VisualDirectionPlan:
    fragment = ContentFragment(
        fragment_id="fragment-1",
        source_atom_id="atom-1",
        text="出现持续刺痛、明显泛红或第二天仍然紧绷时",
        start=0,
        end=len("出现持续刺痛、明显泛红或第二天仍然紧绷时"),
    )
    directive = AssetDirective(
        directive_id="asset-1",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt="真实风格的泛红皮肤特写",
        negative_constraints=("embedded text", "disclaimer"),
        orientation="portrait",
        min_width=300,
        min_height=400,
    )
    pages = tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"purpose-{index}",
            visual_job=f"visual-job-{index}",
            fragment_ids=("fragment-1",) if index == 1 else (f"fragment-{index}",),
            asset_directive_ids=("asset-1",) if index == 1 else (),
        )
        for index in range(1, 6)
    )
    fragments = (fragment,) + tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=f"atom-{index}",
            text=f"内容{index}",
            start=0,
            end=3,
        )
        for index in range(2, 6)
    )
    return VisualDirectionPlan(
        template_family="soft_pink",
        page_count=5,
        content_atom_set_sha256="a" * 64,
        art_direction="editorial",
        palette=("#ffffff",),
        typography_direction={"display": "serif"},
        motifs=("line",),
        content_fragments=fragments,
        page_sequence=pages,
        asset_directives=(directive,),
    )


def test_node_returns_manifest_optional_results_and_transaction_evidence(
    tmp_path: Path,
) -> None:
    from src.nodes.node_p_asset_resolver import asset_resolver_node

    result = asset_resolver_node(
        {
            "visual_direction_plan": _plan(),
            "topic_generation_trace": {"run_id": "trace-42"},
        },
        search_provider=None,
        generation_provider=Generator(),
        safety_checker=Safe(),
        transaction_root=tmp_path,
        transaction_id="tx-node",
    )

    assert result["asset_manifest"].items[0].directive_id == "asset-1"
    assert result["unresolved_optional_assets"] == ()
    assert result["asset_transaction_evidence"].transaction_id == "tx-node"
    assert result["current_node"] == "ASSET_RESOLVER"
    assert "review_status" not in result
