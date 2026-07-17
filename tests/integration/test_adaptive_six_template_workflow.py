"""Offline end-to-end coverage for the adaptive six-template editorial workflow.

These tests drive the production editorial graph (assembler -> visual_strategy
planner -> storyboard_generator -> asset_resolver -> carousel_qa -> editorial
carousel_renderer -> render_qa -> human_review -> final_policy_guard ->
content_writer) entirely offline: the only model boundaries (assembler and
storyboard generator) are stubbed with deterministic responses, no live LLM or
external asset provider is contacted, and the local Chromium renderer is
exercised through the production ``render_carousel`` interface.

They prove the three Task 13 guarantees:

* Every narrative form preserved copy -> storyboard -> render (5-7 pages).
* The eight-fixture matrix selects all six production template families.
* Page count is content driven: the same template family renders 5, 6, and 7
  pages from the same green-catalog contract when only ``recommended_frame_count``
  changes.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import src.graph as graph_module
from memory.memory_manager import XHSMemoryManager
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.editorial_carousel.planner import build_visual_plan
from src.nodes import (
    node_o_assembler as assembler_module,
)
from src.nodes import (
    node_o_storyboards_generator as storyboard_module,
)
from src.nodes import (
    node_p_asset_resolver as resolver_node_module,
)
from src.nodes import (
    node_p_content_writer as writer_module,
)
from src.nodes import (
    node_p_editorial_carousel_renderer as renderer_module,
)
from src.nodes import (
    node_q_01_final_policy_guard as guard_module,
)
from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas.content_contract import ContentContract
from src.schemas.decision import DecisionOutput, HashTagInput, NormalizedInput
from src.schemas.hashtag import HashTagOutput
from src.schemas.narrative import NarrativePlan
from src.schemas.topic import TopicItem
from src.schemas.topic_signal import CreativeSeed
from src.schemas.visual_plan import VisualPlan


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "adaptive_editorial"

ALL_NARRATIVE_FIXTURES = (
    "cognitive_correction",
    "step_tutorial",
    "checklist_collection",
    "comparison",
    "diagnostic_qa",
    "scenario_story",
    "story_reversal",
    "reflective_editorial",
)

ALL_TEMPLATE_FAMILIES = frozenset(
    {
        "pink_red",
        "deep_teal",
        "soft_pink",
        "coral_impact",
        "green_catalog",
        "white_quote",
    }
)

EXPECTED_FONT_FAMILIES = {
    "Source Han Serif SC",
    "Source Han Sans SC",
    "Bodoni Moda",
}


def load_fixture(name: str) -> dict[str, Any]:
    fixture = json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))
    assert fixture["fixture_id"] == name
    assert fixture["test_only"] is True
    assert fixture["intended_use"].startswith("synthetic regression input only")
    return fixture


def _topic(fixture: dict[str, Any]) -> TopicItem:
    package = fixture["package"]
    return TopicItem(
        topic_id=package["topic_id"],
        topic=package["topic"],
        target_group=package["target_group"],
        core_pain=package["core_pain"],
        hook=fixture["content_contract"]["first_screen_promise"],
        content_form="cards",
        risk_note="synthetic test-only input",
        domain="beauty",
        subdomain="skincare",
        content_intent=package["content_intent"],
        risk_level="low",
        risk_flags=[],
        content_contract=ContentContract.model_validate(
            fixture["content_contract"]
        ),
        creative_seed=CreativeSeed(
            signal_type="evergreen_context",
            signal_name="synthetic-regression-only",
            why_now="test-only deterministic execution",
            domain_translation="test-only deterministic execution",
            evergreen_pain="test-only deterministic execution",
            timely_framing="test-only deterministic execution",
        ),
    )


def _initial_state(fixture: dict[str, Any]) -> dict[str, Any]:
    package = fixture["package"]
    topic = _topic(fixture)
    narrative_plan = NarrativePlan.model_validate(fixture["narrative_plan"])
    return {
        "interactive": True,
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain": "beauty",
        "subdomain": "skincare",
        "focus_keyword": package["focus_keyword"],
        "focus_keyword_cli_present": True,
        "domain_context": {
            "domain": "beauty",
            "subdomain": "skincare",
            "profile_version": "beauty-v1",
        },
        "content_policy": {},
        "memory_context": {},
        "evidence_briefs": {},
        "topic_signals": [],
        "trends": [topic],
        "final_policy_issues": [],
        "final_content": HashTagInput(
            final_title=package["title"],
            final_md=package["content"],
            topic_id=package["topic_id"],
            angle_id=package["angle_id"],
            topic=package["topic"],
            angle=package["angle"],
            domain="beauty",
            subdomain="skincare",
            content_intent=package["content_intent"],
            risk_level="low",
            risk_flags=[],
            target_group=package["target_group"],
            core_pain=package["core_pain"],
            best_cover_copy=package["cover_copy"],
            narrative_plan=narrative_plan,
        ),
        "hashtags": HashTagOutput(hashtags=package["hashtags"]),
        "r2_output": {
            "compliance_audit": {
                "compliance_status": "passed",
                "matched_policy_rules": [],
            }
        },
        "topic_generation_trace": {"run_id": f"adaptive-{fixture['fixture_id']}"},
        "review_round": 0,
    }


def _storyboards_for_plan(
    fixture: dict[str, Any],
    visual_plan: VisualPlan,
) -> list[dict[str, Any]]:
    """Synthesize schema-valid storyboards that exactly match ``visual_plan``.

    The cover headline is pinned to ``content_contract.first_screen_promise``
    so the storyboard generator's semantic contract holds. Save/checklist/
    comparison archetypes pick up the fixture's ``visible_copy.save`` anchor
    when present so the saveable page carries identifiable regression copy.
    """

    contract = ContentContract.model_validate(fixture["content_contract"])
    visible = fixture.get("visible_copy") or {}
    save_headline = visible.get("save") or "保存本次合成回归卡"
    cover_headline = contract.first_screen_promise
    storyboards: list[dict[str, Any]] = []
    saveable_archetypes = {"save", "checklist", "comparison"}
    for frame in visual_plan.frame_plan:
        archetype = frame.page_archetype
        if archetype == "cover":
            headline = cover_headline
        elif archetype in saveable_archetypes:
            headline = save_headline
        else:
            headline = frame.purpose
        items = (
            visible.get("items")
            if archetype == "checklist" and "items" in visible
            else ["合成回归项一", "合成回归项二", "合成回归项三"]
        )
        block_type = {
            "checklist": "checklist",
            "comparison": "comparison",
            "steps": "steps",
            "diagnostic": "decision_tree",
            "qa": "text",
        }.get(archetype, "text")
        storyboards.append(
            {
                "frame_id": frame.frame_id,
                "role": frame.role,
                "page_archetype": archetype,
                "headline": headline[:80],
                "kicker": "合成回归",
                "content_blocks": [
                    {
                        "block_type": block_type,
                        "heading": headline[:80],
                        "body": frame.purpose,
                        "items": list(items),
                    }
                ],
                "emphasis": [],
                "visual_slots": [],
                "footer": "仅限合成回归",
            }
        )
    return storyboards


class _OfflineAssemblerModel:
    """Deterministic assembler model: returns the fixture package copy."""

    def __init__(self, package: dict[str, Any]) -> None:
        self._package = package

    def execute(self, _messages):
        return {
            "images": [],
            "hashtags": list(self._package.get("hashtags") or []),
            "notes": [],
        }


class _OfflineStoryboardModel:
    """Deterministic storyboard model: mirrors the visual plan exactly."""

    def __init__(self, storyboards: list[dict[str, Any]]) -> None:
        self._storyboards = storyboards

    def execute(self, _messages):
        return {"storyboards": [dict(frame) for frame in self._storyboards]}


class _OfflineProvider:
    """No-op asset provider used to guarantee offline execution."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.enabled = True
        self.search_calls = 0
        self.download_calls = 0

    def search(self, _requirement):
        self.search_calls += 1
        return []

    def record_download(self, _candidate) -> None:
        return None

    def download(self, _candidate) -> bytes:
        self.download_calls += 1
        return b""


