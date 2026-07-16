from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.schemas.assets import (
    AssetManifest,
    AssetManifestItem,
    AssetRequirement,
    AssetSearchReport,
)
from src.schemas.content_contract import ContentContract
from src.schemas.content_lock import ContentLock
from src.schemas.decision import StoryboardVisibleText
from src.schemas.render_manifest import RenderedPage, RenderManifest
from src.schemas.storyboard import CarouselFrame, CarouselPayload
from src.schemas.visual_plan import VisualPlan


BASE_CONTRACT = {
    "audience": "通勤护肤人群",
    "trigger_situation": "早上护肤后局部卡粉",
    "decision_problem": "如何判断需要调整的面部区域",
    "first_screen_promise": "先看懂分区，再调整护肤步骤",
    "screenshot_asset": "面部分区保存卡",
    "proof_asset": "面部区域图",
    "visual_mode": "text_plus_real_proof",
}

ZONE_PLAN = {
    "design_system": "beauty_editorial_v2",
    "template_family": "deep_teal",
    "template_selection": {
        "template_family": "deep_teal",
        "score": 91,
        "reasons": ["diagnostic clarity"],
        "rejected_families": {
            "pink_red": ["lower diagnostic fit"],
            "soft_pink": ["lower contrast fit"],
            "coral_impact": ["lower tone fit"],
            "green_catalog": ["not an item collection"],
            "white_quote": ["not quote-led"],
        },
    },
    "narrative_form": "diagnostic_qa",
    "content_job": "diagnose_and_adjust",
    "frame_plan": [
        {
            "frame_id": "cover",
            "role": "cover",
            "page_archetype": "cover",
            "purpose": "建立问题与承诺",
            "allowed_density": ["sparse"],
            "asset_roles": ["beauty_subject"],
        },
        {
            "frame_id": "baseline",
            "role": "baseline",
            "page_archetype": "thesis",
            "purpose": "建立质地基线",
            "allowed_density": ["standard"],
            "asset_roles": ["product_texture"],
        },
        {
            "frame_id": "applicable-case",
            "role": "applicable_case",
            "page_archetype": "diagnostic",
            "purpose": "标出适用区域",
            "allowed_density": ["standard", "dense"],
            "asset_roles": ["face_map"],
        },
        {
            "frame_id": "zone-adjustment",
            "role": "zone_adjustment",
            "page_archetype": "explanation",
            "purpose": "展示分区调整",
            "allowed_density": ["standard"],
            "asset_roles": ["face_map"],
        },
        {
            "frame_id": "feedback",
            "role": "feedback_diagnosis",
            "page_archetype": "comparison",
            "purpose": "根据反馈诊断",
            "allowed_density": ["dense"],
            "asset_roles": ["comparison"],
        },
        {
            "frame_id": "save",
            "role": "save",
            "page_archetype": "save",
            "purpose": "提供保存参考",
            "allowed_density": ["standard", "dense"],
            "asset_roles": ["reference"],
        },
    ],
    "required_assets": [],
}

ASSET_REQUIREMENT = {
    "slot_id": "face-map",
    "role": "face_map",
    "page_archetype": "diagnostic",
    "min_width": 1080,
    "min_height": 1440,
    "context_tags": ["t-zone"],
}

ZONE_STORYBOARD = [
    {
        "frame_id": item["frame_id"],
        "role": item["role"],
        "page_archetype": item["page_archetype"],
        "content_density_hint": "auto" if index == 0 else "standard",
        "headline": "先看懂分区，再调整护肤步骤" if index == 0 else item["purpose"],
        "kicker": "分区护肤",
        "content_blocks": [
            {
                "block_type": "text",
                "body": item["purpose"],
            }
        ],
        "emphasis": ["分区"],
        "visual_slots": [
            {
                "slot_id": f'{item["frame_id"]}-visual',
                "role": item["asset_roles"][0],
                "semantic_tags": ["skincare"],
            }
        ],
        "footer": "按肤感微调",
    }
    for index, item in enumerate(ZONE_PLAN["frame_plan"])
]

CONTENT_LOCK = {
    "focus_keyword": "分区护肤",
    "topic": "通勤前的分区护肤",
    "topic_id": "topic-001",
    "angle": "按区域反馈调整",
    "angle_id": "angle-001",
    "target_group": "通勤护肤人群",
    "core_pain": "护肤后局部卡粉",
    "title": "分区护肤调整指南",
    "cover_copy": "先看懂分区",
    "first_screen_promise": "先看懂分区，再调整护肤步骤",
    "content": "根据不同区域的肤感调整用量与等待时间。",
    "hashtags": ["护肤", "通勤护肤"],
    "storyboards": ZONE_STORYBOARD,
    "canonical_sha256": "a" * 64,
}


