"""Deterministic design-plan QA rule tests (Task 9).

Every test builds a minimal *valid* ``DesignPlanQAInputs`` and mutates exactly
one aspect, then asserts the exact failing ``rule`` (and the relevant location)
and that ``passed is False``. The valid base is exercised by
``test_valid_plan_passes``.
"""

from __future__ import annotations

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
from src.schemas.visual_style import FamilyStyleProfile
from src.visual_design.plan_qa import DesignPlanQAInputs, evaluate_design_plan


# --- builders -------------------------------------------------------------

def _atom_set(texts: tuple[str, ...] | None = None) -> ContentAtomSet:
    texts = texts or tuple(f"第{index}页的护肤编辑重点内容。" for index in range(1, 6))
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


def _fragments_for(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{atom.atom_id.split('-')[1]}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for atom in atom_set.atoms
    )


def _direction(
    atom_set: ContentAtomSet,
    *,
    family: str = "pink_red",
    directive: AssetDirective | None = None,
) -> VisualDirectionPlan:
    fragments = _fragments_for(atom_set)
    directives = (directive,) if directive is not None else ()
    return VisualDirectionPlan(
        template_family=family,
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑方向",
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("oversized type",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"visual-job-{index}",
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


def _empty_manifest() -> AssetManifest:
    return AssetManifest(items=())


def _asset_manifest(
    *,
    asset_id: str = "asset-1",
    directive_id: str = "directive-1",
    page_id: str = "page-1",
    security_status: str = "approved",
) -> AssetManifest:
    return AssetManifest(
        items=(
            AssetManifestItem(
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
                security_status=security_status,
                human_decision="pending",
                run_id="run-1",
                transaction_id="tx-1",
                internal_provenance={"provider": "pexels"},
            ),
        )
    )


def _asset_directive(
    *, directive_id: str = "directive-1", page_id: str = "page-1"
) -> AssetDirective:
    return AssetDirective(
        directive_id=directive_id,
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


def _style(family: str = "pink_red") -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family=family,
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
        prohibited_patterns=("thin low-contrast copy", "photoreal product claims"),
    )


def _text(
    element_id: str,
    content_ref: str,
    *,
    font_role: str = "body",
    font_size: float = 28,
    color: str = "#1A1A1A",
    weight: int = 400,
    box: Box | None = None,
    layer: int = 1,
    intentional_overlap_with: tuple[str, ...] = (),
) -> TextElement:
    return TextElement(
        element_id=element_id,
        layer=layer,
        intentional_overlap_with=intentional_overlap_with,
        box=box or Box(x=88, y=88, width=904, height=200),
        content_ref=content_ref,
        style=TextStyle(
            font_role=font_role,
            font_size=font_size,
            line_height=1.3,
            color=color,
            align="left",
            weight=weight,
        ),
    )


def _image(
    element_id: str,
    asset_id: str,
    *,
    box: Box | None = None,
    layer: int = 0,
) -> ImageElement:
    return ImageElement(
        element_id=element_id,
        layer=layer,
        box=box or Box(x=88, y=320, width=904, height=720),
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
    extra_page_elements: dict[str, tuple] | None = None,
    revision: int = 0,
) -> CarouselDesignPlan:
    extra_page_elements = extra_page_elements or {}
    pages: list[PageScene] = []
    for direction_page in direction.page_sequence:
        elements: list = [
            _text(f"text-{direction_page.page_id}", direction_page.fragment_ids[0])
        ]
        # Render the directive's asset on the page that OWNS the directive (per
        # the direction plan); the manifest item's own page_id may legitimately
        # differ, which is exactly what the wrong-page asset test exercises.
        if include_image and direction_page.asset_directive_ids and manifest.items:
            elements.append(
                _image(f"image-{direction_page.page_id}", manifest.items[0].asset_id)
            )
        elements.extend(extra_page_elements.get(direction_page.page_id, ()))
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background="#FFFFFF",
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=revision,
        pages=tuple(pages),
    )


def _inputs(
    *,
    atom_set: ContentAtomSet | None = None,
    direction: VisualDirectionPlan | None = None,
    manifest: AssetManifest | None = None,
    design_plan: CarouselDesignPlan | None = None,
    style: FamilyStyleProfile | None = None,
) -> DesignPlanQAInputs:
    atom_set = atom_set or _atom_set()
    direction = direction or _direction(atom_set)
    manifest = manifest if manifest is not None else _empty_manifest()
    design_plan = design_plan or _design_plan(direction, atom_set, manifest)
    style = style or _style(direction.template_family)
    return DesignPlanQAInputs(
        atoms=atom_set,
        direction=direction,
        assets=manifest,
        design_plan=design_plan,
        style=style,
    )


def _replace_element(
    plan: CarouselDesignPlan, page_id: str, element_id: str, **updates
) -> CarouselDesignPlan:
    new_pages = []
    for page in plan.pages:
        if page.page_id != page_id:
            new_pages.append(page)
            continue
        elements = tuple(
            el.model_copy(update=updates) if el.element_id == element_id else el
            for el in page.elements
        )
        new_pages.append(page.model_copy(update={"elements": elements}))
    return plan.model_copy(update={"pages": tuple(new_pages)})


def _replace_page(
    plan: CarouselDesignPlan, page_id: str, new_page: PageScene
) -> CarouselDesignPlan:
    return plan.model_copy(
        update={
            "pages": tuple(
                new_page if page.page_id == page_id else page for page in plan.pages
            )
        }
    )


def _add_page_element(
    plan: CarouselDesignPlan, page_id: str, element
) -> CarouselDesignPlan:
    new_pages = []
    for page in plan.pages:
        if page.page_id == page_id:
            new_pages.append(page.model_copy(update={"elements": page.elements + (element,)}))
        else:
            new_pages.append(page)
    return plan.model_copy(update={"pages": tuple(new_pages)})


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


# --- passing base ---------------------------------------------------------

def test_valid_plan_passes():
    result = evaluate_design_plan(_inputs())

    assert result.passed is True
    assert result.issues == ()
    assert result.content_coverage_attestation is True
    assert result.family_attestation is True
    assert result.asset_binding_attestation is True
    assert result.design_plan_sha256 == canonical_sha256(_inputs().design_plan)


def test_valid_plan_with_approved_asset_passes():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest()
    plan = _design_plan(direction, atom_set, manifest, include_image=True)

    result = evaluate_design_plan(
        _inputs(
            atom_set=atom_set,
            direction=direction,
            manifest=manifest,
            design_plan=plan,
        )
    )

    assert result.passed is True
    assert result.issues == ()


# --- hash bindings --------------------------------------------------------

def test_wrong_direction_hash_fails():
    base = _inputs()
    plan = base.design_plan.model_copy(update={"direction_plan_sha256": "0" * 64})

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "family.direction_hash_mismatch")
    assert issue is not None
    assert result.family_attestation is False


