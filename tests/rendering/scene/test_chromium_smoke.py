"""Real-Chromium smoke test for the generic scene renderer (Task 11).

Gated on local Playwright Chromium availability exactly like the editorial
smoke test. Renders a small real plan through the default Chromium render path
and asserts actual PNGs and a hash-bound manifest. This test RUNS (it is not
skipped) in environments where Chromium is installed.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

from src.rendering.scene.renderer import render_carousel_scenes
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignPlanQAResult
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
from src.schemas.visual_style import FamilyStyleProfile


def _local_chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except Exception:
        return False


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"冒烟第{index}页内容。" for index in range(1, page_count + 1)]
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


def _build_world(tmp_path: Path) -> tuple:
    atom_set = _atom_set(5)
    fragments = tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )
    # A real image asset on disk so Chromium renders actual pixels.
    from PIL import Image

    asset_payload_path = tmp_path / "source-asset.png"
    Image.new("RGB", (1080, 1440), "#F4A7BF").save(asset_payload_path, format="PNG")
    payload = asset_payload_path.read_bytes()
    asset = AssetManifestItem(
        asset_id="asset-1",
        directive_id="directive-1",
        page_id="page-1",
        source_kind="catalog",
        provider="catalog",
        license="project-owned",
        local_path=str(asset_payload_path),
        width=1080,
        height=1440,
        sha256=hashlib.sha256(payload).hexdigest(),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "catalog"},
    )
    directive = AssetDirective(
        directive_id="directive-1",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="search",
        fallback_source="none",
        query_or_prompt="realistic skin close-up",
        negative_constraints=("no embedded text",),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    direction = VisualDirectionPlan(
        template_family="pink_red",
        page_count=5,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="smoke direction",
        palette=("#F4A7BF",),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("underline",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"p{index}",
                visual_job=f"j{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=("directive-1",) if index == 1 else (),
            )
            for index in range(1, 6)
        ),
        asset_directives=(directive,),
    )
    pages = []
    for direction_page in direction.page_sequence:
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
        if direction_page.page_id == "page-1":
            elements.insert(
                0,
                ImageElement(
                    element_id="image-page-1",
                    layer=0,
                    box=Box(x=80, y=400, width=920, height=720),
                    asset_ref="asset-1",
                    fit="cover",
                    focal_point=(0.5, 0.5),
                    corner_radius=0,
                ),
            )
        else:
            elements.append(
                ShapeElement(
                    element_id=f"shape-{direction_page.page_id}",
                    layer=2,
                    box=Box(x=80, y=1200, width=920, height=40),
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
    design_plan = CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(AssetManifest(items=(asset,))),
        revision=0,
        pages=tuple(pages),
    )
    qa = DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )
    style = FamilyStyleProfile(
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
    fragment_map = {frag.fragment_id: frag for frag in fragments}
    asset_map = {"asset-1": asset}
    return atom_set, direction, design_plan, fragment_map, asset_map, style, qa


@pytest.mark.skipif(
    not _local_chromium_available(),
    reason="local Playwright Chromium is unavailable",
)
def test_real_chromium_renders_generic_carousel_with_probes_and_manifest(tmp_path):
    (
        atom_set,
        direction,
        design_plan,
        fragments,
        assets,
        style,
        qa,
    ) = _build_world(tmp_path)
    output_dir = tmp_path / "render"
    output_dir.mkdir()

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=style,
        design_plan_qa_result=qa,
        output_dir=output_dir,
    )

    assert len(manifest.pages) == 5
    assert [page.sequence for page in manifest.pages] == [1, 2, 3, 4, 5]
    for rendered in manifest.pages:
        path = Path(rendered.path)
        assert path.is_file()
        assert _png_dimensions(path) == (1080, 1440)
        assert rendered.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert rendered.width == 1080 and rendered.height == 1440
        # every planned element produced a probe
        planned_ids = {
            element.element_id
            for page in design_plan.pages
            if page.page_id == rendered.page_id
            for element in page.elements
        }
        probe_ids = {probe.element_id for probe in rendered.element_probes}
        assert probe_ids == planned_ids

    # contact sheet exists, is a real PNG, and has its own byte hash
    sheet = Path(manifest.contact_sheet_path)
    assert sheet.is_file()
    assert _png_dimensions(sheet)[0] > 0
    assert manifest.contact_sheet_sha256 == hashlib.sha256(sheet.read_bytes()).hexdigest()

    # manifest binds to every source hash
    assert manifest.design_plan_sha256 == canonical_sha256(design_plan)
    assert manifest.content_atom_set_sha256 == atom_set.canonical_sha256
    assert manifest.asset_manifest_sha256 == canonical_sha256(
        AssetManifest(items=tuple(assets.values()))
    )
    assert manifest.source_asset_sha256 == {
        "asset-1": hashlib.sha256(
            Path(assets["asset-1"].local_path).read_bytes()
        ).hexdigest()
    }
    # fonts report is non-empty and internally consistent
    assert manifest.fonts.all_loaded is True
    assert manifest.fonts.computed_families

    # no leftover html in the output directory
    assert not list(output_dir.glob("*.html"))

    # page-1 carried a real image probe bound to the rendered asset bytes
    page_one = manifest.pages[0]
    image_probe = next(p for p in page_one.element_probes if p.kind == "image")
    assert image_probe.rendered_asset_sha256 == assets["asset-1"].sha256
    text_probe = next(p for p in page_one.element_probes if p.kind == "text")
    assert text_probe.rasterized_text_sha256 == sha256_text(
        fragments["fragment-1"].text
    )
