from pydantic import BaseModel

from .narrative import NarrativePlan


class DraftItem(BaseModel):
    draft_id: str
    draft_md: str
    topic_id: str
    topic: str
    angle_id: str
    angle: str
    target_group: str
    core_pain: str
    narrative_plan: NarrativePlan
