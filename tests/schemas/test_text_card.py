from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas.text_card import TextCardPayload


def valid_frames():
    return [
        {
            "frame_id": "frame_001",
            "template": "cover_statement",
            "theme": "warm_neutral",
            "kicker": "通勤底妆",
            "headline": "通勤前3步避开防晒搓泥",
            "footer": "先防晒再上妆",
        },
        {
            "frame_id": "frame_002",
            "template": "wrong_vs_right",
            "theme": "warm_neutral",
            "kicker": "避坑对照",
            "headline": "别让底妆越补越糟",
            "footer": "对照后再执行",
            "wrong_items": ["防晒刚涂就上妆", "反复叠加粉底"],
            "right_items": ["等待防晒成膜", "薄涂底妆", "局部补妆"],
        },
        {
            "frame_id": "frame_003",
            "template": "step_timeline",
            "theme": "warm_neutral",
            "kicker": "三步顺序",
            "headline": "按顺序留出成膜时间",
            "footer": "每步都别赶",
            "steps": [
                {"name": "防晒", "hint": "薄涂全脸"},
                {"name": "等待", "hint": "静置三分钟"},
                {"name": "底妆", "hint": "少量点涂"},
            ],
        },
        {
            "frame_id": "frame_004",
            "template": "saveable_checklist",
            "theme": "warm_neutral",
            "kicker": "截图保存",
            "headline": "上妆前快速检查",
            "footer": "照着清单做",
            "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂", "局部补妆"],
        },
        {
            "frame_id": "frame_005",
            "template": "decision_rule",
            "theme": "warm_neutral",
            "kicker": "选择规则",
            "headline": "搓泥时先减少叠加",
            "footer": "先减量再调整",
            "conditions": [
                {"situation": "底妆开始搓泥", "recommendation": "减少用量并等待"},
                {"situation": "时间不足", "recommendation": "先缩减步骤"},
            ],
        },
        {
            "frame_id": "frame_006",
            "template": "question_closer",
            "theme": "warm_neutral",
            "kicker": "留言聊聊",
            "headline": "你的防晒会搓泥吗",
            "footer": "按肤质再微调",
            "question": "你最常在哪一步出现搓泥？",
        },
    ]


def test_text_card_payload_requires_six_cards_in_the_fixed_template_order():
    payload = TextCardPayload.model_validate({"storyboards": valid_frames()})

    assert [frame.template for frame in payload.storyboards] == [
        "cover_statement",
        "wrong_vs_right",
        "step_timeline",
        "saveable_checklist",
        "decision_rule",
        "question_closer",
    ]


@pytest.mark.parametrize("theme", ["soft_blue", "warm_orange", "custom_theme"])
def test_text_card_payload_rejects_themes_without_renderer_tokens(theme):
    frames = valid_frames()
    for frame in frames:
        frame["theme"] = theme

    with pytest.raises(ValidationError, match="warm_neutral|cool_sage"):
        TextCardPayload.model_validate({"storyboards": frames})


def test_storyboard_generator_prompt_only_allows_renderer_themes():
    prompt_path = Path(__file__).parents[2] / "src/prompts/base/storyboards_generator.txt"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert '\"theme\":\"string\"' not in prompt
    assert "warm_neutral" in prompt
    assert "cool_sage" in prompt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("headline", "这是一条超过二十八个汉字限制的标题文案需要被明确拒绝并且不能通过验证"),
        ("kicker", "超过十个汉字的标签需要被拒绝"),
        ("footer", "超过十八个汉字的页脚内容必须被明确拒绝不能通过验证"),
    ],
)
def test_text_card_copy_limits_are_enforced(field, value):
    frame = valid_frames()[0]
    frame[field] = value

    with pytest.raises(ValidationError):
        TextCardPayload.model_validate({"storyboards": [frame, *valid_frames()[1:]]})


@pytest.mark.parametrize("count", [0, 1, 4])
def test_decision_rule_requires_two_or_three_situation_recommendation_pairs(count):
    frames = valid_frames()
    frames[4]["conditions"] = (frames[4]["conditions"] * 2)[:count]

    with pytest.raises(ValidationError):
        TextCardPayload.model_validate({"storyboards": frames})


@pytest.mark.parametrize(
    "path,value",
    [
        (("headline",), "标题🙂"),
        (("wrong_items", 0), "错误🙂"),
        (("steps", 0, "hint"), "提示🙂"),
        (("conditions", 0, "recommendation"), "建议🙂"),
    ],
)
def test_text_card_visible_copy_rejects_emoji_including_nested_and_list_atoms(path, value):
    frames = valid_frames()
    target = frames[4] if path[0] == "conditions" else frames[0]
    if path[0] == "wrong_items":
        target = frames[1]
    elif path[0] == "steps":
        target = frames[2]
    if len(path) == 1:
        target[path[0]] = value
    elif len(path) == 2:
        target[path[0]][path[1]] = value
    else:
        target[path[0]][path[1]][path[2]] = value

    with pytest.raises(ValidationError, match="emoji"):
        TextCardPayload.model_validate({"storyboards": frames})
