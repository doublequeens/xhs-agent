"""Tests for the multimodal Visual Critic LangGraph node (Task 13).

The critic inspects the actual rendered page PNGs (+ contact sheet) and the
selected family reference images, scores the carousel on eight aesthetic
dimensions plus image relevance, and drives a two-round aesthetic redesign
loop (rounds 0 and 1 route failures to ``design_reviser``; round 2 is terminal
and routes to ``human_review``). These tests use an offline fake
``StructuredVisualModel`` that records the ``image_paths`` it was called with;
no real Gemini call is ever made.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.nodes.node_p_visual_critic import (
    route_after_visual_critic,
    visual_critic_node,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.render_manifest import (
    FontLoadReport,
    RenderManifest,
    RenderedElementProbe,
    RenderedPage,
)
from src.schemas.render_qa import RenderQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    TextElement,
    TextStyle,
)
from src.schemas.visual_critique import VisualCritique, VisualCritiqueIssue
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.visual_design.model_retry import (
    MAX_GENERATION_ATTEMPTS,
    VisualProductionInterrupted,
)


# --- offline fake model ---------------------------------------------------


class ScriptedVisualModel:
    """Records every generate_json call and returns pre-built responses."""

    def __init__(
        self,
        responses: Sequence[VisualCritique | Exception],
    ) -> None:
        self.responses: list[VisualCritique | Exception] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,
        response_model: type[VisualCritique],
        image_paths: Sequence[Path] = (),
    ) -> VisualCritique:
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


# --- fixture builders -----------------------------------------------------

_PAGE_COUNT = 5
_BG = "#FFFFFF"
_INK = "#1A1A1A"


def _png_bytes(width: int = 1080, height: int = 1440, color: str = _BG) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _write_png(path: Path, **kwargs) -> str:
    payload = _png_bytes(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _atom_set(page_count: int = _PAGE_COUNT) -> ContentAtomSet:
    texts = tuple(
        f"视觉评审第{index}页的编辑内容文字。" for index in range(1, page_count + 1)
    )
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


def _direction(atom_set: ContentAtomSet) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑方向",
        palette=("#F4A7BF", "#DC2333"),
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
                asset_directive_ids=(),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(),
    )


def _asset_item(*, asset_id: str = "asset-2", page_id: str = "page-2") -> AssetManifestItem:
    return AssetManifestItem(
        asset_id=asset_id,
        directive_id=f"directive-{page_id}",
        page_id=page_id,
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


def _text_element(page_id: str, fragment_id: str) -> TextElement:
    return TextElement(
        element_id=f"text-{page_id}",
        layer=1,
        box=Box(x=80, y=120, width=920, height=160),
        content_ref=fragment_id,
        style=TextStyle(
            font_role="heading",
            font_size=48,
            line_height=1.3,
            color=_INK,
            align="left",
            weight=700,
        ),
    )


def _image_element(page_id: str, asset_id: str) -> ImageElement:
    return ImageElement(
        element_id=f"image-{page_id}",
        layer=0,
        box=Box(x=80, y=400, width=920, height=720),
        asset_ref=asset_id,
        fit="cover",
        focal_point=(0.5, 0.5),
        corner_radius=0,
    )


def _design_plan(
    direction: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    include_image: bool = False,
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction.page_sequence:
        elements: list[Any] = [_text_element(direction_page.page_id, direction_page.fragment_ids[0])]
        approved = next(
            (item for item in manifest.items if item.page_id == direction_page.page_id),
            None,
        )
        if include_image and approved is not None:
            elements.append(_image_element(direction_page.page_id, approved.asset_id))
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background=_BG,
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
    )


def _text_probe(page_id: str, fragment_id: str, text: str) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=f"text-{page_id}",
        kind="text",
        actual_box=Box(x=80, y=120, width=920, height=160),
        computed_font_family="Test Heading",
        computed_font_size=48.0,
        computed_line_height=1.3,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=12.0,
        content_ref=fragment_id,
        asset_ref=None,
        rasterized_text_sha256=sha256_text(text),
    )


def _image_probe(page_id: str, asset: AssetManifestItem) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=f"image-{page_id}",
        kind="image",
        actual_box=Box(x=80, y=400, width=920, height=720),
        computed_font_family=None,
        computed_font_size=None,
        computed_line_height=None,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=1.0,
        content_ref=None,
        asset_ref=asset.asset_id,
        rasterized_text_sha256=None,
        rendered_asset_sha256=asset.sha256,
        actual_focal_point=(0.5, 0.5),
        crop_box=Box(x=0, y=0, width=1080, height=1440),
        natural_width=asset.width,
        natural_height=asset.height,
    )


def _render_manifest(
    design_plan: CarouselDesignPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    direction: VisualDirectionPlan,
    *,
    render_dir: Path,
    include_image: bool = False,
) -> RenderManifest:
    fragment_by_id = {f.fragment_id: f for f in direction.content_fragments}
    pages: list[RenderedPage] = []
    for index, plan_page in enumerate(design_plan.pages, start=1):
        page_path = render_dir / f"page-{index:02d}.png"
        _write_png(page_path)
        first_frag = plan_page.elements[0].content_ref
        probes: list[RenderedElementProbe] = [
            _text_probe(plan_page.page_id, first_frag, fragment_by_id[first_frag].text)
        ]
        if include_image and any(
            isinstance(el, ImageElement) for el in plan_page.elements
        ):
            approved = next(
                (item for item in manifest.items if item.page_id == plan_page.page_id),
                None,
            )
            if approved is not None:
                probes.append(_image_probe(plan_page.page_id, approved))
        pages.append(
            RenderedPage(
                page_id=plan_page.page_id,
                sequence=plan_page.sequence,
                path=str(page_path),
                width=1080,
                height=1440,
                sha256=sha256_text(f"page-{index}"),
                element_probes=tuple(probes),
            )
        )
    contact_path = render_dir / "contact-sheet.png"
    contact_sha = _write_png(contact_path, width=1320, height=1145)
    return RenderManifest(
        design_plan_sha256=canonical_sha256(design_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
        fonts=FontLoadReport(
            all_loaded=True,
            computed_families=("Test Display", "Test Heading", "Test Body"),
        ),
        contact_sheet_path=str(contact_path),
        contact_sheet_sha256=contact_sha,
        source_asset_sha256={item.asset_id: item.sha256 for item in manifest.items},
    )


def _passing_render_qa(render_manifest: RenderManifest) -> RenderQAResult:
    return RenderQAResult(
        passed=True,
        issues=(),
        render_manifest_sha256=canonical_sha256(render_manifest),
        content_attestation=True,
        geometry_attestation=True,
        asset_attestation=True,
    )


def _failing_render_qa(render_manifest: RenderManifest) -> RenderQAResult:
    from src.schemas.render_qa import RenderIssue

    return RenderQAResult(
        passed=False,
        issues=(
            RenderIssue(
                rule="geometry.overflow",
                message="page-1 heading overflows its box",
                repair_instruction="shrink page-1 heading",
                page_id="page-1",
                element_id="text-page-1",
            ),
        ),
        render_manifest_sha256=canonical_sha256(render_manifest),
        content_attestation=True,
        geometry_attestation=False,
        asset_attestation=True,
    )


def _passing_critique(
    *,
    atom_set: ContentAtomSet,
    direction: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    render_manifest: RenderManifest,
    revision_round: int = 0,
    contains_images: bool = False,
) -> VisualCritique:
    return VisualCritique(
        content_atom_set_sha256=atom_set.canonical_sha256,
        direction_plan_sha256=canonical_sha256(direction),
        design_plan_sha256=canonical_sha256(design_plan),
        render_manifest_sha256=canonical_sha256(render_manifest),
        passed=True,
        revision_round=revision_round,
        contains_images=contains_images,
        overall=88,
        hierarchy=78,
        legibility=85,
        composition=84,
        family_consistency=82,
        page_variation=80,
        page_rhythm=78,
        color=85,
        spacing=83,
        image_relevance="not_applicable" if not contains_images else 82,
        issues=(),
        revision_instructions=(),
    )


def _failing_critique(
    *,
    atom_set: ContentAtomSet,
    direction: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    render_manifest: RenderManifest,
    revision_round: int = 0,
    contains_images: bool = False,
) -> VisualCritique:
    return VisualCritique(
        content_atom_set_sha256=atom_set.canonical_sha256,
        direction_plan_sha256=canonical_sha256(direction),
        design_plan_sha256=canonical_sha256(design_plan),
        render_manifest_sha256=canonical_sha256(render_manifest),
        passed=False,
        revision_round=revision_round,
        contains_images=contains_images,
        overall=62,
        hierarchy=58,
        legibility=70,
        composition=68,
        family_consistency=72,
        page_variation=60,
        page_rhythm=55,
        color=70,
        spacing=66,
        image_relevance="not_applicable" if not contains_images else 58,
        issues=(
            VisualCritiqueIssue(
                rule="hierarchy",
                message="page-1 heading is too weak against the family reference",
                revision_instruction="enlarge page-1 display heading and increase weight",
                page_id="page-1",
                element_id="text-page-1",
            ),
        ),
        revision_instructions=(
            "enlarge page-1 display heading and increase weight",
        ),
    )


def _state(
    *,
    atom_set: ContentAtomSet,
    direction: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    manifest: AssetManifest,
    render_manifest: RenderManifest,
    render_qa_result: RenderQAResult,
    visual_critic_round: int = 0,
) -> dict:
    return {
        "content_atom_set": atom_set,
        "visual_direction_plan": direction,
        "carousel_design_plan": design_plan,
        "asset_manifest": manifest,
        "render_manifest": render_manifest,
        "render_qa_result": render_qa_result,
        "visual_critic_round": visual_critic_round,
        "domain_context": {"domain": "beauty", "profile_version": "beauty-v1"},
    }


def _build_text_only(tmp_path: Path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    design_plan = _design_plan(direction, atom_set, manifest, include_image=False)
    render_manifest = _render_manifest(
        design_plan, atom_set, manifest, direction, render_dir=tmp_path, include_image=False
    )
    render_qa = _passing_render_qa(render_manifest)
    return atom_set, direction, design_plan, manifest, render_manifest, render_qa


def _build_with_images(tmp_path: Path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    item = _asset_item(page_id="page-2")
    manifest = AssetManifest(items=(item,))
    design_plan = _design_plan(direction, atom_set, manifest, include_image=True)
    render_manifest = _render_manifest(
        design_plan, atom_set, manifest, direction, render_dir=tmp_path, include_image=True
    )
    render_qa = _passing_render_qa(render_manifest)
    return atom_set, direction, design_plan, manifest, render_manifest, render_qa


# --- model invocation and image assembly ----------------------------------


def test_critic_receives_rendered_page_pngs_contact_sheet_and_family_references(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    model = ScriptedVisualModel([critique])

    visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert len(model.calls) == 1
    image_paths = model.calls[0]["image_paths"]
    # Every rendered page PNG is sent, in sequence order.
    page_paths = [Path(page.path) for page in render_manifest.pages]
    assert image_paths[: len(page_paths)] == tuple(page_paths)
    # The contact sheet follows the page PNGs.
    assert Path(render_manifest.contact_sheet_path) in image_paths
    # The selected family's reference images are included.
    from src.visual_design.style_registry import load_style_registry

    registry = load_style_registry()
    family_refs = tuple(Path(p) for p in registry[direction.template_family].reference_image_paths)
    assert family_refs
    for ref in family_refs:
        assert ref in image_paths
    # Total: pages + contact sheet + family refs.
    assert len(image_paths) == len(page_paths) + 1 + len(family_refs)


def test_critic_scores_all_eight_dimensions_and_image_relevance(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    model = ScriptedVisualModel([critique])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    scored = result["visual_critique"]
    for dimension in (
        "overall",
        "hierarchy",
        "legibility",
        "composition",
        "family_consistency",
        "page_variation",
        "page_rhythm",
        "color",
        "spacing",
    ):
        assert isinstance(getattr(scored, dimension), int)
        assert 0 <= getattr(scored, dimension) <= 100
    # image_relevance is present (not_applicable for text-only).
    assert scored.image_relevance == "not_applicable"
    assert result["current_node"] == "VISUAL_CRITIC"


def test_critic_marks_image_relevance_not_applicable_for_text_only_pages(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        contains_images=False,
    )
    model = ScriptedVisualModel([critique])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert result["visual_critique"].contains_images is False
    assert result["visual_critique"].image_relevance == "not_applicable"


def test_critic_scores_image_relevance_when_carousel_contains_images(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_with_images(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        contains_images=True,
    )
    model = ScriptedVisualModel([critique])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert result["visual_critique"].contains_images is True
    assert isinstance(result["visual_critique"].image_relevance, int)
    assert result["visual_critique"].image_relevance >= 70


def test_critic_names_every_problem_with_page_element_and_revision_instruction(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _failing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    model = ScriptedVisualModel([critique])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    for issue in result["visual_critique"].issues:
        # Every issue must locate a page or element and give concrete advice.
        assert issue.page_id is not None or issue.element_id is not None
        assert issue.revision_instruction.strip()


# --- hard QA gate ---------------------------------------------------------


def test_hard_render_qa_failure_prevents_model_invocation(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        _render_qa,
    ) = _build_text_only(tmp_path)
    failing_qa = _failing_render_qa(render_manifest)
    # Model has no responses queued: any call would IndexError.
    model = ScriptedVisualModel([])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=failing_qa,
        ),
        model=model,
    )

    assert model.calls == []
    assert result["current_node"] == "VISUAL_CRITIC"
    # Defense-in-depth: route back to the reviser without fabricating a critique.
    assert result.get("route") == "design_reviser"
    assert "visual_critique" not in result


# --- routing --------------------------------------------------------------


def test_passed_critique_routes_to_human_review(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    model = ScriptedVisualModel([critique])

    state = _state(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        manifest=manifest,
        render_manifest=render_manifest,
        render_qa_result=render_qa,
    )
    result = visual_critic_node(state, model=model)

    merged = {**state, **result}
    assert route_after_visual_critic(merged) == "human_review"
    assert "review_status" not in result


def test_failed_round_0_routes_to_design_reviser(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _failing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        revision_round=0,
    )
    model = ScriptedVisualModel([critique])

    state = _state(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        manifest=manifest,
        render_manifest=render_manifest,
        render_qa_result=render_qa,
        visual_critic_round=0,
    )
    result = visual_critic_node(state, model=model)

    merged = {**state, **result}
    assert route_after_visual_critic(merged) == "design_reviser"
    assert result["visual_critique"].revision_round == 0
    assert "review_status" not in result


def test_failed_round_1_routes_to_design_reviser(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _failing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        revision_round=1,
    )
    model = ScriptedVisualModel([critique])

    state = _state(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        manifest=manifest,
        render_manifest=render_manifest,
        render_qa_result=render_qa,
        visual_critic_round=1,
    )
    result = visual_critic_node(state, model=model)

    merged = {**state, **result}
    assert route_after_visual_critic(merged) == "design_reviser"
    assert result["visual_critique"].revision_round == 1
    assert "review_status" not in result


def test_failed_round_2_routes_to_human_review_with_visual_needs_attention(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _failing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        revision_round=2,
    )
    model = ScriptedVisualModel([critique])

    state = _state(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        manifest=manifest,
        render_manifest=render_manifest,
        render_qa_result=render_qa,
        visual_critic_round=2,
    )
    result = visual_critic_node(state, model=model)

    merged = {**state, **result}
    assert route_after_visual_critic(merged) == "human_review"
    assert result["visual_critique"].revision_round == 2
    assert result.get("review_status") == "visual_needs_attention"


# --- read-only attestation ------------------------------------------------


def test_critic_rejects_wrong_content_hash_and_retries(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    valid = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    wrong_content = valid.model_copy(
        update={"content_atom_set_sha256": "0" * 64}
    )
    model = ScriptedVisualModel([wrong_content, valid])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert result["visual_critique"] == valid
    assert len(model.calls) == 2
    assert "content" in str(model.calls[1]["prompt"]).lower() or "hash" in str(model.calls[1]["prompt"]).lower()


def test_critic_rejects_wrong_render_manifest_hash_and_retries(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    valid = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    wrong_render = valid.model_copy(update={"render_manifest_sha256": "1" * 64})
    model = ScriptedVisualModel([wrong_render, valid])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert result["visual_critique"] == valid
    assert len(model.calls) == 2


def test_critic_rejects_wrong_contains_images_and_retries(tmp_path):
    """The critic cannot fabricate or hide images: a text-only carousel whose
    critique claims ``contains_images=True`` is rejected and retried."""
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    valid = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        contains_images=False,
    )
    wrong_contains = valid.model_copy(update={"contains_images": True, "image_relevance": 80})
    model = ScriptedVisualModel([wrong_contains, valid])

    result = visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    assert result["visual_critique"] == valid
    assert len(model.calls) == 2


def test_critic_rejects_wrong_revision_round_and_retries(tmp_path):
    """The round is a node-controlled fact, not a model decision: a critique
    returning the wrong ``revision_round`` is rejected and retried."""
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    valid = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
        revision_round=0,
    )
    wrong_round = valid.model_copy(update={"revision_round": 2})
    model = ScriptedVisualModel([wrong_round, valid])

    state = _state(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        manifest=manifest,
        render_manifest=render_manifest,
        render_qa_result=render_qa,
        visual_critic_round=0,
    )
    result = visual_critic_node(state, model=model)

    assert result["visual_critique"] == valid
    assert len(model.calls) == 2


def test_critic_three_hash_mismatches_raise_resumable_interruption(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    invalid = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    ).model_copy(update={"content_atom_set_sha256": "0" * 64})
    model = ScriptedVisualModel([invalid] * MAX_GENERATION_ATTEMPTS)

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        visual_critic_node(
            _state(
                atom_set=atom_set,
                direction=direction,
                design_plan=design_plan,
                manifest=manifest,
                render_manifest=render_manifest,
                render_qa_result=render_qa,
            ),
            model=model,
        )

    interrupted = exc_info.value
    assert interrupted.stage == "visual_critic"
    assert interrupted.resumable is True
    assert len(interrupted.errors) == MAX_GENERATION_ATTEMPTS
    assert len(model.calls) == MAX_GENERATION_ATTEMPTS


# --- prompt content -------------------------------------------------------


def test_critic_prompt_forbids_altering_content_hashes_assets_and_family(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        manifest,
        render_manifest,
        render_qa,
    ) = _build_text_only(tmp_path)
    critique = _passing_critique(
        atom_set=atom_set,
        direction=direction,
        design_plan=design_plan,
        render_manifest=render_manifest,
    )
    model = ScriptedVisualModel([critique])

    visual_critic_node(
        _state(
            atom_set=atom_set,
            direction=direction,
            design_plan=design_plan,
            manifest=manifest,
            render_manifest=render_manifest,
            render_qa_result=render_qa,
        ),
        model=model,
    )

    prompt = str(model.calls[0]["prompt"])
    # The critic scores and instructs; it must not mutate immutable sources.
    assert "read-only" in prompt.lower() or "read only" in prompt.lower()
    assert "content_atom_set_sha256" in prompt
    assert "direction_plan_sha256" in prompt
    assert "design_plan_sha256" in prompt
    assert "render_manifest_sha256" in prompt
    assert "family" in prompt.lower()
    # Global rule: never instruct the critic to add compliance/disclaimer copy.
    assert "disclaimer" in prompt.lower()
    assert "AI disclosure" in prompt or "AI 生成" in prompt