def _frame_sequence(source, archetypes):
    frames = deepcopy(source[: len(archetypes)])
    for frame, archetype in zip(frames, archetypes, strict=True):
        frame["page_archetype"] = archetype
    return frames


def _render_pages(count=5):
    archetypes = [
        "cover",
        "thesis",
        "diagnostic",
        "explanation",
        "save",
        "steps",
        "checklist",
        "quote",
    ]
    return [
        {
            "frame_id": f"frame-{index}",
            "role": "cover" if index == 1 else f"detail-{index}",
            "page_archetype": archetype,
            "template_family": "deep_teal",
            "density": "standard",
            "composition_variant": f"diagnostic-{index}",
            "path": f"{index:02d}-frame.png",
            "width": 1080,
            "height": 1440,
            "sha256": f"{index:064x}",
            "probe": {
                "canvas_width": 1080,
                "canvas_height": 1440,
                "safe_margin": 84,
                "text_results": [
                    {
                        "role": "headline",
                        "text": "标题",
                        "visible": True,
                        "overflow": False,
                        "ink_clipped": False,
                        "layout_clipped": False,
                        "font_family": "Source Han Serif SC",
                        "font_size": 64,
                        "line_height": 74.88,
                        "line_count": 1,
                        "x": 84,
                        "y": 84,
                        "width": 400,
                        "height": 75,
                    }
                ],
                "asset_results": [],
                "issues": [],
            },
        }
        for index, archetype in enumerate(archetypes[:count], start=1)
    ]


def test_content_contract_requires_editorial_strategy_fields():
    with pytest.raises(ValidationError):
        ContentContract.model_validate(BASE_CONTRACT)


def test_content_contract_visual_family_does_not_imply_template_or_frame_count():
    contract_fields = {
        **BASE_CONTRACT,
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "face_zone_map",
        "primary_visual_subject": "face_map",
        "proof_mode": "diagram",
        "recommended_frame_count": 6,
    }
    face_map_contract = ContentContract.model_validate(contract_fields)
    editorial_contract = ContentContract.model_validate(
        {**contract_fields, "primary_visual_family": "beauty_editorial"}
    )
    plan = VisualPlan.model_validate(ZONE_PLAN)

    assert "template_family" not in ContentContract.model_fields
    assert (
        face_map_contract.recommended_frame_count
        == editorial_contract.recommended_frame_count
        == len(plan.frame_plan)
    )
    assert plan.template_family == "deep_teal"


def test_visual_plan_accepts_v2_template_archetypes_and_five_to_seven_frames():
    plan = VisualPlan.model_validate(ZONE_PLAN)
    assert plan.design_system == "beauty_editorial_v2"
    assert plan.template_family == "deep_teal"
    assert plan.template_selection.template_family == "deep_teal"
    assert plan.frame_plan[0].page_archetype == "cover"
    assert 5 <= len(plan.frame_plan) <= 7
    assert any(
        frame.page_archetype in {"save", "checklist", "comparison"}
        for frame in plan.frame_plan
    )
    assert plan.required_assets == []

    broken = deepcopy(ZONE_PLAN)
    broken["frame_plan"][1]["page_archetype"] = "freeform_html"
    with pytest.raises(ValidationError):
        VisualPlan.model_validate(broken)


def test_visual_plan_allows_content_driven_five_to_seven_page_counts():
    closing = {
        **ZONE_PLAN["frame_plan"][-1],
        "frame_id": "closing",
        "role": "closing",
        "page_archetype": "closing",
        "purpose": "收束内容",
    }
    seven_frames = [*ZONE_PLAN["frame_plan"], closing]

    for count in (5, 6, 7):
        plan = VisualPlan.model_validate(
            {**ZONE_PLAN, "frame_plan": seven_frames[:count]}
        )
        assert len(plan.frame_plan) == count

    with pytest.raises(ValidationError):
        VisualPlan.model_validate(
            {**ZONE_PLAN, "frame_plan": ZONE_PLAN["frame_plan"][:4]}
        )
    with pytest.raises(ValidationError):
        VisualPlan.model_validate(
            {
                **ZONE_PLAN,
                "frame_plan": [
                    *seven_frames,
                    {**closing, "frame_id": "extra"},
                ],
            }
        )


@pytest.mark.parametrize(
    "archetypes",
    [
        [
            "thesis",
            "diagnostic",
            "explanation",
            "comparison",
            "save",
        ],
        [
            "cover",
            "thesis",
            "diagnostic",
            "explanation",
            "closing",
        ],
    ],
    ids=["cover-first", "saveable-archetype"],
)
def test_visual_plan_requires_v2_frame_composition(archetypes):
    broken = deepcopy(ZONE_PLAN)
    broken["frame_plan"] = _frame_sequence(ZONE_PLAN["frame_plan"], archetypes)
    with pytest.raises(ValidationError):
        VisualPlan.model_validate(broken)


