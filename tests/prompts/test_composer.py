from pathlib import Path

import pytest

from src.domain import get_domain_profile


ACTIVE_TASKS = (
    "trend_scout",
    "angle_strategist",
    "novelty_guard",
    "virality_scorer",
    "outline_architect",
    "draft_writer",
    "title_lab",
    "title_ranker",
    "r1_reflector",
    "r2_compliance",
    "decision_engine",
    "hashtag_seo",
    "assembler",
    "storyboards_generator",
)


@pytest.mark.parametrize("domain", ["beauty", "wellness", "healthy_lifestyle"])
def test_all_active_tasks_compose_for_each_domain_profile(domain):
    from src.prompts.composer import compose_prompt

    profile = get_domain_profile(domain)

    for task in ACTIVE_TASKS:
        prompt = compose_prompt(task, profile)
        assert prompt
        assert profile.version in prompt
        assert f'"domain": "{profile.domain}"' in prompt


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
    from src.prompts import composer

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
    from src.prompts import composer

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


@pytest.mark.parametrize(
    "node_path",
    [
        "src/nodes/node_a_trend_scout.py",
        "src/nodes/node_b_angle_strategist.py",
        "src/nodes/node_b_novelty_guard.py",
        "src/nodes/node_c_virality_scorer.py",
        "src/nodes/node_d_outline_architect.py",
        "src/nodes/node_e_draft_writer.py",
        "src/nodes/node_f_title_lab.py",
        "src/nodes/node_g_title_ranker.py",
        "src/nodes/node_h_r1_reflector.py",
        "src/nodes/node_i_r2_compliance.py",
        "src/nodes/node_j_decision_engine.py",
        "src/nodes/node_k_hashtag_seo.py",
        "src/nodes/node_o_assembler.py",
        "src/nodes/node_o_storyboards_generator.py",
    ],
)
def test_migrated_active_nodes_do_not_index_all_prompts(node_path):
    source = Path(node_path).read_text(encoding="utf-8")

    assert "all_prompts[" not in source
