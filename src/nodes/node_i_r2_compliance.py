from copy import copy

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.domain import find_policy_violations
from src.models import get_model
from src.schemas import AgentState, R2Output
from src.nodes.publish_patch import (
    extract_storyboard_visible_text,
    merge_storyboard_visible_text,
)
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.nodes.narrative_plan import require_same_narrative_plan


def _get_value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _with_storyboard_visible_text(content_snapshot, storyboard_visible_text):
    if hasattr(content_snapshot, "model_dump"):
        return type(content_snapshot).model_validate(
            {
                **content_snapshot.model_dump(),
                "storyboard_visible_text": storyboard_visible_text,
            }
        )
    updated_snapshot = copy(content_snapshot)
    updated_snapshot.storyboard_visible_text = storyboard_visible_text
    return updated_snapshot


def _dedupe_strings(values):
    seen = set()
    deduped = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _find_deterministic_policy_issues(content_snapshot):
    title = _get_value(content_snapshot, "revised_title", "") or ""
    body = _get_value(content_snapshot, "revised_md", "") or ""
    text_sources = [("revised_title", title), ("revised_md", body)]
    for index, frame in enumerate(
        _get_value(content_snapshot, "storyboard_visible_text", []) or []
    ):
        for field_name, text in dict(_get_value(frame, "text_blocks", {}) or {}).items():
            text_sources.append(
                (
                    f"storyboard_visible_text[{index}].text_blocks.{field_name}",
                    text or "",
                )
            )

    locations_by_rule = {}
    for location, text in text_sources:
        for issue in find_policy_violations(text):
            locations_by_rule.setdefault(issue.rule_id, location)

    combined_text = "\n".join(text for _location, text in text_sources)
    return [
        issue.model_copy(update={"location": locations_by_rule[issue.rule_id]})
        for issue in find_policy_violations(combined_text)
    ]


def _find_unresolved_claims(evidence_briefs, content_snapshot):
    text_fragments = [
        _get_value(content_snapshot, "revised_title", "") or "",
        _get_value(content_snapshot, "revised_md", "") or "",
    ]
    for frame in _get_value(content_snapshot, "storyboard_visible_text", []) or []:
        text_fragments.extend(dict(_get_value(frame, "text_blocks", {}) or {}).values())
    combined_text = "\n".join(text_fragments)
    if not combined_text.strip():
        return []

    unresolved_claims = []
    normalized_text = " ".join(combined_text.split())
    for evidence_brief in (evidence_briefs or {}).values():
        claims = _get_value(evidence_brief, "unsupported_claims", []) or []
        for claim in claims:
            normalized_claim = " ".join(str(claim).split())
            if normalized_claim and normalized_claim in normalized_text:
                unresolved_claims.append(normalized_claim)
    return _dedupe_strings(unresolved_claims)

def r2_compliance_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R2 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R2 output.
    Returns:
        AgentState: Updated agent state with reflections on R2 output.
    """

    decision_output = state["decision_output"]
    r2_input = decision_output.normalized_input.r2_input
    content_snapshot = _get_value(r2_input, "content_snapshot")
    prior_visible_text = extract_storyboard_visible_text(
        (state.get("publish_package") or {}).get("storyboards")
    )
    storyboard_visible_text = merge_storyboard_visible_text(
        prior_visible_text,
        _get_value(content_snapshot, "storyboard_visible_text", []),
    )
    if storyboard_visible_text != _get_value(content_snapshot, "storyboard_visible_text", []):
        content_snapshot = _with_storyboard_visible_text(
            content_snapshot, storyboard_visible_text
        )
        if hasattr(r2_input, "model_copy"):
            r2_input = r2_input.model_copy(update={"content_snapshot": content_snapshot})
        else:
            r2_input = copy(r2_input)
            r2_input.content_snapshot = content_snapshot
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    deterministic_policy_issues = _find_deterministic_policy_issues(content_snapshot)
    unresolved_claims = _find_unresolved_claims(evidence_briefs, content_snapshot)

    system_prompt = compose_prompt_for_state("r2_compliance", state)
    template = PromptTemplate(
        input_variables=[
            "r2_input",
            "domain_context",
            "content_policy",
            "evidence_briefs",
            "deterministic_policy_issues",
            "unresolved_claims",
        ],
        template=(
            "输入参数如下：\n"
            "- r2_input:\n{r2_input}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "- evidence_briefs:\n{evidence_briefs}\n"
            "- deterministic_policy_issues:\n{deterministic_policy_issues}\n"
            "- unresolved_claims:\n{unresolved_claims}\n"
            "请按 system 规则进行处理。"
        ),
    )
    human_prompt = template.format(
        r2_input=serialize_prompt_value(r2_input),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
        evidence_briefs=serialize_prompt_value(evidence_briefs),
        deterministic_policy_issues=serialize_prompt_value(
            [issue.model_dump(mode="json") for issue in deterministic_policy_issues]
        ),
        unresolved_claims=serialize_prompt_value(unresolved_claims),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    
    llm = get_model("deepseek")
    r2_complianced_json = llm.execute(messages)
    
    try:
        r2_output = R2Output(**r2_complianced_json)
    except Exception as e:
        print(f"Failed to transform to R2Output schema, please check the detail: {e}")
        r2_output = None    
        raise RuntimeError(f"Process terminated due to error: {e}")

    selected_narrative_plan = _get_value(content_snapshot, "narrative_plan")
    require_same_narrative_plan(
        r2_output.content_snapshot.narrative_plan,
        selected_narrative_plan,
        stage="r2_compliance",
    )

    audit = r2_output.compliance_audit
    complete_visible_text = merge_storyboard_visible_text(
        _get_value(content_snapshot, "storyboard_visible_text", []),
        r2_output.content_snapshot.storyboard_visible_text,
    )
    if complete_visible_text != r2_output.content_snapshot.storyboard_visible_text:
        r2_output.content_snapshot = _with_storyboard_visible_text(
            r2_output.content_snapshot, complete_visible_text
        )
    deterministic_policy_rule_ids = [issue.rule_id for issue in deterministic_policy_issues]
    matched_policy_rules = _dedupe_strings(
        list(audit.matched_policy_rules) + deterministic_policy_rule_ids
    )
    unresolved_claims = _dedupe_strings(list(audit.unresolved_claims) + unresolved_claims)
    clean_fully_compliant = (
        audit.compliance_status == "fully_compliant"
        and not audit.issues
        and not audit.required_fixes
        and not deterministic_policy_rule_ids
        and not unresolved_claims
    )
    block_publish = False if clean_fully_compliant else bool(
        audit.block_publish
        or audit.required_fixes
        or deterministic_policy_rule_ids
        or unresolved_claims
        or audit.compliance_status == "high_risk_detected"
    )
    r2_output.compliance_audit = audit.model_copy(
        update={
            "block_publish": block_publish,
            "matched_policy_rules": matched_policy_rules,
            "unresolved_claims": unresolved_claims,
        }
    )

    return {
        "r2_output": r2_output,
        "selected_narrative_plan": selected_narrative_plan,
        "current_node": "R2_COMPLIANCE"}