def test_carousel_frame_rejects_network_url_and_free_css():
    frame = deepcopy(ZONE_STORYBOARD[0])
    frame["visual_slots"][0]["network_url"] = "https://example.com/a.jpg"
    with pytest.raises(ValidationError):
        CarouselFrame.model_validate(frame)

    frame = deepcopy(ZONE_STORYBOARD[0])
    frame["free_css"] = "position: absolute"
    with pytest.raises(ValidationError):
        CarouselFrame.model_validate(frame)


def test_carousel_payload_requires_five_to_seven_frames():
    payload = CarouselPayload.model_validate({"storyboards": ZONE_STORYBOARD})
    assert len(payload.storyboards) == 6
    assert payload.storyboards[0].page_archetype == "cover"
    assert payload.storyboards[0].content_density_hint == "auto"
    assert payload.storyboards[1].content_density_hint == "standard"
    with pytest.raises(ValidationError):
        CarouselPayload.model_validate({"storyboards": ZONE_STORYBOARD[:4]})


def test_carousel_frame_density_hint_defaults_to_auto():
    frame = deepcopy(ZONE_STORYBOARD[0])
    frame.pop("content_density_hint")

    assert CarouselFrame.model_validate(frame).content_density_hint == "auto"


def test_carousel_payload_rejects_cross_frame_duplicate_visual_slot_id():
    frames = deepcopy(ZONE_STORYBOARD)
    frames[1]["visual_slots"][0]["slot_id"] = frames[0]["visual_slots"][0][
        "slot_id"
    ]

    with pytest.raises(ValidationError):
        CarouselPayload.model_validate({"storyboards": frames})


@pytest.mark.parametrize(
    "archetypes",
    [
        [
            "thesis",
            "diagnostic",
            "explanation",
            "comparison",
            "save",
        ],
        [
            "cover",
            "thesis",
            "diagnostic",
            "explanation",
            "closing",
        ],
    ],
    ids=["cover-first", "saveable-archetype"],
)
def test_carousel_payload_requires_v2_frame_composition(archetypes):
    frames = _frame_sequence(ZONE_STORYBOARD, archetypes)
    with pytest.raises(ValidationError):
        CarouselPayload.model_validate({"storyboards": frames})


def test_asset_contracts_use_page_archetype():
    requirement = AssetRequirement.model_validate(ASSET_REQUIREMENT)
    manifest_item = AssetManifestItem.model_validate(
        {
            "slot_id": "face-map",
            "role": "face_map",
            "page_archetype": "diagnostic",
            "status": "active",
            "path": "assets/face-map.png",
            "source_type": "bundled",
            "license": "project-owned",
            "width": 1080,
            "height": 1440,
            "sha256": "a" * 64,
        }
    )

    assert requirement.page_archetype == "diagnostic"
    assert manifest_item.page_archetype == "diagnostic"


def test_storyboard_visible_text_preserves_structural_metadata():
    visible = StoryboardVisibleText.model_validate(
        {
            "frame_id": "cover",
            "role": "cover",
            "page_archetype": "cover",
            "content_density_hint": "dense",
            "text_blocks": {"headline": "先看懂分区"},
        }
    )

    assert visible.page_archetype == "cover"
    assert visible.content_density_hint == "dense"


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            VisualPlan,
            {
                **ZONE_PLAN,
                "frame_plan": [
                    {**ZONE_PLAN["frame_plan"][0], "layout": "editorial_cover"},
                    *ZONE_PLAN["frame_plan"][1:],
                ],
            },
        ),
        (
            CarouselFrame,
            {**ZONE_STORYBOARD[0], "layout": "editorial_cover"},
        ),
        (
            AssetRequirement,
            {**ASSET_REQUIREMENT, "layout": "front_face_zone"},
        ),
        (
            AssetManifestItem,
            {
                "slot_id": "face-map",
                "role": "face_map",
                "page_archetype": "diagnostic",
                "layout": "front_face_zone",
                "status": "active",
                "path": "assets/face-map.png",
                "source_type": "bundled",
                "license": "project-owned",
                "width": 1080,
                "height": 1440,
                "sha256": "a" * 64,
            },
        ),
        (
            RenderedPage,
            {**_render_pages(1)[0], "layout": "editorial_cover"},
        ),
        (
            StoryboardVisibleText,
            {
                "frame_id": "cover",
                "role": "cover",
                "page_archetype": "cover",
                "layout": "editorial_cover",
            },
        ),
    ],
)
def test_modern_schemas_reject_legacy_layout(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_manifest_contracts_are_strict():
    search_report = AssetSearchReport.model_validate(
        {"search_triggered": False, "queries": [], "provider_reports": [], "selection_reasons": {}}
    )
    asset_manifest = AssetManifest.model_validate(
        {"items": [], "search_report": search_report.model_dump()}
    )
    render_manifest = RenderManifest.model_validate(
        {
            "pages": _render_pages(),
            "fonts": {"all_loaded": True, "computed_families": []},
            "contact_sheet_path": "contact-sheet.png",
            "contact_sheet_sha256": "f" * 64,
            "contact_sheet_page_sha256": [
                page["sha256"] for page in _render_pages()
            ],
            "source_asset_sha256": {},
        }
    )
    assert asset_manifest.search_report.search_triggered is False
    assert render_manifest.contact_sheet_path == "contact-sheet.png"
    assert render_manifest.pages[0].template_family == "deep_teal"
    assert render_manifest.pages[0].density == "standard"
    assert render_manifest.pages[0].composition_variant == "diagnostic-1"


def test_render_manifest_rejects_mixed_template_families():
    pages = _render_pages()
    pages[-1]["template_family"] = "soft_pink"

    with pytest.raises(
        ValidationError,
        match="all rendered pages must use one template family",
    ):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "f" * 64,
                "contact_sheet_page_sha256": [page["sha256"] for page in pages],
                "source_asset_sha256": {},
            }
        )


