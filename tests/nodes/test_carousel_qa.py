from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1


def _contract(**overrides):
    contract = {
        "audience": "通勤女性",
        "trigger_situation": "早高峰上班前",
        "decision_problem": "防晒和底妆如何不打架",
        "first_screen_promise": "通勤前3步避开防晒搓泥",
        "screenshot_asset": "防晒与底妆搭配清单",
        "proof_asset": "产品质地实拍",
        "visual_mode": "text_card",
    }
    contract.update(overrides)
    return contract


def _frames(contract=None):
    contract = contract or _contract()
    common = {
        "theme": "warm_neutral",
        "footer": "按需微调",
    }
    return [
        {"frame_id": "frame_001", **common, "template": "cover_statement", "kicker": "封面", "headline": contract["first_screen_promise"]},
        {"frame_id": "frame_002", **common, "template": "wrong_vs_right", "kicker": "对照", "headline": "避免搓泥", "wrong_items": ["立刻上妆", "厚涂粉底"], "right_items": ["等待成膜", "少量点涂"]},
        {"frame_id": "frame_003", **common, "template": "step_timeline", "kicker": "步骤", "headline": "三步上妆", "steps": [{"name": "防晒", "hint": "薄涂全脸"}, {"name": "等待", "hint": "静置三分钟"}, {"name": "底妆", "hint": "少量点涂"}]},
        {"frame_id": "frame_004", **common, "template": "saveable_checklist", "kicker": "保存", "headline": "上妆清单", "checklist_items": ["薄涂防晒", "等待成膜", "少量点涂"]},
        {"frame_id": "frame_005", **common, "template": "decision_rule", "kicker": "判断", "headline": "出现搓泥时", "condition": "底妆开始搓泥", "recommendation": "减少用量等待"},
        {"frame_id": "frame_006", **common, "template": "question_closer", "kicker": "讨论", "headline": "你的习惯", "question": "你最常在哪步搓泥？"},
    ]


def _state(**package_overrides):
    contract = _contract()
    package = {
        "draft_id": "draft_001",
        "topic_id": "tp_001",
        "topic": "通勤底妆",
        "angle_id": "ag_001",
        "angle": "防晒打底顺序",
        "target_group": "通勤女性",
        "core_pain": "防晒后底妆搓泥",
        "title": "通勤底妆不搓泥",
        "content": "先给防晒成膜时间，再上底妆。",
        "cover_copy": "通勤底妆不搓泥",
        "storyboards": _frames(contract),
    }
    package.update(package_overrides)
    return {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "publish_package": package,
        "trends": [{"topic_id": "tp_001", "content_contract": contract}],
    }


def _qa_node():
    from src.nodes.node_p_carousel_qa import carousel_qa_node

    return carousel_qa_node


def _route_after_qa():
    from src.nodes.node_p_carousel_qa import route_after_carousel_qa

    return route_after_carousel_qa


def test_carousel_qa_accepts_schema_valid_structured_text_cards():
    result = _qa_node()(_state())

    assert result["carousel_qa_result"].passed is True
    assert result.get("decision_output") is None
    assert _route_after_qa()(result) == "human_review"


def test_carousel_qa_reports_actionable_structured_contract_failures():
    state = _state()
    frames = state["publish_package"]["storyboards"]
    frames[0]["headline"] = "不符合首屏承诺"
    frames[1]["theme"] = "cool_sage"
    frames[3]["template"] = "question_closer"
    frames[3].pop("checklist_items")
    frames[3]["question"] = "你会怎么做？"
    state["publish_package"]["storyboards"] = frames[:5]

    result = _qa_node()(state)

    issues = {
        issue.rule_id: issue.location_hint
        for issue in result["carousel_qa_result"].issues
    }
    assert issues["card_count_out_of_range"] == "storyboards[0].frame_id"
    assert issues["template_order_mismatch"] == "storyboards[0].template"
    assert issues["mixed_theme"] == "storyboards[1].theme"
    assert issues["first_screen_promise_mismatch"] == "storyboards[0].headline"
    assert issues["missing_saveable_checklist"] == "storyboards[3].template"
    assert _route_after_qa()(result) == "r1_reflector"


def test_carousel_qa_turns_invalid_structured_schema_into_atomic_r1_task():
    state = _state()
    state["publish_package"]["storyboards"][0]["card_role"] = "cover"

    result = _qa_node()(state)

    schema_issue = next(
        issue
        for issue in result["carousel_qa_result"].issues
        if issue.rule_id == "storyboard_schema_invalid"
    )
    task = next(
        task
        for task in result["decision_output"].normalized_input.r1_input.editorial_tasks.mandatory
        if task.location_hint == schema_issue.location_hint
    )
    assert schema_issue.location_hint == "storyboards[0].cover_statement.card_role"
    assert task.source == "carousel_qa"
    assert task.severity == "high"
