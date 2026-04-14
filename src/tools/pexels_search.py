import os
import httpx
from langchain_core.tools import tool
from src.schemas import ImageScriptList, RetrievedImageItem, IDMatchedImageItems, ImageItem
from typing import List

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

@tool
def pexels_search(image_scripts: ImageScriptList) -> List[dict]:
    """
    根据image_scroipt多维度搜索 Pexels 素材。
    
    Args:
        image_scripts: ImageScriptList 包含多个图片检索需求的字典。
        列表每个元素ImageScriptItem核心字段包含：
            img_id: str
            purpose: str
            style: str
            orientation: str
            search_query: str
            negative_constraints: List[str]
            on_image_copy: str
            caption_hint: str
        
        
    Returns:
        List[Dict]: 包含img_id、符合条件的图片列表, 图片列表中每个元素包括图片链接及图片描述。
        格式如下：
            List["image_id":string, "image_items": [{"image_url": string, "description":string}]]
    """
    base_url = "https://api.pexels.com/v1/"
    endpoint = "search"
    url = base_url + endpoint
    
    headers = {"Authorization": f"{PEXELS_API_KEY}"}
    id_imageItems_list = []
    with httpx.Client(timeout=20, headers=headers) as client:
        for script in image_scripts.image_scripts:
            img_id = script.img_id
            query = script.search_query
            neg_constraints = [k.lower() for k in script.negative_constraints]
            caption_hint = script.caption_hint
            style = script.style
            try:
                params = {"query": f"{query}", "orientation": "portrait"}
                r = client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
                
                photos_data = data.get("photos", [])
                img_list: List[ImageItem] = []
                
                for p in photos_data:
                    p_description = (p.get("alt") or "").lower()
                    img_url = p["src"]["portrait"]
                    width = p["width"]
                    height = p["height"]
                    if any(k in p_description for k in neg_constraints):
                        continue
                    img_list.append(RetrievedImageItem(image_url=img_url, description=p_description, width=width, height=height))
                id_img_items = IDMatchedImageItems(image_id=img_id, image_items=img_list, caption_hint=caption_hint, style=style, negative_constraints=neg_constraints)
                id_imageItems_list.append(id_img_items)
            except Exception as e:
                print(f"Error fetching image for {img_id}: {e}")
                continue
    return id_imageItems_list