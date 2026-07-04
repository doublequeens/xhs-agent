from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.domain import find_policy_violations, normalize_policy_text
from src.models import get_model
from src.schemas import AgentState, R2Output
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value


def _get_value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


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
    combined_text = "\n".join([title, body])
    ordered_issues = find_policy_violations(combined_text)
    normalized_title = normalize_policy_text(title)

    issues = []
    for issue in ordered_issues:
        location = "revised_title" if issue.matched_text in normalized_title else "revised_md"
        issues.append(issue.model_copy(update={"location": location}))
    return issues


def _find_unresolved_claims(evidence_briefs, content_snapshot):
    combined_text = "\n".join(
        [
            _get_value(content_snapshot, "revised_title", "") or "",
            _get_value(content_snapshot, "revised_md", "") or "",
        ]
    )
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
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})
    evidence_briefs = state.get("evidence_briefs", {})
    content_snapshot = _get_value(r2_input, "content_snapshot")
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

    audit = r2_output.compliance_audit
    matched_policy_rules = _dedupe_strings(
        list(audit.matched_policy_rules) + [issue.rule_id for issue in deterministic_policy_issues]
    )
    unresolved_claims = _dedupe_strings(list(audit.unresolved_claims) + unresolved_claims)
    r2_output.compliance_audit = audit.model_copy(
        update={
            "block_publish": bool(audit.block_publish or matched_policy_rules or unresolved_claims),
            "matched_policy_rules": matched_policy_rules,
            "unresolved_claims": unresolved_claims,
        }
    )

    return {
        "r2_output": r2_output,
        "current_node": "R2_COMPLIANCE"}
