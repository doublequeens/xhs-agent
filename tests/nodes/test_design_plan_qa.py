"""Design-plan QA node: state wiring, route, and 3-strike budget (Task 9)."""

from __future__ import annotations

import pytest

from src.nodes.node_p_design_plan_qa import (
    MAX_QA_FAILURES,
    design_plan_qa_node,
    route_after_design_plan_qa,
)
from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignIssue, DesignPlanQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_director import PageDirection, VisualDirectionPlan
from src.schemas.visual_style import FamilyStyleProfile
from src.visual_design.model_retry import VisualProductionInterrupted


def _atom_set() -> ContentAtomSet:
    texts = tuple(f"第{index}页的护肤编辑重点内容。" for index in range(1, 6))
    atoms = tuple(
        ContentAtom(atom_id=f"atom-{i}", text=t, role="paragraph", sha256=sha256_text(t))
        for i, t in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256([a.model_dump(mode="json") for a in atoms]),
    )


def _direction(atom_set: ContentAtomSet) -> VisualDirectionPlan:
    from src.schemas.content_atoms import ContentFragment

    fragments = tuple(
        ContentFragment(
            fragment_id=f"fragment-{i}",
            source_atom_id=f"atom-{i}",
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for i, atom in enumerate(atom_set.atoms, start=1)
    )
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=5,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="direction",
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        typography_direction={"display": "x"},
        motifs=("oversized type",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{i}",
                sequence=i,
                purpose=f"p{i}",
                visual_job=f"job-{i}",
                fragment_ids=(f"fragment-{i}",),
            )
            for i in range(1, 6)
        ),
        asset_directives=(),
    )


def _design_plan(direction, atom_set, manifest) -> CarouselDesignPlan:
    pages = tuple(
        PageScene(
            page_id=f"page-{i}",
            sequence=i,
            background="#FFFFFF",
            elements=(
                TextElement(
                    element_id=f"text-page-{i}",
                    layer=1,
                    box=Box(x=88, y=88, width=904, height=200),
                    content_ref=f"fragment-{i}",
                    style=TextStyle(
                        font_role="body",
                        font_size=28,
                        line_height=1.3,
                        color="#1A1A1A",
                        align="left",
                        weight=400,
                    ),
                ),
            ),
        )
        for i in range(1, 6)
    )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=pages,
    )


def _style() -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family="pink_red",
        reference_image_paths=("assets/visual-families/dummy.png",),
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        font_roles={
            "display": "Source Han Serif SC",
            "heading": "Source Han Serif SC",
            "body": "Source Han Sans SC",
            "caption": "Source Han Sans SC",
        },
        composition_principles=("hierarchy", "rhythm"),
        whitespace_range=(0.18, 0.42),
        density_range=(0.45, 0.82),
        allowed_motifs=("oversized type",),
        prohibited_patterns=("thin low-contrast copy",),
    )


def _failing_plan(direction, atom_set, manifest) -> CarouselDesignPlan:
    """A plan that violates safe-margin on page-1 (deterministic QA failure)."""
    plan = _design_plan(direction, atom_set, manifest)
    pages = tuple(
        page.model_copy(
            update={
                "elements": tuple(
                    el.model_copy(update={"box": Box(x=40, y=88, width=904, height=200)})
                    if el.element_id == "text-page-1"
                    else el
                    for el in page.elements
                )
            }
        )
        if page.page_id == "page-1"
        else page
        for page in plan.pages
    )
    return plan.model_copy(update={"pages": pages})


def _state(plan, direction, atom_set, *, failures=0) -> dict:
    return {
        "carousel_design_plan": plan,
        "visual_direction_plan": direction,
        "content_atom_set": atom_set,
        "asset_manifest": AssetManifest(items=()),
        "design_plan_qa_failures": failures,
    }


def test_node_writes_qa_result_and_current_node_on_pass():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    plan = _design_plan(direction, atom_set, manifest)

    result = design_plan_qa_node(
        _state(plan, direction, atom_set),
        style_profiles={"pink_red": _style()},
    )

    qa = result["design_plan_qa_result"]
    assert isinstance(qa, DesignPlanQAResult)
    assert qa.passed is True
    assert result["current_node"] == "DESIGN_PLAN_QA"
    assert result["design_plan_qa_failures"] == 0


