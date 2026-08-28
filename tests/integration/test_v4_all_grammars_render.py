"""Real local-Chromium render gate for the five additional v4 grammars.

Each grammar's positive fixture drives a full five-page world through the
real deterministic compiler, Q2 aggregation, the real Chromium renderer and
the independent Q3 evaluator.  Skips when the local sandbox blocks Chromium.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.nodes.v4.design_qa import aggregate_design_qa
from src.nodes.v4.layout import aggregate_layout_plan
from src.rendering.scene.v4_adapter import render_v4_revision
from src.visual_design.v4.authoring_qa import evaluate_authoring
from src.visual_design.v4.render_qa import evaluate_v4_render
from src.visual_design.v4.semantic_qa import evaluate_semantic_model
from src.visual_design.v4.tokens import get_family_tokens
from src.visual_runtime.artifact_identity import (
    ArtifactIdentity,
    ensure_artifact_paths,
    resolve_artifact_paths,
)

from tests.visual_design.v4.test_grammar_cases import (
    CASES_ROOT,
    REMAINING_GRAMMAR_IDS,
)


def _paged_world(case: dict, grammar_id: str, task_kind: str, tmp_path: Path):
    """Five pages with globally exact-once fragment ownership."""

    from src.nodes.v4.composition import build_layout_program
    from src.schemas.assets import AssetManifest
    from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
    from src.schemas.v4.direction import (
        CarouselNarrativeV4,
        NarrativeBeatV4,
        PageBriefSetV4,
        PageBriefV4,
        VisualDirectionPlanV4,
    )
    from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
    from src.visual_design.v4.compiler import (
        LayoutCompilerInputsV4,
        compile_layout,
    )

    # Every page needs a measurable heading hierarchy for Q2: each page owns
    # exactly one heading fragment and one body fragment (globally exact-once).
    # Headings stay short Chinese-only so display-size lines stay legal; the
    # body slots cycle the case's non-heading fragment texts.
    body_specs = [
        item for item in case["fragments"] if item.get("role") != "heading"
    ] or [{"text": "保持节奏与留白的补充说明", "role": "paragraph"}]
    fragments: list[dict] = []
    for sequence in range(1, 6):
        body_spec = body_specs[(sequence - 1) % len(body_specs)]
        fragments.append({"text": f"第{sequence}页要点", "role": "heading"})
        fragments.append({"text": body_spec["text"], "role": "paragraph"})
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
    atom_payload = {"projection_sha256": "1" * 64, "atoms": tuple(atoms)}
    atoms_set = ContentAtomSetV4(
        **atom_payload, canonical_sha256=canonical_sha256_v4(atom_payload)
    )
    semantic_payload = {
        "content_atom_set_sha256": atoms_set.canonical_sha256,
        "fragments": tuple(fragment_models),
        "groups": (),
    }
    semantic = SemanticContentModelV4(
        **semantic_payload, canonical_sha256=canonical_sha256_v4(semantic_payload)
    )

    density = case["density_budget"]
    count = 5
    beats = []
    pages = []
    # Q1 forbids adjacent pages repeating one composition: alternate the
    # grammar under test with a sparse-compile-friendly partner grammar.
    partner_grammar = (
        "summary_closing"
        if grammar_id in {"diagnostic_matrix", "evidence_card"}
        else "diagnostic_matrix"
    )
    partner_kind = "summary" if partner_grammar == "summary_closing" else "diagnosis"
    odd_density = "medium" if density == "low" else density
    for sequence in range(1, count + 1):
        page_grammar = grammar_id if sequence % 2 == 1 else partner_grammar
        page_kind = task_kind if sequence % 2 == 1 else partner_kind
        refs = (
            f"fragment-{(sequence - 1) * 2}",   # heading
            f"fragment-{(sequence - 1) * 2 + 1}",  # body
        )
        beats.append(
            NarrativeBeatV4(
                beat_id=f"beat-{sequence}",
                sequence=sequence,
                task_kind=page_kind,
                fragment_refs=refs,
                task="semantic task",
            )
        )
        directives = ()
        if case.get("with_asset") and sequence == 1:
            from src.schemas.v4.direction import AssetDirectiveV4

            directives = (
                AssetDirectiveV4(
                    directive_id="directive-1",
                    page_id=f"page-{sequence}",
                    role="object",
                    purpose="supporting",
                    supports_fragment_refs=refs,
                    required=True,
                    preferred_source="search",
                    query_or_prompt="text-free texture",
                    orientation="landscape",
                ),
            )
        page_payload = {
            "page_id": f"page-{sequence}",
            "sequence": sequence,
            "narrative_role": page_kind,
            "beat_ref": f"beat-{sequence}",
            "fragment_refs": refs,
            "visual_priority": refs,
            "density_budget": odd_density,
            "preferred_compositions": (page_grammar,),
            "forbidden_patterns": (),
            "asset_directives": directives,
            "continuity_with_previous": "none",
        }
        pages.append(
            PageBriefV4(
                **page_payload, canonical_sha256=canonical_sha256_v4(page_payload)
            )
        )
    narrative_payload = {
        "template_family": "pink_red",
        "page_count": count,
        "beats": tuple(beats),
        "density_curve": (density,) * count,
        "variation_strategy": "stable",
        "continuity_strategy": "stable",
        "art_direction": "editorial",
        "content_atom_set_sha256": atoms_set.canonical_sha256,
    }
    narrative = CarouselNarrativeV4(
        **narrative_payload, canonical_sha256=canonical_sha256_v4(narrative_payload)
    )
    page_set_payload = {
        "page_count": count,
        "pages": tuple(pages),
        "template_family": "pink_red",
        "content_atom_set_sha256": atoms_set.canonical_sha256,
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
        "page_count": count,
        "content_atom_set_sha256": atoms_set.canonical_sha256,
        "semantic_content_model_sha256": semantic.canonical_sha256,
        "narrative_sha256": narrative.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
    }
    direction = VisualDirectionPlanV4(
        **direction_payload, canonical_sha256=canonical_sha256_v4(direction_payload)
    )
    return atoms_set, semantic, direction, narrative, page_set


def _q3_issue_summary(result, manifest) -> str:
    issues = [
        f"{issue.code}@{getattr(issue, 'page_id', '-')}:{getattr(issue, 'element_id', None) or '-'}"
        for issue in getattr(result, "issues", ())
    ]
    return f"failed Q3: {issues[:8]} pages={len(manifest.pages)}"


@pytest.mark.parametrize("grammar_id", REMAINING_GRAMMAR_IDS)
def test_v4_all_grammars_render_is_real_chromium_and_q3_verified(
    grammar_id, tmp_path
):
    payload = json.loads((CASES_ROOT / f"{grammar_id}.json").read_text("utf-8"))
    task_kind = payload["task_kind"]
    case = next(item for item in payload["cases"] if item["kind"] == "positive")
    atoms, semantic, direction, narrative, page_set = _paged_world(
        case, grammar_id, task_kind, tmp_path
    )
    from src.schemas.assets import AssetManifest, AssetManifestItem
    from src.schemas.content_lock import ContentLock

    paths = ensure_artifact_paths(
        resolve_artifact_paths(
            tmp_path, ArtifactIdentity("run-a", "candidate-a", "revision-1")
        )
    )
    manifest = AssetManifest(items=())
    if case.get("with_asset"):
        buffer = BytesIO()
        Image.new("RGB", (1200, 800), "#F4C7CF").save(buffer, format="PNG")
        asset_bytes = buffer.getvalue()
        asset_path = paths.asset_root / "fixture.png"
        asset_path.write_bytes(asset_bytes)
        manifest = AssetManifest(
            items=(
                AssetManifestItem(
                    asset_id="asset-1",
                    directive_id="directive-1",
                    page_id="page-1",
                    source_kind="search",
                    provider="fixture-provider",
                    license="fixture-license",
                    local_path=str(asset_path),
                    width=1200,
                    height=800,
                    sha256=hashlib.sha256(asset_bytes).hexdigest(),
                    subject_focal_point=(0.5, 0.5),
                    crop_guidance="center",
                    security_status="approved",
                    human_decision="pending",
                    run_id="run-a",
                    transaction_id="revision-1",
                    internal_provenance={"source": "fixture"},
                ),
            )
        )

    from src.nodes.v4.composition import build_layout_program
    from src.visual_design.v4.compiler import (
        LayoutCompilerInputsV4,
        compile_layout,
    )

    compiled = tuple(
        compile_layout(
            build_layout_program(
                page,
                grammar_id=page.preferred_compositions[0],
                family="pink_red",
                narrative=narrative,
            ),
            LayoutCompilerInputsV4(
                page_brief=page,
                semantic_content_model=semantic,
                content_atom_set=atoms,
                asset_manifest=manifest,
                candidate_id="candidate-a",
                revision=1,
                run_id="run-a",
                visual_direction_plan=direction,
            ),
        )
        for page in page_set.pages
    )
    from src.schemas.v4.content import canonical_sha256_v4 as _csha

    case_fragments = list(case["fragments"])
    lock_payload = {
        "focus_keyword": "护肤",
        "topic": "屏障修护",
        "topic_id": "topic-1",
        "angle": "温和修护",
        "angle_id": "angle-1",
        "target_group": "干敏肌",
        "core_pain": "屏障受损",
        "title": case_fragments[0]["text"],
        "cover_copy": case_fragments[0]["text"],
        "first_screen_promise": "三步见效",
        "content": "\n\n".join(item["text"] for item in case_fragments),
        "hashtags": ["护肤"],
        "content_atom_set_sha256": atoms.canonical_sha256,
    }
    lock = ContentLock(**lock_payload, canonical_sha256=_csha(lock_payload))
    q0 = evaluate_semantic_model(atoms, semantic, content_lock=lock)
    q1 = evaluate_authoring(
        page_set,
        semantic,
        narrative,
        direction,
        content_lock=lock,
        content_atom_set=atoms,
    )
    plan = aggregate_layout_plan(
        compiled,
        content_atom_set=atoms,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        asset_manifest=manifest,
        family_tokens=get_family_tokens("pink_red"),
        revision=1,
        candidate_id="candidate-a",
        run_id="run-a",
        visual_direction_plan=direction,
    )
    qa = aggregate_design_qa(
        semantic_qa=q0,
        authoring_qa=q1,
        carousel_design_plan=plan,
        content_atom_set=atoms,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=manifest,
    )
    assert qa.passed, f"Q2 failed for {grammar_id}"

    try:
        rendered = render_v4_revision(
            design_plan=plan,
            design_plan_qa_result=qa,
            content_atom_set=atoms,
            content_lock=lock,
            semantic_content_model=semantic,
            page_brief_set=page_set,
            visual_direction_plan=direction,
            asset_manifest=manifest,
            family_tokens="pink_red",
            artifact_paths=paths,
        )
    except Exception as exc:
        message = str(exc.__cause__ or exc)
        if "MachPortRendezvousServer" in message:
            pytest.skip(f"Chromium sandbox launch blocked: {message}")
        raise

    result = evaluate_v4_render(
        render_manifest=rendered.manifest,
        design_plan=plan,
        design_plan_qa_result=qa,
        content_atom_set=atoms,
        content_lock=lock,
        semantic_content_model=semantic,
        page_brief_set=page_set,
        visual_direction_plan=direction,
        asset_manifest=manifest,
        family_tokens="pink_red",
        artifact_paths=paths,
    )
    assert result.passed is True, _q3_issue_summary(result, rendered.manifest)
    assert all(
        page.width == 1080 and page.height == 1440 for page in rendered.manifest.pages
    )
    assert len(rendered.manifest.pages) == len(page_set.pages)
