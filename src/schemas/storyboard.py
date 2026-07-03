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
    character_action: str
    scene_background: str
    composition: str
    text_area: str
    on_image_copy: str
    narration: str
    image_prompt_cn: str
    image_prompt_en: str
    negative_prompt: str
    continuity_note: str


class StoryboardPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    storyboards: list[StoryboardFrame] = Field(min_length=8, max_length=10)
