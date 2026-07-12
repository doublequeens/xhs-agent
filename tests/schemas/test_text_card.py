import pytest
from pydantic import ValidationError

from src.schemas.text_card import TextCardPayload


def valid_frames():
    return [
        {
            "frame_id": "frame_001",
            "template": "cover_statement",
            "theme": "soft_blue",
            "kicker": "通勤底妆",
            "headline": "通勤前3步避开防晒搓泥",
            "footer": "先防晒再上妆",
        },
        {
            "frame_id": "frame_002",
            "template": "wrong_vs_right",
            "theme": "soft_blue",
            "kicker": "避坑对照",
            "headline": "别让底妆越补越糟",
            "footer": "对照后再执行",
            "wrong_items": ["防晒刚涂就上妆", "反复叠加粉底"],
            "right_items": ["等待防晒成膜", "薄涂底妆", "局部补妆"],
        },
        {
            "frame_id": "frame_003",
            "template": "step_timeline",
            "theme": "soft_blue",
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
            "theme": "soft_blue",
            "kicker": "截图保存",
            "headline": "上妆前快速检查",
            "footer": "照着清单做",
            "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂", "局部补妆"],
        },
        {
            "frame_id": "frame_005",
            "template": "decision_rule",
            "theme": "soft_blue",
            "kicker": "选择规则",
            "headline": "搓泥时先减少叠加",
            "footer": "先减量再调整",
            "condition": "底妆开始搓泥",
            "recommendation": "减少用量并等待",
        },
        {
            "frame_id": "frame_006",
            "template": "question_closer",
            "theme": "soft_blue",
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
