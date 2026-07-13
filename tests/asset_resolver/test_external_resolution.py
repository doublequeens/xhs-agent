from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from threading import Barrier

from PIL import Image, ImageDraw
import pytest

from src.asset_resolver.catalog import AssetCatalog
from src.schemas.assets import AssetRequirement
from src.schemas.visual_plan import FramePlanItem, VisualPlan


def image_bytes(
    pattern: int,
    *,
    dark: int = 20,
    light: int = 230,
    size: tuple[int, int] = (1080, 1440),
) -> bytes:
    stream = BytesIO()
    image = Image.new("L", size, dark)
    draw = ImageDraw.Draw(image)
    if pattern % 4 == 0:
        draw.rectangle((size[0] // 2, 0, size[0], size[1]), fill=light)
    elif pattern % 4 == 1:
        draw.rectangle((0, size[1] // 2, size[0], size[1]), fill=light)
    elif pattern % 4 == 2:
        draw.polygon(((0, 0), (size[0], 0), (size[0], size[1])), fill=light)
    else:
        draw.rectangle((size[0] // 4, size[1] // 4, 3 * size[0] // 4, 3 * size[1] // 4), fill=light)
    image.convert("RGB").save(stream, format="PNG")
    return stream.getvalue()


def bit_pattern_image_bytes(*, flip_one: bool = False) -> bytes:
    width, height = 1080, 1440
    image = Image.new("L", (width, height), 20)
    draw = ImageDraw.Draw(image)
    for row in range(8):
        for column in range(8):
            is_light = column >= 4
            if flip_one and (row, column) == (1, 1):
                is_light = not is_light
            if is_light:
                draw.rectangle(
                    (
                        column * width // 8,
                        row * height // 8,
                        (column + 1) * width // 8 - 1,
                        (row + 1) * height // 8 - 1,
                    ),
                    fill=230,
                )
    stream = BytesIO()
    image.convert("RGB").save(stream, format="PNG")
    return stream.getvalue()


class FakeProvider:
    def __init__(
        self,
        name: str,
        results: list[object],
        *,
        downloads: dict[str, bytes] | None = None,
    ) -> None:
        self.name = name
        self.results = results
        self.search_calls: list[AssetRequirement] = []
        self.record_calls: list[object] = []
        self.download_calls: list[object] = []
        self.downloads = downloads or {}

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        return self.results

    def record_download(self, candidate: object) -> None:
        self.record_calls.append(candidate)

    def download(self, candidate: object) -> bytes:
        self.download_calls.append(candidate)
        asset_id = str(getattr(candidate, "provider_asset_id"))
        return self.downloads.get(asset_id, image_bytes(int(asset_id[-1], 36)))


class FailingProvider(FakeProvider):
    def __init__(self, name: str, error: Exception) -> None:
        super().__init__(name, [])
        self.error = error

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        raise self.error


class BarrierProvider(FakeProvider):
    def __init__(self, name: str, results: list[object], barrier: Barrier) -> None:
        super().__init__(name, results)
        self.barrier = barrier

    def search(self, requirement: AssetRequirement) -> list[object]:
        self.search_calls.append(requirement)
        self.barrier.wait(timeout=1)
        return self.results


class FailingDownloadProvider(FakeProvider):
    def download(self, candidate: object) -> bytes:
        self.download_calls.append(candidate)
        raise TimeoutError("download timeout")


def candidate(
    provider: str,
    asset_id: str,
    *,
    score_tags: tuple[str, ...] = ("serum",),
    color: str = "ivory",
):
    from src.asset_resolver.providers import ExternalAssetCandidate

    return ExternalAssetCandidate(
        provider=provider,
        provider_asset_id=asset_id,
        author=f"author-{asset_id}",
        source_url=f"https://example.test/{provider}/{asset_id}",
        source_file_url=f"https://cdn.example.test/{provider}/{asset_id}.png",
        width=1080,
        height=1440,
        role="serum_texture",
        license=f"{provider} license",
        license_snapshot=f"https://example.test/{provider}/license",
        score_tags=score_tags,
        palette_tags=(color,),
        dominant_color=color,
        provider_attribution=(("author", f"author-{asset_id}"),),
    )


def texture_plan() -> VisualPlan:
    requirement = AssetRequirement(
        slot_id="serum-slot",
        role="serum_texture",
        layout="texture_baseline",
        min_width=1080,
        min_height=1440,
        context_tags=["serum", "drop"],
        orientation="portrait",
        palette_tags=["ivory"],
    )
    return VisualPlan(
        design_system="beauty_editorial_v1",
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        supporting_families=["beauty_editorial", "saveable_reference"],
        frame_plan=[
            FramePlanItem(frame_id="cover", role="cover", layout="editorial_cover", purpose="cover"),
            FramePlanItem(frame_id="texture", role="texture", layout="texture_baseline", purpose="texture"),
            FramePlanItem(frame_id="face", role="face", layout="front_face_zone", purpose="face"),
            FramePlanItem(frame_id="steps", role="steps", layout="step_timeline", purpose="steps"),
            FramePlanItem(frame_id="save", role="save", layout="saveable_reference", purpose="save"),
        ],
        required_assets=[requirement],
    )


def empty_catalog(tmp_path: Path, providers: list[object]) -> AssetCatalog:
    return AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=(),
        providers=tuple(providers),
        run_id="run-42",
    )


def test_gap_queries_both_enabled_providers_and_merges_results(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    pexels = FakeProvider("pexels", [candidate("pexels", "p1")])
    unsplash = FakeProvider(
        "unsplash",
        [candidate("unsplash", "u1", score_tags=("serum", "drop"))],
    )

    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))

    assert len(pexels.search_calls) == 1
    assert len(unsplash.search_calls) == 1
    assert manifest.items[0].status == "pending_external"
    assert manifest.items[0].provider_asset_id == "u1"
    assert Path(manifest.items[0].path).is_relative_to(
        tmp_path / "incoming" / "external" / "run-42"
    )


def test_one_provider_timeout_keeps_other_provider_result(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    pexels = FailingProvider("pexels", TimeoutError("timeout"))
    unsplash = FakeProvider("unsplash", [candidate("unsplash", "u1")])

    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))

    assert manifest.search_report.provider_reports[0].status == "failed"
    assert manifest.search_report.provider_reports[0].error == "timeout"
    assert manifest.search_report.provider_reports[0].elapsed_ms is not None
    assert manifest.search_report.provider_reports[0].elapsed_ms >= 0
    assert manifest.items[0].provider == "unsplash"


def test_enabled_provider_searches_overlap_but_reports_keep_catalog_order(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    barrier = Barrier(2)
    pexels = BarrierProvider(
        "pexels", [candidate("pexels", "p1")], barrier
    )
    unsplash = BarrierProvider(
        "unsplash", [candidate("unsplash", "u1")], barrier
    )

    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))

    assert [report.provider for report in manifest.search_report.provider_reports] == [
        "pexels",
        "unsplash",
    ]


def test_download_failure_is_audited_while_other_provider_can_succeed(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    pexels = FailingDownloadProvider(
        "pexels", [candidate("pexels", "p1")]
    )
    unsplash = FakeProvider("unsplash", [candidate("unsplash", "u1")])

    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))

    reports = {report.provider: report for report in manifest.search_report.provider_reports}
    assert reports["pexels"].download_errors == ["p1: download timeout"]
    assert manifest.items[0].provider == "unsplash"


def test_external_gap_downloads_at_most_top_three_ranked_candidates(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", f"p{index}") for index in range(5)],
    )

    resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    assert len(provider.download_calls) == 3
    assert len(provider.record_calls) == 3
    audit_files = list((tmp_path / "incoming" / "external" / "run-42").glob("*.json"))
    assert len(audit_files) == 3
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["source_type"] == "stock_photo"
    assert audit["acquired_at"]
    assert audit["provider_attribution"]


def test_duplicate_source_urls_are_removed_before_download(tmp_path: Path) -> None:
    from dataclasses import replace

    from src.asset_resolver.resolver import resolve_assets

    first = candidate("pexels", "p1")
    duplicate = replace(
        candidate("unsplash", "u1"), source_url=first.source_url
    )
    pexels = FakeProvider("pexels", [first])
    unsplash = FakeProvider("unsplash", [duplicate])

    resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))

    assert len(pexels.download_calls) + len(unsplash.download_calls) == 1


