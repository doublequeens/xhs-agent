from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState, R1Output, R1Scores, RevisionMeta
from src.prompts import all_prompts

def r1_reflector_node(state: AgentState) -> AgentState:
    """
    A node that reflects on R1 output using Gemini models.

    Args:
        state (AgentState): The current state of the agent containing R1 output.
    Returns:
        AgentState: Updated agent state with reflections on R1 output.
    """
    r1_input = state.get("r1_input", None)

    system_prompt = all_prompts["NODE_H_R1_REFLECTOR"]
    template = PromptTemplate(
        input_variables=["r1_input"],
        template="这是R1的输入结果 r1_input：{r1_input}, 请按 system 规则进行反思改稿"
    )
    human_prompt = template.format(r1_input=r1_input)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]

    r1_reflection_json = get_model("gemini").execute(messages)
    for i in r1_reflection_json:
        if i == "scores":
            try:
                r1_reflection_json[i] = R1Scores(**r1_reflection_json[i])
            except Exception as e:
                print(f"Failed to transform scores to R1Scores schema, please check the detail: {e}")
                r1_reflection_json[i] = None
        elif i == "revision_meta":
            try:
                r1_reflection_json[i] = RevisionMeta(**r1_reflection_json[i])
            except Exception as e:
                print(f"Failed to transform revision_meta to RevisionMeta schema, please check the detail: {e}")
                r1_reflection_json[i] = None
        else:
            pass

    try:
        r1_output = R1Output(**r1_reflection_json)
    except Exception as e:
        print(f"Failed to extract reflection from model output, please check the detail: {e}")
        r1_output = None
    return {"r1_output": r1_output}