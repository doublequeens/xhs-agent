"""Fixture-driven compile cases for the five additional v4 Grammars.

Each ``tests/fixtures/llm_scene_v4/grammar_cases/<grammar>.json`` carries one
positive, one boundary and one impossible case.  Positive and boundary cases
must compile to a safe flat scene through the real deterministic compiler;
impossible cases must fail with the approved structured error instead of
shrinking fonts or truncating copy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nodes.v4.composition import build_layout_program
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AssetDirectiveV4,
    CarouselNarrativeV4,
    NarrativeBeatV4,
    PageBriefSetV4,
    PageBriefV4,
    VisualDirectionPlanV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.compiler import (
    COMPILATION_ERROR_CODES_V4,
    LayoutCompilationError,
    LayoutCompilerInputsV4,
    compile_layout,
)

CASES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "llm_scene_v4" / "grammar_cases"
REMAINING_GRAMMAR_IDS = (
    "diagnostic_matrix",
    "checklist",
    "evidence_card",
    "image_annotation",
    "summary_closing",
)


def load_grammar_cases(grammar_id: str) -> list[dict]:
    path = CASES_ROOT / f"{grammar_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["grammar_id"] == grammar_id
    return payload["cases"]


def _world(case: dict, grammar_id: str, task_kind: str):
    fragments = case["fragments"]
    atoms = []
    fragment_models = []
    for index, spec in enumerate(fragments):
        text = spec["text"]
        atom_payload = {
            "atom_id": f"atom-{index}",
            "source_unit_id": f"unit-{index}",
            "source_projection_sha256": "1" * 64,
            "source_field": "content",
            "raw_start": 0,
            "raw_end": len(text),
            "raw_slice_sha256": "2" * 64,
            "text": text,
            "role": spec["role"],
        }
        atoms.append(
            ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload))
        )
        fragment_models.append(
            SemanticFragmentV4(
                fragment_id=f"fragment-{index}",
                source_atom_id=f"atom-{index}",
                start=0,
                end=len(text),
                exact_text=text,
                semantic_role=spec["role"],
                sequence_index=index,
            )
        )
    atom_payload = {
        "projection_sha256": "1" * 64,
        "atoms": tuple(atoms),
    }
    atom_set = ContentAtomSetV4(
        **atom_payload, canonical_sha256=canonical_sha256_v4(atom_payload)
    )
    semantic_payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": tuple(fragment_models),
        "groups": (),
    }
    semantic = SemanticContentModelV4(
        **semantic_payload, canonical_sha256=canonical_sha256_v4(semantic_payload)
    )

    refs = tuple(f"fragment-{index}" for index in range(len(fragments)))
    directives = ()
    if case.get("with_asset"):
        directives = (
            AssetDirectiveV4(
                directive_id="directive-1",
                page_id="page-1",
                role="object",
                purpose="supporting",
                supports_fragment_refs=("fragment-0",),
                required=True,
                preferred_source="search",
                query_or_prompt="text-free texture",
                orientation="landscape",
            ),
        )
    page_payload = {
        "page_id": "page-1",
        "sequence": 1,
        "narrative_role": "typed role",
        "beat_ref": "beat-1",
        "fragment_refs": refs,
        "visual_priority": refs,
        "density_budget": case["density_budget"],
        "preferred_compositions": (grammar_id,),
        "forbidden_patterns": (),
        "asset_directives": directives,
        "continuity_with_previous": "none",
    }
    page = PageBriefV4(**page_payload, canonical_sha256=canonical_sha256_v4(page_payload))
    density = case["density_budget"]
    beats = tuple(
        NarrativeBeatV4(
            beat_id=f"beat-{index}",
            sequence=index,
            task_kind=task_kind,
            fragment_refs=refs,
            task="semantic task",
        )
        for index in range(1, 6)
    )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": 5,
        "beats": beats,
        "density_curve": (density,) * 5,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
        "content_atom_set_sha256": atom_set.canonical_sha256,
    }
    narrative = CarouselNarrativeV4(
        **narrative_payload, canonical_sha256=canonical_sha256_v4(narrative_payload)
    )
    page_payloads = []
    for sequence in range(1, 6):
        clone = page.model_dump(mode="python")
        clone.update(
            {"page_id": f"page-{sequence}", "sequence": sequence, "beat_ref": f"beat-{sequence}"}
        )
        clone.pop("canonical_sha256", None)
        page_payloads.append(clone)
    page_set_payload = {
        "page_count": 5,
        "pages": tuple(
            PageBriefV4(**clone, canonical_sha256=canonical_sha256_v4(clone))
            for clone in page_payloads
        ),
        "template_family": "pink_red",
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
    }
    page_set = PageBriefSetV4(
        **page_set_payload, canonical_sha256=canonical_sha256_v4(page_set_payload)
    )
    direction_payload = {
        "semantic_content_model": semantic,
        "narrative": narrative,
        "page_brief_set": page_set,
        "template_family": "pink_red",
        "page_count": 5,
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    direction = VisualDirectionPlanV4(
        **direction_payload, canonical_sha256=canonical_sha256_v4(direction_payload)
    )
    program = build_layout_program(
        page, grammar_id=grammar_id, family="pink_red", narrative=narrative
    )
    manifest = AssetManifest(items=())
    if case.get("with_asset"):
        manifest = AssetManifest(
            items=(
                AssetManifestItem(
                    asset_id="asset-1",
                    directive_id="directive-1",
                    page_id="page-1",
                    source_kind="search",
                    provider="fixture-provider",
                    license="fixture-license",
                    local_path="/tmp/fixture.png",
                    width=1200,
                    height=800,
                    sha256="3" * 64,
                    subject_focal_point=(0.5, 0.5),
                    crop_guidance="center",
                    security_status="approved",
                    human_decision="pending",
                    run_id="run-1",
                    transaction_id="tx-1",
                    internal_provenance={"source": "fixture"},
                ),
            )
        )
    inputs = LayoutCompilerInputsV4(
        page_brief=page,
        semantic_content_model=semantic,
        content_atom_set=atom_set,
        asset_manifest=manifest,
        candidate_id="candidate-a",
        revision=3,
        run_id="run-a",
        visual_direction_plan=direction,
    )
    return program, inputs


@pytest.mark.parametrize("grammar_id", REMAINING_GRAMMAR_IDS)
def test_each_grammar_has_positive_boundary_and_failure_fixture(grammar_id):
    cases = load_grammar_cases(grammar_id)
    assert {case["kind"] for case in cases} == {"positive", "boundary", "impossible"}
    for case in cases:
        assert case["fragments"], case["kind"]
    impossible = next(case for case in cases if case["kind"] == "impossible")
    assert impossible["expect_code"] in COMPILATION_ERROR_CODES_V4


@pytest.mark.parametrize("grammar_id", REMAINING_GRAMMAR_IDS)
@pytest.mark.parametrize("kind", ("positive", "boundary"))
def test_positive_and_boundary_cases_compile_to_safe_flat_scenes(grammar_id, kind):
    cases = load_grammar_cases(grammar_id)
    task_kind = json.loads((CASES_ROOT / f"{grammar_id}.json").read_text("utf-8"))["task_kind"]
    case = next(item for item in cases if item["kind"] == kind)
    program, inputs = _world(case, grammar_id, task_kind)

    result = compile_layout(program, inputs)

    assert result.scene.sequence == 1
    text_refs = tuple(
        item.content_ref for item in result.scene.elements if item.kind == "text"
    )
    assert text_refs == tuple(item.fragment_ref for item in program.fragment_placements)
    for element in result.scene.elements:
        if element.kind in {"text", "image", "shape", "icon"}:
            assert element.box.x >= 80
            assert element.box.y >= 80
            assert element.box.x + element.box.width <= 1000
            assert element.box.y + element.box.height <= 1360


@pytest.mark.parametrize("grammar_id", REMAINING_GRAMMAR_IDS)
def test_impossible_cases_fail_with_structured_error_not_truncation(grammar_id):
    cases = load_grammar_cases(grammar_id)
    task_kind = json.loads((CASES_ROOT / f"{grammar_id}.json").read_text("utf-8"))["task_kind"]
    case = next(item for item in cases if item["kind"] == "impossible")
    program, inputs = _world(case, grammar_id, task_kind)

    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(program, inputs)
    assert exc.value.code == case["expect_code"]
    assert exc.value.code in COMPILATION_ERROR_CODES_V4
