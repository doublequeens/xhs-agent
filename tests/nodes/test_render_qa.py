import struct
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
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "face_zone_map",
        "primary_visual_subject": "face_map",
        "proof_mode": "product_texture",
        "recommended_frame_count": 6,
    }


def _frames():
    contract = _contract()
    common = {"theme": "warm_neutral", "footer": "按需微调"}
    return [
        {"frame_id": "frame_001", **common, "template": "cover_statement", "kicker": "封面", "headline": contract["first_screen_promise"]},
        {"frame_id": "frame_002", **common, "template": "wrong_vs_right", "kicker": "对照", "headline": "避免搓泥", "wrong_items": ["立刻上妆", "厚涂粉底"], "right_items": ["等待成膜", "少量点涂"]},
        {"frame_id": "frame_003", **common, "template": "step_timeline", "kicker": "步骤", "headline": "三步上妆", "steps": [{"name": "防晒", "hint": "薄涂全脸"}, {"name": "等待", "hint": "静置三分钟"}, {"name": "底妆", "hint": "少量点涂"}]},
        {"frame_id": "frame_004", **common, "template": "saveable_checklist", "kicker": "保存", "headline": "上妆清单", "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂"]},
        {"frame_id": "frame_005", **common, "template": "decision_rule", "kicker": "判断", "headline": "出现搓泥时", "conditions": [{"situation": "底妆开始搓泥", "recommendation": "减少用量等待"}, {"situation": "时间不足", "recommendation": "先缩减步骤"}]},
        {"frame_id": "frame_006", **common, "template": "question_closer", "kicker": "讨论", "headline": "你的习惯", "question": "你最常在哪步搓泥？"},
    ]


def _png(width=1080, height=1440):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"\x08\x02\x00\x00\x00"


def valid_state(publish_root):
    from src.rendering.text_cards import output_paths

    image_dir = publish_root / "20260713-beauty-skincare-test" / "images"
    paths = output_paths(image_dir)
    image_dir.mkdir(parents=True)
    for path in paths:
        path.write_bytes(_png())
    return {
        "publish_package": {
            "draft_id": "draft_001",
            "topic_id": "tp_001",
            "title": "通勤底妆不搓泥",
            "content": "先给防晒成膜时间，再上底妆。",
            "cover_copy": "通勤底妆不搓泥",
            "storyboards": _frames(),
            "rendered_image_paths": [str(path) for path in paths],
        },
        "trends": [{"topic_id": "tp_001", "content_contract": _contract()}],
    }


def test_render_qa_routes_missing_or_wrong_size_pngs_to_r1(monkeypatch, tmp_path):
    import src.nodes.node_p_render_qa as module

    monkeypatch.setattr(module, "PUBLISH_ROOT", tmp_path / "outputs" / "publish")
    state = valid_state(module.PUBLISH_ROOT)
    Path(state["publish_package"]["rendered_image_paths"][0]).write_bytes(_png(1080, 1081))
    Path(state["publish_package"]["rendered_image_paths"][1]).unlink()

    result = module.render_qa_node(state)

    assert result["render_qa_result"].passed is False
    assert {issue.rule_id for issue in result["render_qa_result"].issues} >= {"png_dimensions_invalid", "png_missing"}
    assert result["decision_output"].next_node == "R1_REFLECTOR"
    assert {task.source for task in result["decision_output"].normalized_input.r1_input.editorial_tasks.mandatory} == {"render_qa"}


def test_render_qa_accepts_a_complete_ordered_png_set(monkeypatch, tmp_path):
    import src.nodes.node_p_render_qa as module

    monkeypatch.setattr(module, "PUBLISH_ROOT", tmp_path / "outputs" / "publish")
    result = module.render_qa_node(valid_state(module.PUBLISH_ROOT))

    assert result["render_qa_result"].passed is True
    assert result.get("decision_output") is None
    assert module.route_after_render_qa(result) == "human_review"


def test_render_qa_rejects_each_resumed_path_outside_publish_root(monkeypatch, tmp_path):
    import src.nodes.node_p_render_qa as module

    monkeypatch.setattr(module, "PUBLISH_ROOT", tmp_path / "outputs" / "publish")
    result = module.render_qa_node(valid_state(tmp_path / "tampered-images"))

    outside_root_issues = [
        issue
        for issue in result["render_qa_result"].issues
        if issue.rule_id == "png_outside_publish_root"
    ]
    assert result["render_qa_result"].passed is False
    assert len(outside_root_issues) == 6
    assert result["decision_output"].next_node == "R1_REFLECTOR"
