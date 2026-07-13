import json
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from src.domain import find_policy_violations, get_topic_metadata
from src.models import get_model
from src.schemas import AgentState
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas import DecisionOutput


def _get_value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _select_topic_angle_ids(source, decision_input):
    if source in {"TITLE_RANKER", "R1_REFLECTOR"}:
        topic_id = _get_value(decision_input, "topic_id")
        angle_id = _get_value(decision_input, "angle_id")
    elif source == "R2_COMPLIANCE":
        content_snapshot = _get_value(decision_input, "content_snapshot")
        topic_id = _get_value(content_snapshot, "topic_id")
        angle_id = _get_value(content_snapshot, "angle_id")
    else:
        raise ValueError(f"Unsupported decision source: {source}")

    if not topic_id or not angle_id:
        raise ValueError(f"Missing topic_id or angle_id for source {source}")

    return topic_id, angle_id


def _extract_selected_content_fields(source, decision_input):
    if source == "TITLE_RANKER":
        payload = _get_value(decision_input, "winner") or _get_value(decision_input, "content_candidate") or decision_input
    elif source == "R1_REFLECTOR":
        payload = _get_value(decision_input, "content_candidate") or _get_value(decision_input, "content_snapshot") or decision_input
    elif source == "R2_COMPLIANCE":
        payload = _get_value(decision_input, "content_snapshot") or decision_input
    else:
        raise ValueError(f"Unsupported decision source: {source}")

    fields = {
        "topic_id": _get_value(payload, "topic_id"),
        "angle_id": _get_value(payload, "angle_id"),
        "topic": _get_value(payload, "topic"),
        "angle": _get_value(payload, "angle"),
        "target_group": _get_value(payload, "target_group"),
        "core_pain": _get_value(payload, "core_pain"),
        "best_cover_copy": _get_value(payload, "best_cover_copy"),
    }

    missing = [name for name, value in fields.items() if value in (None, "")]
    if missing:
        raise ValueError(f"Missing selected content fields for source {source}: {', '.join(missing)}")

    return fields


