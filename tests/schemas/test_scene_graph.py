import pytest
from pydantic import TypeAdapter, ValidationError

from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.scene_graph import (
    CarouselDesignPlan,
    IconElement,
    ImageElement,
    PageScene,
    SceneElement,
    TextElement,
)
from src.schemas.visual_director import PageDirection, VisualDirectionPlan


def make_text_element_payload() -> dict:
    return {
        "kind": "text",
        "element_id": "headline",
        "layer": 2,
        "box": {"x": 100, "y": 100, "width": 800, "height": 180},
        "content_ref": "fragment-1",
        "style": {
            "font_role": "display",
            "font_size": 64,
            "line_height": 1.2,
            "color": "#111111",
            "align": "left",
            "weight": 700,
        },
    }


def make_image_element_payload() -> dict:
    return {
        "kind": "image",
        "element_id": "hero-image",
        "layer": 1,
        "box": {"x": 80, "y": 360, "width": 920, "height": 760},
        "asset_ref": "asset-1",
        "fit": "cover",
        "focal_point": (0.5, 0.5),
        "corner_radius": 32,
    }


def make_asset_manifest() -> AssetManifest:
    return AssetManifest(
        items=(
            AssetManifestItem(
                asset_id="asset-1",
                directive_id="directive-1",
                page_id="page-1",
                source_kind="search",
                provider="approved-provider",
                license="commercial-use",
                local_path="transactions/run-1/asset-1.png",
                width=1200,
                height=1600,
                sha256="b" * 64,
                subject_focal_point=(0.5, 0.45),
                crop_guidance="keep face centered",
                security_status="approved",
                human_decision="pending",
                run_id="run-1",
                transaction_id="transaction-1",
                internal_provenance={"source_url_hash": "c" * 64},
            ),
        ),
    )


def make_atom_set() -> ContentAtomSet:
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(("一", "二", "三", "四", "五"), start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def make_direction_plan() -> VisualDirectionPlan:
    atom_set = make_atom_set()
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
    pages = tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"purpose-{index}",
            visual_job=f"job-{index}",
            fragment_ids=(f"fragment-{index}",),
        )
        for index in range(1, 6)
    )
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=5,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="Warm editorial skincare guide",
        palette=("#FFF0F3", "#C9184A"),
        typography_direction={"display": "high contrast"},
        motifs=("sparkle",),
        content_fragments=fragments,
        page_sequence=pages,
        asset_directives=(),
    )


def make_design_plan(**updates) -> CarouselDesignPlan:
    direction = make_direction_plan()
    atom_set = make_atom_set()
    asset_manifest = make_asset_manifest()
    pages = tuple(
        PageScene(
            page_id=f"page-{index}",
            sequence=index,
            background="#FFF0F3",
            elements=(
                TextElement.model_validate(
                    {
                        **make_text_element_payload(),
                        "element_id": f"headline-{index}",
                        "content_ref": f"fragment-{index}",
                    }
                ),
            ),
        )
        for index in range(1, 6)
    )
    payload = {
        "direction_plan_sha256": canonical_sha256(direction),
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "asset_manifest_sha256": canonical_sha256(asset_manifest),
        "revision": 0,
        "pages": pages,
    }
    payload.update(updates)
    return CarouselDesignPlan.model_validate(payload)


def test_text_element_rejects_embedded_visible_text():
    payload = {
        **make_text_element_payload(),
        "text": "模型擅自增加的文字",
    }
    with pytest.raises(ValidationError, match="extra"):
        TextElement.model_validate(payload)


def test_image_element_requires_asset_ref():
    payload = make_image_element_payload()
    payload.pop("asset_ref")

    with pytest.raises(ValidationError, match=r"asset_ref\n  Field required"):
        ImageElement.model_validate(payload)


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {**make_text_element_payload(), "html": "<strong>copy</strong>"},
        {**make_text_element_payload(), "css": "display:grid"},
        {
            "kind": "icon",
            "element_id": "unknown-icon",
            "layer": 3,
            "box": {"x": 10, "y": 10, "width": 40, "height": 40},
            "icon": "brand-logo",
            "color": "#111111",
        },
    ],
)
def test_scene_rejects_html_css_and_unknown_icons(invalid_payload):
    adapter = TypeAdapter(SceneElement)

    with pytest.raises(ValidationError, match="extra|Input should be"):
        adapter.validate_python(invalid_payload)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("direction_plan_sha256", "design plan direction hash does not match source"),
        (
            "content_atom_set_sha256",
            "design plan content atom set hash does not match source",
        ),
        ("asset_manifest_sha256", "design plan asset manifest hash does not match source"),
    ],
)
def test_design_plan_binds_all_source_hashes(field, message):
    plan = make_design_plan(**{field: "d" * 64})

    with pytest.raises(ValueError, match=message):
        plan.validate_bindings(
            make_direction_plan(),
            make_atom_set(),
            make_asset_manifest(),
        )
