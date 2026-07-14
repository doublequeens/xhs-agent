from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from PIL import Image, ImageDraw

import src.graph as graph_module
from memory.memory_manager import XHSMemoryManager
from src.asset_resolver.providers import ExternalAssetCandidate
from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1
from src.editorial_carousel.strategy import build_visual_plan
from src.publishing.artifacts import export_publish_package
from src.rendering.editorial.design_system import ASSET_ROOT
from src.run_registry import RunRegistry
from src.schemas.content_contract import ContentContract
from src.schemas.decision import DecisionOutput, HashTagInput, NormalizedInput
from src.schemas.hashtag import HashTagOutput
from src.schemas.topic import TopicItem
from src.schemas.topic_signal import CreativeSeed


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/editorial_carousel"
GOLDEN_FIXTURE_NAMES = (
    "zone_diagnosis",
    "ordered_routine",
    "multi_option_decision",
    "reference_checklist",
)
SAVEABLE_LAYOUTS = {"saveable_checklist", "saveable_reference"}
EXPECTED_FONT_FAMILIES = {
    "Source Han Serif SC",
    "Source Han Sans SC",
    "Bodoni Moda",
}


def load_golden(name: str) -> dict:
    fixture = json.loads(
        (FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8")
    )
    assert fixture["fixture_id"] == name
    assert fixture["test_only"] is True
    assert fixture["intended_use"].startswith("synthetic regression input only")
    return fixture


@pytest.mark.parametrize("fixture_name", GOLDEN_FIXTURE_NAMES)
def test_golden_fixture_is_absent_from_production_sources_and_seed_data(
    fixture_name,
):
    fixture = load_golden(fixture_name)
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (
            REPOSITORY_ROOT / "src",
            REPOSITORY_ROOT / "memory",
            REPOSITORY_ROOT / "assets/visual",
        )
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".txt", ".json", ".md"}
    )

    assert fixture_name not in production_text
    assert fixture["synthetic_title"] not in production_text
    assert fixture["package"]["topic_id"] not in production_text
    assert fixture["package"]["topic"] not in production_text


def _storyboards(fixture: dict) -> tuple[object, list[dict]]:
    contract = ContentContract.model_validate(fixture["content_contract"])
    plan = build_visual_plan(contract, recent_signatures=[])
    requirements_by_layout = {
        requirement.layout: requirement for requirement in plan.required_assets
    }
    storyboards = []
    for frame in plan.frame_plan:
        copy = fixture["frame_copy"][frame.role]
        requirement = requirements_by_layout[frame.layout]
        storyboards.append(
            {
                "frame_id": frame.frame_id,
                "role": frame.role,
                "layout": frame.layout,
                "headline": copy["headline"],
                "kicker": "合成回归",
                "content_blocks": [
                    {
                        "block_type": "checklist",
                        "heading": "核对点",
                        "body": copy["body"],
                        "items": copy["items"],
                    }
                ],
                "emphasis": [],
                "visual_slots": [
                    {
                        "slot_id": requirement.slot_id,
                        "role": frame.asset_roles[0],
                        "semantic_tags": ["synthetic", "regression"],
                    }
                ],
                "footer": "仅限合成回归",
            }
        )
    return plan, storyboards


def _topic(fixture: dict) -> TopicItem:
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


def _initial_state(fixture: dict) -> dict:
    package = fixture["package"]
    topic = _topic(fixture)
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
        ),
        "hashtags": HashTagOutput(hashtags=package["hashtags"]),
        "final_images": {"image_final_choices": []},
        "r2_output": {
            "compliance_audit": {
                "compliance_status": "passed",
                "matched_policy_rules": [],
            }
        },
        "topic_generation_trace": {
            "run_id": f"golden-{fixture['fixture_id']}"
        },
        "review_round": 0,
    }


