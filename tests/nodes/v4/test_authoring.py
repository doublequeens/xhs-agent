from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.nodes.v4.authoring import route_after_authoring_qa, visual_authoring_node
from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.direction import (
    AssetDirectiveDraftV4,
    CarouselNarrativeDraftV4,
    NarrativeBeatV4,
    PageBriefDraftV4,
    PageBriefSetDraftV4,
    VisualAuthoringDraftV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4, SemanticFragmentV4
from src.visual_design.v4.semantic_qa import evaluate_semantic_model


@dataclass
class GatewayThatMustNotBeCalled:
    calls: int = 0

    def invoke_structured(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("stale Q0 must fail before gateway invocation")


def _atom_set() -> ContentAtomSetV4:
    atoms = []
    for index in range(5):
        text = f"page fragment {index}"
        payload = {
            "atom_id": f"atom-{index}",
            "source_unit_id": f"unit-{index}",
            "source_projection_sha256": "1" * 64,
            "source_field": "content",
            "raw_start": 0,
            "raw_end": len(text),
            "raw_slice_sha256": canonical_sha256_v4({"text": text}),
            "text": text,
            "role": "paragraph",
        }
        atoms.append(ContentAtomV4(**payload, sha256=canonical_sha256_v4(payload)))
    payload = {"projection_sha256": "1" * 64, "atoms": tuple(atoms)}
    return ContentAtomSetV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _lock(atom_set: ContentAtomSetV4) -> ContentLock:
    payload = {
        "focus_keyword": "护肤",
        "topic": "护肤步骤",
        "topic_id": "topic-1",
        "angle": "按步骤判断",
        "angle_id": "angle-1",
        "target_group": "护肤人群",
        "core_pain": "不知道怎么做",
        "title": "护肤步骤",
        "cover_copy": "看完就会",
        "first_screen_promise": "照着做",
        "content": "\n".join(atom.text for atom in atom_set.atoms),
        "hashtags": ("#护肤",),
        "content_atom_set_sha256": atom_set.canonical_sha256,
    }
    return ContentLock(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _semantic(atom_set: ContentAtomSetV4) -> SemanticContentModelV4:
    fragments = tuple(
        SemanticFragmentV4(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            exact_text=atom.text,
            semantic_role="paragraph",
            sequence_index=index,
        )
        for index, atom in enumerate(atom_set.atoms)
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "fragments": fragments,
        "groups": (),
    }
    return SemanticContentModelV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def _draft() -> VisualAuthoringDraftV4:
    narrative = CarouselNarrativeDraftV4(
        template_family="pink_red",
        page_count=5,
        beats=tuple(
            NarrativeBeatV4(
                beat_id=f"beat-{index}",
                sequence=index + 1,
                task=f"task-{index}",
            )
            for index in range(5)
        ),
        density_curve=("low", "medium", "low", "medium", "low"),
        variation_strategy="alternate compositions",
        continuity_strategy="carry one cue",
        art_direction="clean editorial",
    )
    pages = tuple(
        PageBriefDraftV4(
            page_id=f"page-{index + 1}",
            sequence=index + 1,
            narrative_role=f"role-{index + 1}",
            beat_ref=f"beat-{index}",
            fragment_refs=(f"fragment-{index}",),
            visual_priority=(f"fragment-{index}",),
            density_budget=("low", "medium", "low", "medium", "low")[index],
            preferred_compositions=(
                "editorial_hero" if index % 2 == 0 else "comparison_grid",
            ),
            forbidden_patterns=(),
            asset_directives=(),
            continuity_with_previous="none" if index == 0 else "carry cue",
        )
        for index in range(5)
    )
    return VisualAuthoringDraftV4(
        narrative=narrative,
        page_brief_set=PageBriefSetDraftV4(pages=pages),
    )


@dataclass
class RecordingGateway:
    draft: Any
    calls: list[Any]

    def invoke_structured(self, request, response_model, *args):
        self.calls.append((request, response_model, args))
        return self.draft


@dataclass
class FailingGateway:
    calls: int = 0

    def invoke_structured(self, *args):
        self.calls += 1
        raise RuntimeError("gateway failed")


def _state() -> dict[str, Any]:
    atom_set = _atom_set()
    lock = _lock(atom_set)
    model = _semantic(atom_set)
    q0 = evaluate_semantic_model(atom_set, model, content_lock=lock)
    assert q0.passed
    return {
        "run_id": "run-1",
        "run_mode": "shadow",
        "candidate_id": "candidate-1",
        "revision_id": "revision-1",
        "parent_revision_id": "revision-0",
        "content_atom_set": atom_set,
        "content_lock": lock,
        "semantic_content_model": model,
        "semantic_qa_result": q0,
    }


def test_authoring_node_does_not_call_gateway_for_stale_q0():
    gateway = GatewayThatMustNotBeCalled()
    with pytest.raises(ValueError, match="run_id|fresh|semantic|atom"):
        visual_authoring_node({}, gateway=gateway)
    assert gateway.calls == 0


def test_authoring_node_calls_injected_gateway_once_with_stable_identity_and_routes():
    state = _state()
    gateway = RecordingGateway(_draft(), [])

    result = visual_authoring_node(state, gateway=gateway)

    assert len(gateway.calls) == 1
    request, response_model, _ = gateway.calls[0]
    assert response_model is VisualAuthoringDraftV4
    assert request.node == "visual_authoring"
    assert request.operation_kind == "visual_authoring"
    assert request.page_ids == ("carousel",)
    assert request.payload["constraints"]["allow_coordinates"] is False
    assert result["current_node"] == "V4_VISUAL_AUTHORING"
    assert result["authoring_route"] == "asset_resolver"
    assert result["authoring_qa_result"].passed is True
    plan = result["visual_direction_plan"]
    assert plan.semantic_content_model is result["semantic_content_model"]
    assert plan.narrative is result["narrative"]
    assert plan.page_brief_set is result["page_brief_set"]


def test_authoring_node_rejects_stale_passed_q0_before_gateway():
    state = _state()
    changed = _atom_set().model_copy(
        update={"atoms": tuple(atom.model_copy(update={"text": "changed"}) for atom in _atom_set().atoms)}
    )
    # The stale result remains from the original atom/model revision.
    state["content_atom_set"] = changed
    gateway = RecordingGateway(_draft(), [])

    with pytest.raises(ValueError, match="fresh|semantic|atom"):
        visual_authoring_node(state, gateway=gateway)
    assert gateway.calls == []


def test_authoring_route_recomputes_q1_and_rejects_stale_result():
    state = _state()
    gateway = RecordingGateway(_draft(), [])
    result = visual_authoring_node(state, gateway=gateway)
    complete = {**state, **result}
    assert route_after_authoring_qa(complete) == "asset_resolver"

    stale_plan = result["visual_direction_plan"].model_copy(
        update={"page_count": 6}
    )
    assert route_after_authoring_qa(
        {**complete, "visual_direction_plan": stale_plan}
    ) == "visual_authoring"


def test_authoring_node_keeps_unknown_provider_fragment_in_q1_fail_route():
    draft = _draft()
    pages = list(draft.page_brief_set.pages)
    first = pages[0].model_dump(mode="python")
    first["fragment_refs"] = ("provider-invented-fragment",)
    pages[0] = type(pages[0])(**first)
    invalid = type(draft)(
        narrative=draft.narrative,
        page_brief_set=type(draft.page_brief_set)(pages=tuple(pages)),
    )
    gateway = RecordingGateway(invalid, [])

    result = visual_authoring_node(_state(), gateway=gateway)

    assert result["authoring_route"] == "visual_authoring"
    assert "FRAGMENT_OWNERSHIP_UNKNOWN" in {
        issue.code for issue in result["authoring_qa_result"].issues
    }


def test_authoring_node_returns_failed_candidate_for_empty_pages_without_throwing():
    draft = _draft()
    pages = list(draft.page_brief_set.pages)
    for index in range(1, 5):
        raw = pages[index].model_dump(mode="python")
        raw["fragment_refs"] = ()
        raw["visual_priority"] = ()
        raw["preferred_compositions"] = ()
        pages[index] = PageBriefDraftV4(**raw)
    invalid = VisualAuthoringDraftV4(
        narrative=draft.narrative,
        page_brief_set=PageBriefSetDraftV4(pages=tuple(pages)),
    )
    result = visual_authoring_node(
        _state(),
        gateway=RecordingGateway(invalid, []),
    )
    assert result["authoring_route"] == "visual_authoring"
    assert result["page_brief_set"] is None
    assert result["visual_direction_plan"] is None
    assert "PAGE_BRIEF_DUTY_EMPTY" in {
        issue.code for issue in result["authoring_qa_result"].issues
    }


def test_authoring_node_injects_controlled_asset_resolution_after_q1():
    draft = _draft()
    pages = list(draft.page_brief_set.pages)
    raw = pages[0].model_dump(mode="python")
    raw["asset_directives"] = (
        AssetDirectiveDraftV4(
            directive_id="asset-1",
            page_id="page-1",
            role="evidence_example",
            purpose="evidence",
            supports_fragment_refs=("fragment-0",),
            required=True,
            preferred_source="search",
            query_or_prompt="clean skincare evidence photo",
            orientation="portrait",
        ),
    )
    pages[0] = PageBriefDraftV4(**raw)
    draft_with_asset = VisualAuthoringDraftV4(
        narrative=draft.narrative,
        page_brief_set=PageBriefSetDraftV4(pages=tuple(pages)),
    )
    result = visual_authoring_node(
        _state(),
        gateway=RecordingGateway(draft_with_asset, []),
    )
    assert result["authoring_qa_result"].passed is True
    directive = result["page_brief_set"].pages[0].asset_directives[0]
    assert directive.preferred_resolution == (1080, 1440)


def test_authoring_node_propagates_gateway_failure_without_retry_or_fallback():
    gateway = FailingGateway()

    with pytest.raises(RuntimeError, match="gateway failed"):
        visual_authoring_node(_state(), gateway=gateway)
    assert gateway.calls == 1
