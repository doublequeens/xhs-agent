from pathlib import Path

import pytest

from src.domain import get_domain_profile
from src.evidence import EvidenceBrief, EvidenceItem
from src.prompts.composer import TASK_FILES


def _profile_bound_state():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    return {
        "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
        "domain_context": {
            "domain": "beauty",
            "profile_version": "beauty-v1",
        },
    }


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

    assert composed_count == len(TASK_FILES)


def test_task_profile_matrix_composes_every_task_for_every_domain():
    from src.prompts.composer import compose_prompt

    success_count = 0

    for domain in ("beauty", "wellness", "healthy_lifestyle"):
        profile = get_domain_profile(domain)
        for task in TASK_FILES:
            assert compose_prompt(task, profile)
            success_count += 1

    assert success_count == len(TASK_FILES) * len(("beauty", "wellness", "healthy_lifestyle"))


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


def test_storyboard_prompt_task_is_retired():
    from src.prompts.composer import compose_prompt

    # The storyboards_generator node and its prompt task were removed with the
    # obsolete fixed-template visual path (Task 17); composing it must fail.
    with pytest.raises(ValueError, match="Unknown prompt task: storyboards_generator"):
        compose_prompt("storyboards_generator", get_domain_profile("beauty"))


@pytest.mark.parametrize("task", ["r1_reflector", "decision_engine"])
def test_visible_text_revision_prompts_preserve_v2_structural_metadata(task):
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt(task, get_domain_profile("beauty"))

    assert '"page_archetype"' in prompt
    assert '"content_density_hint"' in prompt
    assert "page_archetype 与 content_density_hint" in prompt
    assert '"layout"' not in prompt


def test_legacy_storyboard_prompt_task_is_retired():
    from src.prompts.composer import compose_prompt

    with pytest.raises(
        ValueError,
        match="Unknown prompt task: storyboards_generator_legacy",
    ):
        compose_prompt(
            "storyboards_generator_legacy",
            get_domain_profile("beauty"),
        )


def test_virality_prompt_requires_integer_breakdown_scores():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt(
        "virality_scorer",
        get_domain_profile("healthy_lifestyle"),
    )

    assert "评分维度均为 0-10 的整数" in prompt
    assert '"click_potential": 0,' in prompt
    assert '"compliance_safety": 0,' in prompt


def test_outline_prompt_follows_narrative_beats_without_fixed_six_part_order():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("outline_architect", get_domain_profile("beauty"))

    assert "narrative_plan.beats" in prompt
    assert "主体展开（至少 3 个逻辑分点）" not in prompt
    assert "必须依次包含" not in prompt
    assert "每篇必须以互动问题收尾" not in prompt


def test_draft_prompt_allows_emoji_and_respects_none_closing_mode():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("draft_writer", get_domain_profile("beauty"))

    assert "emoji" in prompt
    assert "不得使用 emoji" not in prompt
    assert "closing_mode=none" in prompt
    assert "必须互动收尾" not in prompt


def test_angle_prompt_requires_narrative_plan_and_cross_angle_form_variety():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("angle_strategist", get_domain_profile("beauty"))

    assert '"narrative_plan"' in prompt
    assert "至少使用两种不同 narrative_form" in prompt


def test_assembler_prompt_uses_authoritative_narrative_plan_without_reclassification():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("assembler", get_domain_profile("beauty"))

    assert "narrative_plan" in prompt
    assert "storyboard_strategy" not in prompt


@pytest.mark.parametrize(
    "task",
    [
        "novelty_guard",
        "virality_scorer",
        "title_ranker",
        "decision_engine",
        "r1_reflector",
        "r2_compliance",
    ],
)
def test_selected_copy_prompts_require_exact_narrative_plan_preservation(task):
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt(task, get_domain_profile("beauty"))

    assert "narrative_plan" in prompt
    assert "逐字段原样复制" in prompt


def test_r2_prompt_blocks_visible_disclosure_and_disclaimer_copy_without_blocking_risk_guidance():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("r2_compliance", get_domain_profile("beauty"))

    assert "AI 生成" in prompt
    assert "示意图" in prompt
    assert "仅供参考" in prompt
    assert "不构成医疗建议" in prompt
    assert "页面可见" in prompt
    assert "普通事实风险条件" in prompt
    assert "停用指导" in prompt


def test_visual_director_prompt_bans_visible_labels_and_disclaimer_copy():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("visual_director", get_domain_profile("beauty"))

    assert "5–18" in prompt
    assert "one family" in prompt
    assert "embedded text" in prompt
    assert "AI disclosure" in prompt
    assert "disclaimer" in prompt
    assert "AI 生成示意图" in prompt
    assert "仅供参考" in prompt
    assert "不构成医疗建议" in prompt


def test_composer_registry_includes_page_designer_and_design_reviser_tasks():
    from src.prompts.composer import TASK_FILES

    assert TASK_FILES["page_designer"] == "page_designer.txt"
    assert TASK_FILES["design_reviser"] == "design_reviser.txt"


def test_composer_registry_includes_visual_critic_task():
    from src.prompts.composer import TASK_FILES

    assert TASK_FILES["visual_critic"] == "visual_critic.txt"


