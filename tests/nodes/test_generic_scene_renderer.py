"""Tests for the generic scene renderer LangGraph node (Task 11).

The node reads the Task 7-10 top-level state keys and refuses to render unless
``design_plan_qa_result.passed is True``. Rendering itself is injected so these
tests do not launch Chromium.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.nodes.node_p_generic_scene_renderer import generic_scene_renderer_node
from src.rendering.scene.renderer import RenderedPageDraft
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.render_manifest import RenderManifest
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    TextElement,
    TextStyle,
)
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.schemas.visual_style import FamilyStyleProfile


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"节点测试第{index}页。" for index in range(1, page_count + 1)]
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
        art_direction="direction",
        palette=("#F4A7BF",),
        typography_direction={"display": "d", "body": "b"},
        motifs=("m",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose="p",
                visual_job=f"j-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=(),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(),
    )


def _design_plan(direction: VisualDirectionPlan, atom_set: ContentAtomSet) -> CarouselDesignPlan:
    pages = tuple(
        PageScene(
            page_id=page.page_id,
            sequence=page.sequence,
            background="#FFFFFF",
            elements=(
                TextElement(
                    element_id=f"text-{page.page_id}",
                    layer=1,
                    box=Box(x=80, y=120, width=920, height=160),
                    content_ref=page.fragment_ids[0],
                    style=TextStyle(
                        font_role="heading",
                        font_size=48,
                        line_height=1.3,
                        color="#1A1A1A",
                        align="left",
                        weight=700,
                    ),
                ),
            ),
        )
        for page in direction.page_sequence
    )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        # Build the hash from the same AssetManifest the renderer will recompute
        # (canonical_sha256(AssetManifest(items=...))), not a bare list, so the
        # I2 asset-hash cross-check passes: the plan's declared hash must match
        # the supplied assets.
        asset_manifest_sha256=canonical_sha256(AssetManifest(items=())),
        revision=0,
        pages=pages,
    )


def _style_profile() -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family="pink_red",
        reference_image_paths=(
            "assets/visual/beauty-editorial-v1/active/textures/serum-drops.svg",
        ),
        palette=("#F4A7BF", "#1A1A1A", "#FFFFFF"),
        font_roles={
            "display": "Test Display",
            "heading": "Test Heading",
            "body": "Test Body",
            "caption": "Test Caption",
        },
        composition_principles=("hierarchy", "whitespace"),
        whitespace_range=(0.2, 0.6),
        density_range=(0.3, 0.8),
        allowed_motifs=("underline",),
        prohibited_patterns=("clutter",),
    )


class _FakeRenderer:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, design_plan, **kwargs):
        self.calls += 1
        # Return a minimal valid RenderManifest bound to the real hashes.
        from src.rendering.scene.renderer import RenderedPageDraft

        raise NotImplementedError  # pragma: no cover


def _state(
    direction,
    atom_set,
    design_plan,
    output_dir,
    *,
    qa_result,
):
    return {
        "visual_direction_plan": direction,
        "content_atom_set": atom_set,
        "asset_manifest": {"items": ()},
        "carousel_design_plan": design_plan,
        "design_plan_qa_result": qa_result,
        "run_output_dir": str(output_dir),
        "domain_context": {"domain": "beauty", "profile_version": "beauty-v1"},
    }


def _passing_qa(design_plan):
    from src.schemas.design_qa import DesignPlanQAResult

    return DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _failing_qa(design_plan):
    from src.schemas.design_qa import DesignPlanQAResult

    return DesignPlanQAResult(
        passed=False,
        issues=(
            {
                "rule": "coverage",
                "message": "missing",
                "repair_instruction": "fix",
                "atom_id": "atom-1",
            },
        ),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=False,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _stub_render(**overrides):
    """Build a stub render function that records its kwargs."""

    recorded: dict = {}

    def _stub(design_plan, *, fragments, assets, style, design_plan_qa_result, output_dir):
        recorded["design_plan"] = design_plan
        recorded["fragments"] = fragments
        recorded["assets"] = assets
        recorded["style"] = style
        recorded["design_plan_qa_result"] = design_plan_qa_result
        recorded["output_dir"] = output_dir
        return overrides.get("manifest")

    return _stub, recorded


def test_node_renders_when_qa_passes_and_writes_manifest_to_state(tmp_path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    design_plan = _design_plan(direction, atom_set)
    qa = _passing_qa(design_plan)
    state = _state(direction, atom_set, design_plan, tmp_path, qa_result=qa)

    # Build a real manifest via the renderer's public surface so the node
    # round-trips a validated RenderManifest.
    from src.rendering.scene.renderer import render_carousel_scenes
    from tests.rendering.scene.test_renderer import _ScriptedRenderer, _style_profile as _profile

    def real_render(design_plan, **kwargs):
        return render_carousel_scenes(
            design_plan,
            fragments=kwargs["fragments"],
            assets=kwargs["assets"],
            style=kwargs["style"],
            design_plan_qa_result=kwargs["design_plan_qa_result"],
            output_dir=Path(kwargs["output_dir"]),
            render_page_fn=_ScriptedRenderer(),
        )

    result = generic_scene_renderer_node(
        state,
        render_fn=real_render,
        style_profiles={"pink_red": _style_profile()},
    )

    manifest = result["render_manifest"]
    assert isinstance(manifest, RenderManifest)
    assert result["current_node"] == "GENERIC_SCENE_RENDERER"
    assert manifest.design_plan_sha256 == canonical_sha256(design_plan)
    assert manifest.content_atom_set_sha256 == atom_set.canonical_sha256
    assert len(manifest.pages) == 5


def test_node_rejects_failed_qa_without_rendering(tmp_path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    design_plan = _design_plan(direction, atom_set)
    qa = _failing_qa(design_plan)
    state = _state(direction, atom_set, design_plan, tmp_path, qa_result=qa)

    render_calls: list = []

    def render_fn(design_plan, **kwargs):
        render_calls.append(kwargs)
        raise AssertionError("renderer must not run on a failed QA result")

    with pytest.raises(Exception, match="design plan QA"):
        generic_scene_renderer_node(
            state,
            render_fn=render_fn,
            style_profiles={"pink_red": _style_profile()},
        )

    assert render_calls == []


def test_node_rejects_missing_qa_result(tmp_path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    design_plan = _design_plan(direction, atom_set)
    state = _state(direction, atom_set, design_plan, tmp_path, qa_result=None)
    state.pop("design_plan_qa_result")

    with pytest.raises(Exception, match="design plan QA"):
        generic_scene_renderer_node(
            state,
            render_fn=lambda *a, **kw: None,
            style_profiles={"pink_red": _style_profile()},
        )


def test_node_reads_run_output_dir_from_top_level_state(tmp_path):
    atom_set = _atom_set()
    direction = _direction(atom_set)
    design_plan = _design_plan(direction, atom_set)
    qa = _passing_qa(design_plan)
    output_dir = tmp_path / "render"
    state = _state(direction, atom_set, design_plan, output_dir, qa_result=qa)

    recorded: dict = {}

    def real_render(design_plan, **kwargs):
        from src.rendering.scene.renderer import render_carousel_scenes
        from tests.rendering.scene.test_renderer import _ScriptedRenderer

        recorded["output_dir"] = kwargs["output_dir"]
        return render_carousel_scenes(
            design_plan,
            fragments=kwargs["fragments"],
            assets=kwargs["assets"],
            style=kwargs["style"],
            design_plan_qa_result=kwargs["design_plan_qa_result"],
            output_dir=Path(kwargs["output_dir"]),
            render_page_fn=_ScriptedRenderer(),
        )

    result = generic_scene_renderer_node(
        state,
        render_fn=real_render,
        style_profiles={"pink_red": _style_profile()},
    )

    manifest = result["render_manifest"]
    assert isinstance(manifest, RenderManifest)
    assert recorded["output_dir"] == str(output_dir)
    assert result["current_node"] == "GENERIC_SCENE_RENDERER"
    assert len(manifest.pages) == 5
