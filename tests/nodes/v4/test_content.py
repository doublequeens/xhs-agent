from copy import deepcopy

import pytest


CANONICAL_PACKAGE = {
    "focus_keyword": "敏感肌",
    "topic": "敏感状态判断",
    "topic_id": "topic-1",
    "angle": "先看反应",
    "angle_id": "angle-1",
    "target_group": "敏感肌人群",
    "core_pain": "不知道何时停用",
    "title": "**敏感状态**先看这 3 个信号✨",
    "cover_copy": "__刺痛__、_泛红_、~~紧绷~~怎么判断？",
    "first_screen_promise": "三步判断是否需要停用",
    "content": (
        "# 先看当下反应\n\n"
        "普通段落保留 标点，emoji：🧴✨\n"
        "1. 暂停叠加新产品\n"
        "- 减少摩擦，不反复触碰\n"
        "> 出现持续刺痛时\n\n"
        "| 时刻 | 做法 |\n"
        "|---|---|\n"
        "| 午后 | 补涂 |"
    ),
    "hashtags": ["#敏感肌", "#护肤判断"],
    "audit": {"note": "publish-only"},
    "provenance": {"model": "internal"},
}


def atomized_state(**updates):
    package = deepcopy(CANONICAL_PACKAGE)
    package.update(updates.pop("publish_package", {}))
    state = {"publish_package": package}
    state.update(updates)
    return state


def test_table_projection_excludes_structure_before_atom_hashing():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy("| 时刻 | 做法 |\n|---|---|\n| 午后 | 补涂 |")

    assert [unit.text for unit in projection.units] == ["时刻", "做法", "午后", "补涂"]
    assert all("|" not in unit.text for unit in projection.units)
    assert projection.table_groups[0].rows == (("时刻", "做法"), ("午后", "补涂"))


def test_projection_preserves_raw_spans_punctuation_emoji_and_markers_are_structure():
    from src.nodes.v4 import project_visible_copy

    source = "## **标题**✨\n普通  段落，保留！🧴\n1. __步骤__"
    projection = project_visible_copy(source)

    assert [unit.text for unit in projection.units] == [
        "标题✨",
        "普通  段落，保留！🧴",
        "步骤",
    ]
    for unit in projection.units:
        assert source[unit.raw_start : unit.raw_end]
        assert unit.raw_slice_sha256
    assert source[projection.units[0].raw_start : projection.units[0].raw_end] == "## **标题**✨"


def test_escaped_markdown_punctuation_is_restored_without_second_pass_parsing():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy(r"\*literal\* \[literal\](target) \_under\_ \! #")

    assert [unit.text for unit in projection.units] == [
        "*literal* [literal](target) _under_ ! #"
    ]


def test_visible_copy_hash_ignores_markdown_structure_but_full_hash_keeps_provenance():
    from src.nodes.v4 import project_visible_copy

    styled = project_visible_copy("**same**")
    plain = project_visible_copy("same")

    assert [unit.text for unit in styled.units] == [unit.text for unit in plain.units]
    assert styled.canonical_visible_copy_sha256 == plain.canonical_visible_copy_sha256
    assert styled.canonical_sha256 != plain.canonical_sha256


def test_escaped_pipe_is_visible_cell_content_not_a_table_delimiter():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy(
        "| 名称 | 备注 |\n|---|---|\n| A\\|B | 保留 - 号 |"
    )

    assert [unit.text for unit in projection.units] == ["名称", "备注", "A|B", "保留 - 号"]
    assert projection.table_groups[0].rows[-1] == ("A|B", "保留 - 号")


def test_indented_markdown_table_keeps_cells_and_block_relation():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy(
        "  | 时刻 | 做法 |  \n"
        "  | --- | --- |  \n"
        "  | 午后 | 补涂 |  "
    )

    assert [unit.text for unit in projection.units] == ["时刻", "做法", "午后", "补涂"]
    assert projection.table_groups[0].rows == (("时刻", "做法"), ("午后", "补涂"))


def test_table_cell_span_is_trimmed_to_the_exact_source_cell_slice():
    from hashlib import sha256

    from src.nodes.v4 import project_visible_copy

    source = "| A  | B |\n|---|---|\n| C  | D |"
    projection = project_visible_copy(source)

    first_header, second_header, first_cell, second_cell = projection.units
    assert source[first_header.raw_start : first_header.raw_end] == "A"
    assert source[first_cell.raw_start : first_cell.raw_end] == "C"
    assert first_header.raw_slice_sha256 == sha256(b"A").hexdigest()
    assert first_cell.raw_slice_sha256 == sha256(b"C").hexdigest()
    assert source[second_header.raw_start : second_header.raw_end] == "B"
    assert source[second_cell.raw_start : second_cell.raw_end] == "D"


