import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.models import get_model
from src.nodes.publish_patch import (
    apply_storyboard_visible_text_patch,
    extract_storyboard_visible_text,
    merge_publish_package,
    merge_storyboard_visible_text,
    storyboard_patch_without_visible_text,
)
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas import AgentState, CarouselFrame, CarouselPayload, VisualPlan
from src.schemas.content_contract import ContentContract


_STORYBOARDS_GENERATOR_MAX_RETRIES = 3


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def _selected_content_contract(state: AgentState, publish_package: dict) -> dict:
    """Read the topic contract for a pre-visual-plan checkpoint."""

    topic_id = publish_package.get("topic_id")
    matches = [
        topic
        for topic in state.get("trends") or []
        if _get_value(topic, "topic_id") == topic_id
    ]
    if not matches:
        raise ValueError(f"Unknown topic_id: {topic_id}")
    if len(matches) > 1:
        raise ValueError(f"Duplicate topic_id: {topic_id}")

    content_contract = _get_value(matches[0], "content_contract")
    if content_contract is None:
        raise ValueError(f"Selected topic {topic_id} requires content_contract")
    if hasattr(content_contract, "model_dump"):
        return content_contract.model_dump(mode="json")
    return dict(content_contract)


def _final_content_contract(
    publish_package: dict,
    visual_plan: VisualPlan,
) -> ContentContract:
    raw_contract = publish_package.get("content_contract")
    if raw_contract is None:
        raise ValueError(
            "semantic storyboard generation requires "
            "publish_package.content_contract"
        )
    contract = ContentContract.model_validate(raw_contract)
    if contract.content_job != visual_plan.content_job:
        raise ValueError(
            "publish_package.content_contract must match visual_plan "
            "content_job"
        )
    return contract


def _semantic_payload(
    raw_payload: Any,
    visual_plan: VisualPlan,
    content_contract: ContentContract,
) -> CarouselPayload:
    if isinstance(raw_payload, CarouselPayload):
        payload = raw_payload
    else:
        payload = CarouselPayload.model_validate(raw_payload)
    expected = [
        (item.frame_id, item.role, item.page_archetype)
        for item in visual_plan.frame_plan
    ]
    actual = [
        (item.frame_id, item.role, item.page_archetype)
        for item in payload.storyboards
    ]
    if actual != expected:
        raise ValueError(
            "storyboard frames must exactly match visual_plan frame order, "
            "roles, and page archetypes"
        )
    if payload.storyboards[0].headline != content_contract.first_screen_promise:
        raise ValueError(
            "storyboard cover headline must exactly equal "
            "content_contract.first_screen_promise"
        )
    return payload


# Account-level persona rendered on editorial pages. Placeholder — swap for the
# real account persona. Visible/locked content (see CarouselFrame). Per-family so
# each bespoke family can carry its own handle; a family only gets a persona when
# its bespoke renderer renders the persona atom on every path (else the probe's
# actual!=expected copy contract breaks).
_ACCOUNT_PERSONA = "@补妆急救站 · 实操笔记"
_PERSONA_BY_FAMILY: dict[str, str] = {
    "soft_pink": _ACCOUNT_PERSONA,
    "white_quote": "@成分党·文献派",
    "pink_red": "@成分党·文献派",
    "deep_teal": "@成分党·文献派",
    "green_catalog": "@成分党·文献派",
    "coral_impact": "@成分党·文献派",
}
_HERO_DIGIT_RE = re.compile(r"(\d+)\s*步")


def _curate_frames_for_publish(
    payload: CarouselPayload, visual_plan: VisualPlan
) -> CarouselPayload:
    """Curate storyboard frames before the publish package is locked.

    - Drop the compliance footer from EVERY frame (all families): disclaimer
      text must never appear in the rendered images (hard product policy). The
      footer stays absent from the frame, so renderer.render_footer and the
      expected-copy helpers (both ``if frame.footer``) automatically skip it —
      no contract mismatch.
    - Families with a bespoke persona footer (see _PERSONA_BY_FAMILY): add the
      account persona to every frame. Each such family's renderer must emit the
      persona atom on every archetype path.
    - soft_pink only: keep covers clean by dropping their content body (covers
      show only the hero headline + emphasis + persona, matching the approved
      editorial cover) and extract the ``N步`` digit as a hero numeral.
    - white_quote only: keep covers clean (cover shows only the centered quote
      + subtitle + persona, matching the mockup).
    """
    family = visual_plan.template_family
    persona = _PERSONA_BY_FAMILY.get(family)
    curated: list[CarouselFrame] = []
    for frame in payload.storyboards:
        update: dict[str, Any] = {"footer": None}
        if persona:
            update["persona"] = persona
        if family == "soft_pink":
            if frame.page_archetype == "cover":
                update["content_blocks"] = []
                # The cover hero already shows the step count; drop a leading
                # emphasis that repeats it (e.g. "3步清爽补妆") so only the
                # subtitle remains under the title.
                if len(frame.emphasis) > 1:
                    update["emphasis"] = list(frame.emphasis[1:])
                # Extract the step-count digit as a standalone hero numeral
                # (rendered big, beside the title). The digit (and any colon) is
                # removed from the title at render time via
                # primitives.cover_title_text, so the headline stays unchanged.
                match = _HERO_DIGIT_RE.search(frame.headline)
                if match:
                    update["hero_numeral"] = match.group(1)
        elif family in _PERSONA_BY_FAMILY:
            # every bespoke family renders a clean cover (centered hero only);
            # drop the cover body so it matches the mockup and fits the layout.
            if frame.page_archetype == "cover":
                update["content_blocks"] = []
        curated.append(frame.model_copy(update=update))
    return payload.model_copy(update={"storyboards": curated})


