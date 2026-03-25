from pydantic import BaseModel
from typing import List
from src.schemas.image import ImageItem

class IdImageItems(BaseModel):
    image_id:str
    image_items: List[ImageItem]
    caption_hint: str
    style: str
    negative_constraints: List[str]