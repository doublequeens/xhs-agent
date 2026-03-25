from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R2ComplianceAudit, R2ComplianceIssue, R2ContentSnapShoot, R2Decision, R2RequiredFix, R2SuggestedFix, R2Output, RevisionMeta
from src.prompts import all_prompts

def r2_reflector_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R2 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R2 output.
    Returns:
        AgentState: Updated agent state with reflections on R2 output.
    """
    r1_output = state.get("r1_output", None)

    system_prompt = all_prompts["NODE_I_R2_COMPLIANCE"]
    template = PromptTemplate(
        input_variables=["r1_output"],
        template="这是R1 Reflector的输出结果 r1_output：{r1_output}, 请按 system 规则进行合规审查"
    )
    human_prompt = template.format(r1_output=r1_output)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    r2_complianced_json = get_model("gemini").execute(messages)

    try:
        for i in r2_complianced_json:
            if "content_snapshot" == i.lower():
                r2_complianced_json[i] = R2ContentSnapShoot(**r2_complianced_json[i])
            elif "compliance_audit" == i:
                issues = []
                required_fixes = []
                suggested_fixes = []
                for j in r2_complianced_json[i]:
                    if "issues" == j.lower():
                        for issue in r2_complianced_json[i]["issues"]:
                            issues.append(R2ComplianceIssue(**issue))
                    elif "required_fixes" == j.lower():
                        for r_fix in r2_complianced_json[i]["required_fixes"]:
                            required_fixes.append(R2RequiredFix(**r_fix))
                    elif "suggested_fixes" == j.lower():
                        for s_fix in r2_complianced_json[i]["suggested_fixes"]:
                            suggested_fixes.append(R2SuggestedFix(**s_fix))
                    else:
                        pass
                r2_complianced_json[i]["issues"] = issues
                r2_complianced_json[i]["required_fixes"] = required_fixes
                r2_complianced_json[i]["suggested_fixes"] = suggested_fixes
                r2_complianced_json[i] = R2ComplianceAudit(**r2_complianced_json[i])
            elif "r2_decision" == i.lower():
                r2_complianced_json[i] = R2Decision(**r2_complianced_json[i])
            elif i == "revision_meta":
                r2_complianced_json[i] = RevisionMeta(**r2_complianced_json[i])
            else:
                pass
    except Exception as e:
        print(f"Failed to transform to target schema, please check the detail: {e}")
        r2_complianced_json = None
    
    try:
        r2_output = R2Output(**r2_complianced_json)
    except Exception as e:
        print(f"Failed to transform to R2Output schema, please check the detail: {e}")
        r2_output = None    

    return {"r2_output": r2_output}