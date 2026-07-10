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


def _frame(index, **overrides):
    frame = {
        "frame_id": f"frame_{index:03d}",
        "narrative_role": "封面钩子" if index == 1 else "步骤展开",
        "frame_title": f"第 {index} 张",
        "image_orientation": "vertical",
        "aspect_ratio": "3:4",
        "recommended_size": "1080x1440",
        "visual_description": "高对比文字信息卡",
        "scene_background": "干净浅色背景",
        "composition": "清晰分区",
        "text_area": "顶部标题区",
        "on_image_copy": f"第 {index} 个要点",
        "narration": f"第 {index} 步说明",
        "image_prompt_cn": "手机端可读的文字卡",
        "image_prompt_en": "readable mobile text card",
        "negative_prompt": "realistic, horror",
        "card_role": "cover" if index == 1 else "step",
        "is_screenshot_asset": index == 3,
        "visual_mode": "text_card",
    }
    frame.update(overrides)
    return frame


def _state(**package_overrides):
    contract = _contract()
    frames = [_frame(index) for index in range(1, 7)]
    frames[0]["on_image_copy"] = contract["first_screen_promise"]
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
        "storyboards": frames,
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


def test_carousel_qa_rejects_missing_screenshot_asset():
    state = _state()
    for frame in state["publish_package"]["storyboards"]:
        frame["is_screenshot_asset"] = False

    result = _qa_node()(state)

    assert result["carousel_qa_result"].passed is False
    assert result["decision_output"].next_node == "R1_REFLECTOR"
    assert result["carousel_qa_result"].issues[0].rule_id == "missing_screenshot_asset"
    task = result["decision_output"].normalized_input.r1_input.editorial_tasks.mandatory[0]
    assert (task.source, task.severity, task.location_hint) == (
        "carousel_qa",
        "high",
        "storyboards[0].is_screenshot_asset",
    )


def test_carousel_qa_accepts_contract_compliant_cards():
    result = _qa_node()(_state())

    assert result["carousel_qa_result"].passed is True
    assert result.get("decision_output") is None
    assert _route_after_qa()(result) == "human_review"


def test_carousel_qa_reports_each_deterministic_contract_failure():
    state = _state()
    frames = state["publish_package"]["storyboards"]
    state["publish_package"]["storyboards"] = frames[:5]
    frames[0].update({"card_role": "step", "on_image_copy": "不符合首屏承诺"})
    frames[1]["visual_mode"] = "comparison_table"
    frames[2]["visual_description"] = "卡通 IP 装饰插画"
    frames[3]["on_image_copy"] = frames[4]["on_image_copy"]

    result = _qa_node()(state)

    assert {issue.rule_id for issue in result["carousel_qa_result"].issues} == {
        "card_count_out_of_range",
        "cover_role_missing",
        "first_screen_promise_mismatch",
        "visual_mode_mismatch",
        "banned_decorative_term",
        "duplicate_on_image_copy",
    }
    assert {
        issue.rule_id: issue.location_hint
        for issue in result["carousel_qa_result"].issues
    } == {
        "card_count_out_of_range": "storyboards[0].frame_id",
        "cover_role_missing": "storyboards[0].card_role",
        "first_screen_promise_mismatch": "storyboards[0].on_image_copy",
        "visual_mode_mismatch": "storyboards[1].visual_mode",
        "banned_decorative_term": "storyboards[2].visual_description",
        "duplicate_on_image_copy": "storyboards[4].on_image_copy",
    }
    assert all(
        task.location_hint.startswith("storyboards[")
        for task in result["decision_output"].normalized_input.r1_input.editorial_tasks.mandatory
    )
    assert _route_after_qa()(result) == "r1_reflector"


def test_carousel_qa_empty_storyboards_reports_independent_first_card_failures():
    result = _qa_node()(_state(storyboards=[]))

    issues_by_rule = {
        issue.rule_id: issue.location_hint
        for issue in result["carousel_qa_result"].issues
    }
    assert issues_by_rule == {
        "card_count_out_of_range": "storyboards[0].frame_id",
        "cover_role_missing": "storyboards[0].card_role",
        "first_screen_promise_mismatch": "storyboards[0].on_image_copy",
        "missing_screenshot_asset": "storyboards[0].is_screenshot_asset",
    }
    tasks_by_rule = {
        task.task_id.removeprefix("carousel_qa_").rsplit("_", 1)[0]: task.location_hint
        for task in result["decision_output"].normalized_input.r1_input.editorial_tasks.mandatory
    }
    assert tasks_by_rule == issues_by_rule


def test_carousel_qa_turns_schema_failures_into_atomic_r1_tasks():
    state = _state()
    del state["publish_package"]["storyboards"][0]["negative_prompt"]

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
    assert schema_issue.location_hint == "storyboards[0].negative_prompt"
    assert task.source == "carousel_qa"
    assert task.severity == "high"


def test_carousel_qa_rejects_contract_visual_mode_outside_active_creator_profile():
    state = _state()
    state["creator_profile"] = COMMUTING_BEAUTY_WOMEN_V1.model_copy(
        update={"visual_modes": ("comparison_table",)}
    )

    result = _qa_node()(state)

    issue = result["carousel_qa_result"].issues[0]
    assert (issue.rule_id, issue.location_hint) == (
        "creator_profile_visual_mode_mismatch",
        "storyboards[0].visual_mode",
    )
