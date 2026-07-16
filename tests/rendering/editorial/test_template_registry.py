from __future__ import annotations

import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import get_args

import pytest

from src.schemas.editorial_templates import PageArchetype, TemplateFamily


ALL_TEMPLATE_FAMILIES = get_args(TemplateFamily)
ALL_PAGE_ARCHETYPES = get_args(PageArchetype)


@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
@pytest.mark.parametrize("archetype", ALL_PAGE_ARCHETYPES)
def test_registry_has_at_least_one_variant_for_every_family_archetype(
    family,
    archetype,
):
    from src.rendering.editorial.template_registry import TEMPLATE_REGISTRY

    capability = TEMPLATE_REGISTRY[family].archetypes[archetype]

    assert capability.composition_variants
    assert (
        capability.sparse_max_graphemes
        < capability.standard_max_graphemes
        < capability.dense_max_graphemes
    )
    assert capability.min_font_px >= 20


def test_registry_is_immutable_and_uses_only_repo_local_font_files():
    from src.rendering.editorial.template_registry import (
        REPOSITORY_ROOT,
        TEMPLATE_REGISTRY,
    )

    assert isinstance(TEMPLATE_REGISTRY, MappingProxyType)
    for definition in TEMPLATE_REGISTRY.values():
        assert isinstance(definition.colors, MappingProxyType)
        assert isinstance(definition.fonts, MappingProxyType)
        assert isinstance(definition.archetypes, MappingProxyType)
        assert definition.family in ALL_TEMPLATE_FAMILIES
        for path in definition.fonts.values():
            assert isinstance(path, Path)
            assert path.is_file()
            assert path.resolve().is_relative_to(REPOSITORY_ROOT)

    with pytest.raises(TypeError):
        TEMPLATE_REGISTRY["pink_red"] = TEMPLATE_REGISTRY["deep_teal"]


def test_registry_uses_the_pinned_emoji_font_for_every_family():
    from src.rendering.editorial.template_registry import (
        EMOJI_FONT_PATH,
        EMOJI_LICENSE_PATH,
        TEMPLATE_REGISTRY,
    )

    assert EMOJI_FONT_PATH.name == "NotoColorEmoji.ttf"
    assert (
        hashlib.sha256(EMOJI_FONT_PATH.read_bytes()).hexdigest()
        == "72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b"
    )
    assert (
        hashlib.sha256(EMOJI_LICENSE_PATH.read_bytes()).hexdigest()
        == "500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b"
    )
    assert all(
        definition.fonts["emoji"] == EMOJI_FONT_PATH
        for definition in TEMPLATE_REGISTRY.values()
    )


def test_registry_uses_only_declared_family_specific_composition_names():
    from src.rendering.editorial.template_registry import (
        FAMILY_COMPOSITION_VARIANTS,
        TEMPLATE_REGISTRY,
    )

    for family, definition in TEMPLATE_REGISTRY.items():
        declared = set(FAMILY_COMPOSITION_VARIANTS[family])
        used = {
            variant
            for capability in definition.archetypes.values()
            for variant in capability.composition_variants
        }
        assert used <= declared
        assert used