def test_node_writes_failing_result_and_increments_counter():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    plan = _failing_plan(direction, atom_set, manifest)

    result = design_plan_qa_node(
        _state(plan, direction, atom_set, failures=0),
        style_profiles={"pink_red": _style()},
    )

    qa = result["design_plan_qa_result"]
    assert qa.passed is False
    assert result["design_plan_qa_failures"] == 1
    assert result["current_node"] == "DESIGN_PLAN_QA"


def test_route_returns_design_reviser_on_fail():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    plan = _failing_plan(direction, atom_set, AssetManifest(items=()))
    result = design_plan_qa_node(
        _state(plan, direction, atom_set, failures=0),
        style_profiles={"pink_red": _style()},
    )
    state = {"design_plan_qa_result": result["design_plan_qa_result"]}

    assert route_after_design_plan_qa(state) == "design_reviser"


def test_route_returns_generic_scene_renderer_on_pass():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    plan = _design_plan(direction, atom_set, AssetManifest(items=()))
    result = design_plan_qa_node(
        _state(plan, direction, atom_set),
        style_profiles={"pink_red": _style()},
    )
    state = {"design_plan_qa_result": result["design_plan_qa_result"]}

    assert route_after_design_plan_qa(state) == "generic_scene_renderer"


def test_route_reads_passed_flag_directly():
    passing = DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256="0" * 64,
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )
    failing = DesignPlanQAResult(
        passed=False,
        issues=(
            DesignIssue(
                rule="geometry.safe_margin_violation",
                message="text in safe-margin exclusion",
                repair_instruction="move text inside safe area",
                page_id="page-1",
                element_id="text-page-1",
            ),
        ),
        design_plan_sha256="0" * 64,
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )

    assert route_after_design_plan_qa({"design_plan_qa_result": passing}) == "generic_scene_renderer"
    assert route_after_design_plan_qa({"design_plan_qa_result": failing}) == "design_reviser"


def test_exhausted_qa_failures_raise_resumable_interruption():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    plan = _failing_plan(direction, atom_set, manifest)
    style = {"pink_red": _style()}

    # The first MAX_QA_FAILURES - 1 failures return a failing result.
    for prior in range(MAX_QA_FAILURES - 1):
        result = design_plan_qa_node(
            _state(plan, direction, atom_set, failures=prior), style_profiles=style
        )
        assert result["design_plan_qa_failures"] == prior + 1

    # The MAX_QA_FAILURES-th failure raises, never force-pass.
    with pytest.raises(VisualProductionInterrupted) as exc_info:
        design_plan_qa_node(
            _state(
                plan,
                direction,
                atom_set,
                failures=MAX_QA_FAILURES - 1,
            ),
            style_profiles=style,
        )

    assert exc_info.value.stage == "design_plan_qa"
    assert exc_info.value.resumable is True
    assert len(exc_info.value.errors) >= 1
    assert any("safe_margin" in err for err in exc_info.value.errors)


def test_passing_resets_counter_so_no_false_interruption():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    passing_plan = _design_plan(direction, atom_set, manifest)
    style = {"pink_red": _style()}

    result = design_plan_qa_node(
        _state(passing_plan, direction, atom_set, failures=2),  # would be 3rd on a fail
        style_profiles=style,
    )

    assert result["design_plan_qa_result"].passed is True
    assert result["design_plan_qa_failures"] == 0


def test_node_requires_carousel_design_plan_in_state():
    atom_set = _atom_set()
    direction = _direction(atom_set)
    state = {
        "visual_direction_plan": direction,
        "content_atom_set": atom_set,
        "asset_manifest": AssetManifest(items=()),
    }

    with pytest.raises(ValueError, match="carousel_design_plan"):
        design_plan_qa_node(state, style_profiles={"pink_red": _style()})


def test_max_qa_failures_constant_gives_the_reviser_room():
    # The reviser resolves a handful of issues per revision; a large initial QA
    # failure set needs more than the historic 3 rounds.
    assert MAX_QA_FAILURES == 6
