import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

import src.graph as graph_module
import src.nodes.node_q_01_final_policy_guard as final_guard_module
from src.editorial_carousel import build_visual_plan
from src.nodes.node_a_00_domain_confirmation import domain_confirmation_node
from src.nodes.node_a_00_domain_router import domain_router_node
from src.nodes.node_c_01_evidence_brief import evidence_brief_node
from src.nodes.node_q_01_final_policy_guard import final_policy_guard_node
from src.nodes.node_q_human_review import human_review_node
from src.schemas import (
    DecisionOutput,
    DecisionTrace,
    HashTagInput,
    HashTagOutput,
    NormalizedInput,
    R2ContentSnapShoot,
    R2Input,
)
from src.schemas.narrative import NarrativeBeat, NarrativePlan
from src.schemas.r2_output import R2ComplianceAudit, R2Output
from src.schemas.decision import RevisionMeta
from src.schemas.topic import TopicItem


def _creative_seed():
    return {
        "signal_type": "evergreen_context",
        "signal_name": "测试默认信号",
        "why_now": "测试中使用稳定 evergreen 信号。",
        "domain_translation": "测试中保持原 domain/subdomain。",
        "evergreen_pain": "测试核心痛点。",
        "timely_framing": "测试时机包装。",
    }


def _domain_narrative_plan() -> NarrativePlan:
    beats = [
        NarrativeBeat(beat_id="hook", kind="hook", purpose="提出日常习惯问题"),
        NarrativeBeat(beat_id="scene", kind="scene", purpose="定位通勤前场景"),
        NarrativeBeat(beat_id="steps", kind="steps", purpose="拆解可执行步骤"),
        NarrativeBeat(beat_id="check", kind="checklist", purpose="整理保存清单"),
        NarrativeBeat(beat_id="boundary", kind="boundary", purpose="说明适用边界"),
        NarrativeBeat(beat_id="close", kind="action", purpose="选择一个动作开始"),
    ]
    return NarrativePlan(
        narrative_form="checklist_collection",
        beats=beats,
        saveable_beat=beats[3],
        closing_mode="action_prompt",
    )


def _structured_storyboards(contract, narrative_plan, publish_package):
    planned_plan = build_visual_plan(
        contract,
        narrative_plan,
        publish_package,
        recent_signatures=[],
    )
    requirements = {item.slot_id: item for item in planned_plan.required_assets}
    frames = []
    for index, planned in enumerate(planned_plan.frame_plan):
        visual_slots = []
        for role in planned.asset_roles:
            slot_id = f"{planned.frame_id}-{role}"
            if slot_id in requirements:
                visual_slots.append(
                    {
                        "slot_id": slot_id,
                        "role": role,
                        "semantic_tags": ["daily-routine"],
                    }
                )
        frames.append(
            {
                "frame_id": planned.frame_id,
                "role": planned.role,
                "page_archetype": planned.page_archetype,
                "content_density_hint": "auto",
                "headline": (
                    contract.first_screen_promise
                    if index == 0
                    else planned.purpose
                ),
                "kicker": "日常清单",
                "content_blocks": [
                    {"block_type": "text", "body": planned.purpose}
                ],
                "emphasis": ["按需调整"],
                "visual_slots": visual_slots,
                "footer": "逐步记录",
            }
        )
    return frames


class _EvidenceProvider:
    def __init__(self, events, *, has_results=True):
        self.events = events
        self.has_results = has_results

    def search(self, query, allowed_domains):
        self.events["evidence_searches"].append(
            {"query": query, "allowed_domains": allowed_domains}
        )
        if not self.has_results:
            return []
        return [
            {
                "title": "Public health guidance",
                "url": "https://www.who.int/example",
                "content": "规律作息有助于保持一般健康状态。",
            }
        ]


