from __future__ import annotations

import pytest

from memory.novelty_guard import TopicNoveltyGuard


class FakeVectorMemory:
    def __init__(self):
        self.calls = []

    def query_similar(self, **kwargs):
        self.calls.append(kwargs)
        return [
            {
                "content_id": "content-1",
                "document": "doc",
                "metadata": {"domain": "wellness", "subdomain": "sleep"},
                "distance": 0.1,
                "similarity": 0.9,
            }
        ]


def test_topic_novelty_guard_requires_domain_scope_and_forwards_it(monkeypatch):
    vector_memory = FakeVectorMemory()
    guard = TopicNoveltyGuard(vector_memory=vector_memory)

    monkeypatch.setattr(
        "memory.novelty_guard.build_embedding_text",
        lambda **kwargs: "sleep routine 上班族",
    )

    result = guard.check_topic_angle(
        topic="睡前仪式",
        angle="上班族快速放松",
        target_group="上班族",
        domain="wellness",
        subdomain="sleep",
        n_results=3,
    )

    assert vector_memory.calls == [
        {
            "query_text": "sleep routine 上班族",
            "n_results": 3,
            "domain": "wellness",
            "subdomain": "sleep",
        }
    ]
    assert result.should_reject is True
    assert result.max_similarity == 0.9
