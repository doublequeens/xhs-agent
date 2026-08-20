from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.schemas.content_lock import ContentLock
from src.schemas.v4.content import ContentAtomSetV4, ContentAtomV4, canonical_sha256_v4
from src.schemas.v4.semantic import SemanticModelingDraftV4
from src.nodes.v4.semantic import (
    route_after_semantic_qa,
    semantic_modeling_node,
)


def atom_set(text: str = "午后补涂防晒") -> ContentAtomSetV4:
    projection_sha = "1" * 64
    atom_payload = {
        "atom_id": "atom-0",
        "source_unit_id": "unit-0",
        "source_projection_sha256": projection_sha,
        "source_field": "content",
        "raw_start": 0,
        "raw_end": len(text),
        "raw_slice_sha256": canonical_sha256_v4({"text": text}),
        "text": text,
        "role": "step",
    }
    atom = ContentAtomV4(**atom_payload, sha256=canonical_sha256_v4(atom_payload))
    payload = {"projection_sha256": projection_sha, "atoms": (atom,)}
    return ContentAtomSetV4(**payload, canonical_sha256=canonical_sha256_v4(payload))


def lock_for(atom_set_value: ContentAtomSetV4) -> ContentLock:
    payload = {
        "focus_keyword": "防晒",
        "topic": "补涂",
        "topic_id": "topic-1",
        "angle": "看时机",
        "angle_id": "angle-1",
        "target_group": "护肤人群",
        "core_pain": "不会判断",
        "title": "怎么补涂",
        "cover_copy": "午后补涂",
        "first_screen_promise": "看完就会",
        "content": atom_set_value.atoms[0].text,
        "hashtags": ("#防晒",),
        "content_atom_set_sha256": atom_set_value.canonical_sha256,
    }
    return ContentLock(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def state_for(atom_set_value: ContentAtomSetV4 | None = None) -> dict[str, Any]:
    atom_set_value = atom_set_value or atom_set()
    return {
        "run_id": "run-1",
        "run_mode": "shadow",
        "candidate_id": "candidate-1",
        "revision_id": "revision-1",
        "parent_revision_id": "revision-0",
        "content_atom_set": atom_set_value,
        "content_lock": lock_for(atom_set_value),
    }


def draft_for(atom_set_value: ContentAtomSetV4 | None = None) -> SemanticModelingDraftV4:
    atom_set_value = atom_set_value or atom_set()
    text = atom_set_value.atoms[0].text
    return SemanticModelingDraftV4(
        fragments=(
            {
                "fragment_id": "fragment-0",
                "source_atom_id": "atom-0",
                "start": 0,
                "end": 2,
                "semantic_role": "step",
                "parent_fragment_id": None,
                "sequence_index": 0,
            },
            {
                "fragment_id": "fragment-1",
                "source_atom_id": "atom-0",
                "start": 2,
                "end": len(text),
                "semantic_role": "step",
                "parent_fragment_id": "fragment-0",
                "sequence_index": 1,
            },
        ),
        groups=(
            {
                "group_id": "group-0",
                "group_kind": "steps",
                "fragment_ids": ("fragment-0", "fragment-1"),
                "ordering": 0,
            },
        ),
    )


@dataclass
class FakeGateway:
    response: Any
    calls: list[tuple[Any, Any, Any]]

    def invoke_structured(self, request: Any, response_model: Any, policy: Any = None) -> Any:
        self.calls.append((request, response_model, policy))
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def test_semantic_node_rebuilds_visible_text_locally_from_persisted_atoms():
    atoms = atom_set()
    gateway = FakeGateway(draft_for(atoms), [])

    result = semantic_modeling_node(state_for(atoms), gateway=gateway)

    model = result["semantic_content_model"]
    assert [fragment.exact_text for fragment in model.fragments] == [
        atoms.atoms[0].text[:2],
        atoms.atoms[0].text[2:],
    ]
    draft_schema = gateway.calls[0][1].model_json_schema()
    assert "exact_text" not in str(draft_schema)
    assert result["semantic_qa_result"].passed is True
    assert result["current_node"] == "V4_SEMANTIC_MODELING"
    assert result["semantic_route"] == "visual_authoring"


def test_semantic_node_revalidates_tampered_persisted_atom_before_gateway():
    atoms = atom_set()
    tampered_atom = atoms.atoms[0].model_copy(update={"text": "篡改可见文案"})
    tampered_atoms = atoms.model_copy(update={"atoms": (tampered_atom,)})
    gateway = FakeGateway(draft_for(atoms), [])

    with pytest.raises(ValueError, match="content_atom_set"):
        semantic_modeling_node(state_for(tampered_atoms), gateway=gateway)

    assert gateway.calls == []


def test_semantic_node_revalidates_tampered_content_lock_before_gateway():
    gateway = FakeGateway(draft_for(), [])
    state = state_for()
    state["content_lock"] = state["content_lock"].model_copy(update={"title": "篡改"})

    with pytest.raises(ValueError, match="content_lock"):
        semantic_modeling_node(state, gateway=gateway)

    assert gateway.calls == []


def test_semantic_node_revalidates_tampered_gateway_draft_instance():
    draft = draft_for()
    tampered = draft.model_copy(update={"fragments": ({"bad": "draft"},)})
    gateway = FakeGateway(tampered, [])

    with pytest.raises(ValueError, match="draft"):
        semantic_modeling_node(state_for(), gateway=gateway)


def test_semantic_node_request_has_fail_closed_identity_and_content_sentinel():
    atoms = atom_set()
    gateway = FakeGateway(draft_for(atoms), [])

    semantic_modeling_node(state_for(atoms), gateway=gateway)

    request = gateway.calls[0][0]
    assert request.run_id == "run-1"
    assert request.run_mode == "shadow"
    assert request.candidate_id == "candidate-1"
    assert request.revision_id == "revision-1"
    assert request.parent_revision_id == "revision-0"
    assert request.node == "semantic_modeling"
    assert request.operation_kind == "semantic_modeling"
    assert request.page_ids == ("content",)
    assert "api_key" not in request.payload
    assert "absolute_path" not in request.payload
    assert "do not output visible" in request.payload["prompt"].lower()


def test_semantic_node_does_not_retry_or_swallow_gateway_failure():
    gateway = FakeGateway(RuntimeError("gateway failed"), [])

    with pytest.raises(RuntimeError, match="gateway failed"):
        semantic_modeling_node(state_for(), gateway=gateway)

    assert len(gateway.calls) == 1


def test_semantic_node_requires_identity_before_gateway_invocation():
    gateway = FakeGateway(draft_for(), [])
    state = state_for()
    state.pop("run_id")

    with pytest.raises(ValueError, match="run_id"):
        semantic_modeling_node(state, gateway=gateway)

    assert gateway.calls == []


def test_semantic_route_is_a_hard_gate_for_the_next_authoring_boundary():
    atoms = atom_set()
    gateway = FakeGateway(draft_for(atoms), [])
    result = semantic_modeling_node(state_for(atoms), gateway=gateway)

    assert route_after_semantic_qa({**state_for(atoms), **result}) == "visual_authoring"
    failed = {**result, "semantic_qa_result": {"passed": False}}
    assert route_after_semantic_qa(failed) == "semantic_modeling"


def test_semantic_route_rejects_self_consistent_qa_from_an_old_revision():
    atoms = atom_set()
    gateway = FakeGateway(draft_for(atoms), [])
    result = semantic_modeling_node(state_for(atoms), gateway=gateway)
    changed_atoms = atom_set("更换后的锁定文案")

    stale_state = {
        **result,
        **state_for(changed_atoms),
    }

    assert route_after_semantic_qa(stale_state) == "semantic_modeling"
