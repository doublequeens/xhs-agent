from examples.memory_demo import make_content_id

from src.domain.topic_metadata import get_topic_metadata
from memory.memory_manager import XHSMemoryManager, utc_now_iso
from memory.models import ContentRecord
from src.schemas.agent_state import AgentState
from typing import Any, Optional


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


def _final_rendered_paths(state: AgentState, publish_package: dict) -> list[str]:
    render_manifest = state.get("render_manifest")
    if render_manifest is None:
        raise ValueError(
            "content_writer_node requires render_manifest before persistence."
        )
    pages = list(_get_value(render_manifest, "pages") or [])
    paths = [_get_value(page, "path") for page in pages]
    if not paths or any(not isinstance(path, str) or not path for path in paths):
        raise ValueError(
            "content_writer_node requires complete final rendered image paths."
        )
    return paths


def _derive_visual_signatures(
    state: AgentState, publish_package: dict
) -> dict[str, Any]:
    """Derive the five persisted v2 visual signatures from final artifacts.

    Sourcing follows the task-11 brief:
    - ``narrative_form``/``narrative_signature`` come from
      ``publish_package['narrative_plan']``.
    - ``template_family`` is the persisted ``VisualPlan`` identity.
    - ``frame_plan_signature`` comes from each storyboard ``page_archetype``.
    - ``density_profile`` comes from ``render_manifest.pages[*].density``.

    Derivation is defensive: missing sources yield empty lists or ``None``
    so an R2-approved run whose upstream narrative_plan or render_manifest
    is incomplete still persists.
    """

    narrative_plan = _get_value(publish_package, "narrative_plan")
    narrative_form: Optional[str] = None
    narrative_signature: list[str] = []
    if isinstance(narrative_plan, dict) and narrative_plan:
        narrative_form = narrative_plan.get("narrative_form")
        beats = narrative_plan.get("beats") or []
        for beat in beats:
            if not isinstance(beat, dict):
                continue
            kind = beat.get("kind")
            purpose = beat.get("purpose")
            if not kind or not purpose:
                continue
            narrative_signature.append(f"{kind}:{purpose}")

    visual_plan = state.get("visual_plan")
    template_family = (
        _get_value(visual_plan, "template_family") if visual_plan else None
    )

    frame_plan_signature: list[str] = []
    storyboards = _get_value(publish_package, "storyboards") or []
    for frame in storyboards:
        if not isinstance(frame, dict):
            continue
        archetype = _get_value(frame, "page_archetype")
        if archetype:
            frame_plan_signature.append(archetype)

    render_manifest = state.get("render_manifest")
    density_profile: list[str] = []
    if render_manifest:
        for page in list(_get_value(render_manifest, "pages") or []):
            density = _get_value(page, "density")
            if density:
                density_profile.append(density)

    return {
        "narrative_form": narrative_form,
        "narrative_signature": narrative_signature,
        "template_family": template_family,
        "frame_plan_signature": frame_plan_signature,
        "density_profile": density_profile,
    }


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
    rendered_image_paths = _final_rendered_paths(state, publish_package)
    visual_signatures = _derive_visual_signatures(state, publish_package)

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
        image_paths=rendered_image_paths,
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
        narrative_form=visual_signatures["narrative_form"],
        narrative_signature=visual_signatures["narrative_signature"],
        template_family=visual_signatures["template_family"],
        frame_plan_signature=visual_signatures["frame_plan_signature"],
        density_profile=visual_signatures["density_profile"],
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
