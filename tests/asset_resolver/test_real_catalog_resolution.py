from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.schemas.assets import AssetRequirement


CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets/visual/beauty-editorial-v1/manifest.json"
)
class FakeProvider:
    def __init__(self) -> None:
        self.search_calls: list[AssetRequirement] = []

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        return []


def _requirement(
    role: str,
    page_archetype: str,
    *,
    fallback_asset_ids: list[str] | None = None,
) -> AssetRequirement:
    return AssetRequirement(
        slot_id=f"{page_archetype}-{role}",
        role=role,
        page_archetype=page_archetype,
        min_width=1,
        min_height=1,
        orientation="any",
        fallback_asset_ids=fallback_asset_ids or [],
    )


@pytest.mark.parametrize(
    ("role", "page_archetype"),
    [
        ("background_token", "cover"),
        ("serum_texture", "explanation"),
        ("face_angle", "diagnostic"),
        ("line_token", "steps"),
        ("container_shape", "qa"),
    ],
)
def test_real_catalog_resolves_semantic_archetype_requirements_locally(
    role: str,
    page_archetype: str,
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.resolver import resolve_assets

    plan = SimpleNamespace(
        required_assets=[_requirement(role, page_archetype)]
    )
    provider = FakeProvider()
    catalog = replace(load_catalog(CATALOG_PATH), providers=(provider,))

    manifest = resolve_assets(plan, catalog)

    assert len(manifest.items) == len(plan.required_assets)
    assert {item.status for item in manifest.items} == {"active"}
    assert provider.search_calls == []


@pytest.mark.parametrize(
    ("page_archetype", "role", "expected_fallback_id"),
    [
        ("explanation", "serum_texture", "liquid_drips"),
        ("diagnostic", "face_angle", "mask_chin"),
        ("diagnostic", "face_zone_mask", "face_front"),
    ],
)
def test_real_plan_fallback_ids_use_manifest_declared_compatible_roles(
    page_archetype: str,
    role: str,
    expected_fallback_id: str,
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.resolver import resolve_assets

    requirement = _requirement(
        role,
        page_archetype,
        fallback_asset_ids=[expected_fallback_id],
    )
    provider = FakeProvider()
    catalog = load_catalog(CATALOG_PATH)
    recent_exact_matches = frozenset(
        entry.asset_id
        for entry in catalog.entries
        if entry.role == requirement.role
    )
    catalog = replace(
        catalog,
        providers=(provider,),
        recent_asset_ids=recent_exact_matches,
    )
    one_requirement_plan = SimpleNamespace(
        required_assets=[requirement]
    )

    manifest = resolve_assets(one_requirement_plan, catalog)

    fallback = next(
        entry for entry in catalog.entries if entry.asset_id == expected_fallback_id
    )
    primary = next(
        entry for entry in catalog.entries if entry.role == requirement.role
    )
    assert manifest.items[0].status == "fallback"
    assert manifest.items[0].asset_id == expected_fallback_id
    assert fallback.role in primary.fallback_roles
    assert provider.search_calls == []
