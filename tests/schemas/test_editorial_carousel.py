from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.schemas.assets import AssetManifest, AssetSearchReport
from src.schemas.content_contract import ContentContract
from src.schemas.content_lock import ContentLock
from src.schemas.render_manifest import RenderManifest
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
    "design_system": "beauty_editorial_v1",
    "content_job": "diagnose_and_adjust",
    "primary_visual_family": "face_zone_map",
    "supporting_families": ["beauty_editorial", "saveable_reference"],
    "frame_plan": [
        {
            "frame_id": "cover",
            "role": "cover",
            "layout": "editorial_cover",
            "purpose": "建立问题与承诺",
            "asset_roles": ["beauty_subject"],
        },
        {
            "frame_id": "baseline",
            "role": "baseline",
            "layout": "texture_baseline",
            "purpose": "建立质地基线",
            "asset_roles": ["product_texture"],
        },
        {
            "frame_id": "applicable-case",
            "role": "applicable_case",
            "layout": "front_face_zone",
            "purpose": "标出适用区域",
            "asset_roles": ["face_map"],
        },
        {
            "frame_id": "zone-adjustment",
            "role": "zone_adjustment",
            "layout": "three_quarter_face_zone",
            "purpose": "展示分区调整",
            "asset_roles": ["face_map"],
        },
        {
            "frame_id": "feedback",
            "role": "feedback_diagnosis",
            "layout": "three_state_diagnostic",
            "purpose": "根据反馈诊断",
            "asset_roles": ["comparison"],
        },
        {
            "frame_id": "save",
            "role": "save",
            "layout": "saveable_reference",
            "purpose": "提供保存参考",
            "asset_roles": ["reference"],
        },
    ],
    "required_assets": [
        {
            "slot_id": "face-map",
            "role": "face_map",
            "layout": "front_face_zone",
            "min_width": 1080,
            "min_height": 1440,
            "context_tags": ["t-zone"],
        }
    ],
}

ZONE_STORYBOARD = [
    {
        "frame_id": item["frame_id"],
        "role": item["role"],
        "layout": item["layout"],
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


def test_content_contract_requires_editorial_strategy_fields():
    with pytest.raises(ValidationError):
        ContentContract.model_validate(BASE_CONTRACT)


def test_visual_plan_accepts_five_to_seven_frames_and_rejects_arbitrary_layout():
    plan = VisualPlan.model_validate(ZONE_PLAN)
    assert plan.primary_visual_family == "face_zone_map"
    broken = deepcopy(ZONE_PLAN)
    broken["frame_plan"][1]["layout"] = "freeform_html"
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
    with pytest.raises(ValidationError):
        CarouselPayload.model_validate({"storyboards": ZONE_STORYBOARD[:4]})


def test_manifest_contracts_are_strict():
    search_report = AssetSearchReport.model_validate(
        {"search_triggered": False, "queries": [], "provider_reports": [], "selection_reasons": {}}
    )
    asset_manifest = AssetManifest.model_validate(
        {"items": [], "search_report": search_report.model_dump()}
    )
    render_manifest = RenderManifest.model_validate(
        {
            "pages": [],
            "fonts": {"all_loaded": True, "computed_families": []},
            "contact_sheet_path": "contact-sheet.png",
            "source_asset_sha256": {},
        }
    )
    assert asset_manifest.search_report.search_triggered is False
    assert render_manifest.contact_sheet_path == "contact-sheet.png"


def test_content_lock_is_frozen():
    lock = ContentLock.model_validate(CONTENT_LOCK)
    with pytest.raises(ValidationError):
        lock.title = "另一个标题"


def test_content_lock_rejects_noncanonical_hash_shape():
    broken = deepcopy(CONTENT_LOCK)
    broken["canonical_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        ContentLock.model_validate(broken)