def test_byte_identical_downloads_are_deduplicated_by_sha256(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    same_bytes = image_bytes(0)
    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2")],
        downloads={"p1": same_bytes, "p2": same_bytes},
    )

    resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    audits = list((tmp_path / "incoming" / "external" / "run-42").glob("*.json"))
    assert len(provider.download_calls) == 2
    assert len(audits) == 1


def test_visually_identical_downloads_are_deduplicated_by_average_hash(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2")],
        downloads={
            "p1": image_bytes(0, dark=10, light=240),
            "p2": image_bytes(0, dark=30, light=220),
        },
    )

    resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    audits = list((tmp_path / "incoming" / "external" / "run-42").glob("*.json"))
    assert len(audits) == 1


def test_downloaded_pixels_must_still_match_required_orientation(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1")],
        downloads={"p1": image_bytes(0, size=(1600, 1440))},
    )

    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    assert list((tmp_path / "incoming" / "external" / "run-42").glob("*.json")) == []


def test_small_average_hash_distance_is_treated_as_perceptual_duplicate(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2")],
        downloads={
            "p1": bit_pattern_image_bytes(),
            "p2": bit_pattern_image_bytes(flip_one=True),
        },
    )

    resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    audits = list((tmp_path / "incoming" / "external" / "run-42").glob("*.json"))
    assert len(audits) == 1
