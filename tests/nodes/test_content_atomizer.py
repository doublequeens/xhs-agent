from copy import deepcopy

import pytest


CANONICAL_PACKAGE = {
    "title": "敏感状态先看这 3 个信号✨",
    "cover_copy": "刺痛、泛红、紧绷怎么判断？",
    "content": (
        "# 先看当下反应\n\n"
        "普通段落保留标点，emoji 也保留：🧴✨\n\n"
        "1. 暂停叠加新产品\n"
        "2. 记录出现时间与区域\n"
        "- 减少摩擦，不反复触碰\n\n"
        "> 出现持续刺痛、明显泛红或第二天仍然紧绷时"
    ),
    "hashtags": ["#敏感肌", "#护肤判断"],
    "audit": {"note": "免责声明"},
    "provenance": {"label": "AI生成示意图"},
    "runtime_warnings": ["仅供参考"],
}


def _state_with_copy(**package_updates):
    package = deepcopy(CANONICAL_PACKAGE)
    package.update(package_updates)
    return {"publish_package": package}


def test_atomizer_preserves_visible_copy_character_for_character():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    result = content_atomizer_node(_state_with_copy())
    atom_set = result["content_atom_set"]

    assert [atom.atom_id for atom in atom_set.atoms] == [
        "title-001",
        "cover-001",
        "heading-001",
        "paragraph-001",
        "step-001",
        "step-002",
        "list_item-001",
        "quote-001",
    ]
    assert [atom.role for atom in atom_set.atoms] == [
        "title",
        "cover",
        "heading",
        "paragraph",
        "step",
        "step",
        "list_item",
        "quote",
    ]
    assert [atom.text for atom in atom_set.atoms] == [
        "敏感状态先看这 3 个信号✨",
        "刺痛、泛红、紧绷怎么判断？",
        "先看当下反应",
        "普通段落保留标点，emoji 也保留：🧴✨",
        "暂停叠加新产品",
        "记录出现时间与区域",
        "减少摩擦，不反复触碰",
        "出现持续刺痛、明显泛红或第二天仍然紧绷时",
    ]
    assert result["content_atomization_route"] == "visual_director"
    assert result["content_atomization_issues"] == []
    assert result["current_node"] == "CONTENT_ATOMIZER"


def test_atomizer_ignores_publish_only_metadata_and_hashes_only_canonical_copy():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    first = content_atomizer_node(_state_with_copy())["content_atom_set"]
    changed_metadata = content_atomizer_node(
        _state_with_copy(
            hashtags=["#完全不同"],
            audit={"note": "不构成医疗建议"},
            provenance={"label": "示意图"},
            runtime_warnings=["AI 生成"],
        )
    )["content_atom_set"]

    assert changed_metadata == first
    all_text = [atom.text for atom in first.atoms]
    assert "#敏感肌" not in all_text
    assert "免责声明" not in all_text
    assert "AI生成示意图" not in all_text
    assert "仅供参考" not in all_text


@pytest.mark.parametrize(
    ("field", "forbidden"),
    [
        ("title", "AI生成示意图"),
        ("cover_copy", "仅供参考"),
        ("content", "不构成医疗建议"),
        ("content", "免责声明"),
        ("content", "真实皮肤示意图"),
    ],
)
def test_atomizer_routes_system_disclosure_or_disclaimer_copy_back_to_r2(
    field,
    forbidden,
):
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    result = content_atomizer_node(
        _state_with_copy(**{field: f"护肤判断方法\n{forbidden}"})
    )

    assert result["content_atomization_route"] == "r2_compliance"
    assert result["content_atom_set"] is None
    assert field in result["content_atomization_issues"][0]
    assert forbidden in result["content_atomization_issues"][0]
    assert "移除" in result["content_atomization_issues"][0]


