from pathlib import Path

import pytest

from src.domain import get_domain_profile
from src.prompts.composer import TASK_FILES


@pytest.mark.parametrize("domain", ["beauty", "wellness", "healthy_lifestyle"])
def test_all_task_files_compose_for_each_domain_profile(domain):
    from src.prompts.composer import compose_prompt

    profile = get_domain_profile(domain)
    composed_count = 0

    for task in TASK_FILES:
        prompt = compose_prompt(task, profile)
        assert prompt
        assert profile.version in prompt
        assert f'"domain": "{profile.domain}"' in prompt
        composed_count += 1

    assert composed_count == 15


def test_task_profile_matrix_has_45_successful_compositions():
    from src.prompts.composer import compose_prompt

    success_count = 0

    for domain in ("beauty", "wellness", "healthy_lifestyle"):
        profile = get_domain_profile(domain)
        for task in TASK_FILES:
            assert compose_prompt(task, profile)
            success_count += 1

    assert success_count == 45


def test_compose_prompt_includes_task_safety_and_profile_payload_for_wellness():
    from src.prompts.composer import compose_prompt

    profile = get_domain_profile("wellness")

    prompt = compose_prompt("draft_writer", profile)

    assert "Draft Writer" in prompt
    assert "睡眠、压力、作息与恢复" in prompt
    assert "疾病诊断" in prompt
    assert f'"version": "{profile.version}"' in prompt
    assert f'"domain": "{profile.domain}"' in prompt


def test_healthy_lifestyle_prompt_omits_skincare_identity():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("trend_scout", get_domain_profile("healthy_lifestyle"))

    assert "护肤趋势侦察兵" not in prompt
    assert "只讨论日常护肤" not in prompt


def test_compose_prompt_rejects_unknown_task():
    from src.prompts.composer import compose_prompt

    with pytest.raises(ValueError, match="Unknown prompt task: missing_task"):
        compose_prompt("missing_task", get_domain_profile("beauty"))


def test_compose_prompt_surfaces_missing_fragment_path(monkeypatch, tmp_path):
    import src.prompts.composer as composer

    base_dir = tmp_path / "base"
    fragment_dir = tmp_path / "fragments"
    base_dir.mkdir()
    fragment_dir.mkdir()

    (base_dir / "draft_writer.txt").write_text("Draft Writer", encoding="utf-8")

    monkeypatch.setattr(composer, "BASE_DIR", base_dir)
    monkeypatch.setattr(composer, "FRAGMENTS_DIR", fragment_dir)

    with pytest.raises(FileNotFoundError) as excinfo:
        composer.compose_prompt("draft_writer", get_domain_profile("beauty"))

    assert str(fragment_dir / "safety_common.txt") in str(excinfo.value)


def test_compose_prompt_surfaces_missing_base_path(monkeypatch, tmp_path):
    import src.prompts.composer as composer

    base_dir = tmp_path / "base"
    fragment_dir = tmp_path / "fragments"
    base_dir.mkdir()
    fragment_dir.mkdir()

    (fragment_dir / "safety_common.txt").write_text("safety", encoding="utf-8")
    (fragment_dir / "beauty.txt").write_text("beauty", encoding="utf-8")

    monkeypatch.setattr(composer, "BASE_DIR", base_dir)
    monkeypatch.setattr(composer, "FRAGMENTS_DIR", fragment_dir)

    with pytest.raises(FileNotFoundError) as excinfo:
        composer.compose_prompt("draft_writer", get_domain_profile("beauty"))

    assert str(base_dir / "draft_writer.txt") in str(excinfo.value)


def test_prompts_package_keeps_only_legacy_loader_exports():
    import src.prompts as prompts

    assert hasattr(prompts, "all_prompts")
    assert not hasattr(prompts, "compose_prompt")
    assert not hasattr(prompts, "compose_prompt_for_state")
    assert not hasattr(prompts, "serialize_prompt_value")
    assert not hasattr(prompts, "__all__")


def test_compose_prompt_for_state_warns_and_falls_back_for_legacy_missing_domain_context():
    from src.prompts.composer import compose_prompt_for_state

    with pytest.warns(UserWarning, match="legacy checkpoint"):
        prompt = compose_prompt_for_state("trend_scout", {})

    assert '"domain": "beauty"' in prompt
    assert '"version": "beauty-v1"' in prompt


def test_compose_prompt_for_state_rejects_malformed_present_domain_context():
    from src.prompts.composer import compose_prompt_for_state

    with pytest.raises(ValueError, match="requires state.domain_context with both domain and profile_version"):
        compose_prompt_for_state("trend_scout", {"domain_context": {"domain": "wellness"}})


def test_compose_prompt_for_state_rejects_wrong_profile_version_in_modern_state():
    from src.prompts.composer import compose_prompt_for_state

    with pytest.raises(ValueError, match="Unsupported profile version"):
        compose_prompt_for_state(
            "trend_scout",
            {"domain_context": {"domain": "wellness", "profile_version": "beauty-v1"}},
        )


def test_lazy_prompt_mapping_defers_file_reads_and_preserves_legacy_keys(monkeypatch, tmp_path):
    import src.prompts as prompts

    (tmp_path / "node_a_example.txt").write_text("example prompt", encoding="utf-8")
    read_calls = []
    original_read_text = prompts.Path.read_text

    def tracking_read_text(path_self, *args, **kwargs):
        read_calls.append(path_self.name)
        return original_read_text(path_self, *args, **kwargs)

    monkeypatch.setattr(prompts.Path, "read_text", tracking_read_text, raising=True)

    mapping = prompts._LazyPromptMapping(tmp_path)
    assert len(mapping) == 1
    assert list(mapping) == ["NODE_A_EXAMPLE"]
    assert read_calls == []

    assert mapping["NODE_A_EXAMPLE"] == "example prompt"
    assert read_calls == ["node_a_example.txt"]

    assert mapping["NODE_A_EXAMPLE"] == "example prompt"
    assert read_calls == ["node_a_example.txt"]


@pytest.mark.parametrize(
    ("node_path", "import_line"),
    [
        ("src/nodes/node_a_trend_scout.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_b_angle_strategist.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_b_novelty_guard.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_c_virality_scorer.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_d_outline_architect.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_e_draft_writer.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_f_title_lab.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_g_title_ranker.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_h_r1_reflector.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_i_r2_compliance.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_j_decision_engine.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_k_hashtag_seo.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_o_assembler.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
        ("src/nodes/node_o_storyboards_generator.py", "from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value"),
    ],
)
def test_migrated_active_nodes_use_direct_composer_imports(node_path, import_line):
    source = Path(node_path).read_text(encoding="utf-8")

    assert "all_prompts[" not in source
    assert "from src.prompts import compose_prompt_for_state" not in source
    assert "from src.prompts import serialize_prompt_value" not in source
    assert import_line in source