def _snapshot(state, *, title=None):
    context = state["domain_context"]
    trend = state["trends"][0]
    return R2ContentSnapShoot(
        draft_id="draft_001",
        revised_title=title or f"{trend.topic}清单",
        revised_md="记录习惯并逐步调整。",
        topic_id=trend.topic_id,
        topic=trend.topic,
        angle_id="ag_001",
        angle="实用清单",
        target_group=trend.target_group,
        core_pain=trend.core_pain,
        best_cover_copy="一页看懂",
        storyboard_visible_text=[],
        narrative_plan=_domain_narrative_plan(),
    )


def _safe_r2_output(snapshot):
    return R2Output(
        content_snapshot=snapshot,
        compliance_audit=R2ComplianceAudit(
            compliance_status="fully_compliant",
            block_publish=False,
        ),
        revision_meta=RevisionMeta(
            revision_id="rev_001",
            round=1,
            diff_summary=["checked"],
            next_actions=["publish"],
        ),
    )


def _install_graph_doubles(
    monkeypatch,
    events,
    *,
    artifact_root: Path,
    evidence_results=True,
    force_r2_block=False,
):
    def memory_node(state):
        events["memory_calls"].append(state["domain_context"].domain)
        return {"memory_context": {}}

    def topic_signal_collector_node(_state):
        return {"topic_signals": [], "topic_generation_degraded_reason": None}

    def creative_brief_builder_node(_state):
        return {"creative_briefs": []}

    def topic_ideator_node(_state):
        return {"topic_candidates": []}

    def topic_diversity_filter_node(state):
        context = state["domain_context"]
        if context.domain == "beauty":
            intent, risk = "experience", "low"
        elif context.domain == "wellness":
            intent, risk = "basic_science", "medium"
        else:
            intent, risk = "checklist", "low"
        return {
            "trends": [
                TopicItem(
                    topic_id="tp_001",
                    topic=state["focus_keyword"],
                    target_group="上班族",
                    core_pain="难以坚持",
                    hook="从一个小习惯开始",
                    content_form="cards",
                    risk_note="",
                    domain=context.domain,
                    subdomain=context.subdomain,
                    content_intent=intent,
                    risk_level=risk,
                    risk_flags=[],
                    content_contract={
                        "audience": "上班族",
                        "trigger_situation": "通勤前",
                        "decision_problem": "如何安排日常习惯",
                        "first_screen_promise": "通勤前快速掌握基础步骤",
                        "screenshot_asset": "步骤清单截图",
                        "proof_asset": "执行前后对比",
                        "visual_mode": "text_card",
                        "content_job": "save_and_check",
                        "primary_visual_family": "saveable_reference",
                        "primary_visual_subject": "checklist",
                        "proof_mode": "diagram",
                        "recommended_frame_count": 6,
                    },
                    creative_seed=_creative_seed(),
                )
            ]
        }

    def evidence_node(state):
        return evidence_brief_node(
            state,
            provider_factory=lambda: _EvidenceProvider(
                events,
                has_results=evidence_results,
            ),
        )

    def passthrough(key, value):
        def node(_state):
            if key == "outlines":
                events["outline_calls"] += 1
            return {key: value}

        return node

    def title_ranker_node(_state):
        return {
            "title_winner": {},
            "current_node": "TITLE_RANKER",
        }

    def r2_decision(snapshot):
        return DecisionOutput(
            next_node="R2_COMPLIANCE",
            normalized_input=NormalizedInput(
                r2_input=R2Input(
                    content_snapshot=snapshot,
                    revision_meta=RevisionMeta(
                        revision_id="rev_001",
                        round=1,
                        diff_summary=[],
                        next_actions=["R2"],
                    ),
                    decision_trace=DecisionTrace(
                        source_node="INTEGRATION_FIXTURE",
                        why_this_route=["compliance"],
                    ),
                )
            ),
        )

    def decision_node(state):
        current_node = state.get("current_node")
        if current_node == "TITLE_RANKER":
            return {"decision_output": r2_decision(_snapshot(state))}
        if current_node == "R1_REFLECTOR":
            snapshot = _snapshot(state, title=f"{state['trends'][0].topic}安全清单")
            return {"decision_output": r2_decision(snapshot)}

        audit = state["r2_output"].compliance_audit
        if audit.block_publish:
            return {
                "decision_output": DecisionOutput(
                    next_node="R1_REFLECTOR",
                    normalized_input=NormalizedInput(),
                )
            }
        snapshot = state["r2_output"].content_snapshot
        context = state["domain_context"]
        trend = state["trends"][0]
        return {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            ),
            "final_content": HashTagInput(
                final_title=snapshot.revised_title,
                final_md=snapshot.revised_md,
                topic_id=trend.topic_id,
                angle_id="ag_001",
                topic=trend.topic,
                angle="实用清单",
                domain=context.domain,
                subdomain=context.subdomain,
                content_intent=trend.content_intent,
                risk_level=trend.risk_level,
                risk_flags=trend.risk_flags,
                target_group=trend.target_group,
                core_pain=trend.core_pain,
                best_cover_copy="一页看懂",
                narrative_plan=_domain_narrative_plan(),
            ),
        }

    r2_calls = {"count": 0}

    def r2_node(state):
        r2_calls["count"] += 1
        snapshot = state["decision_output"].normalized_input.r2_input.content_snapshot
        unsafe_human_edit = "治疗" in snapshot.revised_title
        blocked = force_r2_block or unsafe_human_edit
        output = _safe_r2_output(snapshot)
        if blocked:
            output.compliance_audit = output.compliance_audit.model_copy(
                update={
                    "compliance_status": "high_risk_detected",
                    "block_publish": True,
                    "matched_policy_rules": ["medical_treatment"],
                }
            )
        return {"r2_output": output, "current_node": "R2_COMPLIANCE"}

    def r1_node(state):
        events["r1_calls"] += 1
        if force_r2_block:
            raise RuntimeError("blocked before hashtags")
        return {
            "r1_output": {},
            "current_node": "R1_REFLECTOR",
        }

    def hashtag_node(state):
        events["hashtag_calls"] += 1
        final_content = state.get("final_content")
        if final_content is None:
            snapshot = state["r2_output"].content_snapshot
            context = state["domain_context"]
            trend = state["trends"][0]
            final_content = HashTagInput(
                final_title=snapshot.revised_title,
                final_md=snapshot.revised_md,
                topic_id=trend.topic_id,
                angle_id="ag_001",
                topic=trend.topic,
                angle="实用清单",
                domain=context.domain,
                subdomain=context.subdomain,
                content_intent=trend.content_intent,
                risk_level=trend.risk_level,
                risk_flags=trend.risk_flags,
                target_group=trend.target_group,
                core_pain=trend.core_pain,
                best_cover_copy="一页看懂",
                narrative_plan=_domain_narrative_plan(),
            )
        return {
            "final_content": final_content,
            "hashtags": HashTagOutput(hashtags=["#习惯"]),
        }

    def assembler_node(state):
        content = state["final_content"]
        contract = state["trends"][0].content_contract
        narrative_plan = _domain_narrative_plan()
        return {
            "publish_package": {
                "topic_id": content.topic_id,
                "topic": content.topic,
                "angle_id": content.angle_id,
                "angle": content.angle,
                "target_group": content.target_group,
                "core_pain": content.core_pain,
                "title": content.final_title,
                "content": content.final_md,
                "cover_copy": content.best_cover_copy,
                "hashtags": state["hashtags"].hashtags,
                "storyboards": [],
                "domain": content.domain,
                "subdomain": content.subdomain,
                "content_intent": content.content_intent,
                "risk_level": content.risk_level,
                "risk_flags": content.risk_flags,
                "profile_version": state["domain_context"].profile_version,
                "content_contract": contract.model_dump(mode="json"),
                "narrative_plan": narrative_plan.model_dump(mode="json"),
                "narrative_form": narrative_plan.narrative_form,
                "closing_mode": narrative_plan.closing_mode,
            }
        }

    def storyboard_generator_node(state):
        contract = state["trends"][0].content_contract
        narrative_plan = _domain_narrative_plan()
        storyboards = _structured_storyboards(
            contract,
            narrative_plan,
            state["publish_package"],
        )
        return {
            "publish_package": {
                **state["publish_package"],
                "storyboards": storyboards,
            }
        }

    active_root = artifact_root / "active"
    active_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(final_guard_module, "ASSET_ACTIVE_ROOT", active_root)
    monkeypatch.setattr(final_guard_module, "RENDER_OUTPUT_ROOT", artifact_root)

    def asset_resolver_node(state):
        items = []
        catalog_assets = []
        for requirement in state["visual_plan"].required_assets:
            width = requirement.min_width
            height = requirement.min_height
            asset_path = active_root / f"{requirement.slot_id}.svg"
            asset_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" '
                f'width="{width}" height="{height}"></svg>'
            )
            asset_id = f"fixture-{requirement.slot_id}"
            asset_sha256 = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            items.append(
                {
                    "slot_id": requirement.slot_id,
                    "role": requirement.role,
                    "page_archetype": requirement.page_archetype,
                    "status": "active",
                    "path": str(asset_path),
                    "sha256": asset_sha256,
                    "asset_id": asset_id,
                    "source_type": "local",
                    "provider": None,
                    "provider_asset_id": None,
                    "source_url": None,
                    "source_file_url": None,
                    "author": None,
                    "provider_attribution": {},
                    "license": "project_internal",
                    "width": width,
                    "height": height,
                    "license_snapshot": None,
                    "license_snapshot_sha256": None,
                    "license_terms_url": None,
                    "run_id": None,
                    "acquired_at": None,
                    "average_hash": None,
                    "requirement_fingerprint": None,
                    "unresolved_safety_checks": [],
                    "safety_review_decisions": {},
                    "safety_reviewed_at": None,
                    "review_status": None,
                    "review_disposition": None,
                }
            )
            catalog_assets.append(
                {
                    "asset_id": asset_id,
                    "role": requirement.role,
                    "path": f"active/{requirement.slot_id}.svg",
                    "ownership": "project_original",
                    "license": "project_internal",
                    "dimensions": {"width": width, "height": height},
                    "sha256": asset_sha256,
                    "allowed_layouts": [requirement.page_archetype],
                    "tags": ["integration"],
                    "disabled_contexts": [],
                    "fallback_roles": [requirement.role],
                    "usage": "production",
                }
            )
        (active_root.parent / "manifest.json").write_text(
            json.dumps(
                {
                    "catalog_id": "domain_integration_catalog",
                    "assets": catalog_assets,
                }
            )
        )
        return {
            "asset_manifest": {"items": items}
        }

    def editorial_renderer_node(state):
        package = dict(state["publish_package"])
        image_root = artifact_root / "images"
        image_root.mkdir(parents=True, exist_ok=True)
        pages = []
        for index, frame in enumerate(package["storyboards"], start=1):
            path = image_root / f"{index:02d}-page.png"
            Image.new("RGB", (16, 16), (index * 20, 30, 40)).save(path)
            text_results = [
                {"role": "kicker", "text": frame["kicker"]},
                {"role": "headline", "text": frame["headline"]},
                {
                    "role": "content_blocks[0].body",
                    "text": frame["content_blocks"][0]["body"],
                },
            ]
            for emphasis_index, emphasis_text in enumerate(frame.get("emphasis") or []):
                text_results.append(
                    {"role": f"emphasis[{emphasis_index}]", "text": emphasis_text}
                )
            text_results.append({"role": "footer", "text": frame["footer"]})
            pages.append(
                {
                    "frame_id": frame["frame_id"],
                    "role": frame["role"],
                    "page_archetype": frame["page_archetype"],
                    "template_family": frame["page_archetype"],
                    "density": "standard",
                    "composition_variant": "integration",
                    "width": 1080,
                    "height": 1440,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "probe": {"text_results": text_results},
                }
            )
        contact_sheet = image_root / "contact-sheet.png"
        Image.new("RGB", (32, 16), "white").save(contact_sheet)
        package["rendered_image_paths"] = [page["path"] for page in pages]
        return {
            "publish_package": package,
            "render_manifest": {
                "pages": pages,
                "source_asset_sha256": {
                    item["slot_id"]: item["sha256"]
                    for item in state["asset_manifest"]["items"]
                },
                "contact_sheet_path": str(contact_sheet),
                "contact_sheet_sha256": hashlib.sha256(
                    contact_sheet.read_bytes()
                ).hexdigest(),
                "contact_sheet_page_sha256": [
                    page["sha256"] for page in pages
                ],
            },
        }

    def render_qa_node(_state):
        return {"render_qa_result": {"passed": True, "issues": []}}

    def writer_node(_state):
        events["writer_calls"] += 1
        events["structured_writes"] += 1
        events["vector_writes"] += 1
        return {"data_writed": True}

    replacements = {
        "domain_router_node": domain_router_node,
        "domain_confirmation_node": domain_confirmation_node,
        "retrieve_memory_node": memory_node,
        "topic_signal_collector_node": topic_signal_collector_node,
        "creative_brief_builder_node": creative_brief_builder_node,
        "topic_ideator_node": topic_ideator_node,
        "topic_diversity_filter_node": topic_diversity_filter_node,
        "angle_strategist_node": passthrough("angles", []),
        "novelty_guard_node": passthrough("novelty_check_results", []),
        "virality_scorer_node": lambda _state: {
            "scores": [{"topic_id": "tp_001"}]
        },
        "evidence_brief_node": evidence_node,
        "outline_architect_node": passthrough("outlines", []),
        "draft_writer_node": passthrough("drafts", []),
        "title_lab_node": passthrough("titles_options", []),
        "title_ranker_node": title_ranker_node,
        "decision_engine_node": decision_node,
        "r1_reflector_node": r1_node,
        "r2_compliance_node": r2_node,
        "hashtag_node": hashtag_node,
        "assembler_node": assembler_node,
        "asset_resolver_node": asset_resolver_node,
        "storyboards_generator_node": storyboard_generator_node,
        "editorial_carousel_renderer_node": editorial_renderer_node,
        "render_qa_node": render_qa_node,
        "human_review_node": human_review_node,
        "final_policy_guard_node": final_policy_guard_node,
        "content_writer_node": writer_node,
    }
    for name, replacement in replacements.items():
        monkeypatch.setattr(graph_module.nodes, name, replacement)