def test_ordinary_pipe_row_is_not_mistaken_for_a_table():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy("| 2024-07-01 | 使用半熟-半生状态 | 观察 3-5 天 |")

    assert len(projection.table_groups) == 0
    assert [unit.text for unit in projection.units] == [
        "| 2024-07-01 | 使用半熟-半生状态 | 观察 3-5 天 |"
    ]


def test_standalone_separator_is_not_discarded_without_a_table_header():
    from src.nodes.v4 import project_visible_copy

    projection = project_visible_copy("|---|---|")

    assert projection.table_groups == ()
    assert [unit.text for unit in projection.units] == ["|---|---|"]


def test_v4_atomizer_excludes_publish_only_metadata_and_returns_lock_builder_route():
    from src.nodes.v4 import content_atomizer_node

    result = content_atomizer_node(atomized_state())
    atom_set = result["content_atom_set"]

    assert result["visible_copy_projection"].content_sha256
    assert result["content_atomization_route"] == "content_lock_builder"
    assert result["content_atomization_issues"] == []
    assert result["current_node"] == "V4_CONTENT_ATOMIZER"
    assert "#敏感肌" not in [atom.text for atom in atom_set.atoms]
    assert result["visible_copy_projection"].title_sha256


def test_content_lock_binds_the_persisted_v4_atom_set():
    from src.nodes.v4 import content_atomizer_node, content_lock_builder_node

    atomized = content_atomizer_node(atomized_state())
    result = content_lock_builder_node({**atomized, "publish_package": CANONICAL_PACKAGE})

    assert result["content_lock"].content_atom_set_sha256 == result["content_atom_set"].canonical_sha256
    assert result["current_node"] == "V4_CONTENT_LOCK_BUILDER"


def test_content_lock_builder_rehydrates_serialized_persisted_contracts():
    from src.nodes.v4 import content_atomizer_node, content_lock_builder_node

    atomized = content_atomizer_node(atomized_state())
    serialized = {
        **atomized,
        "publish_package": CANONICAL_PACKAGE,
        "visible_copy_projection": atomized["visible_copy_projection"].model_dump(mode="json"),
        "content_atom_set": atomized["content_atom_set"].model_dump(mode="json"),
    }

    result = content_lock_builder_node(serialized)

    assert result["content_lock"].content_atom_set_sha256 == result["content_atom_set"].canonical_sha256


def test_content_lock_metadata_drift_changes_lock_not_atom_set():
    from src.nodes.v4 import content_atomizer_node, content_lock_builder_node

    atomized = content_atomizer_node(atomized_state())
    first = content_lock_builder_node({**atomized, "publish_package": CANONICAL_PACKAGE})
    changed_package = deepcopy(CANONICAL_PACKAGE)
    changed_package["hashtags"] = ["#不同标签"]
    second = content_lock_builder_node({**atomized, "publish_package": changed_package})

    assert second["content_atom_set"] == first["content_atom_set"]
    assert second["content_lock"].canonical_sha256 != first["content_lock"].canonical_sha256


def test_content_lock_builder_fails_closed_on_projection_or_atom_drift():
    from src.nodes.v4 import content_atomizer_node, content_lock_builder_node

    atomized = content_atomizer_node(atomized_state())
    with pytest.raises(ValueError, match="projection"):
        content_lock_builder_node({"publish_package": CANONICAL_PACKAGE, **{k: v for k, v in atomized.items() if k != "visible_copy_projection"}})

    drifted = atomized["content_atom_set"].model_copy(
        update={"projection_sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="atom"):
        content_lock_builder_node({**atomized, "publish_package": CANONICAL_PACKAGE, "content_atom_set": drifted})


def test_builder_rejects_package_copy_drift_before_building_lock():
    from src.nodes.v4 import content_atomizer_node, content_lock_builder_node

    atomized = content_atomizer_node(atomized_state())
    changed = deepcopy(CANONICAL_PACKAGE)
    changed["content"] += "\n新增句子"

    with pytest.raises(ValueError, match="source hash"):
        content_lock_builder_node({**atomized, "publish_package": changed})


def test_invalidation_clears_lock_atoms_and_all_downstream_v4_slots_but_not_copy():
    from src.nodes.v4 import invalidate_visible_copy_artifacts

    patch = invalidate_visible_copy_artifacts()
    required = {
        "visible_copy_projection",
        "content_atom_set",
        "content_lock",
        "semantic_content_model",
        "semantic_qa_result",
        "carousel_narrative",
        "page_brief_set",
        "authoring_qa_result",
        "asset_manifest",
        "layout_programs",
        "carousel_design_plan",
        "design_plan_qa_result",
        "render_manifest",
        "render_qa_result",
        "visual_critique",
        "human_review_decision",
        "final_policy_attestation",
        "revision_request",
    }

    assert required <= patch.keys()
    assert all(patch[key] is None for key in required)
    assert "publish_package" not in patch