class _OfflineDatabase:
    """Minimal in-memory stand-in for the structured + vector stores.

    The adaptive workflow only needs the writer to confirm that a record was
    persisted. We back the structured side with the real
    :class:`XHSMemoryManager` against a tmp DB and answer every embedding
    probe with a positive hit so ``data_writed`` is True.
    """

    def __init__(self, db_path: Path, schema_path: Path) -> None:
        self.manager = XHSMemoryManager(db_path)
        self.manager.init_db(schema_path)
        self._ids: set[str] = set()

    def init_db(self, _schema_path) -> None:
        # Already initialized in ``__init__``; the writer re-invokes this
        # with the canonical schema path, which is a no-op for the harness.
        return None

    def save_generated_content(self, record) -> None:
        self.manager.save_generated_content(record)
        self._ids.add(record.content_id)

    def save_embedding_content(self, record) -> None:
        self._ids.add(record.content_id)

    def get_content_by_id(self, content_id):
        return self.manager.get_content_by_id(content_id)

    def get_embedding_content_by_id(self, content_id):
        return content_id if content_id in self._ids else None

    def delete_content_by_id(self, content_id) -> None:
        self._ids.discard(content_id)
        self.manager.delete_content_by_id(content_id)

    def close(self) -> None:
        self.manager.close()