def test_wrong_content_hash_fails():
    base = _inputs()
    plan = base.design_plan.model_copy(update={"content_atom_set_sha256": "1" * 64})

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "content.hash_mismatch")
    assert issue is not None
    assert result.content_coverage_attestation is False


def test_wrong_asset_hash_fails():
    base = _inputs()
    plan = base.design_plan.model_copy(update={"asset_manifest_sha256": "2" * 64})

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "asset.hash_mismatch")
    assert issue is not None
    assert result.asset_binding_attestation is False


def _base_from(base: DesignPlanQAInputs) -> dict:
    """Reuse the base inputs' non-plan, non-style fields when only the plan changes.

    ``style`` is intentionally omitted so callers can override it (e.g. the
    family-mismatch test); when omitted, ``_inputs`` reconstructs the matching
    profile from the direction family.
    """
    return {
        "atom_set": base.atoms,
        "direction": base.direction,
        "manifest": base.assets,
    }


# --- content coverage -----------------------------------------------------

def test_unknown_content_ref_fails():
    base = _inputs()
    plan = _add_page_element(
        base.design_plan,
        "page-1",
        _text("text-unknown", "fragment-unknown", box=Box(x=88, y=300, width=904, height=150)),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "content.unknown_content_ref", page_id="page-1", element_id="text-unknown")
    assert issue is not None
    assert result.content_coverage_attestation is False


