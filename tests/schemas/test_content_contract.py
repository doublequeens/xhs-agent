import pytest
from pydantic import ValidationError

from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.schemas.content_contract import ContentContract


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
            recommended_frame_count=6,
        )
