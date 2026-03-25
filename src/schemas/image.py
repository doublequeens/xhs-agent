from pydantic import BaseModel
from typing import Optional


class ImageItem(BaseModel):
    image_url:str
    description: Optional[str] = None
    width: int
    height: int