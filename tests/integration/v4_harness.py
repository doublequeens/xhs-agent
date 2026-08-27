"""In-process v4 workflow harness for integration tests.

The harness replays one prebuilt Task 16A world (``tests.v4_review_state``
machinery) through the REAL v4 graph: every conditional edge, the typed
revision node, the review workspace builder, the Human Review interrupt and
the Final Guard run for real.  Only the LLM-backed producers (the shared
content chain, semantic/authoring models, the critic's Q4 call) and the
IO-heavy renderer/asset stages are stubbed with exact world contracts, so the
tests exercise routing and boundary semantics rather than providers.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import src.graph_v4 as graph_v4_module
import src.nodes as nodes
from src.nodes.v4 import semantic as v4semantic
from src.nodes.v4 import authoring as v4authoring
from src.nodes.v4 import composition as v4composition
from src.nodes.v4 import critic as v4critic
from src.nodes.v4 import content as v4content
from src.nodes.v4 import assets as v4assets
from src.nodes.v4 import render as v4render


class HarnessStopped(Exception):
    """Raised by stubs to halt the graph at a controlled point."""


class V4Harness:
    """Build one v4 graph around a real prebuilt review world."""

    def __init__(self, monkeypatch, tmp_path: Path, *, thread_id: str = "thread-1"):
        from tests.review.test_v4_workspace import _inputs

        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path
        self.thread_id = thread_id
        self.inputs = _inputs(tmp_path / "world", run_id=thread_id)
        identity = self.inputs.artifact_paths.identity
        self.candidate_id = identity.candidate_id
        self.revision_id = identity.revision_id
        self.shadow_root = tmp_path / "outputs" / "shadow"
        self.publish_root_sentinel = tmp_path / "outputs" / "publish"
        self.content_writer_calls: list[dict] = []
        self.critic_calls = 0
        self._stop_after_failures: int | None = None

        from src.nodes.v4 import shadow_writer as v4shadow

        monkeypatch.setattr(v4shadow, "SHADOW_ROOT", self.shadow_root)

    # -- stubs -----------------------------------------------------------

    def _install_stubs(self, *, critic_passes: bool) -> None:
        monkeypatch = self.monkeypatch
        inputs = self.inputs

        def passthrough(_state, **_kwargs):
            return {}

        for node_name in (
            "domain_router_node", "domain_confirmation_node", "retrieve_memory_node",
            "topic_signal_collector_node", "creative_brief_builder_node",
            "topic_ideator_node", "topic_diversity_filter_node",
            "angle_strategist_node", "novelty_guard_node", "virality_scorer_node",
            "evidence_brief_node", "outline_architect_node", "draft_writer_node",
            "title_lab_node", "title_ranker_node", "hashtag_node",
            "assembler_node", "r1_reflector_node",
        ):
            monkeypatch.setattr(nodes, node_name, passthrough)

        def r2_compliance_halt(_state, **_kwargs):
            # The shared R2 node is out of harness scope; stopping here keeps
            # the visible-copy re-entry deterministic.
            raise HarnessStopped("r2_compliance reached")

        monkeypatch.setattr(nodes, "r2_compliance_node", r2_compliance_halt)

        from src.schemas.decision import DecisionOutput, NormalizedInput

        def decision_route(_state):
            return {
                "decision_output": DecisionOutput(
                    next_node="HASHTAG_SEO", normalized_input=NormalizedInput()
                )
            }

        monkeypatch.setattr(nodes, "decision_engine_node", decision_route)

        def atomizer(_state):
            return {
                "visible_copy_projection": None,
                "content_atom_set": inputs.content_atom_set,
                "content_atomization_route": "content_lock_builder",
                "content_atomization_issues": [],
            }

        def lock_builder(_state):
            return {"content_lock": inputs.content_lock}

        monkeypatch.setattr(v4content, "content_atomizer_node", atomizer)
        monkeypatch.setattr(v4content, "content_lock_builder_node", lock_builder)

        from src.visual_design.v4.semantic_qa import evaluate_semantic_model

        def semantic(_state, **_kwargs):
            model = inputs.semantic_content_model
            q0 = evaluate_semantic_model(
                inputs.content_atom_set, model, content_lock=inputs.content_lock
            )
            return {
                "semantic_content_model": model,
                "semantic_model": model,
                "semantic_qa_result": q0,
                "semantic_qa": q0,
                "semantic_route": "visual_authoring" if q0.passed else "semantic_modeling",
            }

        monkeypatch.setattr(v4semantic, "semantic_modeling_node", semantic)

        from src.visual_design.v4.authoring_qa import evaluate_authoring

        def authoring(_state, **_kwargs):
            q1 = evaluate_authoring(
                inputs.page_brief_set,
                inputs.semantic_content_model,
                inputs.visual_direction_plan.narrative,
                inputs.visual_direction_plan,
                content_lock=inputs.content_lock,
                content_atom_set=inputs.content_atom_set,
            )
            return {
                "narrative": inputs.carousel_narrative,
                "carousel_narrative": inputs.carousel_narrative,
                "page_brief_set": inputs.page_brief_set,
                "page_briefs": inputs.page_brief_set,
                "visual_direction_plan": inputs.visual_direction_plan,
                "authoring_qa_result": q1,
                "authoring_qa": q1,
                "authoring_route": "asset_resolver" if q1.passed else "visual_authoring",
                "route": "asset_resolver" if q1.passed else "visual_authoring",
                "visual_route": "asset_resolver" if q1.passed else "visual_authoring",
            }

        monkeypatch.setattr(v4authoring, "visual_authoring_node", authoring)

        from src.nodes.v4.composition import build_layout_program
        from src.visual_design.v4.tokens import get_family_tokens

        def composition(_state):
            # Replay the world's deterministic per-page program choice so the
            # REAL layout compiler reproduces the world's exact design plan
            # (and the replayed render manifest stays hash-consistent).
            programs = tuple(
                build_layout_program(
                    page,
                    "editorial_hero",
                    family=inputs.visual_direction_plan.template_family,
                    narrative=inputs.carousel_narrative,
                )
                for page in inputs.page_brief_set.pages
            )
            return {
                "layout_programs": programs,
                "family_tokens": get_family_tokens(
                    inputs.visual_direction_plan.template_family
                ),
                "route": "layout_compiler",
                "visual_route": "layout_compiler",
            }

        monkeypatch.setattr(v4composition, "composition_planning_node", composition)

        def asset_resolver(_state):
            return {
                "asset_manifest": inputs.asset_manifest,
                "asset_resolution_result": inputs.asset_resolution_result,
                "unresolved_optional_assets": (),
                "asset_transaction_evidence": None,
                "artifact_paths": inputs.artifact_paths,
                "asset_transaction_paths": inputs.artifact_paths,
                "asset_resolver_route": "composition_planning",
                "route": "composition_planning",
                "visual_route": "composition_planning",
            }

        monkeypatch.setattr(v4assets, "asset_resolver_node", asset_resolver)

        def renderer(_state):
            return {
                "render_manifest_v4": inputs.render_manifest,
                "render_manifest": inputs.render_manifest,
                "artifact_paths": inputs.artifact_paths,
                "route": "render_qa",
                "visual_route": "render_qa",
                "render_route": "render_qa",
            }

        monkeypatch.setattr(v4render, "render_node", renderer)

        from src.schemas.v4.critique import (
            AestheticIssueV4,
            CarouselAestheticEvaluationV4,
            SetAestheticEvaluationV4,
        )
        from src.schemas.v4.revision import (
            FailureFingerprintV4,
            NormalizedFailureV4,
        )

        def critic(_state, **_kwargs):
            self.critic_calls += 1
            if self._stop_after_failures is not None:
                if self.critic_calls > self._stop_after_failures:
                    raise HarnessStopped(
                        f"halted before evaluation #{self.critic_calls}"
                    )

            def canon(value, model):
                if isinstance(value, Mapping):
                    return model.model_validate(dict(value))
                return value

            from src.schemas.v4.rendering import RenderManifestV4
            from src.schemas.v4.direction import PageBriefSetV4

            render = canon(
                _state.get("render_manifest_v4", _state.get("render_manifest")),
                RenderManifestV4,
            )
            q3 = _state.get("render_qa_result_v4", _state.get("render_qa_result"))
            q3_sha = (
                q3.canonical_sha256
                if hasattr(q3, "canonical_sha256")
                else q3["canonical_sha256"]
            )
            page_set = canon(
                _state.get("page_brief_set", _state.get("page_briefs")),
                PageBriefSetV4,
            )
            semantic_model = _state.get(
                "semantic_content_model", _state.get("semantic_model")
            )
            semantic_sha = (
                semantic_model.canonical_sha256
                if hasattr(semantic_model, "canonical_sha256")
                else semantic_model["canonical_sha256"]
            )
            if critic_passes:
                critique = self.inputs.visual_critique
                failures: tuple = ()
                route = "human_review"
            else:
                render_sha = (
                    render.canonical_sha256
                    if hasattr(render, "canonical_sha256")
                    else render["canonical_sha256"]
                )
                page_set_sha = (
                    page_set.canonical_sha256
                    if hasattr(page_set, "canonical_sha256")
                    else page_set["canonical_sha256"]
                )
                issue = AestheticIssueV4.create(
                    severity="major",
                    dimension="rhythm",
                    page_ids=(self.inputs.render_manifest.pages[0].page_id,),
                    evidence="页面之间的节奏重复，缺少有效变化",
                )
                failed_set = SetAestheticEvaluationV4.create(
                    rhythm=60,
                    repetition=90,
                    family_consistency=90,
                    cover_body_consistency=90,
                    issues=(issue,),
                )
                critique = CarouselAestheticEvaluationV4.create(
                    render_manifest_sha256=render_sha,
                    render_qa_result_sha256=q3_sha,
                    page_brief_set_sha256=page_set_sha,
                    semantic_content_model_sha256=semantic_sha,
                    authoring_model_identity="authoring",
                    evaluator_model_identity="evaluator",
                    pages=self.inputs.visual_critique.pages,
                    set_evaluation=failed_set,
                )
                failures = tuple(
                    NormalizedFailureV4.from_fingerprint(
                        FailureFingerprintV4.create(
                            node="V4_VISUAL_CRITIC",
                            page_id=page.page_id,
                            failure_code="AESTHETIC_REVIEW_FAILED",
                            geometry_region=None,
                        )
                    )
                    for page in critique.pages
                )
                route = "revision"
            return {
                "visual_critique_v4": critique,
                "visual_critique": critique,
                "normalized_failures_v4": failures,
                "route": route,
                "visual_route": route,
                "critic_route": route,
            }

        monkeypatch.setattr(v4critic, "aesthetic_critic_node", critic)

        def content_writer_sentinel(state):
            self.content_writer_calls.append(dict(state))
            return {"current_node": "CONTENT_WRITER", "data_writed": True}

        monkeypatch.setattr(nodes, "content_writer_node", content_writer_sentinel)

    # -- driving ---------------------------------------------------------

    def initial_state(self, run_mode: str) -> dict[str, Any]:
        return {
            "run_id": self.thread_id,
            "run_mode": run_mode,
            "candidate_id": self.candidate_id,
            "revision_id": self.revision_id,
            "revision": 1,
            "trends_num": 1,
            "interactive": False,
            "focus_keyword": "护肤",
            "publish_package": self.inputs.content_lock.model_dump(mode="python"),
        }

    def build(self) -> Any:
        return graph_v4_module.create_graph_v4(checkpointer=InMemorySaver())

    def config(self) -> dict:
        return {
            "configurable": {"thread_id": self.thread_id},
            "recursion_limit": 120,
        }

    def run(
        self,
        *,
        run_mode: str = "shadow",
        critic_passes: bool = True,
        intent: dict | None = None,
        resume_command: Command | None = None,
        stop_after_failures: int | None = None,
    ) -> dict[str, Any]:
        """Drive the graph to its terminal state or controlled halt."""

        self._stop_after_failures = stop_after_failures
        self._install_stubs(critic_passes=critic_passes)
        graph = self.build()
        config = self.config()
        if resume_command is None:
            graph.invoke(self.initial_state(run_mode), config)
        else:
            graph.invoke(resume_command, config)
        state = graph.get_state(config)
        values = dict(state.values)
        values["__next__"] = state.next
        return values

    def run_until_review_interrupt(
        self, *, run_mode: str = "shadow", critic_passes: bool = True
    ) -> tuple[Any, dict]:
        """Run until the real Human Review interrupt."""

        self._stop_after_failures = None
        self._install_stubs(critic_passes=critic_passes)
        graph = self.build()
        config = self.config()
        graph.invoke(self.initial_state(run_mode), config)
        return graph, config


def resume_with_intent(graph, config, intent: dict) -> dict[str, Any]:
    graph.invoke(Command(resume={"intent": intent}), config)
    state = graph.get_state(config)
    values = dict(state.values)
    values["__next__"] = state.next
    return values


__all__ = ["HarnessStopped", "V4Harness", "resume_with_intent"]
