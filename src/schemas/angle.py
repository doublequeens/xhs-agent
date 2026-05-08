from pydantic import BaseModel, Field
from typing import List

class ContentAngle(BaseModel):
    angle_id: str
    angle: str
    opening_hook: str
    value_promise: str
    suggested_structure: str

class AngleStrategy(BaseModel):
    topic_id: str
    topic: str
    target_group: str
    core_pain: str
    angles: List[ContentAngle] = Field(min_length=3, max_length=3, description="针对该话题生成的不同切入角度列表")