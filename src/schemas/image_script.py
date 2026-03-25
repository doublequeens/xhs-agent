from pydantic import BaseModel
from typing import List

class ImageScriptItem(BaseModel):
    img_id: str
    purpose: str
    style: str
    orientation: str
    search_query: str
    negative_constraints: List[str]
    on_image_copy: str
    caption_hint: str