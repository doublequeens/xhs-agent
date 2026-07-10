from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StoryboardFrame(BaseModel):
    model_config = ConfigDict(extra="ignore")

    frame_id: str
    narrative_role: str
    frame_title: str
    image_orientation: str
    aspect_ratio: str
    recommended_size: str
    visual_description: str
    scene_background: str
    composition: str
    text_area: str
    on_image_copy: str
    narration: str
    image_prompt_cn: str
    image_prompt_en: str
    negative_prompt: str
    card_role: Literal[
        "cover",
        "decision_rule",
        "step",
        "comparison",
        "screenshot_asset",
        "boundary",
        "discussion",
    ]
    is_screenshot_asset: bool = False
    visual_mode: Literal["text_card", "text_plus_real_proof", "comparison_table"]
    proof_asset_usage: str = "none"


class StoryboardPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    storyboards: list[StoryboardFrame] = Field(min_length=6, max_length=8)
