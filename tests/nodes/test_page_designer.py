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
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.nodes.node_p_page_designer import page_designer_node
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


def _asset_item(
    *,
    asset_id: str = "asset-2",
    directive_id: str = "directive-2",
    page_id: str = "page-2",
) -> AssetManifestItem:
    return AssetManifestItem(
        asset_id=asset_id,
        directive_id=directive_id,
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


def _manifest(items: tuple[AssetManifestItem, ...] = ()) -> AssetManifest:
    return AssetManifest(items=items)


def _text_element(page_id: str, fragment_id: str, *, layer: int = 1) -> TextElement:
    return TextElement(
        element_id=f"text-{page_id}",
        layer=layer,
        box=Box(x=80, y=120, width=920, height=160),
        content_ref=fragment_id,
        style=TextStyle(
            font_role="heading",
            font_size=48,
            line_height=1.3,
            color="#1A1A1A",
            align="left",
            weight=700,
        ),
    )


def _image_element(
    page_id: str,
    asset_id: str,
    *,
    layer: int = 0,
    y: float = 400.0,
) -> ImageElement:
    return ImageElement(
        element_id=f"image-{page_id}",
        layer=layer,
        box=Box(x=80, y=y, width=920, height=720),
        asset_ref=asset_id,
        fit="cover",
        focal_point=(0.5, 0.5),
        corner_radius=0,
    )


def _shape(page_id: str, *, fill: str = "#F4A7BF", y: float = 1180.0) -> ShapeElement:
    return ShapeElement(
        element_id=f"shape-{page_id}",
        layer=2,
        box=Box(x=80, y=y, width=920, height=80),
        shape="rectangle",
        fill=fill,
    )


def _design_plan(
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    variant: int = 0,
    revision: int = 0,
    skip_image_for_pages: frozenset[str] = frozenset(),
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction_plan.page_sequence:
        elements: list = [_text_element(direction_page.page_id, direction_page.fragment_ids[0])]
        approved_asset = next(
            (item for item in manifest.items if item.page_id == direction_page.page_id),
            None,
        )
        if approved_asset is not None and direction_page.page_id not in skip_image_for_pages:
            elements.append(_image_element(direction_page.page_id, approved_asset.asset_id))
        if variant and direction_page.sequence == variant:
            elements.append(_shape(direction_page.page_id))
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
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    *,
    unresolved_optional_assets: tuple = (),
) -> dict:
    return {
        "visual_direction_plan": direction_plan,
        "content_atom_set": atom_set,
        "asset_resolution": {
            "manifest": manifest,
            "unresolved_optional_assets": unresolved_optional_assets,
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


def test_designer_returns_structured_plan_binding_text_and_approved_assets():
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
    manifest = _manifest((_asset_item(),))
    design_plan = _design_plan(direction_plan, atom_set, manifest)
    model = ScriptedVisualModel([design_plan])

    result = page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    plan = result["carousel_design_plan"]
    assert result["current_node"] == "PAGE_DESIGNER"
    plan.validate_bindings(direction_plan, atom_set, manifest)
    # Every text element points at a real fragment id; every image points at an
    # approved asset id from the manifest.
    approved_asset_ids = {item.asset_id for item in manifest.items}
    for page in plan.pages:
        for element in page.elements:
            if element.kind == "image":
                assert element.asset_ref in approved_asset_ids
            elif element.kind == "text":
                assert element.content_ref.startswith("fragment-")
                # No stored copy lives on the element.
                assert "text" not in element.model_dump()


def test_designer_prompt_forbids_embedded_copy_html_css_scripts_and_urls():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = _manifest()
    model = ScriptedVisualModel([_design_plan(direction_plan, atom_set, manifest)])

    page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    prompt = str(model.calls[0]["prompt"])
    assert "HTML" in prompt
    assert "CSS" in prompt
    assert "script" in prompt
    assert "external URL" in prompt
    assert "content_ref" in prompt
    assert "1080" in prompt and "1440" in prompt
    # Model context includes resolved fragment text but never asks it to be
    # stored inside TextElement.
    assert "store" in prompt.lower()
    assert "AI 生成示意图" in prompt
    assert "仅供参考" in prompt
    assert "不构成医疗建议" in prompt


def test_designer_serialized_output_carries_no_html_css_scripts_or_urls():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = _manifest()
    design_plan = _design_plan(direction_plan, atom_set, manifest, variant=2)
    model = ScriptedVisualModel([design_plan])

    result = page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    blob = result["carousel_design_plan"].model_dump_json()
    for forbidden in ("<html", "<style", "<script", "http://", "https://", "<![CDATA["):
        assert forbidden not in blob
    for forbidden in ("AI 生成示意图", "仅供参考", "不构成医疗建议", "免责声明"):
        assert forbidden not in blob


def test_designer_can_vary_composition_across_pages_within_one_family():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = _manifest()
    # Variant puts an extra shape on page 3 only; other pages stay simpler.
    design_plan = _design_plan(direction_plan, atom_set, manifest, variant=3)
    model = ScriptedVisualModel([design_plan])

    result = page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    plan = result["carousel_design_plan"]
    shapes_by_page = {
        page.page_id: sum(1 for el in page.elements if el.kind == "shape")
        for page in plan.pages
    }
    assert shapes_by_page["page-3"] == 1
    assert shapes_by_page["page-1"] == 0
    plan.validate_bindings(direction_plan, atom_set, manifest)


def test_designer_creates_no_image_composition_when_optional_asset_unresolved():
    atom_set = _atom_set()
    directive = AssetDirective(
        directive_id="directive-2",
        page_id="page-2",
        role="decorative",
        required=False,
        preferred_source="search",
        fallback_source="none",
        query_or_prompt="soft pink background texture",
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
    # Manifest is empty: the optional asset failed to resolve.
    manifest = _manifest(())
    unresolved = (
        {
            "directive_id": "directive-2",
            "page_id": "page-2",
            "reason": "offline",
        },
    )
    design_plan = _design_plan(
        direction_plan,
        atom_set,
        manifest,
        skip_image_for_pages=frozenset({"page-2"}),
    )
    model = ScriptedVisualModel([design_plan])

    result = page_designer_node(
        _state(direction_plan, atom_set, manifest, unresolved_optional_assets=unresolved),
        model=model,
    )

    plan = result["carousel_design_plan"]
    plan.validate_bindings(direction_plan, atom_set, manifest)
    page_2 = next(page for page in plan.pages if page.page_id == "page-2")
    assert all(element.kind != "image" for element in page_2.elements)
    # Prompt surfaced the unresolved optional so the model omits the image.
    assert "page-2" in str(model.calls[0]["prompt"])


def test_designer_retries_invalid_model_output_at_most_three_times():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = _manifest()
    valid = _design_plan(direction_plan, atom_set, manifest)
    invalid = valid.model_copy(
        update={
            "content_atom_set_sha256": "0" * 64,
        }
    )
    model = ScriptedVisualModel([invalid, valid])

    result = page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    assert result["carousel_design_plan"] == valid
    assert len(model.calls) == 2
    assert "content atom set hash" in str(model.calls[1]["prompt"])


def test_designer_three_failures_raise_resumable_interruption():
    atom_set = _atom_set()
    direction_plan = _direction_plan(atom_set)
    manifest = _manifest()
    valid = _design_plan(direction_plan, atom_set, manifest)
    invalid = valid.model_copy(
        update={
            "content_atom_set_sha256": "0" * 64,
        }
    )
    model = ScriptedVisualModel([invalid, invalid, invalid])

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        page_designer_node(_state(direction_plan, atom_set, manifest), model=model)

    interruption = exc_info.value
    assert interruption.stage == "page_designer"
    assert len(interruption.errors) == 3
    assert len(model.calls) == 3
