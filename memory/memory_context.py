from __future__ import annotations

from dataclasses import asdict
from typing import Any

from memory.models import MemoryContext


def memory_context_to_prompt_payload(context: MemoryContext) -> dict[str, Any]:
    high_patterns = [
        item for item in context.same_domain_patterns if item.get("performance_signal") == "high"
    ]
    low_patterns = [
        item for item in context.same_domain_patterns if item.get("performance_signal") == "low"
    ]

    return {
        "same_subdomain_recent": context.same_subdomain_recent,
        "same_domain_patterns": context.same_domain_patterns,
        "global_format_patterns": context.global_format_patterns,
        "topics_to_avoid": context.topics_to_avoid,
        "angles_to_avoid": context.angles_to_avoid,
        "recent_hashtags": context.recent_hashtags,
        "recent_content": context.same_subdomain_recent,
        "recent_topics_to_avoid": context.topics_to_avoid,
        "recent_angles_to_avoid": context.angles_to_avoid,
        "high_performing_patterns": high_patterns,
        "low_performing_patterns": low_patterns,
        "usage_rules": [
            "不要生成 topics_to_avoid 中高度相似的主题",
            "不要重复 angles_to_avoid 中高度相似的切入角度",
            "参考 same_domain_patterns 中 performance_signal=high 的结构策略，但不要复制同一主题",
            "避免重复 same_domain_patterns 中 performance_signal=low 的低效选题方式",
            "global_format_patterns 只可借鉴版式和包装方式，不可复制语义内容",
        ],
    }


def memory_context_to_dict(context: MemoryContext) -> dict[str, Any]:
    return asdict(context)