@pytest.mark.parametrize(
    "forbidden",
    [
        "本图由AI绘制",
        "本图由人工智能生成",
        "AI 生成",
        "人工智能生成",
        "（AI生成）",
        "本图片由 AI 技术辅助生成",
        "本文不能代替医生建议",
        "本文不作为诊疗依据",
    ],
)
def test_atomizer_routes_equivalent_disclosure_and_disclaimer_boilerplate_to_r2(
    forbidden,
):
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    result = content_atomizer_node(
        _state_with_copy(content=f"护肤判断方法\n{forbidden}")
    )

    assert result["content_atomization_route"] == "r2_compliance"
    assert result["content_atom_set"] is None
    assert forbidden in result["content_atomization_issues"][0]


def test_atomizer_allows_factual_risk_conditions_and_stop_use_guidance():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    condition = "出现持续刺痛、明显泛红或第二天仍然紧绷时"
    result = content_atomizer_node(
        _state_with_copy(content=f"{condition}\n暂停使用新加的产品并观察")
    )

    assert result["content_atomization_route"] == "visual_director"
    assert [atom.text for atom in result["content_atom_set"].atoms][-2:] == [
        condition,
        "暂停使用新加的产品并观察",
    ]


def test_atomizer_allows_ai_as_an_ordinary_subject_without_source_disclosure():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    ordinary_copy = "AI 可以辅助整理配方趋势，但不能只看一个指标"
    result = content_atomizer_node(_state_with_copy(content=ordinary_copy))

    assert result["content_atomization_route"] == "visual_director"
    assert result["content_atom_set"].atoms[-1].text == ordinary_copy


@pytest.mark.parametrize(
    "ordinary_copy",
    [
        "如何识别AI生成图片的常见瑕疵",
        "AI绘制皮肤纹理为什么容易失真",
        "AI创作和真人摄影有什么差别",
        "我用AI制作内容时会先核对事实",
    ],
)
def test_atomizer_allows_ai_generation_as_the_topic_of_ordinary_discussion(
    ordinary_copy,
):
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    result = content_atomizer_node(_state_with_copy(content=ordinary_copy))

    assert result["content_atomization_route"] == "visual_director"
    assert result["content_atom_set"].atoms[-1].text == ordinary_copy


def test_atomizer_strips_nested_markdown_without_changing_visible_payload():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    result = content_atomizer_node(
        _state_with_copy(
            title="**敏感状态**先看这 3 个信号✨",
            cover_copy="__刺痛__、_泛红_、~~紧绷~~怎么判断？",
            content=(
                "    - **减少摩擦**，不反复触碰\n"
                "        1. __记录__出现时间与区域\n"
                "---\n"
                "普通段落保留 _标点_，emoji：🧴✨"
            ),
        )
    )

    assert [atom.role for atom in result["content_atom_set"].atoms] == [
        "title",
        "cover",
        "list_item",
        "step",
        "paragraph",
    ]
    assert [atom.text for atom in result["content_atom_set"].atoms] == [
        "敏感状态先看这 3 个信号✨",
        "刺痛、泛红、紧绷怎么判断？",
        "减少摩擦，不反复触碰",
        "记录出现时间与区域",
        "普通段落保留 标点，emoji：🧴✨",
    ]


def test_atomizer_hashes_are_stable_and_change_when_visible_copy_changes():
    from src.nodes.node_p_content_atomizer import content_atomizer_node

    first = content_atomizer_node(_state_with_copy())["content_atom_set"]
    repeated = content_atomizer_node(_state_with_copy())["content_atom_set"]
    changed = content_atomizer_node(
        _state_with_copy(cover_copy="刺痛、泛红、紧绷，先看这三点")
    )["content_atom_set"]

    assert repeated.canonical_sha256 == first.canonical_sha256
    assert [atom.sha256 for atom in repeated.atoms] == [
        atom.sha256 for atom in first.atoms
    ]
    assert changed.canonical_sha256 != first.canonical_sha256
    assert changed.atoms[1].sha256 != first.atoms[1].sha256
    assert changed.atoms[0].sha256 == first.atoms[0].sha256