class _StructuredDatabaseHarness:
    """Real temporary SQLite content store with a test-local embedding sidecar."""

    def __init__(self, db_path: Path) -> None:
        self.manager = XHSMemoryManager(db_path)
        self.saved_records = []
        self.embedding_ids: set[str] = set()

    def init_db(self, schema_path) -> None:
        self.manager.init_db(REPOSITORY_ROOT / schema_path)

    def save_generated_content(self, record) -> None:
        self.manager.save_generated_content(record)
        self.saved_records.append(record)

    def save_embedding_content(self, record) -> None:
        self.embedding_ids.add(record.content_id)

    def get_content_by_id(self, content_id):
        return self.manager.get_content_by_id(content_id)

    def get_embedding_content_by_id(self, content_id):
        return content_id if content_id in self.embedding_ids else None

    def delete_content_by_id(self, content_id) -> None:
        self.manager.delete_content_by_id(content_id)

    def close(self) -> None:
        self.manager.close()


class _FakeProvider:
    def __init__(
        self,
        name: str,
        results: list[ExternalAssetCandidate] | None = None,
        downloads: dict[str, bytes] | None = None,
    ) -> None:
        self.name = name
        self.enabled = True
        self.results = list(results or [])
        self.downloads = dict(downloads or {})
        self.search_calls = []
        self.record_calls = []
        self.download_calls = []

    def search(self, requirement):
        self.search_calls.append(requirement)
        return list(self.results)

    def record_download(self, candidate) -> None:
        self.record_calls.append(candidate)

    def download(self, candidate) -> bytes:
        self.download_calls.append(candidate)
        return self.downloads[candidate.provider_asset_id]


def _install_real_workflow_harness(
    monkeypatch,
    fixture: dict,
    tmp_path: Path,
    *,
    pexels: _FakeProvider,
    unsplash: _FakeProvider,
    catalog_root: Path | None = None,
    render_counter: dict | None = None,
):
    from src.nodes import node_o_assembler as assembler_module
    from src.nodes import node_o_storyboards_generator as storyboard_module
    from src.nodes import node_p_asset_resolver as resolver_node_module
    from src.nodes import node_p_content_writer as writer_module
    from src.nodes import node_p_editorial_carousel_renderer as renderer_node_module
    from src.nodes import node_p_text_card_renderer as output_module
    from src.nodes import node_q_01_final_policy_guard as guard_module

    plan, storyboards = _storyboards(fixture)
    package = fixture["package"]

    class FakeAssemblerModel:
        def execute(self, _messages):
            return {
                "images": [],
                "hashtags": package["hashtags"],
                "notes": [],
                "storyboard_strategy": "synthetic-regression-only",
            }

    class FakeStoryboardModel:
        def execute(self, _messages):
            return {"storyboards": storyboards}

    monkeypatch.setattr(assembler_module, "get_model", lambda: FakeAssemblerModel())
    monkeypatch.setattr(
        storyboard_module, "get_model", lambda: FakeStoryboardModel()
    )

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
        carousel_result = state.get("carousel_qa_result")
        render_result = state.get("render_qa_result")
        raise AssertionError(
            "synthetic golden workflow unexpectedly entered a remote revision lane: "
            f"carousel={carousel_result!r}, render={render_result!r}"
        )

    monkeypatch.setattr(
        graph_module.nodes, "r1_reflector_node", unexpected_revision
    )
    monkeypatch.setattr(
        graph_module.nodes, "r2_compliance_node", unexpected_revision
    )

    monkeypatch.setattr(
        resolver_node_module, "PexelsProvider", lambda *_args, **_kwargs: pexels
    )
    monkeypatch.setattr(
        resolver_node_module,
        "UnsplashProvider",
        lambda *_args, **_kwargs: unsplash,
    )
    if catalog_root is not None:
        monkeypatch.setattr(
            resolver_node_module, "CATALOG_PATH", catalog_root / "manifest.json"
        )
        monkeypatch.setattr(guard_module, "ASSET_ACTIVE_ROOT", catalog_root / "active")

    publish_root = tmp_path / "publish"
    monkeypatch.setattr(output_module, "PUBLISH_ROOT", publish_root)
    monkeypatch.setattr(guard_module, "RENDER_OUTPUT_ROOT", publish_root)

    if render_counter is not None:
        real_renderer_node = renderer_node_module.editorial_carousel_renderer_node

        def counted_renderer(state):
            render_counter["calls"] = render_counter.get("calls", 0) + 1
            return real_renderer_node(state)

        monkeypatch.setattr(
            graph_module.nodes,
            "editorial_carousel_renderer_node",
            counted_renderer,
        )

    database = _StructuredDatabaseHarness(tmp_path / "memory.sqlite")
    monkeypatch.setattr(writer_module, "XHSMemoryManager", lambda *_args: database)
    return plan, storyboards, database, publish_root


