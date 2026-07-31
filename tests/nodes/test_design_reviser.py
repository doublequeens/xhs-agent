from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignIssue
from src.schemas.render_qa import RenderIssue
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_critique import VisualCritiqueIssue
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.nodes.node_p_design_reviser import design_reviser_node, validate_revision
from src.visual_design.model_retry import VisualProductionInterrupted


class ScriptedVisualModel:
    def __init__(
        self,
        responses: Sequence[CarouselDesignPlan | Exception],
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate_json(
        self,
        prompt: str,
        response_model: type[CarouselDesignPlan],
        image_paths: Sequence[Path] = (),
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "response_model": response_model,
                "image_paths": tuple(image_paths),
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"第{index}页内容重点。" for index in range(1, page_count + 1)]
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def _fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def _direction_plan(
    atom_set: ContentAtomSet,
    *,
    page_directive: AssetDirective | None = None,
) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    directives = (page_directive,) if page_directive is not None else ()
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑方向",
        palette=("#F4A7BF",),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("red underlines",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"visual-job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=(
                    (page_directive.directive_id,)
                    if page_directive is not None
                    and page_directive.page_id == f"page-{index}"
                    else ()
                ),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=directives,
    )


def _asset_item() -> AssetManifestItem:
    return AssetManifestItem(
        asset_id="asset-2",
        directive_id="directive-2",
        page_id="page-2",
        source_kind="search",
        provider="pexels",
        license="Pexels License",
        local_path="/tmp/asset.png",
        width=1080,
        height=1440,
        sha256=sha256_text("asset-bytes"),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered crop",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "pexels"},
    )


def _design_plan(
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    revision: int = 0,
    extra_shape_pages: frozenset[str] = frozenset(),
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction_plan.page_sequence:
        elements: list = [
            TextElement(
                element_id=f"text-{direction_page.page_id}",
                layer=1,
                box=Box(x=80, y=120, width=920, height=160),
                content_ref=direction_page.fragment_ids[0],
                style=TextStyle(
                    font_role="heading",
                    font_size=48,
                    line_height=1.3,
                    color="#1A1A1A",
                    align="left",
                    weight=700,
                ),
            )
        ]
        approved_asset = next(
            (item for item in manifest.items if item.page_id == direction_page.page_id),
            None,
        )
        if approved_asset is not None:
            elements.append(
                ImageElement(
                    element_id=f"image-{direction_page.page_id}",
                    layer=0,
                    box=Box(x=80, y=400, width=920, height=720),
                    asset_ref=approved_asset.asset_id,
                    fit="cover",
                    focal_point=(0.5, 0.5),
                    corner_radius=0,
                )
            )
        if direction_page.page_id in extra_shape_pages:
            elements.append(
                ShapeElement(
                    element_id=f"shape-{direction_page.page_id}",
                    layer=2,
                    box=Box(x=80, y=1180, width=920, height=80),
                    shape="rectangle",
                    fill="#F4A7BF",
                )
            )
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background="#FFFFFF",
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=revision,
        pages=tuple(pages),
    )


def _state(
    design_plan: CarouselDesignPlan,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    revision_request: dict,
) -> dict:
    return {
        "carousel_design_plan": design_plan,
        "revision_request": revision_request,
        "visual_direction_plan": direction_plan,
        "content_atom_set": atom_set,
        "asset_resolution": {
            "manifest": manifest,
            "unresolved_optional_assets": (),
            "transaction_evidence": {
                "run_id": "run-1",
                "transaction_id": "tx-1",
                "transaction_root": "/tmp/tx-1",
                "journal_path": "/tmp/tx-1/recovery.json",
                "status": "complete",
            },
        },
        "domain_context": {
            "domain": "beauty",
            "profile_version": "beauty-v1",
        },
    }


def test_reviser_patches_only_named_pages_and_increments_revision():
    atom_set = _atom_set()
    directive = AssetDirective(
        directive_id="directive-2",
        page_id="page-2",
        role="skin_example",
        required=True,
        preferred_source="search",
        fallback_source="none",
        query_or_prompt="realistic skin close-up",
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    direction_plan = _direction_plan(atom_set, page_directive=directive)
    manifest = AssetManifest(items=(_asset_item(),))
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)
    # Revised plan adds a shape only on page-2 (the named page) and bumps
    # revision. All other pages stay byte-equal.
    revised = _design_plan(
        direction_plan,
        atom_set,
        manifest,
        revision=1,
        extra_shape_pages=frozenset({"page-2"}),
    )
    model = ScriptedVisualModel([revised])
    request = {
        "source": "design_plan_qa",
        "issues": (
            DesignIssue(
                rule="spacing",
                message="page-2 needs a footer accent",
                repair_instruction="add a shape band on page-2",
                page_id="page-2",
                element_id="text-page-2",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    result = design_reviser_node(
        _state(before, direction_plan, atom_set, manifest, revision_request=request),
        model=model,
    )

    after = result["carousel_design_plan"]
    assert after.revision == 1
    after.validate_bindings(direction_plan, atom_set, manifest)
    # Unnamed pages preserved verbatim.
    page_by_id_before = {page.page_id: page for page in before.pages}
    for page in after.pages:
        if page.page_id != "page-2":
            assert page == page_by_id_before[page.page_id]
    # Named page changed (now carries a shape).
    revised_page_2 = next(page for page in after.pages if page.page_id == "page-2")
    assert any(element.kind == "shape" for element in revised_page_2.elements)


def test_reviser_preserves_hashes_and_family_via_validate_revision():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=2)
    revised = before.model_copy(update={"revision": 3})

    validate_revision(before, revised)


def test_validate_revision_rejects_changed_content_hash():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest)
    revised = before.model_copy(update={"content_atom_set_sha256": "1" * 64})

    with pytest.raises(ValueError, match="content binding"):
        validate_revision(before, revised)


def test_validate_revision_rejects_changed_asset_hash():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest)
    revised = before.model_copy(update={"asset_manifest_sha256": "1" * 64})

    with pytest.raises(ValueError, match="asset binding"):
        validate_revision(before, revised)