def test_duplicated_content_ref_fails():
    base = _inputs()
    plan = _add_page_element(
        base.design_plan,
        "page-1",
        _text("text-dup", "fragment-1", box=Box(x=88, y=300, width=904, height=150)),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "content.duplicated_content_ref", element_id="text-dup")
    assert issue is not None


def test_missing_fragment_fails():
    base = _inputs()
    # Replace page-5's text with a shape so fragment-5 (atom-5) is never rendered.
    shape_page = PageScene(
        page_id="page-5",
        sequence=5,
        background="#FFFFFF",
        elements=(
            ShapeElement(
                element_id="shape-page-5",
                layer=1,
                box=Box(x=88, y=1180, width=904, height=80),
                shape="rectangle",
                fill="#F4A7BF",
            ),
        ),
    )
    plan = _replace_page(base.design_plan, "page-5", shape_page)

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "content.missing_fragment", atom_id="atom-5")
    assert issue is not None
    # The issue must name the fragment's owning page so the design reviser is
    # permitted to patch that page to add the missing text element; otherwise
    # the reviser's "only named pages may change" rule forbids any edit.
    assert issue.page_id == "page-5"


def test_reordered_content_ref_within_page_fails():
    text_a = "第一页的前半段内容文字。第一页的后半段内容文字。"
    mid = len(text_a) // 2
    atom_set = ContentAtomSet(
        atoms=(
            ContentAtom(atom_id="atom-1", text=text_a, role="paragraph", sha256=sha256_text(text_a)),
            *(ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容文字。", role="paragraph",
                          sha256=sha256_text(f"第{i}页内容文字。")) for i in range(2, 6)),
        ),
        canonical_sha256=canonical_sha256(
            [ContentAtom(atom_id="atom-1", text=text_a, role="paragraph",
                         sha256=sha256_text(text_a)).model_dump(mode="json")]
            + [ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容文字。", role="paragraph",
                           sha256=sha256_text(f"第{i}页内容文字。")).model_dump(mode="json")
               for i in range(2, 6)]
        ),
    )
    fragments = (
        ContentFragment(fragment_id="fragment-1a", source_atom_id="atom-1", start=0, end=mid, text=text_a[:mid]),
        ContentFragment(fragment_id="fragment-1b", source_atom_id="atom-1", start=mid, end=len(text_a), text=text_a[mid:]),
        *(ContentFragment(fragment_id=f"fragment-{i}", source_atom_id=f"atom-{i}", start=0,
                          end=len(f"第{i}页内容文字。"), text=f"第{i}页内容文字。") for i in range(2, 6)),
    )
    direction = VisualDirectionPlan(
        template_family="pink_red",
        page_count=5,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="direction",
        palette=("#F4A7BF", "#DC2333", "#FFF7F8"),
        typography_direction={"display": "x"},
        motifs=("oversized type",),
        content_fragments=fragments,
        page_sequence=(
            PageDirection(page_id="page-1", sequence=1, purpose="p1", visual_job="job-1",
                          fragment_ids=("fragment-1a", "fragment-1b")),
            *(PageDirection(page_id=f"page-{i}", sequence=i, purpose=f"p{i}", visual_job=f"job-{i}",
                            fragment_ids=(f"fragment-{i}",)) for i in range(2, 6)),
        ),
        asset_directives=(),
    )
    # Render fragment-1b BEFORE fragment-1a within page-1.
    pages = []
    for page in direction.page_sequence:
        if page.page_id == "page-1":
            elements = (
                _text("text-1b", "fragment-1b", box=Box(x=88, y=88, width=904, height=150)),
                _text("text-1a", "fragment-1a", box=Box(x=88, y=260, width=904, height=150)),
            )
        else:
            elements = (_text(f"text-{page.page_id}", page.fragment_ids[0]),)
        pages.append(PageScene(page_id=page.page_id, sequence=page.sequence, background="#FFFFFF", elements=elements))
    plan = CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(_empty_manifest()),
        revision=0,
        pages=tuple(pages),
    )

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "content.reordered_content_ref", page_id="page-1")
    assert issue is not None


