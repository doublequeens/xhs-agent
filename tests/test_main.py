import importlib
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import get_args

import pytest
from PIL import Image

from src.domain import DomainName
from src.run_registry import RunRegistry


def _load_main(monkeypatch):
    models = ModuleType("src.models")
    models.set_default_provider = lambda _provider: None
    graph = ModuleType("src.graph")
    graph.create_graph = lambda: object()
    memory_memory_manager = ModuleType("memory.memory_manager")

    class FakeMemoryManager:
        def __init__(self, *args, **kwargs):
            pass

        def init_db(self, *args, **kwargs):
            pass

    memory_memory_manager.XHSMemoryManager = FakeMemoryManager

    monkeypatch.setitem(sys.modules, "src.models", models)
    monkeypatch.setitem(sys.modules, "src.graph", graph)
    monkeypatch.setitem(sys.modules, "memory.memory_manager", memory_memory_manager)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


@pytest.fixture(autouse=True)
def renderer_publish_root(monkeypatch, tmp_path):
    from src.nodes import node_p_text_card_renderer

    monkeypatch.setattr(
        node_p_text_card_renderer,
        "PUBLISH_ROOT",
        tmp_path / "outputs" / "publish",
    )


def test_build_thread_id_preserves_explicit_resume_id(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.build_thread_id("existing-conversation") == "existing-conversation"


def test_build_thread_id_generates_fresh_ids(monkeypatch):
    main = _load_main(monkeypatch)
    now = datetime(2026, 7, 3, 10, 30, tzinfo=timezone.utc)

    first = main.build_thread_id(None, now=now)
    second = main.build_thread_id(None, now=now)

    assert first.startswith("xhs_conversation_20260703T103000_")
    assert second.startswith("xhs_conversation_20260703T103000_")
    assert first != second


def test_supported_domains_come_from_domain_name(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.SUPPORTED_DOMAINS == get_args(DomainName)


def test_collect_human_review_returns_explicit_pending_asset_decisions(monkeypatch):
    main = _load_main(monkeypatch)
    answers = iter(["approved", "rejected", "yes"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    result = main.collect_human_review(
        {
            "message": "review",
            "publish_package": {"title": "carousel"},
            "pending_assets": [
                {
                    "decision_id": "pending-1",
                    "provider": "pexels",
                    "decision_binding": {"pending_id": "pending-1", "sha256": "a" * 64},
                },
                {
                    "decision_id": "pending-2",
                    "provider": "unsplash",
                    "decision_binding": {"pending_id": "pending-2", "sha256": "b" * 64},
                },
            ],
        }
    )

    assert result["approved"] is True
    assert result["asset_decisions"] == {
        "pending-1": {
            "decision": "approved",
            "binding": {"pending_id": "pending-1", "sha256": "a" * 64},
            "safety_decisions": {},
        },
        "pending-2": {
            "decision": "rejected",
            "binding": {"pending_id": "pending-2", "sha256": "b" * 64},
            "safety_decisions": {},
        },
    }


def test_collect_human_review_records_each_unknown_safety_decision(monkeypatch):
    main = _load_main(monkeypatch)
    answers = iter(["approved", "no", "yes", "yes"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    binding = {
        "pending_id": "pending-1",
        "slot_id": "slot-1",
        "provider": "pexels",
        "provider_asset_id": "42",
        "requirement_fingerprint": "a" * 64,
        "sha256": "b" * 64,
        "metadata_path": "/tmp/pending-1.json",
    }

    result = main.collect_human_review(
        {
            "message": "review",
            "publish_package": {"title": "carousel"},
            "pending_assets": [
                {
                    "decision_id": "pending-1",
                    "decision_binding": binding,
                    "provider": "pexels",
                    "provider_asset_id": "42",
                    "unresolved_safety_checks": [
                        "has_logo",
                        "allowed_for_publishing",
                    ],
                }
            ],
        }
    )

    assert result["asset_decisions"]["pending-1"] == {
        "decision": "approved",
        "binding": binding,
        "safety_decisions": {
            "has_logo": False,
            "allowed_for_publishing": True,
        },
    }


def test_cli_review_without_pending_assets_routes_directly_to_final_guard(
    monkeypatch,
):
    main = _load_main(monkeypatch)
    review_module = importlib.import_module("src.nodes.node_q_human_review")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "yes")
    resume_payload = main.collect_human_review(
        {
            "message": "review",
            "publish_package": {"title": "carousel"},
            "pending_assets": [],
        }
    )
    monkeypatch.setattr(review_module, "interrupt", lambda _payload: resume_payload)

    result = review_module.human_review_node(
        {
            "publish_package": {"title": "carousel"},
            "asset_manifest": {"items": []},
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    assert "asset_decisions" not in resume_payload
    assert result["review_status"] == "approved"
    assert review_module.route_after_human_review(result) == "final_policy_guard"


def test_cli_review_routes_after_pending_then_allows_second_final_approval(
    monkeypatch,
):
    main = _load_main(monkeypatch)
    review_module = importlib.import_module("src.nodes.node_q_human_review")
    first_answers = iter(["approved", "yes"])
    monkeypatch.setattr(
        "builtins.input", lambda _prompt="": next(first_answers)
    )
    first_resume = main.collect_human_review(
        {
            "message": "review",
            "publish_package": {"title": "carousel"},
            "pending_assets": [
                {"decision_id": "pending-1", "provider": "pexels"}
            ],
        }
    )
    active_manifest = {"items": [{"slot_id": "slot-1", "status": "active"}]}
    monkeypatch.setattr(review_module, "interrupt", lambda _payload: first_resume)
    monkeypatch.setattr(
        review_module,
        "_apply_asset_decisions",
        lambda *_args: (active_manifest, "render_qa"),
    )
    first_result = review_module.human_review_node(
        {
            "publish_package": {"title": "carousel"},
            "asset_manifest": {
                "items": [
                    {
                        "status": "pending_external",
                        "pending_id": "pending-1",
                    }
                ]
            },
            "review_round": 0,
            "final_policy_issues": [],
        }
    )

    assert review_module.route_after_human_review(first_result) == "render_qa"

    monkeypatch.setattr("builtins.input", lambda _prompt="": "yes")
    second_resume = main.collect_human_review(
        {
            "message": "review",
            "publish_package": {"title": "carousel"},
            "pending_assets": [],
        }
    )
    monkeypatch.setattr(review_module, "interrupt", lambda _payload: second_resume)
    second_result = review_module.human_review_node(
        {
            **first_result,
            "asset_manifest": active_manifest,
            "review_round": first_result["review_round"],
        }
    )

    assert "asset_decisions" not in second_resume
    assert second_result["review_status"] == "approved"
    assert review_module.route_after_human_review(second_result) == "final_policy_guard"


def test_fresh_thread_keeps_new_routing_initial_state(monkeypatch):
    main = _load_main(monkeypatch)
    old_thread_id = "xhs_conversation_database_20260517_01"
    old_state = SimpleNamespace(values={"domain": "beauty"}, next=("trend_scout",))
    empty_state = SimpleNamespace(values={}, next=())

    class FakeGraph:
        def get_state(self, config):
            if config["configurable"]["thread_id"] == old_thread_id:
                return old_state
            return empty_state

    initial_state = {
        "domain": "wellness",
        "focus_keyword": "改善睡眠",
        "domain_context": None,
        "content_policy": None,
    }
    config = main.build_run_config(None)

    current_state, run_input = main.load_run_state(
        FakeGraph(), config, initial_state
    )

    assert config["configurable"]["thread_id"] != old_thread_id
    assert current_state is empty_state
    assert run_input is initial_state


def test_explicit_thread_id_resumes_existing_checkpoint(monkeypatch):
    main = _load_main(monkeypatch)
    existing_state = SimpleNamespace(
        values={
            "domain": "beauty",
            "domain_context": {
                "domain": "beauty",
                "subdomain": "skincare",
                "classification_source": "explicit",
                "classification_confidence": 1,
                "profile_version": "beauty-v1",
                "risk_level": "low",
            },
        },
        next=("trend_scout",),
    )

    class FakeGraph:
        def get_state(self, config):
            assert config["configurable"]["thread_id"] == "existing-conversation"
            return existing_state

    current_state, run_input = main.load_run_state(
        FakeGraph(),
        main.build_run_config("existing-conversation"),
        {"domain": "wellness"},
    )

    assert current_state is existing_state
    assert run_input is None


def test_hydrate_legacy_domain_state_returns_default_beauty_context_once(monkeypatch):
    main = _load_main(monkeypatch)

    with pytest.warns(UserWarning, match="legacy domain checkpoint"):
        updates = main.hydrate_legacy_domain_state({"domain": "beauty"})

    assert updates["domain_context"].domain == "beauty"
    assert updates["domain_context"].subdomain == "skincare"
    assert updates["domain_context"].classification_source == "default"
    assert updates["domain_context"].profile_version == "beauty-v1"
    assert updates["domain_context"].risk_level == "low"
    assert updates["content_policy"].risk_level == "low"
    assert updates["content_policy"].require_evidence_brief is False


def test_hydrate_legacy_domain_state_returns_no_update_for_modern_or_malformed_state(monkeypatch):
    main = _load_main(monkeypatch)

    modern_updates = main.hydrate_legacy_domain_state(
        {
            "domain_context": {
                "domain": "wellness",
                "subdomain": "sleep",
                "classification_source": "explicit",
                "classification_confidence": 1,
                "profile_version": "wellness-v1",
                "risk_level": "medium",
            }
        }
    )
    malformed_updates = main.hydrate_legacy_domain_state(
        {"domain_context": {"domain": "wellness"}}
    )

    assert modern_updates == {}
    assert malformed_updates == {}


def test_load_run_state_hydrates_legacy_checkpoint_via_graph_update(monkeypatch):
    main = _load_main(monkeypatch)
    config = main.build_run_config("existing-conversation")

    legacy_state = SimpleNamespace(values={"domain": "beauty"}, next=("trend_scout",))
    hydrated_values = {
        "domain": "beauty",
        "domain_context": {
            "domain": "beauty",
            "subdomain": "skincare",
            "classification_source": "default",
            "classification_confidence": 1,
            "profile_version": "beauty-v1",
            "risk_level": "low",
        },
        "content_policy": {
            "risk_level": "low",
            "require_evidence_brief": False,
            "require_human_review": True,
        },
    }
    hydrated_state = SimpleNamespace(values=hydrated_values, next=("trend_scout",))
    calls = {"get_state": 0, "update_state": []}

    class FakeGraph:
        def get_state(self, passed_config):
            calls["get_state"] += 1
            if calls["get_state"] == 1:
                return legacy_state
            return hydrated_state

        def update_state(self, passed_config, updates):
            calls["update_state"].append((passed_config, updates))

    with pytest.warns(UserWarning, match="legacy domain checkpoint"):
        current_state, run_input = main.load_run_state(
            FakeGraph(),
            config,
            {"domain": "wellness"},
        )

    assert run_input is None
    assert current_state is hydrated_state
    assert calls["get_state"] == 2
    assert len(calls["update_state"]) == 1
    passed_config, updates = calls["update_state"][0]
    assert passed_config == config
    assert updates["domain_context"].profile_version == "beauty-v1"
    assert updates["content_policy"].risk_level == "low"


def test_load_run_state_hydrates_only_explicit_old_editorial_checkpoint(monkeypatch):
    main = _load_main(monkeypatch)
    config = main.build_run_config("legacy-editorial")
    old_contract = {
        "audience": "通勤女性",
        "trigger_situation": "早上",
        "decision_problem": "怎么护肤",
        "first_screen_promise": "三步完成",
        "screenshot_asset": "清单",
        "proof_asset": "对照",
        "visual_mode": "text_card",
    }
    old_values = {
        "domain_context": {"domain": "beauty"},
        "publish_package": {
            "content_contract": old_contract,
            "storyboards": [
                {"frame_id": "frame-1", "template": "cover_statement"}
            ],
        },
    }
    old_state = SimpleNamespace(values=old_values, next=("carousel_qa",))
    calls = []

    class FakeGraph:
        def get_state(self, _config):
            if not calls:
                return old_state
            return SimpleNamespace(
                values={**old_values, **calls[-1]}, next=("carousel_qa",)
            )

        def update_state(self, _config, updates, *, as_node=None):
            assert as_node == "asset_resolver"
            calls.append(updates)

    current_state, run_input = main.load_run_state(
        FakeGraph(), config, {"visual_plan": None}
    )

    assert run_input is None
    assert current_state.next == ("carousel_qa",)
    assert calls[0]["legacy_editorial_checkpoint"] is True
    assert calls[0]["editorial_workflow_version"] == "legacy_v1"
    assert calls[0]["visual_plan"] is None
    assert calls[0]["asset_manifest"] is None
    assert calls[0]["render_manifest"] is None
    assert calls[0]["publish_package"]["content_contract"]["content_job"] == "save_and_check"


def test_load_run_state_preserves_modern_checkpoint_without_resolving_again(
    monkeypatch,
):
    main = _load_main(monkeypatch)
    state = SimpleNamespace(
        values={
            "domain_context": {"domain": "beauty"},
            "visual_plan": {"frame_plan": []},
            "asset_manifest": {"items": [{"status": "pending_external"}]},
            "render_manifest": None,
        },
        next=("carousel_qa",),
    )

    class FakeGraph:
        def get_state(self, _config):
            return state

        def update_state(self, _config, _updates):
            raise AssertionError("modern checkpoint must not be rewritten")

    monkeypatch.setattr(
        "src.asset_resolver.resolver.resolve_assets",
        lambda *_args: pytest.fail("resume must not repeat external resolution"),
    )

    current_state, run_input = main.load_run_state(
        FakeGraph(), main.build_run_config("modern"), {}
    )

    assert current_state is state
    assert current_state.next == ("carousel_qa",)
    assert run_input is None


@pytest.mark.parametrize("storyboards", [[], [{}], [{"frame_id": "frame-1"}]])
def test_partial_or_corrupt_modern_checkpoint_is_not_hydrated_as_legacy(
    monkeypatch,
    storyboards,
):
    main = _load_main(monkeypatch)
    state = SimpleNamespace(
        values={
            "domain_context": {},
            "publish_package": {"storyboards": storyboards},
        },
        next=("carousel_qa",),
    )

    class FakeGraph:
        def get_state(self, _config):
            return state

        def update_state(self, _config, _updates):
            raise AssertionError("modern partial state must not be legacy hydrated")

    current_state, run_input = main.load_run_state(
        FakeGraph(), {"configurable": {"thread_id": "partial"}}, {}
    )

    assert current_state is state
    assert run_input is None


def test_modern_checkpoint_clears_stale_legacy_marker(monkeypatch):
    main = _load_main(monkeypatch)
    values = {
        "domain_context": {},
        "legacy_editorial_checkpoint": True,
        "publish_package": {
            "storyboards": [
                {
                    "frame_id": "frame-1",
                    "role": "cover",
                    "layout": "editorial_cover",
                    "content_blocks": [],
                    "visual_slots": [],
                }
            ]
        },
    }
    calls = []

    class FakeGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={**values, **(calls[-1] if calls else {})},
                next=("carousel_qa",),
            )

        def update_state(self, _config, updates):
            calls.append(updates)

    current_state, _ = main.load_run_state(
        FakeGraph(), {"configurable": {"thread_id": "modern"}}, {}
    )

    assert calls == [
        {
            "legacy_editorial_checkpoint": False,
            "editorial_workflow_version": "modern_v2",
        }
    ]
    assert current_state.values["legacy_editorial_checkpoint"] is False


def test_explicit_modern_v2_old_shape_cannot_be_downgraded_by_marker(
    monkeypatch,
):
    main = _load_main(monkeypatch)
    values = {
        "domain_context": {},
        "editorial_workflow_version": "modern_v2",
        "legacy_editorial_checkpoint": True,
        "publish_package": {
            "storyboards": [
                {"frame_id": "frame-1", "template": "cover_statement"}
            ]
        },
    }
    calls = []

    class FakeGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={**values, **(calls[-1] if calls else {})},
                next=("carousel_qa",),
            )

        def update_state(self, _config, updates, **_kwargs):
            calls.append(updates)

    current_state, _ = main.load_run_state(
        FakeGraph(), {"configurable": {"thread_id": "modern-old-shape"}}, {}
    )

    assert calls == [{"legacy_editorial_checkpoint": False}]
    assert current_state.values["editorial_workflow_version"] == "modern_v2"
    assert current_state.values["legacy_editorial_checkpoint"] is False
    assert "visual_plan" not in current_state.values


def test_unknown_editorial_version_with_legacy_marker_fails_closed(monkeypatch):
    main = _load_main(monkeypatch)
    state = SimpleNamespace(
        values={
            "domain_context": {},
            "editorial_workflow_version": "attacker_v9",
            "legacy_editorial_checkpoint": True,
            "publish_package": {
                "storyboards": [
                    {"frame_id": "frame-1", "template": "cover_statement"}
                ]
            },
        },
        next=("carousel_qa",),
    )

    class FakeGraph:
        def get_state(self, _config):
            return state

        def update_state(self, *_args, **_kwargs):
            raise AssertionError("unknown versions must not be rewritten")

    with pytest.raises(ValueError, match="unsupported editorial workflow version"):
        main.load_run_state(
            FakeGraph(), {"configurable": {"thread_id": "unknown-version"}}, {}
        )


def test_load_run_state_does_not_replace_present_malformed_domain_context(monkeypatch):
    main = _load_main(monkeypatch)
    malformed_state = SimpleNamespace(
        values={"domain_context": {"domain": "wellness"}},
        next=("trend_scout",),
    )
    config = main.build_run_config("existing-conversation")

    class FakeGraph:
        def get_state(self, passed_config):
            return malformed_state

        def update_state(self, passed_config, updates):
            raise AssertionError("update_state should not be called")

    current_state, run_input = main.load_run_state(
        FakeGraph(),
        config,
        {"domain": "wellness"},
    )

    assert current_state is malformed_state
    assert run_input is None


def valid_publish_package_with_rendered_images(
    tmp_path: Path,
    *,
    domain: str = "beauty",
    subdomain: str = "skincare",
    profile_version: str = "beauty-v1",
    title: str = "通勤底妆指南",
    publish_root: Path | None = None,
    frame_count: int = 5,
) -> dict:
    root = publish_root or tmp_path / "outputs" / "publish"
    image_dir = root / f"20260713-{domain}-{subdomain}-{title}" / "images"
    image_dir.mkdir(parents=True)
    layouts = [
        "editorial_cover",
        "texture_baseline",
        "front_face_zone",
        "saveable_checklist",
        "saveable_reference",
        "decision_tree",
        "three_state_diagnostic",
    ]
    frames = [
        {
            "frame_id": f"frame-{index}",
            "role": "cover" if index == 1 else f"detail-{index}",
            "layout": layouts[index - 1],
            "headline": title if index == 1 else f"第{index}页",
            "kicker": "通勤护肤",
            "content_blocks": [
                {"block_type": "text", "body": f"第{index}页正文"}
            ],
            "emphasis": [],
            "visual_slots": [],
            "footer": "按肤感微调",
        }
        for index in range(1, frame_count + 1)
    ]
    paths = [
        image_dir
        / (
            "01-cover.png"
            if index == 1
            else f"{index:02d}-{frame['role']}.png"
        )
        for index, frame in enumerate(frames, start=1)
    ]
    for path in paths:
        Image.new("RGB", (1080, 1440), (1, 2, 3)).save(path, "PNG")
    contact_sheet = image_dir / "contact-sheet.png"
    Image.new("RGB", (540, 720), (3, 2, 1)).save(contact_sheet, "PNG")
    pages = [
        {
            "frame_id": frame["frame_id"],
            "role": frame["role"],
            "layout": frame["layout"],
            "path": str(path),
            "width": 1080,
            "height": 1440,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "probe": {
                "canvas_width": 1080,
                "canvas_height": 1440,
                "safe_margin": 72,
                "text_results": [
                    {
                        "role": "headline",
                        "text": frame["headline"],
                        "visible": True,
                        "overflow": False,
                        "ink_clipped": False,
                        "layout_clipped": False,
                        "font_family": "Source Han Serif SC",
                        "font_size": 64,
                        "line_height": 78,
                        "line_count": 1,
                        "x": 100,
                        "y": 100,
                        "width": 600,
                        "height": 80,
                    }
                ],
                "asset_results": [],
                "issues": [],
            },
        }
        for frame, path in zip(frames, paths, strict=True)
    ]
    return {
        "focus_keyword": "通勤底妆",
        "focus_keyword_cli_present": True,
        "topic": "通勤底妆不搓泥",
        "topic_id": "topic-commute-base",
        "angle": "按成膜顺序判断",
        "angle_id": "angle-commute-order",
        "target_group": "通勤护肤人群",
        "core_pain": "防晒后底妆搓泥",
        "title": title,
        "content": "body",
        "cover_copy": "先看这张",
        "hashtags": ["#通勤底妆", "#护肤"],
        "storyboards": frames,
        "content_contract": {
            "audience": "通勤护肤人群",
            "trigger_situation": "早高峰上班前",
            "decision_problem": "防晒和底妆如何避免搓泥",
            "first_screen_promise": "通勤前 3 步避开防晒搓泥",
            "screenshot_asset": "防晒与底妆搭配清单",
            "proof_asset": "产品质地实拍",
            "visual_mode": "text_card",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "primary_visual_subject": "face_map",
            "proof_mode": "product_texture",
            "recommended_frame_count": frame_count,
        },
        "domain": domain,
        "subdomain": subdomain,
        "profile_version": profile_version,
        "rendered_image_paths": [str(path) for path in paths],
        "visual_plan": {
            "design_system": "beauty_editorial_v1",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "supporting_families": [],
            "frame_plan": [
                {
                    "frame_id": frame["frame_id"],
                    "role": frame["role"],
                    "layout": frame["layout"],
                    "purpose": frame["headline"],
                    "asset_roles": [],
                }
                for frame in frames
            ],
            "required_assets": [],
        },
        "asset_manifest": {
            "items": [],
            "search_report": {
                "search_triggered": False,
                "queries": [],
                "provider_reports": [],
                "selection_reasons": {},
            },
        },
        "render_manifest": {
            "pages": pages,
            "fonts": {
                "all_loaded": True,
                "computed_families": [
                    "Source Han Serif SC",
                    "Source Han Sans SC",
                    "Bodoni Moda",
                ],
            },
            "contact_sheet_path": str(contact_sheet),
            "contact_sheet_sha256": hashlib.sha256(contact_sheet.read_bytes()).hexdigest(),
            "contact_sheet_page_sha256": [page["sha256"] for page in pages],
            "source_asset_sha256": {},
        },
        "publish_authorization": {
            "workflow_completed": True,
            "review_status": "approved",
            "final_policy_issues": [],
            "carousel_qa_result": {"passed": True, "issues": []},
            "render_qa_result": {"passed": True, "issues": []},
            "focus_keyword_cli_present": True,
            "focus_keyword": "通勤底妆",
        },
        "expected_artifact_generation": 0,
    }


@pytest.mark.parametrize("frame_count", [5, 7])
def test_export_publish_package_accepts_dynamic_manifest_page_counts(
    monkeypatch, tmp_path, frame_count
):
    main = _load_main(monkeypatch)
    package = valid_publish_package_with_rendered_images(
        tmp_path, frame_count=frame_count
    )
    monkeypatch.chdir(tmp_path)

    result = main.export_publish_package(package)

    exported = sorted((tmp_path / "outputs" / "publish").glob("*/images/*.png"))[0]
    assert exported.name == "01-cover.png"
    assert len(result.rendered_image_paths) == frame_count
    assert result.publish_copy_path.is_file()
    assert result.rescue_prompt_path.is_file()
    assert not list((tmp_path / "outputs" / "publish").glob("*/Storyboard_images_generator_prompt.txt"))


def test_export_publish_package_uses_renderer_root_from_another_cwd_and_removes_legacy_prompt(
    monkeypatch,
    tmp_path,
):
    main = _load_main(monkeypatch)
    from src.nodes import node_p_text_card_renderer

    renderer_root = tmp_path / "repository" / "outputs" / "publish"
    monkeypatch.setattr(node_p_text_card_renderer, "PUBLISH_ROOT", renderer_root)
    package = valid_publish_package_with_rendered_images(
        tmp_path,
        publish_root=renderer_root,
    )
    package_dir = Path(package["rendered_image_paths"][0]).parent.parent
    legacy_prompt = package_dir / "Storyboard_images_generator_prompt.txt"
    legacy_prompt.write_text("obsolete image prompt", encoding="utf-8")
    different_cwd = tmp_path / "other-working-directory"
    different_cwd.mkdir()
    monkeypatch.chdir(different_cwd)

    main.export_publish_package(package)

    assert not legacy_prompt.exists()
    assert (package_dir / f"{package['title']}.json").is_file()


def test_export_publish_package_preserves_metadata_with_package_relative_image_paths(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    package = valid_publish_package_with_rendered_images(tmp_path)
    package["content_contract"].update(
        {
            "first_screen_promise": "通勤前 3 分钟底妆不搓泥",
            "screenshot_asset": "防晒成膜计时截图",
        }
    )

    main.export_publish_package(package)

    audit_path = next(tmp_path.glob("outputs/publish/*/*.json"))
    audit = __import__("json").loads(audit_path.read_text(encoding="utf-8"))
    assert audit["content_contract"] == package["content_contract"]
    assert audit["rendered_image_paths"] == [
        f"images/{Path(path).name}" for path in package["rendered_image_paths"]
    ]
    assert audit["content_lock"]["focus_keyword"] == package["focus_keyword"]
    assert audit["visual_plan"] == package["visual_plan"]
    assert audit["asset_manifest"] == package["asset_manifest"]
    assert [page["path"] for page in audit["render_manifest"]["pages"]] == [
        f"images/{Path(path).name}" for path in package["rendered_image_paths"]
    ]
    assert audit["render_manifest"]["contact_sheet_path"] == "images/contact-sheet.png"


def test_export_publish_package_partitions_directory_by_domain_and_subdomain(
    monkeypatch,
    tmp_path,
):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    main.export_publish_package(
        valid_publish_package_with_rendered_images(
            tmp_path,
            domain="wellness",
            subdomain="sleep",
            profile_version="wellness-v1",
            title="共同标题",
        )
    )

    output_dirs = [path.name for path in (tmp_path / "outputs" / "publish").iterdir()]
    assert len(output_dirs) == 1
    assert output_dirs[0].endswith("-wellness-sleep-共同标题")


def test_export_publish_package_rejects_paths_outside_package_images(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    package = valid_publish_package_with_rendered_images(tmp_path)
    outside_path = tmp_path / "outside.png"
    outside_path.write_bytes(b"not part of this package")
    package["rendered_image_paths"][0] = str(outside_path)
    package["render_manifest"]["pages"][0]["path"] = str(outside_path)

    with pytest.raises(ValueError, match="inside outputs/publish"):
        main.export_publish_package(package)


def test_export_publish_package_rejects_non_png_or_wrong_sequence(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    package = valid_publish_package_with_rendered_images(tmp_path)
    non_png = Path(package["rendered_image_paths"][0]).with_suffix(".jpg")
    non_png.write_bytes(b"wrong extension")
    package["rendered_image_paths"][0] = str(non_png)
    package["render_manifest"]["pages"][0]["path"] = str(non_png)

    with pytest.raises(ValueError, match="PNG"):
        main.export_publish_package(package)

    package = valid_publish_package_with_rendered_images(tmp_path, title="伪造图片")
    Path(package["rendered_image_paths"][0]).write_bytes(b"not a PNG")

    with pytest.raises(ValueError, match="PNG"):
        main.export_publish_package(package)

    package = valid_publish_package_with_rendered_images(tmp_path, title="另一份指南")
    package["rendered_image_paths"].reverse()

    with pytest.raises(ValueError, match="RenderManifest order"):
        main.export_publish_package(package)


def test_export_publish_package_rejects_unlisted_png(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    package = valid_publish_package_with_rendered_images(tmp_path)
    image_dir = Path(package["rendered_image_paths"][0]).parent
    (image_dir / "unlisted.png").write_bytes(b"\x89PNG\r\n\x1a\nextra")

    with pytest.raises(ValueError, match="unlisted PNG"):
        main.export_publish_package(package)


def test_export_publish_package_requires_valid_domain_metadata(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    publish_package = {
        "title": "睡眠改善指南",
        "content": "body",
        "cover_copy": "cover",
        "storyboards": [],
        "domain": "wellness",
    }

    with pytest.raises(ValueError, match="publish_package requires valid domain and profile_version metadata"):
        main.export_publish_package(publish_package)


def test_completed_export_injects_state_manifests_before_delegating(
    monkeypatch, tmp_path
):
    main = _load_main(monkeypatch)
    package = valid_publish_package_with_rendered_images(tmp_path)
    package.pop("publish_authorization")
    state_manifests = {
        name: package.pop(name)
        for name in ("visual_plan", "asset_manifest", "render_manifest")
    }
    captured = {}

    class CompletedGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "review_status": "approved",
                    "final_policy_issues": [],
                    "carousel_qa_result": {"passed": True, "issues": []},
                    "render_qa_result": {"passed": True, "issues": []},
                    "focus_keyword_cli_present": True,
                    "focus_keyword": "通勤底妆",
                    "publish_package": package,
                    **state_manifests,
                },
                next=(),
            )

    monkeypatch.setattr(
        main,
        "export_publish_package",
        lambda payload: captured.update(payload=payload),
    )

    assert main.export_completed_publish_package(CompletedGraph(), {}) is True
    assert all(
        captured["payload"][name] is value
        for name, value in state_manifests.items()
    )
    assert captured["payload"]["publish_authorization"] == {
        "workflow_completed": True,
        "review_status": "approved",
        "final_policy_issues": [],
        "carousel_qa_result": {"passed": True, "issues": []},
        "render_qa_result": {"passed": True, "issues": []},
        "focus_keyword_cli_present": True,
        "focus_keyword": "通勤底妆",
    }


@pytest.mark.parametrize(
    "missing_or_invalid",
    [
        "final_policy_issues",
        "carousel_qa_result",
        "render_qa_result",
        "focus_keyword_cli_present",
    ],
)
def test_completed_export_requires_explicit_publishability_state(
    monkeypatch, tmp_path, missing_or_invalid
):
    main = _load_main(monkeypatch)
    package = valid_publish_package_with_rendered_images(tmp_path)
    values = {
        "review_status": "approved",
        "final_policy_issues": [],
        "carousel_qa_result": {"passed": True, "issues": []},
        "render_qa_result": {"passed": True, "issues": []},
        "focus_keyword_cli_present": True,
        "focus_keyword": "通勤底妆",
        "publish_package": package,
        "visual_plan": package["visual_plan"],
        "asset_manifest": package["asset_manifest"],
        "render_manifest": package["render_manifest"],
    }
    values.pop(missing_or_invalid)

    class CompletedGraph:
        def get_state(self, _config):
            return SimpleNamespace(values=values, next=())

    monkeypatch.setattr(
        main,
        "export_publish_package",
        lambda _payload: pytest.fail("non-publishable state reached exporter"),
    )

    assert main.export_completed_publish_package(CompletedGraph(), {}) is False


def test_completed_checkpoint_export_retry_uses_current_artifact_generation(
    monkeypatch, tmp_path
):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)
    package = valid_publish_package_with_rendered_images(tmp_path)
    package.pop("publish_authorization")
    package.pop("expected_artifact_generation")
    values = {
        "review_status": "approved",
        "final_policy_issues": [],
        "carousel_qa_result": {"passed": True, "issues": []},
        "render_qa_result": {"passed": True, "issues": []},
        "focus_keyword_cli_present": True,
        "focus_keyword": "通勤底妆",
        "publish_package": package,
        "visual_plan": package["visual_plan"],
        "asset_manifest": package["asset_manifest"],
        "render_manifest": package["render_manifest"],
    }

    class CompletedGraph:
        def get_state(self, _config):
            return SimpleNamespace(values=values, next=())

    assert main.export_completed_publish_package(CompletedGraph(), {}) is True
    assert main.export_completed_publish_package(CompletedGraph(), {}) is True
    audit_path = next(tmp_path.glob("outputs/publish/*/*.json"))
    audit = __import__("json").loads(audit_path.read_text(encoding="utf-8"))
    assert audit["artifact_generation"] == 2


def test_main_rejects_subdomain_without_domain(monkeypatch):
    main = _load_main(monkeypatch)

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--subdomain", "daily_habits"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 2


def test_cli_persists_whether_focus_keyword_was_explicitly_present(monkeypatch):
    main = _load_main(monkeypatch)

    without_keyword = main.create_initial_state(main.parse_cli_args([]))
    with_keyword = main.create_initial_state(
        main.parse_cli_args(["--focus_keyword", "防晒搓泥"])
    )

    assert without_keyword["focus_keyword"] == ""
    assert without_keyword["focus_keyword_cli_present"] is False
    assert with_keyword["focus_keyword"] == "防晒搓泥"
    assert with_keyword["focus_keyword_cli_present"] is True


def test_cli_rejects_an_explicit_empty_focus_keyword(monkeypatch):
    main = _load_main(monkeypatch)

    with pytest.raises(SystemExit) as exc_info:
        main.parse_cli_args(["--focus_keyword", ""])

    assert exc_info.value.code == 2


def test_main_rejects_subdomain_outside_domain(monkeypatch):
    main = _load_main(monkeypatch)

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--domain", "healthy_lifestyle", "--subdomain", "skincare"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 2


def test_collect_domain_confirmation_limits_cli_choices_to_profile_scope(monkeypatch, capsys):
    main = _load_main(monkeypatch)
    inputs = iter(["beauty", "makeup_basics"])
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return next(inputs)

    monkeypatch.setattr("builtins.input", fake_input)

    selection = main.collect_domain_confirmation(
        {
            "kind": "domain_confirmation",
            "message": "确认领域",
            "context": {"domain": "beauty", "subdomain": "skincare"},
            "allowed_domains": ("beauty",),
            "allowed_subdomains": ("skincare", "makeup_basics"),
        }
    )

    assert selection == {"domain": "beauty", "subdomain": "makeup_basics"}
    assert "('beauty',)" in prompts[0]
    output = capsys.readouterr().out
    assert "skincare, makeup_basics" in output
    assert "haircare" not in output


def test_main_initial_state_defaults_to_interactive(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    captured = {}

    class FakeMemoryManager:
        def __init__(self, *args, **kwargs):
            pass

        def init_db(self, *args, **kwargs):
            pass

    class FakeGraph:
        def get_state(self, _config):
            return SimpleNamespace(values={}, next=())

        def stream(self, *_args, **_kwargs):
            return iter(())

    monkeypatch.setattr(main, "XHSMemoryManager", FakeMemoryManager)
    monkeypatch.setattr(main, "create_graph", lambda: FakeGraph())
    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", tmp_path / "agent_runs.sqlite")

    def fake_load_run_state(graph, config, initial_state):
        captured["initial_state"] = initial_state
        return SimpleNamespace(values={}, next=()), initial_state

    monkeypatch.setattr(main, "load_run_state", fake_load_run_state)
    monkeypatch.setattr("sys.argv", ["main.py", "--focus_keyword", "改善睡眠"])

    main.main()

    assert captured["initial_state"]["interactive"] is True
    assert captured["initial_state"]["visual_plan"] is None
    assert captured["initial_state"]["asset_manifest"] is None
    assert captured["initial_state"]["render_manifest"] is None
    assert (
        captured["initial_state"]["creator_profile"].profile_id
        == "commuting_beauty_women_v1"
    )


def test_parse_cli_args_makes_new_resume_and_thread_id_mutually_exclusive(monkeypatch):
    main = _load_main(monkeypatch)

    with pytest.raises(SystemExit) as exc_info:
        main.parse_cli_args(["--new", "--thread-id", "old-thread"])

    assert exc_info.value.code == 2


def test_default_selection_shows_business_summary_and_reuses_chosen_thread(monkeypatch, tmp_path, capsys):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    older = registry.create_run("thread-older", "旧关键词")
    chosen = registry.create_run("thread-newer", "通勤防晒")
    registry.update_run(chosen.thread_id, status="interrupted", title="防晒后底妆卡粉怎么办")
    args = main.parse_cli_args([])

    selection = main.select_run(registry, args, input_fn=lambda _prompt: str(chosen.run_id))

    assert selection == (chosen.thread_id, False)
    assert registry.get_by_thread_id(chosen.thread_id).status == "running"
    assert older.focus_keyword in capsys.readouterr().out


def test_default_selection_accepts_n_and_q(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    registry.create_run("thread-existing", "通勤防晒")
    args = main.parse_cli_args([])

    new_selection = main.select_run(registry, args, input_fn=lambda _prompt: "n")
    quit_selection = main.select_run(registry, args, input_fn=lambda _prompt: "q")

    assert new_selection is not None and new_selection[1] is True
    assert registry.get_by_thread_id(new_selection[0]).status == "running"
    assert quit_selection is None


def test_resume_accepts_run_id_or_full_thread_id(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("full-thread-id", "通勤防晒")
    registry.update_run(run.thread_id, status="interrupted")

    assert main.select_run(registry, main.parse_cli_args(["--resume", str(run.run_id)])) == (run.thread_id, False)
    registry.update_run(run.thread_id, status="interrupted")
    assert main.select_run(registry, main.parse_cli_args(["--resume", run.thread_id])) == (run.thread_id, False)


def test_resume_prefers_exact_numeric_thread_id_over_run_id_collision(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    unrelated = registry.create_run("thread-unrelated", "旧任务")
    numeric_thread = registry.create_run("1", "数字线程")
    registry.update_run(unrelated.thread_id, status="interrupted")
    registry.update_run(numeric_thread.thread_id, status="interrupted")

    selection = main.select_run(registry, main.parse_cli_args(["--resume", "1"]))

    assert selection == (numeric_thread.thread_id, False)
    assert registry.get_by_thread_id(numeric_thread.thread_id).status == "running"
    assert registry.get_by_thread_id(unrelated.thread_id).status == "interrupted"


def test_bare_resume_uses_interactive_recovery_list(monkeypatch, tmp_path, capsys):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("thread-resume", "通勤防晒")

    selection = main.select_run(
        registry,
        main.parse_cli_args(["--resume"]),
        input_fn=lambda _prompt: str(run.run_id),
    )

    assert selection == (run.thread_id, False)
    assert "可恢复的任务" in capsys.readouterr().out


def test_extract_run_updates_prefers_publish_package_then_first_trend(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.extract_run_updates(
        {"trends": [{"topic": "防晒后底妆卡粉"}]}, "trend_scout"
    ) == {"topic_summary": "防晒后底妆卡粉", "last_node": "trend_scout"}

    assert main.extract_run_updates(
        {
            "domain_context": {"domain": "beauty", "subdomain": "skincare"},
            "publish_package": {"title": "通勤底妆指南", "topic": "防晒后底妆卡粉"},
            "trends": [{"topic": "不应覆盖"}],
        },
        "TEXT_CARD_RENDERER",
    ) == {
        "domain": "beauty", "subdomain": "skincare", "title": "通勤底妆指南",
        "topic_summary": "防晒后底妆卡粉", "last_node": "TEXT_CARD_RENDERER",
    }


def test_backfill_legacy_run_uses_checkpoint_summary_only_when_values_exist(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")

    main.backfill_legacy_run(registry, "empty-thread", SimpleNamespace(values={}, next=("trend_scout",)))
    main.backfill_legacy_run(
        registry,
        "legacy-thread",
        SimpleNamespace(
            values={"domain": "beauty", "trends": [{"topic": "通勤防晒"}]},
            next=(),
        ),
    )

    assert registry.get_by_thread_id("empty-thread") is None
    run = registry.get_by_thread_id("legacy-thread")
    assert run is not None
    assert run.status == "running"
    assert run.domain == "beauty"
    assert run.topic_summary == "通勤防晒"


def test_runs_exits_before_memory_manager_or_graph(monkeypatch, tmp_path, capsys):
    main = _load_main(monkeypatch)
    registry_path = tmp_path / "agent_runs.sqlite"
    registry = RunRegistry(registry_path)
    registry.create_run("thread-existing", "通勤防晒")
    registry.close()
    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(main, "XHSMemoryManager", lambda *_args: pytest.fail("memory should not be constructed"))
    monkeypatch.setattr(main, "create_graph", lambda: pytest.fail("graph should not be constructed"))
    monkeypatch.setattr("sys.argv", ["main.py", "--runs"])

    main.main()

    assert "通勤防晒" in capsys.readouterr().out


def test_runs_verbose_prints_full_ids_and_limits_output_to_twenty(monkeypatch, tmp_path, capsys):
    main = _load_main(monkeypatch)
    registry_path = tmp_path / "agent_runs.sqlite"
    registry = RunRegistry(registry_path)
    thread_ids = [f"thread-{index}-{'x' * 40}" for index in range(21)]
    for thread_id in thread_ids:
        registry.create_run(thread_id, "通勤防晒")
    registry.close()
    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(main, "XHSMemoryManager", lambda *_args: pytest.fail("memory should not be constructed"))
    monkeypatch.setattr(main, "create_graph", lambda: pytest.fail("graph should not be constructed"))
    monkeypatch.setattr("sys.argv", ["main.py", "--runs", "--verbose"])

    main.main()

    output = capsys.readouterr().out
    assert output.count("ID：") == 20
    assert thread_ids[0] not in output
    assert thread_ids[-1] in output


def test_stream_syncs_last_node_and_summary_before_clean_export(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("stream-thread", "通勤防晒")

    class FakeGraph:
        def stream(self, _run_input, config):
            assert config["configurable"]["thread_id"] == run.thread_id
            yield {"title_ranker": {}}

        def get_state(self, _config):
            return SimpleNamespace(
                values={"current_node": "TITLE_RANKER", "trends": [{"topic": "防晒后底妆卡粉"}]},
                next=(),
            )

    monkeypatch.setattr(main, "export_completed_publish_package", lambda *_args: True)
    assert main.stream_graph_until_stop(
        FakeGraph(), {}, main.build_run_config(run.thread_id), registry=registry, thread_id=run.thread_id
    ) is True

    updated = registry.get_by_thread_id(run.thread_id)
    assert updated.status == "running"
    assert updated.last_node == "TITLE_RANKER"
    assert updated.topic_summary == "防晒后底妆卡粉"


def test_main_marks_timeout_interrupted_with_truncated_reason(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    path = tmp_path / "agent_runs.sqlite"
    registry = RunRegistry(path)
    run = registry.create_run("timeout-thread", "通勤防晒")
    registry.close()
    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", path)
    monkeypatch.setattr(main, "select_run", lambda *_args, **_kwargs: (run.thread_id, False))
    monkeypatch.setattr(main, "XHSMemoryManager", lambda *_args: SimpleNamespace(init_db=lambda *_: None))
    monkeypatch.setattr(main, "create_graph", lambda: SimpleNamespace(
        get_state=lambda _config: SimpleNamespace(
            values={"domain_context": {"domain": "beauty"}, "trends": []},
            next=("node",),
        )
    ))
    monkeypatch.setattr(
        main, "stream_graph_until_stop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("request timed out")),
    )
    monkeypatch.setattr("sys.argv", ["main.py"])

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 1
    check = RunRegistry(path)
    assert check.get_by_thread_id(run.thread_id).status == "interrupted"
    assert check.get_by_thread_id(run.thread_id).error_summary == "TimeoutError: request timed out"
    check.close()


def test_review_interrupt_remains_awaiting_review_when_input_stops(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("review-thread", "通勤防晒")

    class Interrupt:
        value = {"kind": "publish_review", "message": "请审核", "publish_package": {"title": "标题"}}

    class FakeGraph:
        def stream(self, *_args, **_kwargs):
            yield {"__interrupt__": [Interrupt()]}

        def get_state(self, _config):
            return SimpleNamespace(values={"review_status": None}, next=("human_review",))

    monkeypatch.setattr(
        main, "collect_interrupt_response",
        lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        main.stream_graph_until_stop(
            FakeGraph(), {}, main.build_run_config(run.thread_id), registry=registry, thread_id=run.thread_id
        )
    assert registry.get_by_thread_id(run.thread_id).status == "awaiting_review"


def test_legacy_thread_id_backfills_only_real_checkpoints(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    active = SimpleNamespace(values={"trends": [{"topic": "防晒后底妆卡粉"}]}, next=("title_ranker",))
    terminal = SimpleNamespace(values={"publish_package": {"title": "通勤底妆指南"}}, next=())
    empty = SimpleNamespace(values={}, next=())

    main.backfill_legacy_run(registry, "active-legacy", active)
    main.backfill_legacy_run(registry, "terminal-legacy", terminal)
    main.backfill_legacy_run(registry, "empty-legacy", empty)

    assert registry.get_by_thread_id("active-legacy").status == "running"
    assert registry.get_by_thread_id("active-legacy").topic_summary == "防晒后底妆卡粉"
    assert registry.get_by_thread_id("terminal-legacy").status == "running"
    assert registry.get_by_thread_id("empty-legacy") is None


def test_terminal_legacy_checkpoint_awaits_review_when_safe_export_fails(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    path = tmp_path / "agent_runs.sqlite"
    terminal_state = SimpleNamespace(
        values={
            "domain_context": {"domain": "beauty"},
            "publish_package": {"title": "通勤底妆指南"},
        },
        next=(),
    )

    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", path)
    monkeypatch.setattr(
        main,
        "create_graph",
        lambda: SimpleNamespace(get_state=lambda _config: terminal_state),
    )
    monkeypatch.setattr(main, "export_completed_publish_package", lambda *_args: False)
    monkeypatch.setattr("sys.argv", ["main.py", "--thread-id", "terminal-legacy"])

    main.main()

    registry = RunRegistry(path)
    assert registry.get_by_thread_id("terminal-legacy").status == "awaiting_review"
    registry.close()
