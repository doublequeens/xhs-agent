from __future__ import annotations

import hashlib
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


def _template_selection() -> dict:
    return {
        "template_family": "pink_red",
        "score": 10,
        "reasons": ["deterministic test fixture"],
        "rejected_families": {
            family: ["not selected in deterministic fixture"]
            for family in (
                "deep_teal",
                "soft_pink",
                "coral_impact",
                "green_catalog",
                "white_quote",
            )
        },
    }


def _plan(requirement: AssetRequirement | None = None) -> VisualPlan:
    frame_specs = (
        ("cover", "cover", "cover", ()),
        ("texture", "texture", "explanation", ()),
        (
            "face",
            "face",
            "diagnostic",
            (requirement.role,) if requirement is not None else (),
        ),
        ("steps", "steps", "steps", ()),
        ("save", "save", "save", ()),
    )
    return VisualPlan(
        design_system="beauty_editorial_v2",
        template_family="pink_red",
        template_selection=_template_selection(),
        narrative_form="scenario_story",
        content_job="diagnose_and_adjust",
        frame_plan=[
            FramePlanItem(
                frame_id=frame_id,
                role=role,
                page_archetype=page_archetype,
                purpose=role,
                allowed_density=["standard"],
                asset_roles=list(asset_roles),
            )
            for frame_id, role, page_archetype, asset_roles in frame_specs
        ],
        required_assets=[requirement] if requirement is not None else [],
    )


def _requirement(
    *,
    role: str = "face_angle",
    page_archetype: str = "diagnostic",
    fallback_asset_ids: list[str] | None = None,
) -> AssetRequirement:
    return AssetRequirement(
        slot_id="face-slot",
        role=role,
        page_archetype=page_archetype,
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
    layouts: tuple[str, ...] = ("diagnostic",),
    tags: tuple[str, ...] = ("face", "zone", "mauve"),
    disabled_contexts: tuple[str, ...] = (),
    fallback_roles: tuple[str, ...] = (),
    ownership: str = "project_original",
    license: str = "project_internal",
    usage: str = "production",
    under_active: bool = True,
    sha256: str | None = None,
):
    from src.asset_resolver.catalog import AssetEntry

    parent = tmp_path / "active" if under_active else tmp_path
    parent.mkdir(exist_ok=True)
    path = parent / f"{asset_id}.svg"
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
        fallback_roles=fallback_roles,
        ownership=ownership,
        license=license,
        sha256=sha256 or hashlib.sha256(path.read_bytes()).hexdigest(),
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


def test_resolve_assets_returns_auditable_empty_manifest_without_calling_providers(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider()
    catalog = _catalog(tmp_path, [], providers=[provider])

    manifest = resolve_assets(_plan(), catalog)

    assert manifest.items == []
    assert manifest.search_report.search_triggered is False
    assert manifest.search_report.queries == []
    assert manifest.search_report.provider_reports == []
    assert manifest.search_report.selection_reasons == {}
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
        layouts=("diagnostic",),
    )
    primary = _entry(
        tmp_path,
        asset_id="primary-too-small",
        width=512,
        height=512,
        fallback_roles=("face_zone_mask",),
    )
    catalog = _catalog(tmp_path, [primary, fallback])

    manifest = resolve_assets(
        _plan(_requirement(fallback_asset_ids=["fallback-mask"])), catalog
    )

    assert manifest.items[0].status == "fallback"
    assert manifest.items[0].asset_id == "fallback-mask"


def test_explicit_fallback_id_must_also_have_manifest_declared_role(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    primary = _entry(
        tmp_path,
        asset_id="primary-too-small",
        width=512,
        height=512,
        fallback_roles=(),
    )
    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
    )
    catalog = _catalog(tmp_path, [primary, fallback])

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(
            _plan(_requirement(fallback_asset_ids=["fallback-mask"])), catalog
        )


def test_reference_entry_cannot_declare_a_production_fallback(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    reference_declaration = _entry(
        tmp_path,
        asset_id="reference-declaration",
        width=512,
        height=512,
        usage="reference_only",
        fallback_roles=("face_zone_mask",),
    )
    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
    )
    catalog = _catalog(tmp_path, [reference_declaration, fallback])

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(
            _plan(_requirement(fallback_asset_ids=["fallback-mask"])), catalog
        )


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


def test_hard_filters_reject_asset_outside_catalog_active_root(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    outside = _entry(tmp_path, under_active=False)

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), _catalog(tmp_path, [outside]))


def test_outside_catalog_asset_is_rejected_before_its_bytes_are_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    outside = _entry(tmp_path, under_active=False)
    outside_path = outside.path.resolve()
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path.resolve() == outside_path:
            raise AssertionError("outside-catalog bytes must not be read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), _catalog(tmp_path, [outside]))


def test_hard_filters_reject_asset_whose_bytes_do_not_match_sha256(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    mismatched = _entry(tmp_path, sha256="a" * 64)

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(_plan(_requirement()), _catalog(tmp_path, [mismatched]))


def test_off_active_primary_cannot_authorize_named_fallback(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    declaration = _entry(
        tmp_path,
        asset_id="outside-primary",
        width=512,
        height=512,
        fallback_roles=("face_zone_mask",),
        under_active=False,
    )
    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
    )

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(
            _plan(_requirement(fallback_asset_ids=["fallback-mask"])),
            _catalog(tmp_path, [declaration, fallback]),
        )


def test_stale_hash_primary_cannot_authorize_named_fallback(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    declaration = _entry(
        tmp_path,
        asset_id="stale-primary",
        width=512,
        height=512,
        fallback_roles=("face_zone_mask",),
        sha256="a" * 64,
    )
    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
    )

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(
            _plan(_requirement(fallback_asset_ids=["fallback-mask"])),
            _catalog(tmp_path, [declaration, fallback]),
        )


def test_incomplete_provenance_primary_cannot_authorize_named_fallback(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    declaration = _entry(
        tmp_path,
        asset_id="unlicensed-primary",
        width=512,
        height=512,
        fallback_roles=("face_zone_mask",),
        license="",
    )
    fallback = _entry(
        tmp_path,
        asset_id="fallback-mask",
        role="face_zone_mask",
    )

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(
            _plan(_requirement(fallback_asset_ids=["fallback-mask"])),
            _catalog(tmp_path, [declaration, fallback]),
        )


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
