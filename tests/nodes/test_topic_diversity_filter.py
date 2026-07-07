from datetime import datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_05_topic_diversity_filter import topic_diversity_filter_node
from tests.topic_signals.test_diversity import _topic


class FakeManager:
    def __init__(self):
        self.traces = []

    def save_topic_generation_trace(self, trace):
        self.traces.append(trace)

    def init_db(self, schema_path):
        pass


def test_topic_diversity_filter_writes_trends_and_trace(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(
        "src.nodes.node_a_05_topic_diversity_filter.XHSMemoryManager",
        lambda path: manager,
    )
    result = topic_diversity_filter_node(
        {
            "topic_candidates": [
                _topic("tp_001", "高温天补水提醒", "高温天"),
                _topic("tp_002", "周一开工拉伸", "周一开工"),
            ],
            "trends_num": 2,
            "domain_context": {
                "domain": "healthy_lifestyle",
                "subdomain": "daily_habits",
            },
            "topic_signals": [],
            "creative_briefs": [],
            "topic_generation_degraded_reason": None,
            "_now_for_test": datetime(
                2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
        }
    )
    assert len(result["trends"]) == 2
    assert manager.traces[0].domain == "healthy_lifestyle"
