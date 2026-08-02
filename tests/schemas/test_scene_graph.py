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
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)


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


def make_asset_manifest(**item_updates) -> AssetManifest:
    item = AssetManifestItem(
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
    )
    if item_updates:
        item = item.model_copy(update=item_updates)
    return AssetManifest(
        items=(item,),
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


def make_direction_plan(*, with_asset: bool = False) -> VisualDirectionPlan:
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
            asset_directive_ids=("directive-1",)
            if with_asset and index == 1
            else (),
        )
        for index in range(1, 6)
    )
    directives = (
        (
            AssetDirective(
                directive_id="directive-1",
                page_id="page-1",
                role="skin_example",
                required=True,
                preferred_source="search",
                fallback_source="none",
                query_or_prompt="healthy skin close-up",
                orientation="portrait",
                min_width=1080,
                min_height=1440,
            ),
        )
        if with_asset
        else ()
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
        asset_directives=directives,
    )


def make_design_plan(
    *,
    direction: VisualDirectionPlan | None = None,
    atom_set: ContentAtomSet | None = None,
    asset_manifest: AssetManifest | None = None,
    include_image: bool = False,
    **updates,
) -> CarouselDesignPlan:
    direction = direction or make_direction_plan(with_asset=include_image)
    atom_set = atom_set or make_atom_set()
    asset_manifest = asset_manifest or make_asset_manifest()
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
                *(
                    (ImageElement.model_validate(make_image_element_payload()),)
                    if include_image and index == 1
                    else ()
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


def test_scene_rejects_html_field():
    adapter = TypeAdapter(SceneElement)
    payload = {**make_text_element_payload(), "html": "<strong>copy</strong>"}

    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python(payload)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("text", "html")
    assert error["type"] == "extra_forbidden"
    assert error["msg"] == "Extra inputs are not permitted"


def test_scene_rejects_css_field():
    adapter = TypeAdapter(SceneElement)
    payload = {**make_text_element_payload(), "css": "display:grid"}

    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python(payload)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("text", "css")
    assert error["type"] == "extra_forbidden"
    assert error["msg"] == "Extra inputs are not permitted"


def test_scene_rejects_unknown_icon():
    adapter = TypeAdapter(SceneElement)
    payload = {
        "kind": "icon",
        "element_id": "unknown-icon",
        "layer": 3,
        "box": {"x": 10, "y": 10, "width": 40, "height": 40},
        "icon": "brand-logo",
        "color": "#111111",
    }

    with pytest.raises(ValidationError) as exc_info:
        adapter.validate_python(payload)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("icon", "icon")
    assert error["type"] == "literal_error"
    assert error["ctx"]["expected"] == (
        "'arrow', 'check', 'cross', 'sparkle', 'dot' or 'bracket'"
    )


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


def test_design_plan_pages_must_exactly_match_direction_pages():
    direction = make_direction_plan()
    plan = make_design_plan(direction=direction)
    pages = list(plan.pages)
    pages[0] = pages[0].model_copy(update={"page_id": "page-2"})
    pages[1] = pages[1].model_copy(update={"page_id": "page-1"})
    mismatched = plan.model_copy(update={"pages": tuple(pages)})

    with pytest.raises(
        ValueError,
        match="design plan pages must exactly match direction page IDs and sequences",
    ):
        mismatched.validate_bindings(direction, make_atom_set(), make_asset_manifest())


def test_design_plan_rejects_unknown_text_content_ref():
    plan = make_design_plan()
    pages = list(plan.pages)
    text = pages[0].elements[0].model_copy(update={"content_ref": "fragment-unknown"})
    pages[0] = pages[0].model_copy(update={"elements": (text,)})
    plan = plan.model_copy(update={"pages": tuple(pages)})

    with pytest.raises(
        ValueError,
        match="text element content reference is unknown: fragment-unknown",
    ):
        plan.validate_bindings(
            make_direction_plan(),
            make_atom_set(),
            make_asset_manifest(),
        )


def test_design_plan_rejects_cross_page_text_content_ref():
    plan = make_design_plan()
    pages = list(plan.pages)
    text = pages[0].elements[0].model_copy(update={"content_ref": "fragment-2"})
    pages[0] = pages[0].model_copy(update={"elements": (text,)})
    plan = plan.model_copy(update={"pages": tuple(pages)})

    with pytest.raises(
        ValueError,
        match=(
            "text element content reference belongs to a different page: fragment-2"
        ),
    ):
        plan.validate_bindings(
            make_direction_plan(),
            make_atom_set(),
            make_asset_manifest(),
        )


def test_design_plan_revalidates_direction_fragments_against_atoms():
    direction = make_direction_plan()
    fragments = list(direction.content_fragments)
    fragments[0] = fragments[0].model_copy(update={"text": "改"})
    invalid_direction = direction.model_copy(
        update={"content_fragments": tuple(fragments)}
    )
    plan = make_design_plan(
        direction=invalid_direction,
        direction_plan_sha256=canonical_sha256(invalid_direction),
    )

    with pytest.raises(
        ValueError,
        match="content fragment text must exactly match source atom slice",
    ):
        plan.validate_bindings(
            invalid_direction,
            make_atom_set(),
            make_asset_manifest(),
        )


def test_design_plan_rejects_unknown_image_asset_ref():
    direction = make_direction_plan(with_asset=True)
    plan = make_design_plan(direction=direction, include_image=True)
    pages = list(plan.pages)
    image = pages[0].elements[1].model_copy(update={"asset_ref": "asset-unknown"})
    pages[0] = pages[0].model_copy(
        update={"elements": (pages[0].elements[0], image)}
    )
    plan = plan.model_copy(update={"pages": tuple(pages)})

    with pytest.raises(
        ValueError,
        match="image element asset reference is unknown: asset-unknown",
    ):
        plan.validate_bindings(direction, make_atom_set(), make_asset_manifest())


def test_design_plan_rejects_unsafe_image_asset():
    direction = make_direction_plan(with_asset=True)
    assets = make_asset_manifest(security_status="rejected")
    plan = make_design_plan(
        direction=direction,
        asset_manifest=assets,
        include_image=True,
    )

    with pytest.raises(
        ValueError,
        match="image element asset is not security-approved: asset-1",
    ):
        plan.validate_bindings(direction, make_atom_set(), assets)


def test_design_plan_rejects_cross_page_image_asset():
    direction = make_direction_plan(with_asset=True)
    assets = make_asset_manifest(page_id="page-2")
    plan = make_design_plan(
        direction=direction,
        asset_manifest=assets,
        include_image=True,
    )

    with pytest.raises(
        ValueError,
        match="image element asset belongs to a different page: asset-1",
    ):
        plan.validate_bindings(direction, make_atom_set(), assets)


def test_design_plan_rejects_asset_directive_not_owned_by_page():
    direction = make_direction_plan(with_asset=True)
    assets = make_asset_manifest(directive_id="directive-unknown")
    plan = make_design_plan(
        direction=direction,
        asset_manifest=assets,
        include_image=True,
    )

    with pytest.raises(
        ValueError,
        match="image element asset directive is not owned by page: directive-unknown",
    ):
        plan.validate_bindings(direction, make_atom_set(), assets)


def test_asset_internal_provenance_is_deeply_immutable_and_serializable():
    assets = make_asset_manifest()

    with pytest.raises(
        TypeError,
        match="'mappingproxy' object does not support item assignment",
    ):
        assets.items[0].internal_provenance["source_url_hash"] = "d" * 64

    assert (
        assets.model_dump(mode="json")["items"][0]["internal_provenance"][
            "source_url_hash"
        ]
        == "c" * 64
    )