# --- asset bindings -------------------------------------------------------

def _asset_base():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest()
    plan = _design_plan(direction, atom_set, manifest, include_image=True)
    return _inputs(atom_set=atom_set, direction=direction, manifest=manifest, design_plan=plan)


def test_unknown_asset_ref_fails():
    base = _asset_base()
    plan = _replace_element(base.design_plan, "page-1", "image-page-1", asset_ref="asset-missing")

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "asset.unknown_asset_ref", page_id="page-1", element_id="image-page-1")
    assert issue is not None
    assert result.asset_binding_attestation is False


def test_unapproved_asset_fails():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest(security_status="rejected")
    plan = _design_plan(direction, atom_set, manifest, include_image=True)

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, manifest=manifest, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "asset.unapproved_asset", page_id="page-1", element_id="image-page-1")
    assert issue is not None


def test_wrong_page_asset_fails():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest(page_id="page-2")
    plan = _design_plan(direction, atom_set, manifest, include_image=True)

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, manifest=manifest, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "asset.wrong_page_asset", page_id="page-1", element_id="image-page-1")
    assert issue is not None


def test_asset_directive_not_owned_fails():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest(directive_id="directive-orphan")
    plan = _design_plan(direction, atom_set, manifest, include_image=True)

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, manifest=manifest, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "asset.directive_not_owned", page_id="page-1", element_id="image-page-1")
    assert issue is not None


def test_unrendered_approved_asset_fails():
    atom_set = _atom_set()
    directive = _asset_directive()
    direction = _direction(atom_set, directive=directive)
    manifest = _asset_manifest()
    # No image element anywhere -> approved asset is dropped.
    plan = _design_plan(direction, atom_set, manifest, include_image=False)

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, manifest=manifest, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "asset.unrendered_asset", page_id="page-1")
    assert issue is not None


# --- geometry -------------------------------------------------------------

def test_box_out_of_bounds_fails():
    base = _inputs()
    plan = _add_page_element(
        base.design_plan,
        "page-1",
        ShapeElement(
            element_id="shape-overflow",
            layer=2,
            box=Box(x=88, y=1380, width=904, height=160),  # y+height = 1540 > 1440
            shape="rectangle",
            fill="#F4A7BF",
        ),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "geometry.box_out_of_bounds", element_id="shape-overflow")
    assert issue is not None


def test_safe_margin_violation_fails():
    base = _inputs()
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        box=Box(x=40, y=88, width=904, height=200),  # x=40 < 84
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "geometry.safe_margin_violation", element_id="text-page-1")
    assert issue is not None


def test_long_text_at_display_font_in_small_box_flags_overflow_estimate():
    base = _inputs()
    # A full sentence set in 72px display type inside a narrow badge cannot fit
    # its box; this must be caught statically before it reaches the renderer.
    overflowing = _text(
        "num-badge-1",
        "fragment-1",
        font_role="display",
        font_size=72,
        box=Box(x=520, y=190, width=180, height=100),
    )
    plan = _add_page_element(base.design_plan, "page-1", overflowing)

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(
        result, "geometry.text_overflow_estimate", element_id="num-badge-1"
    )
    assert issue is not None


