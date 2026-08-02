import pytest
from pydantic import ValidationError

from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.schemas.content_contract import ContentContract


def _content_contract(**overrides):
    fields = {
        "audience": "容易敏感的通勤人群",
        "trigger_situation": "护肤后皮肤持续刺痛",
        "decision_problem": "应该继续建立耐受还是立即停用",
        "first_screen_promise": "一分钟判断该继续还是停用",
        "screenshot_asset": "停止使用判断清单",
        "proof_asset": "真实风格皮肤状态示例",
        "visual_mode": "text_plus_real_proof",
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "face_zone_map",
        "primary_visual_subject": "skin_macro",
        "proof_mode": "real_photo",
    }
    fields.update(overrides)
    return ContentContract(**fields)


def test_content_contract_requires_first_screen_and_screenshot_asset():
    with pytest.raises(ValidationError):
        ContentContract(
            audience=COMMUTING_BEAUTY_WOMEN_V1.audience,
            trigger_situation="早八通勤前",
            decision_problem="防晒后是否能立刻上底妆",
            first_screen_promise="",
            screenshot_asset="",
            proof_asset="质地对比图",
            visual_mode="text_plus_real_proof",
            content_job="diagnose_and_adjust",
            primary_visual_family="face_zone_map",
            primary_visual_subject="face_map",
            proof_mode="product_texture",
            page_count_hint=6,
        )


@pytest.mark.parametrize("value", [5, 12, 18])
def test_page_count_hint_accepts_full_dynamic_range(value):
    assert _content_contract(page_count_hint=value).page_count_hint == value


@pytest.mark.parametrize("value", [4, 19])
def test_page_count_hint_rejects_out_of_range(value):
    with pytest.raises(ValidationError):
        _content_contract(page_count_hint=value)
