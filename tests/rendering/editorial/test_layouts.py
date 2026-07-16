from __future__ import annotations

from types import MappingProxyType
from typing import get_args

from src.schemas.editorial_templates import TemplateFamily


def test_template_dispatch_contains_exactly_the_six_approved_families():
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS

    assert isinstance(TEMPLATE_RENDERERS, MappingProxyType)
    assert set(TEMPLATE_RENDERERS) == set(get_args(TemplateFamily))
    assert all(callable(renderer) for renderer in TEMPLATE_RENDERERS.values())


def test_template_dispatch_uses_only_the_explicit_family_key():
    from conftest import make_frame
    from src.rendering.editorial.copy_metrics import measure_frame_copy
    from src.rendering.editorial.layouts import TEMPLATE_RENDERERS
    from src.rendering.editorial.variant_resolver import resolve_variant

    frame = make_frame("qa").model_copy(
        update={"headline": "面部分区 步骤 对比 清单"}
    )
    outputs = {}
    for family, renderer in TEMPLATE_RENDERERS.items():
        variant = resolve_variant(
            family,
            frame.page_archetype,
            "auto",
            measure_frame_copy(frame),
        )
        outputs[family] = renderer(frame, [], variant)

    assert len(set(outputs.values())) == len(TEMPLATE_RENDERERS)
    assert all(
        f'data-template-family="{family}"' in output
        for family, output in outputs.items()
    )