@pytest.fixture
def offline_harness(monkeypatch, tmp_path):
    """Install offline stubs around the production editorial graph."""

    publish_root = tmp_path / "publish"
    publish_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer_module, "PUBLISH_ROOT", publish_root)
    monkeypatch.setattr(guard_module, "RENDER_OUTPUT_ROOT", publish_root)

    database = _OfflineDatabase(
        tmp_path / "memory.sqlite",
        REPOSITORY_ROOT / "memory" / "schema.sql",
    )
    monkeypatch.setattr(writer_module, "XHSMemoryManager", lambda *_a, **_kw: database)

    def passthrough(_state):
        return {}

    for node_name in (
        "domain_router_node",
        "domain_confirmation_node",
        "retrieve_memory_node",
        "topic_signal_collector_node",
        "creative_brief_builder_node",
        "topic_ideator_node",
        "topic_diversity_filter_node",
        "angle_strategist_node",
        "novelty_guard_node",
        "virality_scorer_node",
        "evidence_brief_node",
        "outline_architect_node",
        "draft_writer_node",
        "title_lab_node",
        "title_ranker_node",
        "hashtag_node",
    ):
        monkeypatch.setattr(graph_module.nodes, node_name, passthrough)
    monkeypatch.setattr(
        graph_module.nodes,
        "decision_engine_node",
        lambda _state: {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        },
    )

    def unexpected_revision(state):
        raise AssertionError(
            "adaptive offline workflow entered a remote revision lane: "
            f"carousel={state.get('carousel_qa_result')!r}, "
            f"render={state.get('render_qa_result')!r}"
        )

    monkeypatch.setattr(
        graph_module.nodes, "r1_reflector_node", unexpected_revision
    )
    monkeypatch.setattr(
        graph_module.nodes, "r2_compliance_node", unexpected_revision
    )

    pexels = _OfflineProvider("pexels")
    unsplash = _OfflineProvider("unsplash")
    monkeypatch.setattr(
        resolver_node_module, "PexelsProvider", lambda *_a, **_kw: pexels
    )
    monkeypatch.setattr(
        resolver_node_module, "UnsplashProvider", lambda *_a, **_kw: unsplash
    )

    yield {
        "pexels": pexels,
        "unsplash": unsplash,
        "publish_root": publish_root,
        "database": database,
    }
    database.close()


