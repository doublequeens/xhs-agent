from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.schemas.assets import AssetRequirement
from src.schemas.visual_plan import FramePlanItem, VisualPlan


class FakeProvider:
    def __init__(self) -> None:
        self.search_calls: list[object] = []

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        return []


def _plan(requirement: AssetRequirement) -> VisualPlan:
    return VisualPlan(
        design_system="beauty_editorial_v1",
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        supporting_families=["beauty_editorial", "saveable_reference"],
        frame_plan=[
            FramePlanItem(
                frame_id="cover",
                role="cover",
                layout="editorial_cover",
                purpose="cover",
            ),
            FramePlanItem(
                frame_id="texture",
                role="texture",
                layout="texture_baseline",
                purpose="texture",
            ),
            FramePlanItem(
                frame_id="face",
                role="face",
                layout="front_face_zone",
                purpose="face",
            ),
            FramePlanItem(
                frame_id="steps",
                role="steps",
                layout="step_timeline",
                purpose="steps",
            ),
            FramePlanItem(
                frame_id="save",
                role="save",
                layout="saveable_reference",
                purpose="save",
            ),
        ],
        required_assets=[requirement],
    )


def _requirement(
    *,
    role: str = "face_angle",
    layout: str = "front_face_zone",
    fallback_asset_ids: list[str] | None = None,
) -> AssetRequirement:
    return AssetRequirement(
        slot_id="face-slot",
        role=role,
        layout=layout,
        min_width=1080,
        min_height=1440,
        context_tags=["face", "zone"],
        orientation="portrait",
        palette_tags=["mauve"],
        fallback_asset_ids=fallback_asset_ids or [],
    )


def _entry(
    tmp_path: Path,
    *,
    asset_id: str = "face-front",
    role: str = "face_angle",
    width: int = 1080,
    height: int = 1440,
    layouts: tuple[str, ...] = ("front_face_zone",),
    tags: tuple[str, ...] = ("face", "zone", "mauve"),
    disabled_contexts: tuple[str, ...] = (),
    ownership: str = "project_original",
    license: str = "project_internal",
    usage: str = "production",
):
    from src.asset_resolver.catalog import AssetEntry

    path = tmp_path / f"{asset_id}.svg"
    path.write_text("<svg/>", encoding="utf-8")
    return AssetEntry(
        asset_id=asset_id,
        role=role,
        path=path,
        width=width,
        height=height,
        allowed_layouts=layouts,
        tags=tags,
        disabled_contexts=disabled_contexts,
        ownership=ownership,
        license=license,
        sha256="a" * 64,
        usage=usage,
    )


def _catalog(
    tmp_path: Path,
    entries: list[object],
    *,
    providers: list[object] | None = None,
    recent_asset_ids: set[str] | None = None,
    last_used_at: dict[str, datetime] | None = None,
):
    from src.asset_resolver.catalog import AssetCatalog

    return AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=tuple(entries),
        providers=tuple(providers or []),
        recent_asset_ids=frozenset(recent_asset_ids or set()),
        last_used_at=last_used_at or {},
    )


def test_local_match_prevents_provider_calls(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider()
    catalog = _catalog(tmp_path, [_entry(tmp_path)], providers=[provider])

    manifest = resolve_assets(_plan(_requirement()), catalog)

    assert manifest.items[0].status == "active"
    assert manifest.items[0].asset_id == "face-front"
    assert manifest.items[0].source_type == "local"
    assert provider.search_calls == []


def test_existing_but_incompatible_asset_triggers_gap_resolution(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    catalog = _catalog(tmp_path, [_entry(tmp_path, width=512, height=512)])

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), catalog)


def test_recent_repeat_is_excluded_before_deterministic_asset_id_tiebreak(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    recent = _entry(tmp_path, asset_id="a-recent")
    selected = _entry(tmp_path, asset_id="z-fresh")
    catalog = _catalog(tmp_path, [selected, recent], recent_asset_ids={"a-recent"})

    manifest = resolve_assets(_plan(_requirement()), catalog)

    assert manifest.items[0].asset_id == "z-fresh"


def test_explicit_fallback_is_used_only_when_named_by_requirement(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
        layouts=("front_face_zone",),
    )
    catalog = _catalog(tmp_path, [fallback])

    manifest = resolve_assets(
        _plan(_requirement(fallback_asset_ids=["fallback-mask"])), catalog
    )

    assert manifest.items[0].status == "fallback"
    assert manifest.items[0].asset_id == "fallback-mask"


def test_unrelated_local_asset_is_not_an_implicit_fallback(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    unrelated = _entry(tmp_path, asset_id="unrelated", role="face_zone_mask")
    catalog = _catalog(tmp_path, [unrelated])

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), catalog)


@pytest.mark.parametrize(
    "ineligible",
    [
        {"width": 1440, "height": 1080},
        {"disabled_contexts": ("zone",)},
        {"license": ""},
        {"usage": "reference_only"},
    ],
    ids=["crop-orientation", "disabled-context", "provenance", "reference-only"],
)
def test_hard_filters_reject_ineligible_local_assets(
    tmp_path: Path, ineligible: dict[str, object]
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    catalog = _catalog(tmp_path, [_entry(tmp_path, **ineligible)])

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), catalog)


def test_ranking_prefers_tag_and_palette_overlap_before_asset_id(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    alphabetically_first = _entry(
        tmp_path, asset_id="a-partial", tags=("face",)
    )
    semantic_match = _entry(
        tmp_path, asset_id="z-semantic", tags=("face", "zone", "mauve")
    )

    manifest = resolve_assets(
        _plan(_requirement()),
        _catalog(tmp_path, [alphabetically_first, semantic_match]),
    )

    assert manifest.items[0].asset_id == "z-semantic"


def test_ranking_prefers_least_recently_used_before_asset_id(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    newer = _entry(tmp_path, asset_id="a-newer")
    older = _entry(tmp_path, asset_id="z-older")
    catalog = _catalog(
        tmp_path,
        [newer, older],
        last_used_at={
            "a-newer": datetime(2026, 7, 14, tzinfo=UTC),
            "z-older": datetime(2026, 7, 1, tzinfo=UTC),
        },
    )

    manifest = resolve_assets(_plan(_requirement()), catalog)

    assert manifest.items[0].asset_id == "z-older"


def test_asset_id_breaks_complete_ranking_ties(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    second = _entry(tmp_path, asset_id="b-face")
    first = _entry(tmp_path, asset_id="a-face")
    catalog = _catalog(tmp_path, [second, first])

    assert resolve_assets(_plan(_requirement()), catalog).items[0].asset_id == "a-face"
