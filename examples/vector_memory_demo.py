import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from memory.vector_memory import XHSVectorMemory
from memory.embedding import build_embedding_text
from memory.novelty_guard import TopicNoveltyGuard


def main() -> None:
    vector_memory = XHSVectorMemory("data/chroma")

    # 1. 写入一条历史内容
    old_text = build_embedding_text(
        topic="防晒是否需要卸妆",
        angle="一杯水判断防晒是否防水",
        title="省钱了！这种防晒可能不用额外卸妆",
        target_group="通勤防晒人群",
        core_pain="担心洗不干净，又怕过度清洁",
        hashtags=["#防晒卸妆", "#护肤新手"],
    )

    vector_memory.upsert_content(
        content_id="local_demo_001",
        embedding_text=old_text,
        metadata={
            "topic": "防晒是否需要卸妆",
            "angle": "一杯水判断法",
            "title": "省钱了！这种防晒可能不用额外卸妆",
            "created_at": "2026-01-01",
            "performance_level": "high",
        },
    )

    print("Vector count:", vector_memory.count())

    # 2. 查询一个类似主题
    guard = TopicNoveltyGuard(vector_memory)

    result = guard.check_topic_angle(
        topic="只涂防晒要不要卸妆",
        angle="用水测试防晒是否防水",
        target_group="通勤护肤新手",
        core_pain="怕闷痘又怕过度清洁",
    )

    print(result)


if __name__ == "__main__":
    main()