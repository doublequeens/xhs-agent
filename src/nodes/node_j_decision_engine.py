from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from src.models import get_model
from src.schemas import AgentState
from src.prompts import all_prompts
from src.schemas import DecisionOutput

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
    
    system_prompt = all_prompts["NODE_J_DECISION_ENGINE"]
    template = PromptTemplate(
        input_variables=["source", "decision_input"],
        template="这是source：{source}, 这是decision_input：{decision_input}, 请按 system 规则进行处理。 "
    )
    human_prompt = template.format(source=source, decision_input=decision_input)

    messages8 = [
        SystemMessage(content=system_prompt), 
        HumanMessage(content=human_prompt)
    ]

    model = get_model("glm")
    decision_output_json = model.execute(messages8)

    try:
        decision_output = DecisionOutput(**decision_output_json)
        print(f"Decision Engine Node - finished. ")
    except Exception as e:
        print(f"Failed to transform to DecisionOutput schema, please check the detail: {e}")
        decision_output = None
        exit()  

    return {
        "decision_output": decision_output
    }