def _install_offline_models(monkeypatch, fixture: dict[str, Any]):
    """Install deterministic assembler/storyboard models for ``fixture``."""

    package = fixture["package"]
    contract = ContentContract.model_validate(fixture["content_contract"])
    narrative_plan = NarrativePlan.model_validate(fixture["narrative_plan"])
    visual_plan = build_visual_plan(
        contract,
        narrative_plan,
        package,
        recent_signatures=[],
    )
    storyboards = _storyboards_for_plan(fixture, visual_plan)
    monkeypatch.setattr(
        assembler_module, "get_model", lambda: _OfflineAssemblerModel(package)
    )
    monkeypatch.setattr(
        storyboard_module,
        "get_model",
        lambda: _OfflineStoryboardModel(storyboards),
    )
    return visual_plan


def run_offline_editorial_pipeline(
    fixture: dict[str, Any],
    tmp_path: Path,
    *,
    monkeypatch=None,
) -> dict[str, Any]:
    """Drive the production editorial graph offline for one fixture.

    The graph is invoked once to reach Human Review, then resumed with an
    explicit approval so ``content_writer`` runs and the published package is
    materialized. The returned dict exposes ``visual_plan``,
    ``publish_package``, ``render_manifest`` and other snapshot values needed
    by the adaptive workflow assertions.
    """

    if monkeypatch is None:
        raise TypeError(
            "run_offline_editorial_pipeline requires an active monkeypatch"
        )

    _install_offline_models(monkeypatch, fixture)
    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"adaptive-{fixture['fixture_id']}"}}
    initial_state = _initial_state(fixture)

    interrupted = graph.invoke(initial_state, config=config)
    interrupts = interrupted.get("__interrupt__")
    assert interrupts, "adaptive workflow must pause at real Human Review"
    snapshot = graph.get_state(config)
    resumed = graph.invoke(Command(resume={"approved": True}), config=config)
    assert resumed.get("data_writed") is True

    final_snapshot = graph.get_state(config)
    return dict(final_snapshot.values)


@pytest.fixture
def harness_with_monkeypatch(monkeypatch, tmp_path, offline_harness):
    """Bundle monkeypatch + offline_harness for the parametrized tests."""

    return monkeypatch, tmp_path


@pytest.mark.parametrize("fixture_name", ALL_NARRATIVE_FIXTURES)
def test_narrative_fixture_keeps_one_form_from_copy_to_storyboard(
    fixture_name,
    tmp_path,
    monkeypatch,
    offline_harness,
):
    fixture = load_fixture(fixture_name)
    state = run_offline_editorial_pipeline(fixture, tmp_path, monkeypatch=monkeypatch)

    publish_package = state["publish_package"]
    visual_plan = VisualPlan.model_validate(state["visual_plan"])

    assert publish_package["narrative_form"] == fixture["narrative_form"]
    assert visual_plan.narrative_form == fixture["narrative_form"]
    assert publish_package["narrative_plan"]["narrative_form"] == fixture[
        "narrative_form"
    ]
    assert 5 <= len(publish_package["storyboards"]) <= 7
    assert len(publish_package["storyboards"]) == len(visual_plan.frame_plan)

    storyboard_forms = [
        frame["page_archetype"] for frame in publish_package["storyboards"]
    ]
    planned_forms = [frame.page_archetype for frame in visual_plan.frame_plan]
    assert storyboard_forms == planned_forms
    assert storyboard_forms[0] == "cover"

    carousel_qa = state["carousel_qa_result"]
    render_qa = state["render_qa_result"]
    assert carousel_qa.passed is True
    assert render_qa.passed is True


def test_fixture_matrix_selects_all_six_template_families(
    tmp_path,
    monkeypatch,
    offline_harness,
):
    selected = set()
    for name in ALL_NARRATIVE_FIXTURES:
        fixture = load_fixture(name)
        state = run_offline_editorial_pipeline(
            fixture, tmp_path / name, monkeypatch=monkeypatch
        )
        visual_plan = VisualPlan.model_validate(state["visual_plan"])
        assert visual_plan.template_family == fixture["expected_template_family"]
        selected.add(visual_plan.template_family)

    assert selected == ALL_TEMPLATE_FAMILIES