def _interrupt_payload(result: dict) -> dict:
    interrupts = result.get("__interrupt__")
    assert interrupts, "workflow must pause at real Human Review"
    return interrupts[0].value


def _approve_pending_payload(payload: dict) -> dict:
    decisions = {}
    for item in payload["pending_assets"]:
        decisions[item["decision_id"]] = {
            "decision": "approved",
            "binding": item["decision_binding"],
            "safety_decisions": {
                name: name == "allowed_for_publishing"
                for name in item["unresolved_safety_checks"]
            },
        }
    return {"approved": True, "asset_decisions": decisions}


@pytest.mark.parametrize("fixture_name", GOLDEN_FIXTURE_NAMES)
def test_golden_fixture_runs_real_local_editorial_workflow_end_to_end(
    fixture_name,
    monkeypatch,
    tmp_path,
):
    fixture = load_golden(fixture_name)
    pexels = _FakeProvider("pexels")
    unsplash = _FakeProvider("unsplash")
    plan, _storyboard, database, publish_root = _install_real_workflow_harness(
        monkeypatch,
        fixture,
        tmp_path,
        pexels=pexels,
        unsplash=unsplash,
    )
    graph = graph_module.create_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"golden-{fixture_name}"}}

    interrupted = graph.invoke(_initial_state(fixture), config=config)
    review_payload = _interrupt_payload(interrupted)
    completed = graph.invoke(Command(resume={"approved": True}), config=config)
    snapshot = graph.get_state(config)
    artifacts = export_publish_package(snapshot)

    signature = [(frame.role, frame.layout) for frame in plan.frame_plan]
    assert plan.primary_visual_family == fixture["expected_primary_family"]
    assert signature == [tuple(item) for item in fixture["expected_frame_signature"]]
    assert 5 <= len(plan.frame_plan) <= 7
    assert len({frame.layout for frame in plan.frame_plan}) >= 3
    assert any(frame.layout in SAVEABLE_LAYOUTS for frame in plan.frame_plan)

    render_manifest = snapshot.values["render_manifest"]
    rendered_paths = [Path(page.path) for page in render_manifest.pages]
    assert len(rendered_paths) == len(plan.frame_plan)
    assert rendered_paths[0].name == "01-cover.png"
    assert [int(path.name[:2]) for path in rendered_paths] == list(
        range(1, len(rendered_paths) + 1)
    )
    assert all(path.is_file() for path in rendered_paths)
    assert set(render_manifest.fonts.computed_families) == EXPECTED_FONT_FAMILIES
    assert render_manifest.fonts.all_loaded is True
    assert Path(render_manifest.contact_sheet_path).is_file()
    assert review_payload["carousel_qa_result"]["passed"] is True
    assert review_payload["render_qa_result"]["passed"] is True
    assert snapshot.values["carousel_qa_result"].passed is True
    assert snapshot.values["render_qa_result"].passed is True
    assert completed["data_writed"] is True

    assert len(database.saved_records) == 1
    record = database.saved_records[0]
    assert database.get_content_by_id(record.content_id)
    assert record.image_paths == [str(path) for path in rendered_paths]
    assert record.title == fixture["synthetic_title"]

    assert artifacts.publish_copy_path.is_file()
    assert artifacts.rescue_prompt_path.is_file()
    assert artifacts.audit_json_path.name == f"{fixture['synthetic_title']}.json"
    rescue_prompt = artifacts.rescue_prompt_path.read_text(encoding="utf-8")
    assert fixture["synthetic_title"] in rescue_prompt
    assert artifacts.content_lock.canonical_sha256 in rescue_prompt
    assert "禁止重新选题" in rescue_prompt
    audit = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert audit["content_lock"]["canonical_sha256"] == (
        artifacts.content_lock.canonical_sha256
    )
    assert audit["rendered_image_paths"] == [
        f"images/{path.name}" for path in rendered_paths
    ]
    assert artifacts.artifact_generation == 1
    assert pexels.search_calls == []
    assert unsplash.search_calls == []
    assert not pexels.download_calls
    assert not unsplash.download_calls
    assert len(list(publish_root.glob("*/images/*.png"))) == len(rendered_paths) + 1
    database.close()


