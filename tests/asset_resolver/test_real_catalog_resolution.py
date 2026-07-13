from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.schemas.assets import AssetRequirement
from src.schemas.content_contract import ContentContract


CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets/visual/beauty-editorial-v1/manifest.json"
)
FAMILY_BY_JOB = {
    "diagnose_and_adjust": "face_zone_map",
    "follow_steps": "step_flow",
    "compare_and_choose": "comparison_decision",
    "save_and_check": "saveable_reference",
    "understand_and_notice": "beauty_editorial",
}


class FakeProvider:
    def __init__(self) -> None:
        self.search_calls: list[AssetRequirement] = []

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        return []


def _contract(job: str) -> ContentContract:
    return ContentContract(
        audience="通勤护肤人群",
        trigger_situation="早上需要快速完成护肤",
        decision_problem="根据当前任务选择合适的执行方式",
        first_screen_promise="用一套清晰方法完成今天的护肤判断",
        screenshot_asset="可保存的执行参考卡",
        proof_asset="结构化对照证据",
        visual_mode="text_plus_real_proof",
        content_job=job,
        primary_visual_family=FAMILY_BY_JOB[job],
        primary_visual_subject="serum_texture",
        proof_mode="diagram",
        recommended_frame_count=6,
    )


@pytest.mark.parametrize("job", FAMILY_BY_JOB)
@pytest.mark.parametrize("repeat_recipe", [False, True], ids=["base", "alternative"])
def test_real_strategy_plan_resolves_only_real_local_catalog_assets(
    job: str,
    repeat_recipe: bool,
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.resolver import resolve_assets
    from src.editorial_carousel.strategy import build_visual_plan

    original = build_visual_plan(_contract(job), recent_signatures=[])
    recent_signatures = []
    if repeat_recipe:
        recent_signatures = [
            tuple((frame.role, frame.layout) for frame in original.frame_plan)
        ]
    plan = build_visual_plan(_contract(job), recent_signatures=recent_signatures)
    provider = FakeProvider()
    catalog = replace(load_catalog(CATALOG_PATH), providers=(provider,))

    manifest = resolve_assets(plan, catalog)

    assert len(manifest.items) == len(plan.required_assets)
    assert {item.status for item in manifest.items} == {"active"}
    assert provider.search_calls == []


@pytest.mark.parametrize(
    "layout,expected_fallback_id",
    [
        ("texture_baseline", "liquid_drips"),
        ("front_face_zone", "mask_chin"),
        ("three_quarter_face_zone", "face_front"),
    ],
)
def test_real_plan_fallback_ids_use_manifest_declared_compatible_roles(
    layout: str,
    expected_fallback_id: str,
) -> None:
    from src.asset_resolver.catalog import load_catalog
    from src.asset_resolver.resolver import resolve_assets
    from src.editorial_carousel.strategy import build_visual_plan

    plan = build_visual_plan(
        _contract("diagnose_and_adjust"), recent_signatures=[]
    )
    requirement = next(
        item for item in plan.required_assets if item.layout == layout
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
    one_requirement_plan = plan.model_copy(
        update={"required_assets": [requirement]}
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
