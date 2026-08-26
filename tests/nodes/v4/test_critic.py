from __future__ import annotations

import pytest
from types import SimpleNamespace

from src.schemas.v4.critique import (
    AestheticIssueDraftV4,
    AestheticPageDraftV4,
    AestheticPagePassV4,
    AestheticSetDraftV4,
    AestheticSetPassV4,
)


def test_v4_critic_public_names_are_available():
    from src.nodes.v4.critic import aesthetic_critic_node, route_after_aesthetic_critic

    assert callable(aesthetic_critic_node)
    assert callable(route_after_aesthetic_critic)


def test_v4_critic_rejects_missing_q3_before_gateway():
    from src.nodes.v4.critic import aesthetic_critic_node

    class Gateway:
        calls = 0

        def evaluate_images(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("must not be called")

    gateway = Gateway()
    with pytest.raises(ValueError, match="Q3|render|canonical"):
        aesthetic_critic_node({}, gateway=gateway)
    assert gateway.calls == 0


def test_v4_critic_runs_q3_before_two_blind_evaluator_passes(tmp_path):
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.nodes.v4.critic import aesthetic_critic_node
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    q3 = evaluate_v4_render(**values)

    class Gateway:
        provider_config = SimpleNamespace(model="critic-model")

        def __init__(self):
            self.calls = []

        def evaluate_images(self, request, response_model, *args):
            self.calls.append(request)
            if response_model is AestheticPagePassV4:
                return AestheticPagePassV4(pages=tuple(
                    AestheticPageDraftV4(
                        page_id=page_id, hierarchy=90, readability=90, composition=90,
                        whitespace=90, visual_focus=90, asset_integration=90,
                    ) for page_id in request.page_ids
                ))
            return AestheticSetPassV4(set_evaluation=AestheticSetDraftV4(
                rhythm=90, repetition=90, family_consistency=90, cover_body_consistency=90,
            ))

    gateway = Gateway()
    result = aesthetic_critic_node({
        **values, "carousel_design_plan": values["design_plan"], "render_qa_result": q3,
        "run_id": values["render_manifest"].run_id, "run_mode": "shadow",
        "candidate_id": values["render_manifest"].candidate_id,
        "revision_id": values["render_manifest"].revision_id,
        "authoring_model_identity": "author-model",
    }, gateway=gateway)

    assert result["route"] == "human_review"
    assert [request.payload["pass_kind"] for request in gateway.calls] == ["page", "set"]
    assert result["visual_critique"].critic_independence == "degraded"


def test_v4_critic_failed_page_routes_exact_normalized_aesthetic_failure(tmp_path):
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.nodes.v4.critic import aesthetic_critic_node
    from src.schemas.v4.revision import NormalizedFailureV4
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    q3 = evaluate_v4_render(**values)

    class Gateway:
        provider_config = SimpleNamespace(model="critic-model")

        def evaluate_images(self, request, response_model, *args):
            if response_model is AestheticPagePassV4:
                return AestheticPagePassV4(pages=tuple(
                    AestheticPageDraftV4(
                        page_id=page_id, hierarchy=90, readability=90, composition=90,
                        whitespace=90, visual_focus=90, asset_integration=90,
                        issues=(AestheticIssueDraftV4(
                            severity="critical", dimension="composition", page_ids=(page_id,),
                            evidence="focal product is obscured by an overlapping text block",
                        ),) if page_id == "page-3" else (),
                    ) for page_id in request.page_ids
                ))
            return AestheticSetPassV4(set_evaluation=AestheticSetDraftV4(
                rhythm=90, repetition=90, family_consistency=90, cover_body_consistency=90,
            ))

    result = aesthetic_critic_node({
        **values, "carousel_design_plan": values["design_plan"], "render_qa_result": q3,
        "run_id": q3.artifact_identity.run_id, "run_mode": "shadow",
        "candidate_id": q3.artifact_identity.candidate_id, "revision_id": q3.artifact_identity.revision_id,
    }, gateway=Gateway())

    assert result["route"] == "revision"
    assert len(result["normalized_failures_v4"]) == 1
    failure = result["normalized_failures_v4"][0]
    assert type(failure) is NormalizedFailureV4
    assert failure.fingerprint.node == "V4_VISUAL_CRITIC"
    assert failure.failure_code == "AESTHETIC_REVIEW_FAILED"
    assert failure.page_id == "page-3"


def test_public_critic_failure_composes_into_revision_with_fresh_hard_gates(tmp_path):
    """Only real critic output may carry a passed Q0--Q3 state into repair."""
    from tests.nodes.v4.test_design_qa import _fixture
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.nodes.v4.critic import aesthetic_critic_node
    from src.nodes.v4.design_qa import aggregate_design_qa
    from src.nodes.v4.revision import revision_node
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    fixture = _fixture()
    q2 = aggregate_design_qa(
        semantic_qa=fixture["q0"], authoring_qa=fixture["q1"],
        carousel_design_plan=values["design_plan"], content_atom_set=values["content_atom_set"],
        content_lock=values["content_lock"], semantic_content_model=values["semantic_content_model"],
        page_brief_set=values["page_brief_set"], visual_direction_plan=values["visual_direction_plan"],
        asset_manifest=values["asset_manifest"],
    )
    q3 = evaluate_v4_render(**values)
    assert q2.passed and q3.passed

    class Gateway:
        provider_config = SimpleNamespace(model="critic-model")

        def evaluate_images(self, request, response_model, *args):
            if response_model is AestheticPagePassV4:
                return AestheticPagePassV4(pages=tuple(
                    AestheticPageDraftV4(
                        page_id=page_id, hierarchy=90, readability=90, composition=90,
                        whitespace=90, visual_focus=90, asset_integration=90,
                    ) for page_id in request.page_ids
                ))
            return AestheticSetPassV4(set_evaluation=AestheticSetDraftV4(
                rhythm=60, repetition=90, family_consistency=90, cover_body_consistency=90,
                issues=(AestheticIssueDraftV4(
                    severity="major", dimension="rhythm", page_ids=("page-1",),
                    evidence="all pages repeat the same centered text stack without pacing",
                ),),
            ))

    state = {
        **values, "carousel_design_plan": values["design_plan"],
        "run_id": q3.artifact_identity.run_id, "run_mode": "shadow",
        "candidate_id": q3.artifact_identity.candidate_id,
        "revision_id": q3.artifact_identity.revision_id,
        "semantic_qa_result": fixture["q0"], "authoring_qa_result": fixture["q1"],
        "design_plan_qa_result_v4": q2, "render_qa_result_v4": q3,
        "revision_history_v4": (),
    }
    critic_result = aesthetic_critic_node(state, gateway=Gateway())
    assert critic_result["route"] == "revision"

    revision_result = revision_node({**state, **critic_result})

    assert revision_result["revision_request_v4"].target_layer == "AESTHETIC"
    assert revision_result["revision_request_v4"].affected_pages == values["render_manifest"].page_ids
    assert len(critic_result["normalized_failures_v4"]) == len(values["render_manifest"].page_ids)
    assert critic_result["visual_critique"].set_evaluation.issues[0].page_ids == ("page-1",)


@pytest.mark.parametrize("attack", ("changed_bytes", "symlink"))
def test_v4_critic_rejects_hash_and_symlink_png_attacks_before_gateway(tmp_path, attack):
    from tests.visual_design.v4.test_v4_render_qa import _world
    from src.nodes.v4.critic import aesthetic_critic_node
    from src.visual_design.v4.render_qa import evaluate_v4_render

    values = _world(tmp_path)
    q3 = evaluate_v4_render(**values)
    page_path = values["artifact_paths"].revision_root / values["render_manifest"].pages[0].path
    if attack == "changed_bytes":
        page_path.write_bytes(b"not-the-hashed-png")
    else:
        outside = tmp_path / "outside.png"
        outside.write_bytes(page_path.read_bytes())
        page_path.unlink()
        page_path.symlink_to(outside)

    class Gateway:
        provider_config = SimpleNamespace(model="critic-model")
        calls = 0

        def evaluate_images(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError("must not reach evaluator")

    gateway = Gateway()
    with pytest.raises(ValueError, match="Q3|forged|revalidate"):
        aesthetic_critic_node({
            **values, "carousel_design_plan": values["design_plan"], "render_qa_result": q3,
            "run_id": q3.artifact_identity.run_id, "run_mode": "shadow",
            "candidate_id": q3.artifact_identity.candidate_id, "revision_id": q3.artifact_identity.revision_id,
        }, gateway=gateway)
    assert gateway.calls == 0
