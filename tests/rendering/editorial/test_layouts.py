from __future__ import annotations

import pytest

from src.schemas.assets import LayoutName

from conftest import make_asset, make_frame


ALL_LAYOUT_NAMES: tuple[LayoutName, ...] = (
    "editorial_cover",
    "texture_baseline",
    "front_face_zone",
    "three_quarter_face_zone",
    "step_timeline",
    "morning_evening_flow",
    "left_right_comparison",
    "three_state_diagnostic",
    "decision_tree",
    "saveable_checklist",
    "saveable_reference",
)


@pytest.mark.parametrize("layout", ALL_LAYOUT_NAMES)
def test_every_layout_has_one_renderer(layout):
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS

    assert set(LAYOUT_RENDERERS) == set(ALL_LAYOUT_NAMES)
    html = LAYOUT_RENDERERS[layout](make_frame(layout), [make_asset(layout)])
    assert 'class="card"' in html
    assert 'data-layout="' + layout + '"' in html
    assert "data-card-copy" in html


@pytest.mark.parametrize("layout", ALL_LAYOUT_NAMES)
def test_layouts_escape_storyboard_copy_and_use_only_resolved_local_assets(layout):
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS

    html = LAYOUT_RENDERERS[layout](make_frame(layout), [make_asset(layout)])

    assert "先看懂 &lt;分区&gt; &amp; 再调整" in html
    assert '<分区>' not in html
    assert '编辑型 &quot;护肤&quot;' in html
    assert "file://" in html
    assert "http://" not in html
    assert "https://" not in html


def test_layout_dispatch_does_not_inspect_topic_keywords():
    from src.rendering.editorial.layouts import LAYOUT_RENDERERS

    frame = make_frame("decision_tree").model_copy(
        update={"headline": "面部分区 步骤 对比 清单"}
    )

    html = LAYOUT_RENDERERS["decision_tree"](
        frame, [make_asset("decision_tree")]
    )

    assert 'data-layout="decision_tree"' in html
    assert "layout-decision-tree" in html
