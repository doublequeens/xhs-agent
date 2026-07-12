import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import get_args

import pytest

from src.domain import DomainName
from src.rendering.text_cards import output_paths


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
) -> dict:
    root = publish_root or tmp_path / "outputs" / "publish"
    image_dir = root / f"20260713-{domain}-{subdomain}-{title}" / "images"
    image_dir.mkdir(parents=True)
    paths = output_paths(image_dir)
    for path in paths:
        path.write_bytes(b"\x89PNG\r\n\x1a\nlocally rendered png")
    return {
        "title": title,
        "content": "body",
        "cover_copy": "先看这张",
        "storyboards": [],
        "domain": domain,
        "subdomain": subdomain,
        "profile_version": profile_version,
        "rendered_image_paths": [str(path) for path in paths],
    }


def test_export_publish_package_preserves_rendered_cards_without_image_prompt(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    package = valid_publish_package_with_rendered_images(tmp_path)
    monkeypatch.chdir(tmp_path)

    main.export_publish_package(package)

    exported = sorted((tmp_path / "outputs" / "publish").glob("*/images/*.png"))[0]
    assert exported.name == "01-cover.png"
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
    package["content_contract"] = {
        "first_screen_promise": "通勤前 3 分钟底妆不搓泥",
        "screenshot_asset": "防晒成膜计时截图",
    }

    main.export_publish_package(package)

    audit_path = next(tmp_path.glob("outputs/publish/*/*.json"))
    audit = __import__("json").loads(audit_path.read_text(encoding="utf-8"))
    assert audit["content_contract"] == package["content_contract"]
    assert audit["rendered_image_paths"] == [
        f"images/{path.name}" for path in output_paths(Path("images"))
    ]


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

    with pytest.raises(ValueError, match="inside outputs/publish"):
        main.export_publish_package(package)


def test_export_publish_package_rejects_non_png_or_wrong_sequence(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    monkeypatch.chdir(tmp_path)

    package = valid_publish_package_with_rendered_images(tmp_path)
    non_png = Path(package["rendered_image_paths"][0]).with_suffix(".jpg")
    non_png.write_bytes(b"wrong extension")
    package["rendered_image_paths"][0] = str(non_png)

    with pytest.raises(ValueError, match="PNG"):
        main.export_publish_package(package)

    package = valid_publish_package_with_rendered_images(tmp_path, title="伪造图片")
    Path(package["rendered_image_paths"][0]).write_bytes(b"not a PNG")

    with pytest.raises(ValueError, match="PNG"):
        main.export_publish_package(package)

    package = valid_publish_package_with_rendered_images(tmp_path, title="另一份指南")
    package["rendered_image_paths"].reverse()

    with pytest.raises(ValueError, match="required sequence"):
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


def test_main_rejects_subdomain_without_domain(monkeypatch):
    main = _load_main(monkeypatch)

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--subdomain", "daily_habits"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

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


def test_main_initial_state_defaults_to_interactive(monkeypatch):
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

    def fake_load_run_state(graph, config, initial_state):
        captured["initial_state"] = initial_state
        return SimpleNamespace(values={}, next=()), initial_state

    monkeypatch.setattr(main, "load_run_state", fake_load_run_state)
    monkeypatch.setattr("sys.argv", ["main.py", "--focus_keyword", "改善睡眠"])

    main.main()

    assert captured["initial_state"]["interactive"] is True
    assert (
        captured["initial_state"]["creator_profile"].profile_id
        == "commuting_beauty_women_v1"
    )