def test_visual_critic_prompt_lays_out_scoring_dimensions_and_read_only_contract():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("visual_critic", get_domain_profile("beauty"))

    # The eight aesthetic dimensions the multimodal critic must score.
    for dimension in (
        "hierarchy",
        "legibility",
        "composition",
        "family",
        "variation",
        "rhythm",
        "color",
        "spacing",
    ):
        assert dimension in prompt.lower()
    assert "image relevance" in prompt.lower() or "image_relevance" in prompt
    assert "not_applicable" in prompt
    # The critic scores and instructs only; it must not mutate immutable sources.
    assert "read-only" in prompt.lower() or "read only" in prompt.lower()
    assert "content_atom_set_sha256" in prompt
    assert "direction_plan_sha256" in prompt
    assert "design_plan_sha256" in prompt
    assert "render_manifest_sha256" in prompt
    # Every issue must locate a page/element and give concrete revision advice.
    assert "revision_instruction" in prompt
    # Global rule: never instruct the critic to add compliance/disclaimer copy.
    assert "disclaimer" in prompt.lower()
    assert "AI disclosure" in prompt or "AI 生成" in prompt


def test_page_designer_prompt_lays_out_canvas_and_structured_element_contract():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("page_designer", get_domain_profile("beauty"))

    assert "1080" in prompt
    assert "1440" in prompt
    assert "content_ref" in prompt
    assert "asset_ref" in prompt
    assert "font_role" in prompt
    assert "display" in prompt
    assert "heading" in prompt
    assert "HTML" in prompt
    assert "CSS" in prompt
    assert "script" in prompt
    assert "external URL" in prompt
    assert "AI 生成示意图" in prompt
    assert "仅供参考" in prompt
    assert "不构成医疗建议" in prompt


def test_design_reviser_prompt_constrains_patches_and_routes_replan_feedback():
    from src.prompts.composer import compose_prompt

    prompt = compose_prompt("design_reviser", get_domain_profile("beauty"))

    assert "revision" in prompt
    assert "content_ref" in prompt
    assert "asset_ref" in prompt
    assert "approved" in prompt
    assert "HTML" in prompt
    assert "CSS" in prompt
    assert "The system — not you — decides whether to route back to the Visual Director." in prompt
    assert "Do NOT emit a `route` field" in prompt
    assert "the returned object is a CarouselDesignPlan" in prompt
    assert "AI 生成示意图" in prompt
    assert "不构成医疗建议" in prompt


def test_compose_prompt_rejects_unknown_task():
    from src.prompts.composer import compose_prompt

    with pytest.raises(ValueError, match="Unknown prompt task: missing_task"):
        compose_prompt("missing_task", get_domain_profile("beauty"))


def test_compose_prompt_rejects_removed_storyboard_image_generator_task():
    from src.prompts.composer import compose_prompt

    with pytest.raises(ValueError, match="Unknown prompt task"):
        compose_prompt("storyboards_images_generator", get_domain_profile("beauty"))


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


def test_stateful_prompt_includes_creator_profile_fragment():
    from src.prompts.composer import compose_prompt_for_state

    prompt = compose_prompt_for_state("draft_writer", _profile_bound_state())

    assert "23–35 岁、通勤、有基础护肤和底妆需求的女性" in prompt
    assert "不使用卡通角色、IP 或纯装饰性 AI 插图" in prompt


def test_stateful_prompt_layers_creator_profile_between_safety_and_domain_fragments():
    from src.prompts.composer import compose_prompt_for_state

    prompt = compose_prompt_for_state("draft_writer", _profile_bound_state())

    assert (
        prompt.index("【Shared Safety Rules】")
        < prompt.index("【Creator Profile Contract】")
        < prompt.index("【Creator Profile】")
        < prompt.index("【Domain Fragment】")
    )


def test_serialize_prompt_value_json_serializes_nested_evidence_briefs_with_url_strings():
    from src.prompts.composer import serialize_prompt_value

    serialized = serialize_prompt_value(
        {
            "evidence_briefs": {
                "tp_001": EvidenceBrief(
                    topic_id="tp_001",
                    items=[
                        EvidenceItem(
                            claim="保持规律睡眠时间有助于睡眠卫生。",
                            summary="保持规律睡眠时间有助于睡眠卫生。这只是搜索摘要片段。",
                            source_title="Sleep hygiene basics",
                            source_url="https://www.who.int/news-room/fact-sheets/detail/sleep",
                            source_type="public_health",
                            provenance_type="search_snippet",
                            verified=False,
                        )
                    ],
                    unsupported_claims=["主题“睡眠改善”的完整结论仍需逐条核验"],
                )
            }
        }
    )

    assert '"source_url": "https://www.who.int/news-room/fact-sheets/detail/sleep"' in serialized
    assert '"provenance_type": "search_snippet"' in serialized
    assert '"verified": false' in serialized


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
    ],
)
def test_migrated_active_nodes_use_direct_composer_imports(node_path, import_line):
    source = Path(node_path).read_text(encoding="utf-8")

    assert "all_prompts[" not in source
    assert "from src.prompts import compose_prompt_for_state" not in source
    assert "from src.prompts import serialize_prompt_value" not in source
    assert import_line in source
