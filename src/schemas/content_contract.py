from typing import Literal

from pydantic import BaseModel, Field


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