def test_validate_revision_rejects_family_or_page_sequence_change():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest)
    # Swap page IDs to simulate a family/sequence change.
    swapped_pages = tuple(reversed(before.pages))
    revised = before.model_copy(update={"pages": swapped_pages})

    with pytest.raises(ValueError, match="visual_director"):
        validate_revision(before, revised)


def test_reviser_rejects_revision_referencing_unapproved_asset():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)

    # Construct a "revised" plan whose page-2 image points at an asset that is
    # not in the approved manifest.
    invalid_pages = list(before.pages)
    invalid_pages[1] = invalid_pages[1].model_copy(
        update={
            "elements": (
                ImageElement(
                    element_id="image-page-2",
                    layer=0,
                    box=Box(x=80, y=400, width=920, height=720),
                    asset_ref="not-in-manifest",
                    fit="cover",
                    focal_point=(0.5, 0.5),
                    corner_radius=0,
                ),
                *invalid_pages[1].elements,
            )
        }
    )
    invalid = before.model_copy(
        update={"pages": tuple(invalid_pages), "revision": 1}
    )
    valid = before.model_copy(update={"revision": 1})
    model = ScriptedVisualModel([invalid, valid])
    request = {
        "source": "render_qa",
        "issues": (
            RenderIssue(
                rule="geometry",
                message="page-2 image crop is off",
                repair_instruction="rework page-2 image placement",
                page_id="page-2",
                element_id="image-page-2",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    result = design_reviser_node(
        _state(before, direction_plan, atom_set, manifest, revision_request=request),
        model=model,
    )

    assert result["carousel_design_plan"] == valid
    assert "not in" in str(model.calls[1]["prompt"]).lower() or "asset" in str(
        model.calls[1]["prompt"]
    ).lower()


def test_reviser_routes_to_visual_director_when_feedback_requires_replan():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)
    model = ScriptedVisualModel([])  # Should not be called.
    request = {
        "source": "visual_critic",
        "issues": (
            VisualCritiqueIssue(
                rule="family_consistency",
                message="family no longer fits content; replan family",
                revision_instruction="route back to visual director to pick a new family",
                page_id="page-1",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    result = design_reviser_node(
        _state(before, direction_plan, atom_set, manifest, revision_request=request),
        model=model,
    )

    assert result["route"] == "visual_director"
    assert result["current_node"] == "DESIGN_REVISER"
    assert model.calls == []


def test_reviser_routes_to_director_when_issue_names_missing_page():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)
    model = ScriptedVisualModel([])
    request = {
        "source": "human_review",
        "issues": (
            DesignIssue(
                rule="coverage",
                message="add a page summarizing the routine",
                repair_instruction="add page page-9 for summary",
                page_id="page-9",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    result = design_reviser_node(
        _state(before, direction_plan, atom_set, manifest, revision_request=request),
        model=model,
    )

    assert result["route"] == "visual_director"
    assert model.calls == []


def test_reviser_retries_invalid_output_at_most_three_times():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)
    valid = before.model_copy(update={"revision": 1})
    invalid = valid.model_copy(update={"content_atom_set_sha256": "0" * 64})
    model = ScriptedVisualModel([invalid, valid])
    request = {
        "source": "design_plan_qa",
        "issues": (
            DesignIssue(
                rule="spacing",
                message="tighten page-1 spacing",
                repair_instruction="reduce page-1 padding",
                page_id="page-1",
                element_id="text-page-1",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    result = design_reviser_node(
        _state(before, direction_plan, atom_set, manifest, revision_request=request),
        model=model,
    )

    assert result["carousel_design_plan"] == valid
    assert len(model.calls) == 2
    assert "content binding" in str(model.calls[1]["prompt"])


def test_reviser_three_failures_raise_resumable_interruption():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = AssetManifest(items=())
    before = _design_plan(direction_plan, atom_set, manifest, revision=0)
    invalid = before.model_copy(update={"revision": 1, "content_atom_set_sha256": "0" * 64})
    model = ScriptedVisualModel([invalid, invalid, invalid])
    request = {
        "source": "design_plan_qa",
        "issues": (
            DesignIssue(
                rule="spacing",
                message="tighten page-1 spacing",
                repair_instruction="reduce page-1 padding",
                page_id="page-1",
            ).model_dump(mode="json"),
        ),
        "current_revision": 0,
    }

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        design_reviser_node(
            _state(before, direction_plan, atom_set, manifest, revision_request=request),
            model=model,
        )

    assert exc_info.value.stage == "design_reviser"
    assert len(model.calls) == 3
