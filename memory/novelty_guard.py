from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memory.embedding import build_embedding_text
from memory.vector_memory import XHSVectorMemory


@dataclass
class NoveltyResult:
    should_reject: bool
    novelty_score: float
    max_similarity: float
    matched_history: list[dict[str, Any]]
    reason: str


class TopicNoveltyGuard:
    def __init__(
        self,
        vector_memory: XHSVectorMemory,
        reject_similarity_threshold: float = 0.86,
        warn_similarity_threshold: float = 0.78,
    ) -> None:
        self.vector_memory = vector_memory
        self.reject_similarity_threshold = reject_similarity_threshold
        self.warn_similarity_threshold = warn_similarity_threshold

    def check_topic_angle(
        self,
        *,
        topic: str,
        domain: str,
        subdomain: str,
        angle: str | None = None,
        title: str | None = None,
        target_group: str | None = None,
        core_pain: str | None = None,
        hashtags: list[str] | None = None,
        n_results: int = 5,
    ) -> NoveltyResult:
        query_text = build_embedding_text(
            topic=topic,
            angle=angle,
            title=title,
            target_group=target_group,
            core_pain=core_pain,
            hashtags=hashtags,
        )

        matches = self.vector_memory.query_similar(
            query_text=query_text,
            n_results=n_results,
            domain=domain,
            subdomain=subdomain,
        )

        max_similarity = max([m["similarity"] for m in matches], default=0.0)
        novelty_score = max(0.0, 1.0 - max_similarity)

        if max_similarity >= self.reject_similarity_threshold:
            return NoveltyResult(
                should_reject=True,
                novelty_score=novelty_score,
                max_similarity=max_similarity,
                matched_history=matches,
                reason="与历史内容高度相似，建议拒绝该主题/角度。",
            )

        if max_similarity >= self.warn_similarity_threshold:
            return NoveltyResult(
                should_reject=False,
                novelty_score=novelty_score,
                max_similarity=max_similarity,
                matched_history=matches,
                reason="与历史内容存在相似性，建议调整角度或扩大差异。",
            )

        return NoveltyResult(
            should_reject=False,
            novelty_score=novelty_score,
            max_similarity=max_similarity,
            matched_history=matches,
            reason="与历史内容相似度较低，可以继续生成。",
        )
