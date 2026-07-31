"""Deterministic render-QA rule tests (Task 12).

Every test builds a minimal *valid* ``RenderQAInputs`` (synthetic
``RenderManifest`` + probes bound to real PNG files on tmp_path — no Chromium)
and mutates exactly one aspect, then asserts the exact failing ``rule`` (and
the relevant ids) and that ``passed is False``. The valid base is exercised by
``test_valid_render_passes``.

Rules are grouped by attestation prefix:

* ``content.``  — manifest/atom/plan hash bindings, page count/order/canvas,
  page/contact-sheet file hashes, rasterized-text attestation, forbidden labels.
* ``geometry.`` — missing/extra probes, clipping/overflow, off-canvas bounds,
  undersized fonts, low contrast, unintended overlap.
* ``asset.``    — source-asset hashes, image crop/focal-point/asset-hash binds.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import (
    FontLoadReport,
    RenderManifest,
    RenderedElementProbe,
    RenderedPage,
)
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
from src.visual_design.plan_qa import contrast_ratio
from src.visual_design.render_qa import (
    MAX_RENDER_QA_FAILURES,
    RenderQAInputs,
    evaluate_render,
    render_qa_exhausted,
)


# --- fixture builders -----------------------------------------------------

_PAGE_COUNT = 5
_BG = "#FFFFFF"
_INK = "#1A1A1A"
_INK_ON_BG = contrast_ratio(_INK, _BG)


def _png_bytes(width: int = 1080, height: int = 1440, color: str = _BG) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _write_png(path: Path, **kwargs) -> str:
    payload = _png_bytes(**kwargs)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _atom_set(page_count: int = _PAGE_COUNT) -> ContentAtomSet:
    texts = tuple(f"渲染QA第{index}页的编辑内容文字。" for index in range(1, page_count + 1))
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


def _direction(
    atom_set: ContentAtomSet,
    *,
    directive: AssetDirective | None = None,
) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    directives = (directive,) if directive is not None else ()
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="护肤编辑方向",
        palette=("#F4A7BF", "#1A1A1A", "#FFFFFF"),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("oversized type",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=(
                    (directive.directive_id,)
                    if directive is not None and directive.page_id == f"page-{index}"
                    else ()
                ),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=directives,
    )


def _asset_directive(*, page_id: str = "page-1") -> AssetDirective:
    return AssetDirective(
        directive_id="directive-image",
        page_id=page_id,
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


def _asset_item(path: Path, *, payload: bytes | None = None) -> AssetManifestItem:
    payload = payload if payload is not None else _png_bytes(1080, 1440)
    path.write_bytes(payload)
    return AssetManifestItem(
        asset_id="asset-image",
        directive_id="directive-image",
        page_id="page-1",
        source_kind="catalog",
        provider="catalog",
        license="project-owned",
        local_path=str(path),
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


def _text_element(page_id: str, fragment_id: str) -> TextElement:
    return TextElement(
        element_id=f"text-{page_id}",
        layer=1,
        box=Box(x=88, y=120, width=904, height=160),
        content_ref=fragment_id,
        style=TextStyle(
            font_role="body",
            font_size=28,
            line_height=1.45,
            color=_INK,
            align="left",
            weight=500,
        ),
    )


def _image_element(page_id: str) -> ImageElement:
    return ImageElement(
        element_id=f"image-{page_id}",
        layer=0,
        box=Box(x=88, y=320, width=904, height=720),
        asset_ref="asset-image",
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
        elements: list = [_text_element(direction_page.page_id, direction_page.fragment_ids[0])]
        if include_image and direction_page.asset_directive_ids:
            elements.append(_image_element(direction_page.page_id))
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


def _text_probe(page_id: str, fragment_id: str, fragment_text: str) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=f"text-{page_id}",
        kind="text",
        actual_box=Box(x=88, y=120, width=904, height=160),
        computed_font_family="Test Body",
        computed_font_size=28.0,
        computed_line_height=40.6,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=_INK_ON_BG,
        content_ref=fragment_id,
        asset_ref=None,
        rasterized_text_sha256=sha256_text(fragment_text),
        rendered_asset_sha256=None,
    )


def _image_probe(page_id: str, asset: AssetManifestItem) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=f"image-{page_id}",
        kind="image",
        actual_box=Box(x=88, y=320, width=904, height=720),
        computed_font_family=None,
        computed_font_size=None,
        computed_line_height=None,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=0.0,
        content_ref=None,
        asset_ref=asset.asset_id,
        rasterized_text_sha256=None,
        rendered_asset_sha256=asset.sha256,
        actual_focal_point=(0.5, 0.5),
        crop_box=Box(x=0, y=0, width=1080, height=1440),
        natural_width=asset.width,
        natural_height=asset.height,
    )


def _first_fragment(plan_page: PageScene) -> str:
    for el in plan_page.elements:
        if isinstance(el, TextElement):
            return el.content_ref
    raise AssertionError("plan page must contain a text element")


def _render_manifest(
    design_plan: CarouselDesignPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    direction: VisualDirectionPlan,
    *,
    render_dir: Path,
    include_image: bool,
    image_probes: dict[str, RenderedElementProbe] | None = None,
    contact_sheet_color: str = _BG,
) -> RenderManifest:
    image_probes = image_probes or {}
    fragment_by_id = {f.fragment_id: f for f in direction.content_fragments}
    pages: list[RenderedPage] = []
    for index, plan_page in enumerate(design_plan.pages, start=1):
        page_path = render_dir / f"page-{index:02d}.png"
        page_sha = _write_png(page_path)
        first_frag = _first_fragment(plan_page)
        probes: list[RenderedElementProbe] = [
            _text_probe(plan_page.page_id, first_frag, fragment_by_id[first_frag].text)
        ]
        if include_image and any(
            isinstance(el, ImageElement) for el in plan_page.elements
        ):
            asset = manifest.items[0]
            probes.append(image_probes.get(plan_page.page_id, _image_probe(plan_page.page_id, asset)))
        pages.append(
            RenderedPage(
                page_id=plan_page.page_id,
                sequence=plan_page.sequence,
                path=str(page_path),
                width=1080,
                height=1440,
                sha256=page_sha,
                element_probes=tuple(probes),
            )
        )
    contact_path = render_dir / "contact-sheet.png"
    contact_sha = _write_png(contact_path, width=1320, height=1145, color=contact_sheet_color)
    return RenderManifest(
        design_plan_sha256=canonical_sha256(design_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
        fonts=FontLoadReport(all_loaded=True, computed_families=("Test Display", "Test Heading", "Test Body")),
        contact_sheet_path=str(contact_path),
        contact_sheet_sha256=contact_sha,
        source_asset_sha256={item.asset_id: item.sha256 for item in manifest.items},
    )


def _passing_design_qa(design_plan: CarouselDesignPlan) -> DesignPlanQAResult:
    return DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _inputs(
    tmp_path: Path,
    *,
    atom_set: ContentAtomSet | None = None,
    direction: VisualDirectionPlan | None = None,
    manifest: AssetManifest | None = None,
    design_plan: CarouselDesignPlan | None = None,
    design_plan_qa: DesignPlanQAResult | None = None,
    render_manifest: RenderManifest | None = None,
    include_image: bool = False,
) -> RenderQAInputs:
    atom_set = atom_set or _atom_set()
    directive = _asset_directive() if include_image else None
    direction = direction or _direction(atom_set, directive=directive)
    if manifest is None:
        if include_image:
            asset_path = tmp_path / "asset.png"
            manifest = AssetManifest(items=(_asset_item(asset_path),))
        else:
            manifest = AssetManifest(items=())
    design_plan = design_plan or _design_plan(direction, atom_set, manifest, include_image=include_image)
    design_plan_qa = design_plan_qa or _passing_design_qa(design_plan)
    render_manifest = render_manifest or _render_manifest(
        design_plan,
        atom_set,
        manifest,
        direction,
        render_dir=tmp_path,
        include_image=include_image,
    )
    return RenderQAInputs(
        atoms=atom_set,
        direction=direction,
        assets=manifest,
        design_plan=design_plan,
        design_plan_qa=design_plan_qa,
        render_manifest=render_manifest,
    )


def _copy_inputs(base: RenderQAInputs, **overrides) -> RenderQAInputs:
    return RenderQAInputs(
        atoms=overrides.get("atoms", base.atoms),
        direction=overrides.get("direction", base.direction),
        assets=overrides.get("assets", base.assets),
        design_plan=overrides.get("design_plan", base.design_plan),
        design_plan_qa=overrides.get("design_plan_qa", base.design_plan_qa),
        render_manifest=overrides.get("render_manifest", base.render_manifest),
    )


def _find(result, rule, *, page_id=None, element_id=None, atom_id=None):
    matches = [
        issue
        for issue in result.issues
        if issue.rule == rule
        and (page_id is None or issue.page_id == page_id)
        and (element_id is None or issue.element_id == element_id)
        and (atom_id is None or issue.atom_id == atom_id)
    ]
    return matches[0] if matches else None


def _replace_probe(manifest: RenderManifest, page_id: str, element_id: str, **updates) -> RenderManifest:
    new_pages = []
    for page in manifest.pages:
        if page.page_id != page_id:
            new_pages.append(page)
            continue
        probes = tuple(
            probe.model_copy(update=updates) if probe.element_id == element_id else probe
            for probe in page.element_probes
        )
        new_pages.append(page.model_copy(update={"element_probes": probes}))
    return manifest.model_copy(update={"pages": tuple(new_pages)})


# --- passing base ---------------------------------------------------------

def test_valid_render_passes(tmp_path):
    result = evaluate_render(_inputs(tmp_path))

    assert result.passed is True
    assert result.issues == ()
    assert result.content_attestation is True
    assert result.geometry_attestation is True
    assert result.asset_attestation is True
    assert result.render_manifest_sha256 == canonical_sha256(
        _inputs(tmp_path).render_manifest
    )


def test_valid_render_with_image_passes(tmp_path):
    result = evaluate_render(_inputs(tmp_path, include_image=True))

    assert result.passed is True
    assert result.issues == ()


# --- manifest hash bindings -----------------------------------------------

def test_design_plan_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = base.render_manifest.model_copy(update={"design_plan_sha256": "0" * 64})

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.design_plan_hash_mismatch")
    assert issue is not None
    assert result.content_attestation is False


def test_atom_set_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = base.render_manifest.model_copy(update={"content_atom_set_sha256": "1" * 64})

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.atom_set_hash_mismatch")
    assert issue is not None
    assert result.content_attestation is False


def test_asset_manifest_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    manifest = base.render_manifest.model_copy(update={"asset_manifest_sha256": "2" * 64})

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.manifest_hash_mismatch")
    assert issue is not None
    assert result.asset_attestation is False


def test_design_plan_qa_not_passing_fails(tmp_path):
    base = _inputs(tmp_path)
    qa = DesignPlanQAResult(
        passed=False,
        issues=(
            {
                "rule": "coverage",
                "message": "missing",
                "repair_instruction": "fix",
                "atom_id": "atom-1",
            },
        ),
        design_plan_sha256=canonical_sha256(base.design_plan),
        content_coverage_attestation=False,
        family_attestation=True,
        asset_binding_attestation=True,
    )

    result = evaluate_render(_copy_inputs(base, design_plan_qa=qa))

    assert result.passed is False
    issue = _find(result, "content.design_plan_qa_not_passing")
    assert issue is not None
    assert result.content_attestation is False


def test_design_plan_qa_hash_stale_fails(tmp_path):
    base = _inputs(tmp_path)
    stale = base.design_plan_qa.model_copy(update={"design_plan_sha256": "3" * 64})

    result = evaluate_render(_copy_inputs(base, design_plan_qa=stale))

    assert result.passed is False
    issue = _find(result, "content.design_plan_qa_hash_stale")
    assert issue is not None


# --- page files / order / canvas ------------------------------------------

def test_page_order_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    # Swap two page_ids-in-sequence so the manifest order disagrees with the plan.
    pages = list(base.render_manifest.pages)
    pages[0], pages[1] = pages[1], pages[0]
    manifest = base.render_manifest.model_copy(update={"pages": tuple(pages)})

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.page_order_mismatch")
    assert issue is not None
    assert result.content_attestation is False


def test_page_count_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    # Drop the last rendered page (forge past schema min_length via model_copy).
    manifest = base.render_manifest.model_copy(update={"pages": base.render_manifest.pages[:-1]})

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.page_count_mismatch")
    assert issue is not None


def test_page_file_missing_fails(tmp_path):
    base = _inputs(tmp_path)
    Path(base.render_manifest.pages[0].path).unlink()

    result = evaluate_render(_copy_inputs(base))

    assert result.passed is False
    issue = _find(result, "content.page_file_missing", page_id="page-1")
    assert issue is not None


def test_page_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    # Rewrite the page PNG with different bytes but keep the stale declared hash.
    page_path = Path(base.render_manifest.pages[1].path)
    page_path.write_bytes(_png_bytes(color="#DEDEDE"))

    result = evaluate_render(_copy_inputs(base))

    assert result.passed is False
    issue = _find(result, "content.page_hash_mismatch", page_id="page-2")
    assert issue is not None


def test_page_png_dimensions_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    page_path = Path(base.render_manifest.pages[2].path)
    payload = _png_bytes(1080, 1080)
    page_path.write_bytes(payload)
    page = base.render_manifest.pages[2].model_copy(
        update={"sha256": hashlib.sha256(payload).hexdigest()}
    )
    manifest = base.render_manifest.model_copy(
        update={"pages": tuple(base.render_manifest.pages[:2]) + (page,) + tuple(base.render_manifest.pages[3:])}
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.page_png_dimensions_mismatch", page_id="page-3")
    assert issue is not None


def test_contact_sheet_missing_fails(tmp_path):
    base = _inputs(tmp_path)
    Path(base.render_manifest.contact_sheet_path).unlink()

    result = evaluate_render(_copy_inputs(base))

    assert result.passed is False
    issue = _find(result, "asset.contact_sheet_missing")
    assert issue is not None
    assert result.asset_attestation is False


def test_contact_sheet_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    sheet_path = Path(base.render_manifest.contact_sheet_path)
    sheet_path.write_bytes(_png_bytes(width=1320, height=1145, color="#C0C0C0"))

    result = evaluate_render(_copy_inputs(base))

    assert result.passed is False
    issue = _find(result, "asset.contact_sheet_hash_mismatch")
    assert issue is not None


def test_source_asset_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    manifest = base.render_manifest.model_copy(
        update={
            "source_asset_sha256": {
                **base.render_manifest.source_asset_sha256,
                "asset-image": "e" * 64,
            }
        }
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.source_asset_hash_mismatch")
    assert issue is not None


def test_source_asset_file_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    # Tamper the asset file on disk so its byte hash disagrees with the manifest
    # entry (which still matches the AssetManifestItem's declared sha256).
    asset_path = Path(base.assets.items[0].local_path)
    asset_path.write_bytes(_png_bytes(color="#123456"))

    result = evaluate_render(_copy_inputs(base))

    assert result.passed is False
    issue = _find(result, "asset.source_asset_file_hash_mismatch")
    assert issue is not None


# --- element probes: missing / extra --------------------------------------

def test_missing_probe_fails(tmp_path):
    base = _inputs(tmp_path)
    # Remove the only probe from page-2.
    page = base.render_manifest.pages[1]
    empty = page.model_copy(update={"element_probes": ()})  # forge past min_length=1
    manifest = base.render_manifest.model_copy(
        update={"pages": tuple(base.render_manifest.pages[:1]) + (empty,) + tuple(base.render_manifest.pages[2:])}
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.missing_probe", page_id="page-2", element_id="text-page-2")
    assert issue is not None
    assert result.geometry_attestation is False


def test_extra_probe_fails(tmp_path):
    base = _inputs(tmp_path)
    extra = _text_probe("page-1", "fragment-1", base.direction.content_fragments[0].text).model_copy(
        update={"element_id": "text-ghost"}
    )
    page = base.render_manifest.pages[0]
    page = page.model_copy(update={"element_probes": page.element_probes + (extra,)})
    manifest = base.render_manifest.model_copy(
        update={"pages": (page,) + tuple(base.render_manifest.pages[1:])}
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.extra_probe", page_id="page-1", element_id="text-ghost")
    assert issue is not None


# --- geometry: clipping / overflow / bounds -------------------------------

def test_overflow_probe_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", overflow=True)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.overflow", page_id="page-1", element_id="text-page-1")
    assert issue is not None


def test_ink_clipped_probe_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-2", "text-page-2", ink_clipped=True)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.ink_clipped", page_id="page-2", element_id="text-page-2")
    assert issue is not None


def test_layout_clipped_probe_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-3", "text-page-3", layout_clipped=True)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.layout_clipped", page_id="page-3", element_id="text-page-3")
    assert issue is not None


def test_off_canvas_box_fails(tmp_path):
    base = _inputs(tmp_path)
    off_canvas = Box(x=900, y=120, width=904, height=160)  # right edge = 1804 > 1080
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", actual_box=off_canvas)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.box_out_of_bounds", page_id="page-1", element_id="text-page-1")
    assert issue is not None


def test_unintended_overlap_fails(tmp_path):
    base = _inputs(tmp_path)
    # Add a second text element + probe on page-1 that overlaps the first.
    overlapping = TextElement(
        element_id="text-overlay",
        layer=2,
        box=Box(x=88, y=140, width=904, height=160),  # overlaps text-page-1 box
        content_ref="fragment-1",
        style=TextStyle(
            font_role="body",
            font_size=28,
            line_height=1.45,
            color=_INK,
            align="left",
            weight=500,
        ),
    )
    plan = base.design_plan.model_copy(
        update={
            "pages": tuple(
                page.model_copy(update={"elements": page.elements + (overlapping,)})
                if page.page_id == "page-1"
                else page
                for page in base.design_plan.pages
            )
        }
    )
    extra_probe = RenderedElementProbe(
        element_id="text-overlay",
        kind="text",
        actual_box=Box(x=88, y=140, width=904, height=160),
        computed_font_family="Test Body",
        computed_font_size=28.0,
        computed_line_height=40.6,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=_INK_ON_BG,
        content_ref="fragment-1",
        asset_ref=None,
        rasterized_text_sha256=sha256_text(base.direction.content_fragments[0].text),
        rendered_asset_sha256=None,
    )
    page = base.render_manifest.pages[0]
    page = page.model_copy(update={"element_probes": page.element_probes + (extra_probe,)})
    manifest = base.render_manifest.model_copy(
        update={"pages": (page,) + tuple(base.render_manifest.pages[1:])}
    )

    result = evaluate_render(_copy_inputs(base, design_plan=plan, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.unintended_overlap", page_id="page-1")
    assert issue is not None


# --- typography: undersized font / low contrast ---------------------------

def test_undersized_font_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", computed_font_size=18.0)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.undersized_font", page_id="page-1", element_id="text-page-1")
    assert issue is not None


def test_low_contrast_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", contrast_ratio=2.0)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "geometry.low_contrast", page_id="page-1", element_id="text-page-1")
    assert issue is not None
    assert "4.5" in issue.message


# --- text attestation -----------------------------------------------------

def test_rasterized_text_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(
        base.render_manifest,
        "page-1",
        "text-page-1",
        rasterized_text_sha256="a" * 64,
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.rasterized_text_hash_mismatch", page_id="page-1", element_id="text-page-1")
    assert issue is not None
    assert result.content_attestation is False


def test_unknown_content_ref_fails(tmp_path):
    base = _inputs(tmp_path)
    manifest = _replace_probe(
        base.render_manifest,
        "page-1",
        "text-page-1",
        content_ref="fragment-unknown",
        rasterized_text_sha256=sha256_text("whatever"),
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "content.unknown_content_ref", page_id="page-1", element_id="text-page-1")
    assert issue is not None


def test_forbidden_visible_label_fails(tmp_path):
    forbidden = "免责声明：本内容仅供参考。"
    atoms = (
        ContentAtom(atom_id="atom-1", text=forbidden, role="paragraph", sha256=sha256_text(forbidden)),
    ) + tuple(
        ContentAtom(
            atom_id=f"atom-{i}",
            text=f"渲染QA第{i}页文字。",
            role="paragraph",
            sha256=sha256_text(f"渲染QA第{i}页文字。"),
        )
        for i in range(2, _PAGE_COUNT + 1)
    )
    atom_set = ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256([atom.model_dump(mode="json") for atom in atoms]),
    )
    direction = _direction(atom_set)
    manifest = AssetManifest(items=())
    design_plan = _design_plan(direction, atom_set, manifest)
    inputs = _inputs(
        tmp_path,
        atom_set=atom_set,
        direction=direction,
        manifest=manifest,
        design_plan=design_plan,
    )

    result = evaluate_render(inputs)

    assert result.passed is False
    issue = _find(result, "content.forbidden_visible_label", page_id="page-1", atom_id="atom-1")
    assert issue is not None


# --- image crop / focal point / asset hash --------------------------------

def test_image_rendered_hash_mismatch_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    manifest = _replace_probe(
        base.render_manifest,
        "page-1",
        "image-page-1",
        rendered_asset_sha256="b" * 64,
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.rendered_hash_mismatch", page_id="page-1", element_id="image-page-1")
    assert issue is not None
    assert result.asset_attestation is False


def test_image_focal_point_mismatch_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    manifest = _replace_probe(
        base.render_manifest,
        "page-1",
        "image-page-1",
        actual_focal_point=(0.9, 0.1),
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.focal_point_mismatch", page_id="page-1", element_id="image-page-1")
    assert issue is not None


def test_image_unknown_asset_ref_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    manifest = _replace_probe(
        base.render_manifest,
        "page-1",
        "image-page-1",
        asset_ref="asset-missing",
        rendered_asset_sha256=base.assets.items[0].sha256,
    )

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.unknown_asset_ref", page_id="page-1", element_id="image-page-1")
    assert issue is not None


def test_unrendered_approved_asset_fails(tmp_path):
    base = _inputs(tmp_path, include_image=True)
    # Drop the image element + image probe so the approved asset is never rendered.
    plan_pages = []
    for page in base.design_plan.pages:
        if page.page_id == "page-1":
            plan_pages.append(
                page.model_copy(
                    update={"elements": tuple(el for el in page.elements if not isinstance(el, ImageElement))}
                )
            )
        else:
            plan_pages.append(page)
    plan = base.design_plan.model_copy(update={"pages": tuple(plan_pages)})
    rm_page = base.render_manifest.pages[0]
    rm_page = rm_page.model_copy(
        update={"element_probes": tuple(p for p in rm_page.element_probes if p.kind != "image")}
    )
    manifest = base.render_manifest.model_copy(
        update={"pages": (rm_page,) + tuple(base.render_manifest.pages[1:])}
    )

    result = evaluate_render(_copy_inputs(base, design_plan=plan, render_manifest=manifest))

    assert result.passed is False
    issue = _find(result, "asset.unrendered_asset", page_id="page-1")
    assert issue is not None


# --- determinism / ordering ------------------------------------------------

def test_issues_are_deterministic_in_order(tmp_path):
    base = _inputs(tmp_path)
    # Introduce two independent issues: undersized font on page-1, low contrast on page-2.
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", computed_font_size=18.0)
    manifest = _replace_probe(manifest, "page-2", "text-page-2", contrast_ratio=2.0)
    inputs = _copy_inputs(base, render_manifest=manifest)

    first = evaluate_render(inputs)
    second = evaluate_render(inputs)

    assert first.passed is False
    assert [i.rule for i in first.issues] == [i.rule for i in second.issues]
    assert first.issues == second.issues


# --- 3-strike budget (pure boundary) --------------------------------------

def test_three_strike_budget_is_three():
    assert MAX_RENDER_QA_FAILURES == 3


def test_three_strike_budget_exhausts_on_third_failure():
    # A fresh failure with 0 or 1 prior failures is recoverable; the third
    # failure (2 prior + this one) exhausts the budget and must interrupt.
    assert render_qa_exhausted(0) is False
    assert render_qa_exhausted(1) is False
    assert render_qa_exhausted(2) is True


def test_passing_result_is_never_force_passed(tmp_path):
    # A failing fixture must produce passed=False regardless of budget; the gate
    # never force-passes.
    base = _inputs(tmp_path)
    manifest = _replace_probe(base.render_manifest, "page-1", "text-page-1", overflow=True)

    result = evaluate_render(_copy_inputs(base, render_manifest=manifest))

    assert result.passed is False
    assert result.issues  # independently enforced by the RenderQAResult validator