def _external_png() -> bytes:
    stream = BytesIO()
    image = Image.new("RGB", (512, 512), "#D45D4C")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 250, 470), fill="#F7F2EA")
    draw.ellipse((220, 90, 480, 350), fill="#78805E")
    image.save(stream, format="PNG")
    return stream.getvalue()


def _external_candidate() -> ExternalAssetCandidate:
    return ExternalAssetCandidate(
        provider="unsplash",
        provider_asset_id="synthetic-texture-1",
        author="synthetic-author",
        source_url="https://unsplash.com/photos/synthetic-texture-1",
        source_file_url="https://images.unsplash.com/synthetic-texture-1",
        width=512,
        height=512,
        role="serum_texture",
        license="Unsplash test fixture license",
        license_snapshot=(
            "Unsplash test fixture terms\n"
            "Official terms: https://unsplash.com/license\n"
            "Mandatory human review before production use."
        ),
        license_terms_url="https://unsplash.com/license",
        score_tags=("product_texture", "synthetic"),
        palette_tags=("coral",),
        dominant_color="coral",
        provider_attribution=(("author", "synthetic-author"),),
    )


def _catalog_with_external_texture_gap(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    shutil.copytree(ASSET_ROOT, root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"] = [
        item for item in manifest["assets"] if item["role"] != "serum_texture"
    ]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def _stream_until_node(graph, run_input, config, node_name: str) -> None:
    stream = graph.stream(run_input, config=config)
    try:
        for event in stream:
            if node_name in event:
                return
    finally:
        stream.close()
    raise AssertionError(f"workflow never reached {node_name}")


def test_external_gap_resume_after_download_approves_without_duplicate_work(
    monkeypatch,
    tmp_path,
):
    fixture = load_golden("zone_diagnosis")
    catalog_root = _catalog_with_external_texture_gap(tmp_path)
    pexels = _FakeProvider("pexels")
    candidate = _external_candidate()
    unsplash = _FakeProvider(
        "unsplash",
        [candidate],
        {candidate.provider_asset_id: _external_png()},
    )
    render_counter = {}
    plan, _storyboard, database, _publish_root = _install_real_workflow_harness(
        monkeypatch,
        fixture,
        tmp_path,
        pexels=pexels,
        unsplash=unsplash,
        catalog_root=catalog_root,
        render_counter=render_counter,
    )
    connection = sqlite3.connect(tmp_path / "checkpoint.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    graph = graph_module.create_graph(checkpointer=checkpointer)
    thread_id = "same-thread-after-provider-download"
    config = {"configurable": {"thread_id": thread_id}}
    registry = RunRegistry(tmp_path / "runs.sqlite")
    registry.create_run(thread_id, fixture["package"]["focus_keyword"])

    _stream_until_node(
        graph,
        _initial_state(fixture),
        config,
        "carousel_qa",
    )
    registry.update_run(thread_id, status="interrupted", last_node="asset_resolver")
    state_after_download = graph.get_state(config)
    pending_before_resume = state_after_download.values["asset_manifest"]
    assert sum(len(provider.search_calls) for provider in (pexels, unsplash)) == 2
    assert len(unsplash.download_calls) == 1
    assert any(item.status == "pending_external" for item in pending_before_resume.items)

    resumed_graph = graph_module.create_graph(checkpointer=checkpointer)
    resumed = resumed_graph.invoke(None, config=config)
    review_payload = _interrupt_payload(resumed)
    assert len(unsplash.download_calls) == 1
    assert render_counter["calls"] == 1
    assert len(review_payload["pending_assets"]) == 1

    second_review = resumed_graph.invoke(
        Command(resume=_approve_pending_payload(review_payload)),
        config=config,
    )
    assert _interrupt_payload(second_review)["pending_assets"] == []
    completed = resumed_graph.invoke(
        Command(resume={"approved": True}), config=config
    )
    registry.update_run(thread_id, status="completed", last_node="content_writer")
    snapshot = resumed_graph.get_state(config)
    artifacts = export_publish_package(snapshot)

    external_item = next(
        item
        for item in snapshot.values["asset_manifest"].items
        if item.provider == "unsplash"
    )
    active_sha256 = hashlib.sha256(Path(external_item.path).read_bytes()).hexdigest()
    render_sha256 = snapshot.values["render_manifest"].source_asset_sha256[
        external_item.slot_id
    ]
    assert external_item.status == "active"
    assert external_item.review_status == "approved"
    assert active_sha256 == external_item.sha256 == render_sha256
    assert completed["data_writed"] is True
    assert artifacts.artifact_generation == 1
    assert len(unsplash.download_calls) == 1
    assert render_counter["calls"] == 1
    assert len(registry.list_recent()) == 1
    assert registry.get_by_thread_id(thread_id).status == "completed"
    assert len(plan.required_assets) == len(snapshot.values["asset_manifest"].items)
    registry.close()
    connection.close()
    database.close()


def test_resume_after_render_reuses_output_and_one_registry_entry(
    monkeypatch,
    tmp_path,
):
    fixture = load_golden("ordered_routine")
    pexels = _FakeProvider("pexels")
    unsplash = _FakeProvider("unsplash")
    render_counter = {}
    plan, _storyboard, database, publish_root = _install_real_workflow_harness(
        monkeypatch,
        fixture,
        tmp_path,
        pexels=pexels,
        unsplash=unsplash,
        render_counter=render_counter,
    )
    connection = sqlite3.connect(tmp_path / "checkpoint.sqlite", check_same_thread=False)
    checkpointer = SqliteSaver(connection)
    checkpointer.setup()
    graph = graph_module.create_graph(checkpointer=checkpointer)
    thread_id = "same-thread-after-render"
    config = {"configurable": {"thread_id": thread_id}}
    registry = RunRegistry(tmp_path / "runs.sqlite")
    registry.create_run(thread_id, fixture["package"]["focus_keyword"])

    _stream_until_node(
        graph,
        _initial_state(fixture),
        config,
        "render_qa",
    )
    registry.update_run(
        thread_id,
        status="interrupted",
        last_node="editorial_carousel_renderer",
    )
    first_manifest = graph.get_state(config).values["render_manifest"]
    first_paths = [page.path for page in first_manifest.pages]
    first_hashes = [page.sha256 for page in first_manifest.pages]
    assert render_counter["calls"] == 1

    resumed_graph = graph_module.create_graph(checkpointer=checkpointer)
    interrupted = resumed_graph.invoke(None, config=config)
    _interrupt_payload(interrupted)
    assert render_counter["calls"] == 1
    completed = resumed_graph.invoke(
        Command(resume={"approved": True}), config=config
    )
    registry.update_run(thread_id, status="completed", last_node="content_writer")
    snapshot = resumed_graph.get_state(config)
    artifacts = export_publish_package(snapshot)

    assert completed["data_writed"] is True
    assert [page.path for page in snapshot.values["render_manifest"].pages] == first_paths
    assert [page.sha256 for page in snapshot.values["render_manifest"].pages] == first_hashes
    assert render_counter["calls"] == 1
    assert artifacts.artifact_generation == 1
    assert len(list(publish_root.glob("*/images/01-cover.png"))) == 1
    assert len(list(publish_root.glob("*/.publish-artifacts.version"))) == 1
    assert len(registry.list_recent()) == 1
    assert registry.get_by_thread_id(thread_id).status == "completed"
    assert len(first_paths) == len(plan.frame_plan)
    assert pexels.search_calls == []
    assert unsplash.search_calls == []
    registry.close()
    connection.close()
    database.close()
