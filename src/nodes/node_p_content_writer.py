from examples.memory_demo import make_content_id

from src.domain.topic_metadata import get_topic_metadata
from memory.memory_manager import XHSMemoryManager, utc_now_iso
from memory.models import ContentRecord
from src.schemas.agent_state import AgentState


def _get_value(payload, key, default=None):
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _require_review_approval(state: AgentState) -> None:
    if state.get("review_status") != "approved":
        raise ValueError("content_writer_node requires review_status == approved before persistence.")


def _require_value(source, key: str) -> str:
    value = _get_value(source, key)
    if value in (None, ""):
        raise ValueError(f"content_writer_node requires {key} metadata before persistence.")
    return value


def _require_content_contract(publish_package: dict) -> dict:
    content_contract = publish_package.get("content_contract")
    if content_contract is None:
        raise ValueError("content_writer_node requires content_contract metadata before persistence.")
    if hasattr(content_contract, "model_dump"):
        return content_contract.model_dump(mode="json")
    return dict(content_contract)


def _require_r2_compliance_status(state: AgentState) -> str:
    r2_output = state.get("r2_output")
    if r2_output is None:
        raise ValueError("content_writer_node requires r2_output.compliance_audit.compliance_status before persistence.")

    compliance_audit = _get_value(r2_output, "compliance_audit")
    compliance_status = _get_value(compliance_audit, "compliance_status")
    if compliance_status in (None, ""):
        raise ValueError("content_writer_node requires r2_output.compliance_audit.compliance_status before persistence.")

    return compliance_status


def content_writer_node(state: AgentState) -> AgentState:
    """
    A node that writes the final content to the database after assembly.

    Args:
        state (AgentState): The current state of the agent containing the final assembled content and memory manager instance.
    Returns:
        AgentState: The updated agent state.
    """
    _require_review_approval(state)

    publish_package = state.get("publish_package", {})
    trends = state.get("trends")
    if not trends:
        raise ValueError("content_writer_node requires state.trends before persistence.")

    topic_id = _require_value(publish_package, "topic_id")
    topic_metadata = get_topic_metadata(trends, topic_id)

    domain_context = state.get("domain_context", {})
    compliance_status = _require_r2_compliance_status(state)
    profile_version = _require_value(domain_context, "profile_version")
    content_contract = _require_content_contract(publish_package)
    storyboards = list(_get_value(publish_package, "storyboards") or [])
    images = list(_get_value(publish_package, "images") or [])

    record = ContentRecord(
        content_id=make_content_id(),
        status="reviewed",
        created_at=utc_now_iso(),
        topic=publish_package["topic"],
        topic_id=topic_id,
        angle=publish_package["angle"],
        angle_id=publish_package["angle_id"],
        domain=topic_metadata["domain"],
        subdomain=topic_metadata["subdomain"],
        content_intent=topic_metadata["content_intent"],
        profile_version=profile_version,
        risk_level=topic_metadata["risk_level"],
        target_group=publish_package["target_group"],
        core_pain=publish_package["core_pain"],
        title=publish_package["title"],
        cover_copy=publish_package.get("cover_copy"),
        content=publish_package["content"],
        hashtags=publish_package["hashtags"],
        content_format=publish_package.get("content_format", "educational_cards"),
        visual_style=publish_package.get("visual_style", "domain_editorial"),
        card_count=len(storyboards),
        storyboards=storyboards,
        image_paths=[img["image_url"] for img in images],
        compliance_status=compliance_status,
        embedding_text=" ".join([
            publish_package["topic"],
            publish_package["angle"],
            publish_package["target_group"],
            publish_package["core_pain"],
            publish_package["title"],
            " ".join(publish_package["hashtags"]),
        ]),
        metadata={
            "domain": topic_metadata["domain"],
            "subdomain": topic_metadata["subdomain"],
            "content_intent": topic_metadata["content_intent"],
            "profile_version": profile_version,
            "risk_level": topic_metadata["risk_level"],
            "content_contract": content_contract,
        },
    )

    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    try:
        database.save_generated_content(record)
    except Exception as e:
        raise Exception(f"Error occurred while saving generated content to structured database sqlite: {e}")

    try:
        database.save_embedding_content(record)
    except Exception as vector_error:
        try:
            database.delete_content_by_id(record.content_id)
        except Exception as cleanup_error:
            raise RuntimeError(
                "Error occurred while saving generated content to vector database chromadb: "
                f"{vector_error}; compensation delete failed: {cleanup_error}"
            ) from vector_error

        raise RuntimeError(
            f"Error occurred while saving generated content to vector database chromadb: {vector_error}"
        ) from vector_error

    if database.get_content_by_id(record.content_id) and database.get_embedding_content_by_id(record.content_id):
        print(f"Content with ID {record.content_id}, with title {record.title} successfully saved to the structured and embedding database.")
        return {"data_writed": True}

    return {"data_writed": False}
