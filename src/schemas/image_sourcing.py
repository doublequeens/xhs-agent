from pydantic import BaseModel
from typing import List, Optional

class RetrievedImageItem(BaseModel):
    image_url:str
    description: Optional[str] = None
    width: int
    height: int

class IDMatchedImageItems(BaseModel):
    image_id:str
    image_items: List[RetrievedImageItem]
    caption_hint: str
    style: str
    negative_constraints: List[str]


class SingleImageResult(BaseModel):
    image_url: str
    description: Optional[str] = None
    width: int
    height: int
    why_match: str

class ImageCandidateItem(BaseModel):
    img_id: str
    purpose: str
    style: str
    orientation: str
    on_image_copy: str
    caption_hint: str
    selected: List[SingleImageResult]

class ImageCandidates(BaseModel):
    image_candidates: List[ImageCandidateItem]