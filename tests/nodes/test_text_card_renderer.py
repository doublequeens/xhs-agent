from pathlib import Path


def _contract():
    return {
        "audience": "通勤女性",
        "trigger_situation": "早高峰上班前",
        "decision_problem": "防晒和底妆如何不打架",
        "first_screen_promise": "通勤前3步避开防晒搓泥",
        "screenshot_asset": "防晒与底妆搭配清单",
        "proof_asset": "产品质地实拍",
        "visual_mode": "text_card",
    }


def _frames():
    contract = _contract()
    common = {"theme": "warm_neutral", "footer": "按需微调"}
    return [
        {"frame_id": "frame_001", **common, "template": "cover_statement", "kicker": "封面", "headline": contract["first_screen_promise"]},
        {"frame_id": "frame_002", **common, "template": "wrong_vs_right", "kicker": "对照", "headline": "避免搓泥", "wrong_items": ["立刻上妆", "厚涂粉底"], "right_items": ["等待成膜", "少量点涂"]},
        {"frame_id": "frame_003", **common, "template": "step_timeline", "kicker": "步骤", "headline": "三步上妆", "steps": [{"name": "防晒", "hint": "薄涂全脸"}, {"name": "等待", "hint": "静置三分钟"}, {"name": "底妆", "hint": "少量点涂"}]},
        {"frame_id": "frame_004", **common, "template": "saveable_checklist", "kicker": "保存", "headline": "上妆清单", "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂"]},
        {"frame_id": "frame_005", **common, "template": "decision_rule", "kicker": "判断", "headline": "出现搓泥时", "condition": "底妆开始搓泥", "recommendation": "减少用量等待"},
        {"frame_id": "frame_006", **common, "template": "question_closer", "kicker": "讨论", "headline": "你的习惯", "question": "你最常在哪步搓泥？"},
    ]


def valid_state():
    return {
        "publish_package": {
            "topic_id": "tp_001",
            "title": "通勤底妆不搓泥",
            "domain": "beauty",
            "subdomain": "skincare",
            "profile_version": "beauty-v1",
            "storyboards": _frames(),
        },
        "trends": [{"topic_id": "tp_001", "content_contract": _contract()}],
    }


def test_renderer_node_adds_six_ordered_local_paths(monkeypatch, tmp_path):
    import src.nodes.node_p_text_card_renderer as module

    monkeypatch.setattr(module, "PUBLISH_ROOT", tmp_path / "outputs" / "publish")

    def fake_renderer_writing_pngs(_payload, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = module.output_paths(output_dir)
        for path in paths:
            path.write_bytes(b"fake png")
        return paths

    monkeypatch.setattr(module, "render_text_cards", fake_renderer_writing_pngs)

    result = module.text_card_renderer_node(valid_state())

    paths = result["publish_package"]["rendered_image_paths"]
    assert [Path(path).name for path in paths] == [
        "01-cover.png", "02-wrong-vs-right.png", "03-timeline.png",
        "04-checklist.png", "05-decision.png", "06-question.png",
    ]
    assert all(Path(path).is_relative_to(module.PUBLISH_ROOT.resolve()) for path in paths)
    assert result["current_node"] == "TEXT_CARD_RENDERER"


def test_renderer_node_rejects_titles_that_escape_local_publish_root(monkeypatch, tmp_path):
    import pytest
    import src.nodes.node_p_text_card_renderer as module

    monkeypatch.setattr(module, "PUBLISH_ROOT", tmp_path / "outputs" / "publish")
    state = valid_state()
    state["publish_package"]["title"] = "x/../../../../outside"

    with pytest.raises(ValueError, match="inside outputs/publish"):
        module.text_card_renderer_node(state)