def test_short_text_at_display_font_in_wide_box_does_not_flag_overflow():
    base = _inputs()
    # A short display label in a box sized for it must NOT be flagged.
    fits = _text(
        "title-1",
        "fragment-1",
        font_role="display",
        font_size=72,
        box=Box(x=88, y=88, width=904, height=200),
    )
    plan = _add_page_element(base.design_plan, "page-1", fits)

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert _find(result, "geometry.text_overflow_estimate", element_id="title-1") is None


def test_unintended_overlap_fails():
    base = _inputs()
    plan = _add_page_element(
        base.design_plan,
        "page-1",
        ShapeElement(
            element_id="shape-overlap",
            layer=2,
            box=Box(x=88, y=100, width=904, height=200),  # overlaps text box
            shape="rectangle",
            fill="#F4A7BF",
        ),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "geometry.unintended_overlap", page_id="page-1")
    assert issue is not None
    assert issue.element_id in {"text-page-1", "shape-overlap"}


def test_intentional_overlap_does_not_fail():
    base = _inputs()
    text = _text(
        "text-page-1",
        "fragment-1",
        intentional_overlap_with=("shape-overlap",),
    )
    page1 = PageScene(
        page_id="page-1",
        sequence=1,
        background="#FFFFFF",
        elements=(
            text,
            ShapeElement(
                element_id="shape-overlap",
                layer=2,
                box=Box(x=88, y=100, width=904, height=200),
                shape="rectangle",
                fill="#F4A7BF",
            ),
        ),
    )
    plan = _replace_page(base.design_plan, "page-1", page1)

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert _find(result, "geometry.unintended_overlap") is None
    assert result.passed is True


# --- typography -----------------------------------------------------------

def test_undersized_body_text_fails():
    base = _inputs()
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        style=base.design_plan.pages[0].elements[0].style.model_copy(update={"font_size": 20}),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "typography.undersized_body_text", element_id="text-page-1")
    assert issue is not None


def test_undersized_display_text_fails():
    base = _inputs()
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        style=base.design_plan.pages[0].elements[0].style.model_copy(
            update={"font_role": "display", "font_size": 28}
        ),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "typography.undersized_display_text", element_id="text-page-1")
    assert issue is not None


def test_insufficient_contrast_normal_text_fails():
    base = _inputs()
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        style=base.design_plan.pages[0].elements[0].style.model_copy(update={"color": "#999999"}),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "typography.insufficient_contrast", element_id="text-page-1")
    assert issue is not None
    assert "4.5" in issue.message


def test_insufficient_contrast_large_text_fails():
    base = _inputs()
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        style=base.design_plan.pages[0].elements[0].style.model_copy(
            update={"font_role": "display", "font_size": 40, "color": "#AAAAAA"}
        ),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "typography.insufficient_contrast", element_id="text-page-1")
    assert issue is not None
    assert "3.0" in issue.message


def test_contrast_uses_shape_behind_text_not_page_background():
    """Regression: a text element whose color matches the PAGE background but
    sits on a contrasting shape/card must NOT be flagged. The contrast check
    must use the topmost shape painted behind the text, not page.background."""
    base = _inputs()
    base_style = base.design_plan.pages[0].elements[0].style
    dark_card = ShapeElement(
        element_id="card-page-1",
        layer=0,  # painted behind the text (text sits at layer 1)
        box=Box(x=80, y=80, width=920, height=220),  # overlaps the text box
        shape="rectangle",
        fill="#0E5A5A",
    )
    plan = _add_page_element(base.design_plan, "page-1", dark_card)
    # Text color == page background (#FFFFFF): against the page this is 1:1
    # (would false-fail); against the dark card it is high contrast.
    plan = _replace_element(
        plan,
        "page-1",
        "text-page-1",
        style=base_style.model_copy(update={"color": "#FFFFFF"}),
        intentional_overlap_with=("card-page-1",),
    )

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert (
        _find(result, "typography.insufficient_contrast", element_id="text-page-1")
        is None
    )


