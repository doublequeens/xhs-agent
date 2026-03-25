from pydantic import BaseModel

class OutlineItem(BaseModel):
    outline_id: str
    outline_md: str
    topic_id: str
    topic_name: str
    angle_id: str
    angle_name: str
    target_group: str
    core_pain: str   