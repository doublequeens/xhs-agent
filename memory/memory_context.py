from __future__ import annotations

from dataclasses import asdict
from typing import Any

from memory.models import MemoryContext


def memory_context_to_prompt_payload(context: MemoryContext) -> dict[str, Any]:
    return {
        "recent_content": context.recent_contents,
        "recent_topics_to_avoid": context.recent_topics_to_avoid,
        "recent_angles_to_avoid": context.recent_angles_to_avoid,
        "recent_hashtags": context.recent_hashtags,
        "high_performing_patterns": context.high_performing_patterns,
        "low_performing_patterns": context.low_performing_patterns,
        "usage_rules": [
            "不要生成 recent_topics_to_avoid 中高度相似的主题",
            "不要重复 recent_angles_to_avoid 中高度相似的切入角度",
            "可以借鉴 high_performing_patterns 的结构和策略，但不要复制同一主题",
            "避免重复 low_performing_patterns 中表现较差的选题方式",
        ],
    }


def memory_context_to_dict(context: MemoryContext) -> dict[str, Any]:
    return asdict(context)