def _human_prompt(
    *,
    publish_package: dict,
    content_contract: dict,
    visual_plan: VisualPlan | None,
    domain_context,
    content_policy,
    evidence_briefs,
) -> str:
    sections = [
        "输入参数如下：",
        f"- publish_package:\n{serialize_prompt_value(publish_package)}",
        f"- content_contract:\n{serialize_prompt_value(content_contract)}",
    ]
    if visual_plan is not None:
        sections.append(f"- visual_plan:\n{serialize_prompt_value(visual_plan)}")
    sections.extend(
        [
            f"- domain_context:\n{serialize_prompt_value(domain_context)}",
            f"- content_policy:\n{serialize_prompt_value(content_policy)}",
            f"- evidence_briefs:\n{serialize_prompt_value(evidence_briefs)}",
            "请按照 system 规则进行处理。",
        ]
    )
    return "\n".join(sections)


def storyboards_generator_node(state: AgentState) -> AgentState:
    """Generate a strict semantic carousel from the persisted modern plan."""

    publish_package = state.get("publish_package", {})
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    visual_plan_value = state.get("visual_plan")
    if visual_plan_value is None:
        raise ValueError("storyboards_generator_node requires visual_plan")
    visual_plan = VisualPlan.model_validate(visual_plan_value)
    validated_contract = _final_content_contract(
        publish_package,
        visual_plan,
    )
    content_contract = validated_contract.model_dump(mode="json")

    messages = [
        SystemMessage(
            content=compose_prompt_for_state("storyboards_generator", state)
        ),
        HumanMessage(
            content=_human_prompt(
                publish_package=publish_package,
                content_contract=content_contract,
                visual_plan=visual_plan,
                domain_context=domain_context,
                content_policy=content_policy,
                evidence_briefs=evidence_briefs,
            )
        ),
    ]

    payload: CarouselPayload | None = None
    last_error: Exception | None = None
    for attempt in range(_STORYBOARDS_GENERATOR_MAX_RETRIES):
        storyboard_json = get_model().execute(messages)
        try:
            payload = CarouselPayload.model_validate(storyboard_json)
            break
        except Exception as error:
            last_error = error
            print(
                f"[Attempt {attempt + 1}/{_STORYBOARDS_GENERATOR_MAX_RETRIES}] "
                f"格式校验失败，触发大模型自修复机制: {error}"
            )
            if attempt == _STORYBOARDS_GENERATOR_MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Process terminated due to storyboards generator error "
                    f"after {_STORYBOARDS_GENERATOR_MAX_RETRIES} attempts: {error}"
                ) from error
            messages.append(
                AIMessage(content=json.dumps(storyboard_json, ensure_ascii=False, default=str))
            )
            messages.append(
                HumanMessage(
                    content=(
                        "你的上一次输出触发了以下数据校验错误:\n"
                        f"{error}\n"
                        "请务必严格按照要求的 JSON 结构重新输出，"
                        "不要漏掉必填字段，也不要改变字段层级。注意："
                        "storyboard 数组必须严格匹配 visual_plan 的 frame 顺序、"
                        "role 与 page archetype；"
                        "首帧 headline 必须逐字等于 content_contract.first_screen_promise；"
                        "content_blocks / visual_slots / emphasis 等数组字段不能写成 null，"
                        "缺失时输出空数组；"
                        "block_type、role、layout 等 enum 字段必须使用各自允许的取值。"
                    )
                )
            )

    if payload is None:
        raise RuntimeError(
            f"storyboards generator produced no payload: {last_error}"
        )

    # Re-run the full semantic payload (structural checks raise ValueError unchanged).
    payload = _semantic_payload(payload, visual_plan, validated_contract)
    generated_storyboards = payload.model_dump(mode="json")["storyboards"]

    merged_publish_package = dict(publish_package)
    merged_publish_package["content_contract"] = content_contract
    merged_publish_package["storyboards"] = generated_storyboards

    pending_patch = state.get("pending_human_publish_patch")
    if pending_patch:
        merged_publish_package = merge_publish_package(
            merged_publish_package,
            storyboard_patch_without_visible_text(pending_patch),
            replace_storyboards=bool(
                state.get("pending_human_replace_storyboards")
            ),
        )

    r2_output = state.get("r2_output")
    content_snapshot = getattr(r2_output, "content_snapshot", None)
    if content_snapshot is None and isinstance(r2_output, dict):
        content_snapshot = r2_output.get("content_snapshot")
    visible_text = getattr(content_snapshot, "storyboard_visible_text", None)
    if visible_text is None and isinstance(content_snapshot, dict):
        visible_text = content_snapshot.get("storyboard_visible_text")
    if visible_text is not None:
        visible_patch = merge_storyboard_visible_text(
            extract_storyboard_visible_text(publish_package.get("storyboards")),
            visible_text,
        )
        if visible_patch:
            merged_publish_package["storyboards"] = (
                apply_storyboard_visible_text_patch(
                    merged_publish_package.get("storyboards"),
                    visible_patch,
                )
            )

    final_payload = _semantic_payload(
        {"storyboards": merged_publish_package.get("storyboards")},
        visual_plan,
        validated_contract,
    )
    final_payload = _curate_frames_for_publish(final_payload, visual_plan)
    merged_publish_package["storyboards"] = final_payload.model_dump(
        mode="json"
    )["storyboards"]

    return {
        "publish_package": merged_publish_package,
        "pending_human_publish_patch": None,
        "pending_human_replace_storyboards": None,
    }