@pytest.fixture
def graph_factory(monkeypatch, tmp_path):
    connections = []

    def factory(*, evidence_results=True, force_r2_block=False):
        events = {
            "memory_calls": [],
            "evidence_searches": [],
            "outline_calls": 0,
            "r1_calls": 0,
            "hashtag_calls": 0,
            "writer_calls": 0,
            "structured_writes": 0,
            "vector_writes": 0,
        }
        _install_graph_doubles(
            monkeypatch,
            events,
            artifact_root=tmp_path / f"artifacts-{len(connections)}",
            evidence_results=evidence_results,
            force_r2_block=force_r2_block,
        )
        connection = sqlite3.connect(
            tmp_path / f"checkpoint-{len(connections)}.sqlite",
            check_same_thread=False,
        )
        connections.append(connection)
        checkpointer = SqliteSaver(connection)
        checkpointer.setup()
        return graph_module.create_graph(checkpointer=checkpointer), events

    yield factory

    for connection in connections:
        connection.close()


def _run_to_review(graph, initial_state, thread_id):
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(initial_state, config=config)
    assert result["__interrupt__"]
    return config, result


@pytest.mark.parametrize(
    "initial_state,expected",
    [
        (
            {"domain": "beauty", "subdomain": "skincare", "focus_keyword": "夏季防晒", "trends_num": 1},
            ("beauty", "skincare", "experience", "low", False),
        ),
        (
            {"focus_keyword": "睡眠改善", "trends_num": 1},
            ("wellness", "sleep", "basic_science", "medium", True),
        ),
            (
                {
                    "focus_keyword": "运动清单",
                    "trends_num": 1,
                },
                ("healthy_lifestyle", "exercise", "checklist", "low", False),
            ),
    ],
)
def test_domain_paths_reach_review_with_partitioned_metadata(
    graph_factory,
    initial_state,
    expected,
):
    graph, events = graph_factory()
    config, interrupted = _run_to_review(
        graph,
        initial_state,
        f"domain-{expected[0]}",
    )

    domain, subdomain, intent, risk, expects_evidence = expected
    package = interrupted["publish_package"]
    assert package["domain"] == domain
    assert package["subdomain"] == subdomain
    assert package["content_intent"] == intent
    assert package["risk_level"] == risk
    assert bool(interrupted.get("evidence_briefs")) is expects_evidence
    assert bool(events["evidence_searches"]) is expects_evidence

    completed = graph.invoke(Command(resume={"approved": True}), config=config)
    assert completed["data_writed"] is True
    assert events["writer_calls"] == 1


