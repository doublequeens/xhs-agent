from langgraph.types import interrupt

from src.schemas import AgentState


def human_review_node(state: AgentState) -> AgentState:
    """
    Pause after assembler so a human can review or edit publish_package.
    Execution continues only after the human explicitly approves it.
    """
    publish_package = state.get("publish_package")
    if not publish_package:
        raise ValueError("human_review_node requires `publish_package` in state.")

    review_round = state.get("review_round", 0) or 0

    while True:
        review_result = interrupt(
            {
                "kind": "publish_review",
                "message": "请审核 assembler 的结果。只有输入 yes 才会继续到 content_writer。",
                "publish_package": publish_package,
                "review_round": review_round + 1,
            }
        )

        if not isinstance(review_result, dict):
            raise ValueError("Human review resume payload must be a dict.")

        edited_publish_package = review_result.get("edited_publish_package")
        if edited_publish_package is not None:
            publish_package = edited_publish_package

        approved = review_result.get("approved", False)
        feedback = review_result.get("feedback")
        review_round += 1

        if approved:
            return {
                "publish_package": publish_package,
                "review_status": "approved",
                "review_feedback": feedback,
                "review_round": review_round,
                "current_node": "HUMAN_REVIEW",
            }