def _dedupe_tasks(tasks):
    deduped = []
    seen = set()
    for task in tasks:
        key = (task["instruction"], task["location_hint"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(task)
    return deduped


def _deterministic_policy_locations(r2_output):
    content_snapshot = _get_value(r2_output, "content_snapshot")
    title = _get_value(content_snapshot, "revised_title", "") or ""
    body = _get_value(content_snapshot, "revised_md", "") or ""
    locations = {
        issue.rule_id: "title"
        for issue in find_policy_violations(title)
    }
    for issue in find_policy_violations(body):
        locations.setdefault(issue.rule_id, "draft_md")
    for index, frame in enumerate(
        _get_value(content_snapshot, "storyboard_visible_text", []) or []
    ):
        for field_name, text in dict(_get_value(frame, "text_blocks", {}) or {}).items():
            for issue in find_policy_violations(
                text or ""
            ):
                locations.setdefault(
                    issue.rule_id,
                    f"storyboard_visible_text[{index}].text_blocks.{field_name}",
                )
    return locations


def _build_blocked_r2_tasks(r2_output):
    compliance_audit = _get_value(r2_output, "compliance_audit")
    required_fixes = list(_get_value(compliance_audit, "required_fixes", []) or [])
    suggested_fixes = list(_get_value(compliance_audit, "suggested_fixes", []) or [])
    matched_policy_rules = list(_get_value(compliance_audit, "matched_policy_rules", []) or [])
    unresolved_claims = list(_get_value(compliance_audit, "unresolved_claims", []) or [])
    policy_locations = _deterministic_policy_locations(r2_output)

    mandatory = [
        {
            "task_id": _get_value(fix, "fix_id", f"de_required_{index:03d}"),
            "source": "r2_compliance",
            "instruction": _get_value(fix, "instruction", "Resolve required compliance issue."),
            "severity": "high",
            "location_hint": "title" if _get_value(fix, "location_hint") == "revised_title" else "draft_md",
            "rationale": "Required by compliance audit.",
            "before": _get_value(fix, "before"),
            "after_hint": _get_value(fix, "after_suggestion"),
        }
        for index, fix in enumerate(required_fixes, start=1)
    ]
    optional = [
        {
            "task_id": _get_value(fix, "fix_id", f"de_optional_{index:03d}"),
            "source": "r2_compliance",
            "instruction": _get_value(fix, "instruction", "Consider the suggested compliance improvement."),
            "severity": "medium",
            "location_hint": "title" if _get_value(fix, "location_hint") == "revised_title" else "draft_md",
            "rationale": "Suggested by compliance audit.",
            "before": _get_value(fix, "before"),
            "after_hint": _get_value(fix, "after_suggestion"),
        }
        for index, fix in enumerate(suggested_fixes, start=1)
    ]

    for index, rule_id in enumerate(matched_policy_rules, start=1):
        mandatory.append(
            {
                "task_id": f"de_policy_{index:03d}",
                "source": "system",
                "instruction": f"Remove or rewrite content that triggers policy rule `{rule_id}`.",
                "severity": "high",
                "location_hint": policy_locations.get(rule_id, "draft_md"),
                "rationale": "Deterministic policy guard blocked publish.",
                "before": None,
                "after_hint": "Use neutral, non-medical language without guarantees or dosage advice.",
            }
        )

    for index, claim in enumerate(unresolved_claims, start=1):
        mandatory.append(
            {
                "task_id": f"de_claim_{index:03d}",
                "source": "system",
                "instruction": f"Remove or substantiate the unsupported claim: {claim}",
                "severity": "high",
                "location_hint": "draft_md",
                "rationale": "Evidence brief still marks this claim unsupported.",
                "before": claim,
                "after_hint": "Replace with a sourced, non-absolute description or remove it.",
            }
        )

    return {
        "mandatory": _dedupe_tasks(mandatory),
        "optional": _dedupe_tasks(optional),
    }


def _task_identity(task):
    return (_get_value(task, "task_id"), _get_value(task, "source"))


def _is_deterministic_system_task(task):
    if _get_value(task, "source") != "system":
        return False
    task_id = _get_value(task, "task_id", "") or ""
    return task_id.startswith("de_policy_") or task_id.startswith("de_claim_")


def _is_valid_editorial_tasks(editorial_tasks):
    if not isinstance(editorial_tasks, dict):
        return False
    mandatory = editorial_tasks.get("mandatory")
    optional = editorial_tasks.get("optional")
    return isinstance(mandatory, list) and isinstance(optional, list)


def _is_valid_r1_input(r1_input):
    if not isinstance(r1_input, dict):
        return False
    return all(
        key in r1_input
        for key in ("content_candidate", "editorial_tasks", "revision_meta", "decision_trace")
    ) and _is_valid_editorial_tasks(r1_input["editorial_tasks"])


def _storyboard_visible_text_as_dicts(value):
    return [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in list(value or [])
    ]


def _set_r1_storyboard_visible_text(r1_input, content_snapshot):
    merged_r1_input = dict(r1_input)
    content_candidate = dict(merged_r1_input["content_candidate"])
    content_candidate["storyboard_visible_text"] = _storyboard_visible_text_as_dicts(
        _get_value(content_snapshot, "storyboard_visible_text", [])
    )
    merged_r1_input["content_candidate"] = content_candidate
    return merged_r1_input


def _propagate_storyboard_visible_text(decision_output_json, decision_input):
    storyboard_visible_text = _storyboard_visible_text_as_dicts(
        _get_value(decision_input, "storyboard_visible_text", [])
    )
    if not storyboard_visible_text:
        return decision_output_json

    normalized_input = _get_value(decision_output_json, "normalized_input")
    if not isinstance(normalized_input, dict):
        return decision_output_json

    destination_key = (
        "r2_input"
        if _get_value(decision_output_json, "next_node") == "R2_COMPLIANCE"
        else "r1_input"
    )
    destination = normalized_input.get(destination_key)
    if not isinstance(destination, dict):
        return decision_output_json

    container_key = (
        "content_snapshot" if destination_key == "r2_input" else "content_candidate"
    )
    container = destination.get(container_key)
    if not isinstance(container, dict):
        return decision_output_json

    updated_output = dict(decision_output_json)
    updated_normalized = dict(normalized_input)
    updated_destination = dict(destination)
    updated_container = dict(container)
    updated_container["storyboard_visible_text"] = storyboard_visible_text
    updated_destination[container_key] = updated_container
    updated_normalized[destination_key] = updated_destination
    updated_output["normalized_input"] = updated_normalized
    return updated_output


def _merge_blocked_r2_tasks(r1_input, blocked_tasks):
    editorial_tasks = dict(r1_input["editorial_tasks"])
    existing_mandatory = [
        task for task in list(editorial_tasks.get("mandatory") or [])
        if not _is_deterministic_system_task(task)
    ]
    existing_optional = [
        task for task in list(editorial_tasks.get("optional") or [])
        if not _is_deterministic_system_task(task)
    ]
    deterministic_mandatory = list(blocked_tasks.get("mandatory") or [])
    blocked_optional = list(blocked_tasks.get("optional") or [])

    merged_mandatory = list(existing_mandatory)
    mandatory_index_by_key = {
        _task_identity(task): index
        for index, task in enumerate(merged_mandatory)
    }

    for task in deterministic_mandatory:
        key = _task_identity(task)
        existing_index = mandatory_index_by_key.get(key)
        if existing_index is None:
            mandatory_index_by_key[key] = len(merged_mandatory)
            merged_mandatory.append(task)
            continue
        merged_mandatory[existing_index] = task

    merged_optional = list(existing_optional)
    optional_index_by_key = {
        _task_identity(task): index
        for index, task in enumerate(merged_optional)
    }
    for task in blocked_optional:
        key = _task_identity(task)
        existing_index = optional_index_by_key.get(key)
        if existing_index is None:
            optional_index_by_key[key] = len(merged_optional)
            merged_optional.append(task)
            continue
        merged_optional[existing_index] = task

    merged_editorial_tasks = dict(editorial_tasks)
    merged_editorial_tasks["mandatory"] = merged_mandatory
    merged_editorial_tasks["optional"] = merged_optional

    merged_r1_input = dict(r1_input)
    merged_r1_input["editorial_tasks"] = merged_editorial_tasks
    return merged_r1_input


def _enforce_blocked_r2_decision(decision_output_json, decision_input):
    compliance_audit = _get_value(decision_input, "compliance_audit")
    if not _get_value(compliance_audit, "block_publish", False):
        return decision_output_json

    blocked_tasks = _build_blocked_r2_tasks(decision_input)
    normalized_input = _get_value(decision_output_json, "normalized_input", {}) or {}
    r1_input = _get_value(normalized_input, "r1_input")
    if _get_value(decision_output_json, "next_node") == "R1_REFLECTOR" and _is_valid_r1_input(r1_input):
        decision_output_json["normalized_input"] = dict(normalized_input)
        r1_input = _set_r1_storyboard_visible_text(r1_input, _get_value(decision_input, "content_snapshot"))
        decision_output_json["normalized_input"]["r1_input"] = _merge_blocked_r2_tasks(
            r1_input,
            blocked_tasks,
        )
        return decision_output_json

    content_snapshot = _get_value(decision_input, "content_snapshot")
    revision_meta = _get_value(decision_input, "revision_meta")
    matched_policy_rules = list(_get_value(compliance_audit, "matched_policy_rules", []) or [])
    unresolved_claims = list(_get_value(compliance_audit, "unresolved_claims", []) or [])
    why_this_route = ["Deterministic policy guard blocked publish; return to R1."]
    if matched_policy_rules:
        why_this_route.append(f"matched_policy_rules={matched_policy_rules}")
    if unresolved_claims:
        why_this_route.append(f"unresolved_claims={unresolved_claims}")

    decision_output_json["next_node"] = "R1_REFLECTOR"
    decision_output_json["normalized_input"] = {
        "r1_input": {
            "content_candidate": {
                "draft_id": _get_value(content_snapshot, "draft_id"),
                "draft_md": _get_value(content_snapshot, "revised_md"),
                "best_title": _get_value(content_snapshot, "revised_title"),
                "best_title_id": None,
                "safer_title": None,
                "safer_title_id": None,
                "why_win": None,
                "topic_id": _get_value(content_snapshot, "topic_id"),
                "topic": _get_value(content_snapshot, "topic"),
                "angle_id": _get_value(content_snapshot, "angle_id"),
                "angle": _get_value(content_snapshot, "angle"),
                "target_group": _get_value(content_snapshot, "target_group"),
                "core_pain": _get_value(content_snapshot, "core_pain"),
                "best_cover_copy": _get_value(content_snapshot, "best_cover_copy"),
                "storyboard_visible_text": _storyboard_visible_text_as_dicts(
                    _get_value(content_snapshot, "storyboard_visible_text", [])
                ),
            },
            "editorial_tasks": blocked_tasks,
            "revision_meta": {
                "revision_id": _get_value(revision_meta, "revision_id"),
                "round": _get_value(revision_meta, "round"),
                "diff_summary": list(_get_value(revision_meta, "diff_summary", []) or []),
                "next_actions": list(_get_value(revision_meta, "next_actions", []) or []),
            },
            "decision_trace": {
                "source_node": "R2_COMPLIANCE",
                "why_this_route": why_this_route,
            },
        }
    }
    return decision_output_json

def decision_engine_node(state: AgentState) -> AgentState:
    """
    A node that makes decisions based on the outputs of previous nodes. It evaluates the outputs from the title ranker, R1 reflector, and R2 compliance nodes to determine the best course of action for content creation.
    R2 compliance node and decides where to route the workflow next, such as whether to proceed to R2 compliance check, or to go back to R1 reflection for further refinement. And the output format of the decision engine will
    be differ based on the target node, the output format of R1, R2 and hashtag will be different.
    Args:
        state (AgentState): The current state of the agent.
    Returns:
        AgentState: Updated agent state with the decision output.
    """

    current_node = state.get("current_node", None)
    if "TITLE_RANKER" == current_node:
        source = "TITLE_RANKER"
        decision_input = state["title_winner"]
    elif "R1_REFLECTOR" == current_node:
        source = "R1_REFLECTOR"
        decision_input = state["r1_output"]
    else:
        source = "R2_COMPLIANCE"
        decision_input = state["r2_output"]

    selected_fields = _extract_selected_content_fields(source, decision_input)
    topic_metadata = get_topic_metadata(state.get("trends", []), selected_fields["topic_id"])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    
    system_prompt = compose_prompt_for_state("decision_engine", state)
    template = PromptTemplate(
        input_variables=["source", "decision_input", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- source:\n{source}\n"
            "- decision_input:\n{decision_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请按 system 规则处理。"
        ),
    )
    human_prompt = template.format(
        source=source,
        decision_input=serialize_prompt_value(decision_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )

    messages8 = [
        SystemMessage(content=system_prompt), 
        HumanMessage(content=human_prompt)
    ]

    model = get_model()

    # 引入自修复重试机制 (Self-Correction Loop)
    max_retries = 3
    for attempt in range(max_retries):
        decision_output_json = model.execute(messages8)
        if source == "R2_COMPLIANCE":
            decision_output_json = _enforce_blocked_r2_decision(decision_output_json, decision_input)
        elif source == "R1_REFLECTOR":
            decision_output_json = _propagate_storyboard_visible_text(
                decision_output_json,
                decision_input,
            )

        try:
            normalized_input = decision_output_json.get("normalized_input", {})
            hashtag_input = normalized_input.get("hashtag_input") if isinstance(normalized_input, dict) else None
            if hashtag_input is not None:
                hashtag_input.update(
                    {
                        "topic_id": selected_fields["topic_id"],
                        "angle_id": selected_fields["angle_id"],
                        "topic": selected_fields["topic"],
                        "angle": selected_fields["angle"],
                        "target_group": selected_fields["target_group"],
                        "core_pain": selected_fields["core_pain"],
                        "best_cover_copy": selected_fields["best_cover_copy"],
                        **topic_metadata,
                    }
                )
            decision_output = DecisionOutput(**decision_output_json)
            # 解析成功，跳出循环并返回
            return {"decision_output": decision_output}
        except Exception as e:
            print(f"[Attempt {attempt + 1}/{max_retries}] 格式校验失败，触发大模型自修复机制: {e}")
            if attempt == max_retries - 1:
                # 如果最后一次重试仍然失败，才抛出异常
                raise RuntimeError(f"Process terminated due to error after {max_retries} attempts: {e}")
            
            # 将错误的输出和报错信息喂给大模型，让它自己修正
            messages8.append(AIMessage(content=json.dumps(decision_output_json, ensure_ascii=False)))
            messages8.append(HumanMessage(content=f"你的上一次输出触发了以下数据校验错误:\n{e}\n请务必严格按照要求的 JSON 结构重新输出，不要漏掉必填字段，也不要改变字段层级。"))
