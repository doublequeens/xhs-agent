"""Content-writer node for the ``llm_scene_v3`` dynamic-visual path (Task 16).

Persists the visual-diversity memory metadata derived from the final approved
dynamic visual contracts after Human Review approval + R2 compliance. The v3
writer does NOT read ``visual_plan`` or ``storyboards``; page count comes from
the persisted ``CarouselDesignPlan``/``RenderManifest`` and the visual identity
comes from the ``VisualDirectionPlan``. Historical storyboard/template columns
stay readable for old analytics but the v3 path stops consuming them.
"""

from examples.memory_demo import make_content_id

from src.domain.topic_metadata import get_topic_metadata
from memory.memory_manager import XHSMemoryManager, utc_now_iso
from memory.models import ContentRecord
from src.schemas.agent_state import AgentState
from src.schemas.content_atoms import canonical_sha256
from src.schemas.scene_graph import TextElement
from typing import Any, Optional


def _get_value(payload, key, default=None):
    if payload is None:
        return default
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _require_review_approval(state: AgentState) -> None:
    if state.get("review_status") != "approved":
        raise ValueError(
            "content_writer_node requires review_status == approved before persistence."
        )


def _require_value(source, key: str) -> str:
    value = _get_value(source, key)
    if value in (None, ""):
        raise ValueError(
            f"content_writer_node requires {key} metadata before persistence."
        )
    return value


def _require_content_contract(publish_package: dict) -> dict:
    content_contract = publish_package.get("content_contract")
    if content_contract is None:
        raise ValueError(
            "content_writer_node requires content_contract metadata before persistence."
        )
    if hasattr(content_contract, "model_dump"):
        return content_contract.model_dump(mode="json")
    return dict(content_contract)


def _require_r2_compliance_status(state: AgentState) -> str:
    r2_output = state.get("r2_output")
    if r2_output is None:
        raise ValueError(
            "content_writer_node requires "
            "r2_output.compliance_audit.compliance_status before persistence."
        )

    compliance_audit = _get_value(r2_output, "compliance_audit")
    compliance_status = _get_value(compliance_audit, "compliance_status")
    if compliance_status in (None, ""):
        raise ValueError(
            "content_writer_node requires "
            "r2_output.compliance_audit.compliance_status before persistence."
        )

    return compliance_status


def _final_rendered_paths(state: AgentState) -> list[str]:
    """Page count + paths from the v3 ``RenderManifest`` (no storyboards)."""
    render_manifest = state.get("render_manifest")
    if render_manifest is None:
        raise ValueError(
            "content_writer_node requires render_manifest before persistence."
        )
    pages = list(_get_value(render_manifest, "pages") or [])
    paths = [_get_value(page, "path") for page in pages]
    if not paths or any(
        not isinstance(path, str) or not path for path in paths
    ):
        raise ValueError(
            "content_writer_node requires complete final rendered image paths."
        )
    return paths


def _derive_dynamic_visual_metadata(state: AgentState) -> dict[str, Any]:
    """Derive the v3 visual-diversity metadata from the dynamic visual contracts.

    - ``page_count``: number of pages in the persisted RenderManifest
      (== CarouselDesignPlan page count on a consistent run).
    - ``template_family``: the ``VisualDirectionPlan`` family identity.
    - ``direction_signature``/``design_signature``: canonical sha256 of the
      persisted ``VisualDirectionPlan``/``CarouselDesignPlan`` pydantic models.
    - ``density_summary``: per-page count of text elements from the
      ``CarouselDesignPlan`` (a compact, deterministic density signal).
    - ``color_summary``: the direction palette plus the per-page background
      color from the ``CarouselDesignPlan``.

    Derivation is defensive so an approved run whose upstream contracts are
    incomplete still persists (missing sources yield empty/None), but the
    production path always reaches the writer with complete contracts because
    Final Guard hard-gates on every contract attestation.
    """
    direction_plan = state.get("visual_direction_plan")
    design_plan = state.get("carousel_design_plan")
    render_manifest = state.get("render_manifest")

    template_family: Optional[str] = (
        _get_value(direction_plan, "template_family")
        if direction_plan is not None
        else None
    )

    direction_signature: Optional[str] = None
    if direction_plan is not None and hasattr(direction_plan, "model_dump"):
        direction_signature = canonical_sha256(direction_plan)

    design_signature: Optional[str] = None
    if design_plan is not None and hasattr(design_plan, "model_dump"):
        design_signature = canonical_sha256(design_plan)

    page_count: Optional[int] = None
    if render_manifest is not None:
        pages = list(_get_value(render_manifest, "pages") or [])
        page_count = len(pages)
    elif design_plan is not None:
        page_count = len(_get_value(design_plan, "pages") or [])

    density_summary: list[int] = []
    color_summary: dict[str, Any] = {}
    if design_plan is not None:
        design_pages = list(_get_value(design_plan, "pages") or [])
        density_summary = [
            sum(
                1
                for element in (_get_value(page, "elements") or ())
                if isinstance(element, TextElement)
            )
            for page in design_pages
        ]
        page_backgrounds = [
            _get_value(page, "background") for page in design_pages
        ]
        palette = list(_get_value(direction_plan, "palette") or []) if direction_plan is not None else []
        color_summary = {
            "palette": palette,
            "page_backgrounds": page_backgrounds,
        }

    return {
        "page_count": page_count,
        "template_family": template_family,
        "direction_signature": direction_signature,
        "design_signature": design_signature,
        "density_summary": density_summary,
        "color_summary": color_summary,
    }


def content_writer_node(state: AgentState) -> AgentState:
    """
    Persist the final approved content + v3 visual-diversity metadata to memory.

    The v3 path reads the dynamic visual contracts (``visual_direction_plan``,
    ``carousel_design_plan``, ``render_manifest``) and the publish package. It
    does NOT read ``visual_plan`` or ``storyboards``. Only invoked after Human
    Review approval and R2 compliance (the gates enforced below).
    """
    _require_review_approval(state)

    publish_package = state.get("publish_package", {})
    trends = state.get("trends")
    if not trends:
        raise ValueError(
            "content_writer_node requires state.trends before persistence."
        )

    topic_id = _require_value(publish_package, "topic_id")
    topic_metadata = get_topic_metadata(trends, topic_id)

    domain_context = state.get("domain_context", {})
    compliance_status = _require_r2_compliance_status(state)
    profile_version = _require_value(domain_context, "profile_version")
    content_contract = _require_content_contract(publish_package)
    rendered_image_paths = _final_rendered_paths(state)
    visual_metadata = _derive_dynamic_visual_metadata(state)

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
        # Legacy columns stay readable for old analytics; the v3 path writes no
        # storyboard payload and derives card_count from the rendered pages.
        card_count=visual_metadata["page_count"],
        storyboards=[],
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
        template_family=visual_metadata["template_family"],
        page_count=visual_metadata["page_count"],
        direction_signature=visual_metadata["direction_signature"],
        design_signature=visual_metadata["design_signature"],
        density_summary=visual_metadata["density_summary"],
        color_summary=visual_metadata["color_summary"],
    )

    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    try:
        database.save_generated_content(record)
    except Exception as e:
        raise Exception(
            f"Error occurred while saving generated content to structured database sqlite: {e}"
        )

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

    if database.get_content_by_id(record.content_id) and database.get_embedding_content_by_id(
        record.content_id
    ):
        print(
            f"Content with ID {record.content_id}, with title {record.title} "
            "successfully saved to the structured and embedding database."
        )
        return {"data_writed": True}

    return {"data_writed": False}
