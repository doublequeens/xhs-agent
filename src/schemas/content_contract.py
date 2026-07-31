from typing import Literal

from pydantic import BaseModel, Field

ContentJob = Literal[
    "diagnose_and_adjust",
    "follow_steps",
    "compare_and_choose",
    "save_and_check",
    "understand_and_notice",
]

PrimaryVisualStructure = Literal[
    "beauty_editorial",
    "face_zone_map",
    "step_flow",
    "comparison_decision",
    "saveable_reference",
]


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
    primary_visual_family: PrimaryVisualStructure
    primary_visual_subject: Literal[
        "face_map",
        "serum_texture",
        "product_cutout",
        "skin_macro",
        "checklist",
        "process",
    ]
    proof_mode: Literal["diagram", "real_photo", "product_texture", "comparison", "none"]
    page_count_hint: int | None = Field(default=None, ge=5, le=18)
