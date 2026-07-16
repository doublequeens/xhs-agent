import pytest
from pydantic import ValidationError

from src.schemas.narrative import NarrativePlan


PLAN = {
    "narrative_form": "cognitive_correction",
    "beats": [
        {"beat_id": "hook", "kind": "hook", "purpose": "提出常见误区"},
        {"beat_id": "mistake", "kind": "misconception", "purpose": "展示误区"},
        {"beat_id": "reveal", "kind": "reveal", "purpose": "给出反转"},
        {"beat_id": "action", "kind": "action", "purpose": "给出替代动作"},
    ],
    "saveable_beat": {
        "beat_id": "action",
        "kind": "action",
        "purpose": "给出替代动作",
    },
    "closing_mode": "none",
}


def test_narrative_plan_accepts_supported_form_and_embedded_saveable_beat():
    plan = NarrativePlan.model_validate(PLAN)
    assert plan.narrative_form == "cognitive_correction"
    assert plan.saveable_beat == plan.beats[-1]


def test_narrative_plan_rejects_saveable_beat_not_in_beats():
    broken = {
        **PLAN,
        "saveable_beat": {
            "beat_id": "missing",
            "kind": "summary",
            "purpose": "不存在",
        },
    }
    with pytest.raises(ValidationError, match="saveable_beat"):
        NarrativePlan.model_validate(broken)


def test_narrative_plan_rejects_duplicate_beat_ids():
    broken = {
        **PLAN,
        "beats": [PLAN["beats"][0], PLAN["beats"][0], *PLAN["beats"][2:]],
    }
    with pytest.raises(ValidationError, match="beat IDs"):
        NarrativePlan.model_validate(broken)
