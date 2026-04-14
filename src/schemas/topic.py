from pydantic import BaseModel

class TopicItem(BaseModel):
    topic_id: str
    topic: str  
    target_group: str
    core_pain: str
    hook: str
    content_form: str
    risk_note: str