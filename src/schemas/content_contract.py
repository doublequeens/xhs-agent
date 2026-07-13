from typing import Literal

from pydantic import BaseModel, Field

from .visual_plan import ContentJob, VisualFamily


class ContentContract(BaseModel):
    audience: str = Field(min_length=1)
    trigger_situation: str = Field(min_length=1)
    decision_problem: str = Field(min_length=1)
    first_screen_promise: str = Field(min_length=8, max_length=42)
    screenshot_asset: str = Field(min_length=1)
    proof_asset: str = Field(min_length=1)
    visual_mode: Literal[
        "text_card", "text_plus_real_proof", "comparison_table"
    ]
    content_job: ContentJob
    primary_visual_family: VisualFamily
    primary_visual_subject: Literal[
        "face_map",
        "serum_texture",
        "product_cutout",
        "skin_macro",
        "checklist",
        "process",
    ]
    proof_mode: Literal["diagram", "real_photo", "product_texture", "comparison", "none"]
    recommended_frame_count: int = Field(ge=5, le=7)
