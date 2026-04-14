from pydantic import BaseModel
from typing import List, Optional

class FinalImageItem(BaseModel):
    img_id: str
    purpose: str
    width: str
    height: str
    why_selected: List[str]
    on_image_copy: Optional[str] = None
    caption_hint: Optional[str] = None
    image_url: Optional[str] = None

class FinalImages(BaseModel):
    image_final_choices: List[FinalImageItem]