def _render_green_catalog(
    monkeypatch,
    tmp_path: Path,
    *,
    recommended_frame_count: int,
    label: str,
) -> RenderManifest:  # noqa: F821 - imported lazily below
    from src.rendering.editorial.renderer import render_carousel
    from src.schemas.storyboard import CarouselPayload

    base = load_fixture("comparison")
    fixture = json.loads(json.dumps(base))
    fixture["content_contract_override"] = None
    contract_payload = dict(fixture["content_contract"])
    contract_payload["recommended_frame_count"] = recommended_frame_count
    fixture["content_contract"] = contract_payload
    package = dict(fixture["package"])
    package["topic_id"] = f"synthetic-green-catalog-{label}"
    package["angle_id"] = f"synthetic-green-catalog-angle-{label}"
    fixture["package"] = package

    _install_offline_models(monkeypatch, fixture)

    contract = ContentContract.model_validate(fixture["content_contract"])
    narrative_plan = NarrativePlan.model_validate(fixture["narrative_plan"])
    visual_plan = build_visual_plan(
        contract,
        narrative_plan,
        package,
        recent_signatures=[],
    )
    assert visual_plan.template_family == "green_catalog"
    storyboards = _storyboards_for_plan(fixture, visual_plan)
    payload = CarouselPayload.model_validate({"storyboards": storyboards})
    assets = _empty_asset_manifest()

    output_dir = tmp_path / f"green-catalog-{label}" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    return render_carousel(visual_plan, payload, assets, output_dir)


def _empty_asset_manifest():
    """Return a schema-valid AssetManifest with no items (pure-text render)."""

    from src.schemas.assets import AssetManifest

    return AssetManifest.model_validate(
        {
            "items": [],
            "search_report": {
                "search_triggered": False,
                "queries": [],
                "provider_reports": [],
                "selection_reasons": {},
            },
        }
    )


def test_template_page_count_is_content_driven(
    tmp_path,
    monkeypatch,
    offline_harness,
):
    five = _render_green_catalog(
        monkeypatch,
        tmp_path / "five",
        recommended_frame_count=5,
        label="5",
    )
    six = _render_green_catalog(
        monkeypatch,
        tmp_path / "six",
        recommended_frame_count=6,
        label="6",
    )
    seven = _render_green_catalog(
        monkeypatch,
        tmp_path / "seven",
        recommended_frame_count=7,
        label="7",
    )
    assert [len(value.pages) for value in (five, six, seven)] == [5, 6, 7]
    for manifest in (five, six, seven):
        assert all(Path(page.path).is_file() for page in manifest.pages)
        assert manifest.fonts.all_loaded is True
        # green_catalog pins its own display/body fonts; just assert a
        # non-empty, fully-loaded computed family set per render.
        assert manifest.fonts.computed_families


def test_every_narrative_fixture_is_isolated_from_production_sources(
    fixture_name=None,
):
    # Mirror the production-source isolation guard from the v1 suite so any
    # fixture string escaping into production Python/prompts fails loudly.
    tracked = subprocess_run_git_ls_files()
    production_files = [
        REPOSITORY_ROOT / relative
        for relative in tracked
        if relative
        and (REPOSITORY_ROOT / relative).is_file()
        and not relative.startswith(
            ("tests/", "docs/", ".superpowers/", ".worktrees/", "outputs/")
        )
    ]
    production_text_parts = []
    for path in production_files:
        try:
            production_text_parts.append(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            continue
    production_text = "\n".join(production_text_parts)

    for name in ALL_NARRATIVE_FIXTURES:
        fixture = load_fixture(name)
        # The fixture ``fixture_id`` is intentionally identical to its
        # ``NarrativeForm`` value (e.g. ``cognitive_correction``), which
        # legitimately appears in production blueprints; only the unique
        # synthetic copy strings must remain isolated from production.
        isolated_values = {
            fixture["synthetic_title"],
            fixture["package"]["topic_id"],
            fixture["package"]["topic"],
            fixture["package"]["focus_keyword"],
            fixture["package"]["cover_copy"],
        }
        for value in isolated_values:
            assert value not in production_text, (
                f"adaptive fixture {name!r} leaked into production sources"
            )


def subprocess_run_git_ls_files():
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    return [entry for entry in tracked if entry]
