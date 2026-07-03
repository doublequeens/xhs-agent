from examples.memory_demo import make_content_id

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


def _resolve_compliance_status(state: AgentState, publish_package) -> str:
    r2_output = state.get("r2_output")
    if r2_output is not None:
        compliance_audit = _get_value(r2_output, "compliance_audit")
        compliance_status = _get_value(compliance_audit, "compliance_status")
        if compliance_status:
            return compliance_status

    legacy_status = _get_value(publish_package, "compliance_status")
    if legacy_status:
        return legacy_status

    return "fully_compliant"


def content_writer_node(state: AgentState) -> AgentState:
    """
    A node that writes the final content to the database after assembly.

    Args:
        state (AgentState): The current state of the agent containing the final assembled content and memory manager instance.
    Returns:
        AgentState: The updated agent state.
    """
    _require_review_approval(state)

    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    publish_package = state.get("publish_package", {})
    domain_context = state.get("domain_context", {})
    domain = _require_value(publish_package, "domain")
    subdomain = _require_value(publish_package, "subdomain")
    content_intent = _require_value(publish_package, "content_intent")
    profile_version = _require_value(domain_context, "profile_version")
    risk_level = _require_value(publish_package, "risk_level")
    storyboards = list(_get_value(publish_package, "storyboards") or [])
    images = list(_get_value(publish_package, "images") or [])

    record = ContentRecord(
        content_id=make_content_id(),
        status="reviewed",
        created_at=utc_now_iso(),
        topic=publish_package["topic"],
        topic_id=publish_package["topic_id"],
        angle=publish_package["angle"],
        angle_id=publish_package["angle_id"],
        domain=domain,
        subdomain=subdomain,
        content_intent=content_intent,
        profile_version=profile_version,
        risk_level=risk_level,
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
        compliance_status=_resolve_compliance_status(state, publish_package),
        embedding_text=" ".join([
            publish_package["topic"],
            publish_package["angle"],
            publish_package["target_group"],
            publish_package["core_pain"],
            publish_package["title"],
            " ".join(publish_package["hashtags"]),
        ]),
        metadata={
            "domain": domain,
            "subdomain": subdomain,
            "content_intent": content_intent,
            "profile_version": profile_version,
            "risk_level": risk_level,
        },
    )

    try:
        database.save_generated_content(record)
    except Exception as e:
        raise Exception(f"Error occurred while saving generated content to structured database sqlite: {e}")

    try:
        database.save_embedding_content(record)
    except Exception as e:
        raise Exception(f"Error occurred while saving generated content to vector database chromadb: {e}")

    if database.get_content_by_id(record.content_id) and database.get_embedding_content_by_id(record.content_id):
        print(f"Content with ID {record.content_id}, with title {record.title} successfully saved to the structured and embedding database.")
        return {"data_writed": True}

    return {"data_writed": False}