def test_render_manifest_requires_durable_page_probe_and_artifact_evidence():
    pages = _render_pages()
    for page in pages:
        page.pop("sha256")
        page.pop("probe")
    with pytest.raises(ValidationError):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "source_asset_sha256": {},
            }
        )


def test_page_probe_asset_slot_ids_are_unique():
    pages = _render_pages()
    geometry = {
        "slot_id": "cover-visual",
        "natural_width": 1080,
        "natural_height": 1440,
        "rendered_width": 360,
        "rendered_height": 480,
        "object_fit": "contain",
        "cropped": False,
        "aspect_ratio_error": 0,
    }
    pages[0]["probe"]["asset_results"] = [geometry, deepcopy(geometry)]

    with pytest.raises(ValidationError):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "f" * 64,
                "contact_sheet_page_sha256": [page["sha256"] for page in pages],
                "source_asset_sha256": {},
            }
        )


def test_contact_sheet_page_hash_binding_requires_strict_sha256_values():
    pages = _render_pages()
    hashes = [page["sha256"] for page in pages]
    hashes[2] = "not-a-sha256"

    with pytest.raises(ValidationError):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "f" * 64,
                "contact_sheet_page_sha256": hashes,
                "source_asset_sha256": {},
            }
        )


@pytest.mark.parametrize("count", [0, 4, 8])
def test_render_manifest_requires_five_to_seven_pages(count):
    pages = _render_pages(count)
    with pytest.raises(ValidationError):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "f" * 64,
                "contact_sheet_page_sha256": [page["sha256"] for page in pages],
                "source_asset_sha256": {},
            }
        )


@pytest.mark.parametrize(("field", "value"), [("width", 1079), ("height", 1441)])
def test_rendered_pages_require_exact_canvas_dimensions(field, value):
    pages = _render_pages()
    pages[0][field] = value
    with pytest.raises(ValidationError):
        RenderManifest.model_validate(
            {
                "pages": pages,
                "fonts": {"all_loaded": True, "computed_families": []},
                "contact_sheet_path": "contact-sheet.png",
                "contact_sheet_sha256": "f" * 64,
                "contact_sheet_page_sha256": [page["sha256"] for page in pages],
                "source_asset_sha256": {},
            }
        )


def test_content_lock_is_frozen():
    lock = ContentLock.model_validate(CONTENT_LOCK)
    with pytest.raises(ValidationError):
        lock.title = "另一个标题"


def test_content_lock_is_deeply_frozen_and_serializes_as_json_arrays_and_objects():
    lock = ContentLock.model_validate(CONTENT_LOCK)

    with pytest.raises((AttributeError, TypeError)):
        lock.hashtags.append("新标签")
    with pytest.raises((AttributeError, TypeError)):
        lock.storyboards[0]["headline"] = "篡改标题"
    with pytest.raises((AttributeError, TypeError)):
        lock.storyboards[0]["visual_slots"].append({"slot_id": "injected"})

    serialized = lock.model_dump(mode="json")
    assert isinstance(serialized["hashtags"], list)
    assert isinstance(serialized["storyboards"], list)
    assert isinstance(serialized["storyboards"][0], dict)
    assert serialized == CONTENT_LOCK


def test_content_lock_rejects_noncanonical_hash_shape():
    broken = deepcopy(CONTENT_LOCK)
    broken["canonical_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        ContentLock.model_validate(broken)
