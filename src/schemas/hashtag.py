from pydantic import BaseModel
from typing import List

class HashTagOutput(BaseModel):
    hashtags: List[str]