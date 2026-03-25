from pydantic import BaseModel
from typing import List

class Title(BaseModel):
    title_id: str
    title: str
    type: str
    core_hook: str
    emotion_trigger: str

class DraftTitles(BaseModel):
    draft_id: str
    titles:List[Title]
    cover_copies: List[str]