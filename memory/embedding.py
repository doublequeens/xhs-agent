from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from sentence_transformers import SentenceTransformer


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_embedding_model(model_name: str = DEFAULT_EMBEDDING_MODEL) -> SentenceTransformer:
    """
    本地加载 embedding model。
    第一次运行会下载模型，之后会使用本地缓存。
    """
    return SentenceTransformer(model_name)


def embed_texts(texts: list[str], model_name: str = DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    model = get_embedding_model(model_name)
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


def build_embedding_text(
    *,
    topic: str,
    angle: str | None = None,
    title: str | None = None,
    target_group: str | None = None,
    core_pain: str | None = None,
    hashtags: Iterable[str] | None = None
) -> str:
    """
    用于向量检索的语义文本，不需要放完整正文。
    重点是：主题 + 切入角度 + 目标人群 + 痛点 + 标题 + 标签。
    """
    parts = [
        f"主题：{topic}",
        f"切入角度：{angle or ''}",
        f"标题：{title or ''}",
        f"目标人群：{target_group or ''}",
        f"核心痛点：{core_pain or ''}",
        f"标签：{' '.join(hashtags or [])}" 
        ]
    return "\n".join([p for p in parts if p.strip()])