# --- family envelope ------------------------------------------------------

def test_family_mismatch_fails():
    base = _inputs()
    result = evaluate_design_plan(_inputs(style=_style("deep_teal"), **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "family.mismatch")
    assert issue is not None
    assert result.family_attestation is False


def test_forbidden_visible_label_atom_fails():
    text = "免责声明：本内容仅供参考。"
    atom_set = ContentAtomSet(
        atoms=(
            ContentAtom(atom_id="atom-1", text=text, role="paragraph", sha256=sha256_text(text)),
            *(ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容。", role="paragraph",
                          sha256=sha256_text(f"第{i}页内容。")) for i in range(2, 6)),
        ),
        canonical_sha256=canonical_sha256(
            [ContentAtom(atom_id="atom-1", text=text, role="paragraph",
                         sha256=sha256_text(text)).model_dump(mode="json")]
            + [ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容。", role="paragraph",
                           sha256=sha256_text(f"第{i}页内容。")).model_dump(mode="json")
               for i in range(2, 6)]
        ),
    )
    direction = _direction(atom_set)
    plan = _design_plan(direction, atom_set, _empty_manifest())

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "family.forbidden_visible_label", page_id="page-1", atom_id="atom-1")
    assert issue is not None


def test_script_like_atom_content_fails():
    text = "正常文字<script>alert(1)</script>结尾"
    atom_set = ContentAtomSet(
        atoms=(
            ContentAtom(atom_id="atom-1", text=text, role="paragraph", sha256=sha256_text(text)),
            *(ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容。", role="paragraph",
                          sha256=sha256_text(f"第{i}页内容。")) for i in range(2, 6)),
        ),
        canonical_sha256=canonical_sha256(
            [ContentAtom(atom_id="atom-1", text=text, role="paragraph",
                         sha256=sha256_text(text)).model_dump(mode="json")]
            + [ContentAtom(atom_id=f"atom-{i}", text=f"第{i}页内容。", role="paragraph",
                           sha256=sha256_text(f"第{i}页内容。")).model_dump(mode="json")
               for i in range(2, 6)]
        ),
    )
    direction = _direction(atom_set)
    plan = _design_plan(direction, atom_set, _empty_manifest())

    result = evaluate_design_plan(
        _inputs(atom_set=atom_set, direction=direction, design_plan=plan)
    )

    assert result.passed is False
    issue = _find(result, "family.script_like_content", page_id="page-1", atom_id="atom-1")
    assert issue is not None


def test_page_count_below_minimum_fails():
    base = _inputs()
    # CarouselDesignPlan pins ``pages`` to min_length=5 at the schema layer, so
    # forge a 4-page plan past the validator (model_copy does not re-validate)
    # to confirm the QA gate does not rely on the schema alone.
    forged_pages = base.design_plan.pages[:4]
    plan = base.design_plan.model_copy(update={"pages": forged_pages})

    result = evaluate_design_plan(_inputs(design_plan=plan, **_base_from(base)))

    assert result.passed is False
    issue = _find(result, "family.page_count_out_of_range")
    assert issue is not None


# --- determinism ----------------------------------------------------------

def test_issues_are_deterministic_in_order():
    base = _inputs()
    # Introduce two independent issues on different pages.
    plan = _replace_element(
        base.design_plan,
        "page-1",
        "text-page-1",
        style=base.design_plan.pages[0].elements[0].style.model_copy(update={"font_size": 20}),
    )
    plan = _replace_element(
        plan,
        "page-2",
        "text-page-2",
        box=Box(x=40, y=88, width=904, height=200),
    )
    inputs = _inputs(design_plan=plan, **_base_from(base))

    first = evaluate_design_plan(inputs)
    second = evaluate_design_plan(inputs)

    assert first.passed is False
    assert [i.rule for i in first.issues] == [i.rule for i in second.issues]
    assert first.issues == second.issues
