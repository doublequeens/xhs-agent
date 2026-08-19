from src.nodes import node_c_virality_scorer as module
from src.schemas.narrative import NarrativePlan
from src.schemas.novelty_guard import NoveltyCheckResults


def _narrative_plan() -> dict:
    beats = [
        {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
        {"beat_id": "scene", "kind": "scene", "purpose": "呈现具体场景"},
        {"beat_id": "steps", "kind": "steps", "purpose": "给出可执行步骤"},
        {"beat_id": "summary", "kind": "summary", "purpose": "总结可保存结论"},
    ]
    return NarrativePlan(
        narrative_form="step_tutorial",
        beats=beats,
        saveable_beat=beats[2],
        closing_mode="none",
    ).model_dump(mode="json")


def _novelty_check_results() -> NoveltyCheckResults:
    return NoveltyCheckResults(
        novelty_results=[
            {
                "topic_id": "tp_001",
                "topic": "健康生活习惯",
                "target_group": "上班族",
                "core_pain": "难坚持",
                "angle_id": "ag_001",
                "angle": "微习惯清单",
                "opening_hook": "先从一分钟开始",
                "value_promise": "降低执行门槛",
                "suggested_structure": "场景、步骤、清单",
                "narrative_plan": _narrative_plan(),
                "decision": "keep",
                "novelty_score": 0.9,
                "max_similarity": 0.1,
                "matched_history": [],
                "reason": "足够新颖",
                "revision_suggestions": [],
                "memory_signal": {
                    "decision": "keep",
                    "novelty_score": 0.9,
                    "max_similarity": 0.1,
                    "rejected_by_memory": False,
                    "similar_to_recent_content": False,
                    "similar_to_high_performing_pattern": False,
                    "similar_to_low_performing_pattern": False,
                    "recommended_for_virality_scorer": True,
                },
            }
        ]
    )


def _valid_score():
    return {
        "total_score": 8.5,
        "breakdown": {
            "click_potential": 8,
            "save_value": 9,
            "comment_potential": 7,
            "execution_barrier": 3,
            "compliance_safety": 9,
            "memory_fit_score": 8,
        },
        "strengths": ["清单明确"],
        "weaknesses": ["需要控制篇幅"],
        "optimization_suggestions": ["突出可执行步骤"],
        "absorbed_memory_suggestions": [],
        "memory_decision": "keep",
        "novelty_score": 0.9,
        "max_similarity": 0.1,
        "topic_id": "tp_001",
        "topic": "健康生活习惯",
        "angle_id": "ag_001",
        "angle": "微习惯清单",
        "target_group": "上班族",
        "core_pain": "难坚持",
        "opening_hook": "先从一分钟开始",
        "value_promise": "降低执行门槛",
        "suggested_structure": "场景、步骤、清单",
        "narrative_plan": _narrative_plan(),
    }


def test_virality_scorer_receives_content_contract(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.last_messages = []

        def execute(self, messages):
            self.last_messages = messages
            return [_valid_score()]

    fake_model = FakeModel()
    monkeypatch.setattr(module, "get_model", lambda: fake_model)

    result = module.virality_scorer_node(
        {
            "novelty_check_results": _novelty_check_results(),
            "trends": [
                {
                    "topic_id": "tp_001",
                    "content_contract": {
                        "audience": "23–35 岁、通勤、有基础护肤和底妆需求的女性",
                        "trigger_situation": "早高峰通勤前",
                        "decision_problem": "底妆是否会斑驳",
                        "first_screen_promise": "通勤前底妆判断清单",
                        "screenshot_asset": "三步判断清单",
                        "proof_asset": "产品质地实拍",
                        "visual_mode": "text_plus_real_proof",
                        "content_job": "save_and_check",
                        "primary_visual_family": "saveable_reference",
                        "primary_visual_subject": "checklist",
                        "proof_mode": "product_texture",
                        "recommended_frame_count": 6,
                    },
                }
            ],
            "domain_context": {
                "domain": "beauty",
                "profile_version": "beauty-v1",
            },
            "content_policy": {},
        }
    )

    assert result["scores"][0].topic_id == "tp_001"
    sent = fake_model.last_messages[-1].content
    assert '"first_screen_promise"' in sent
    assert '"screenshot_asset"' in sent


def test_virality_scorer_retries_schema_errors_with_model_feedback(monkeypatch):
    invalid = _valid_score()
    invalid.pop("suggested_structure")

    class FakeModel:
        def __init__(self):
            self.calls = []

        def execute(self, messages):
            self.calls.append(list(messages))
            return [invalid] if len(self.calls) == 1 else [_valid_score()]

    model = FakeModel()
    monkeypatch.setattr(module, "get_model", lambda: model)

    result = module.virality_scorer_node(
        {
            "novelty_check_results": _novelty_check_results(),
            "domain_context": {
                "domain": "healthy_lifestyle",
                "profile_version": "healthy-lifestyle-v1",
            },
            "content_policy": {},
        }
    )

    assert len(model.calls) == 2
    assert result["scores"][0].suggested_structure == "场景、步骤、清单"
    assert "suggested_structure" in model.calls[1][-1].content