def test_unknown_explicit_domain_fails_before_memory_retrieval(graph_factory):
    graph, events = graph_factory()

    with pytest.raises(ValueError, match="Unsupported domain"):
        graph.invoke(
            {"domain": "medical", "focus_keyword": "处方", "trends_num": 1},
            config={"configurable": {"thread_id": "unknown-domain"}},
        )

    assert events["memory_calls"] == []


def test_missing_required_evidence_stops_before_outline(graph_factory):
    graph, events = graph_factory(evidence_results=False)

    with pytest.raises(RuntimeError, match="No allowlisted evidence"):
        graph.invoke(
            {"focus_keyword": "睡眠改善", "trends_num": 1},
            config={"configurable": {"thread_id": "missing-evidence"}},
        )

    assert events["outline_calls"] == 0


def test_blocked_r2_cannot_reach_hashtags(graph_factory):
    graph, events = graph_factory(force_r2_block=True)

    with pytest.raises(RuntimeError, match="blocked before hashtags"):
        graph.invoke(
            {"domain": "beauty", "subdomain": "skincare", "focus_keyword": "夏季防晒", "trends_num": 1},
            config={"configurable": {"thread_id": "blocked-r2"}},
        )

    assert events["r1_calls"] == 1
    assert events["hashtag_calls"] == 0


def test_human_treatment_edit_returns_to_review_before_write(graph_factory):
    graph, events = graph_factory()
    config, _interrupted = _run_to_review(
        graph,
        {"domain": "beauty", "subdomain": "skincare", "focus_keyword": "夏季防晒", "trends_num": 1},
        "human-edit",
    )

    second_review = graph.invoke(
        Command(
            resume={
                "approved": True,
                "edited_publish_package": {"title": "治疗晒伤的方法"},
            }
        ),
        config=config,
    )

    assert second_review["__interrupt__"]
    assert second_review["publish_package"]["title"] == "夏季防晒安全清单"
    assert events["r1_calls"] == 1
    assert events["writer_calls"] == 0


def test_rejected_review_never_calls_memory_writes(graph_factory):
    graph, events = graph_factory()
    config, _interrupted = _run_to_review(
        graph,
        {"domain": "beauty", "subdomain": "skincare", "focus_keyword": "夏季防晒", "trends_num": 1},
        "rejected-review",
    )

    rejected = graph.invoke(
        Command(resume={"approved": False, "feedback": "rewrite"}),
        config=config,
    )

    assert rejected["__interrupt__"]
    assert events["structured_writes"] == 0
    assert events["vector_writes"] == 0
