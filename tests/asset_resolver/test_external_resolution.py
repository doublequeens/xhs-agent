from __future__ import annotations

import json
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Barrier
from threading import Event

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


class DelayedThirdReservationProvider(FakeProvider):
    def __init__(self, name: str, results: list[object]) -> None:
        super().__init__(name, results)
        self.third_download_started = Event()

    def download(self, candidate: object) -> bytes:
        self.download_calls.append(candidate)
        asset_id = str(getattr(candidate, "provider_asset_id"))
        if asset_id in {"p1", "p2"}:
            return image_bytes(int(asset_id[-1]), size=(1600, 1440))
        self.third_download_started.set()
        time.sleep(0.2)
        return image_bytes(3)


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

    if provider == "pexels":
        source_url = f"https://www.pexels.com/photo/{asset_id}/"
        source_file_url = f"https://images.pexels.com/photos/{asset_id}.png"
        license_terms_url = "https://www.pexels.com/license/"
    else:
        source_url = f"https://unsplash.com/photos/{asset_id}"
        source_file_url = f"https://images.unsplash.com/{asset_id}"
        license_terms_url = "https://unsplash.com/license"
    return ExternalAssetCandidate(
        provider=provider,
        provider_asset_id=asset_id,
        author=f"author-{asset_id}",
        source_url=source_url,
        source_file_url=source_file_url,
        width=1080,
        height=1440,
        role="serum_texture",
        license=f"{provider} license",
        license_snapshot=(
            f"{provider} terms summary v1\n"
            f"Official terms: {license_terms_url}\n"
            "Mandatory human review before production use."
        ),
        license_terms_url=license_terms_url,
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


def empty_catalog(
    tmp_path: Path, providers: list[object], *, run_id: str = "run-42"
) -> AssetCatalog:
    return AssetCatalog(
        catalog_id="test-catalog",
        root=tmp_path,
        entries=(),
        providers=tuple(providers),
        run_id=run_id,
    )


@pytest.mark.parametrize("run_id", ["../escape", "/tmp/escape", ".", "a/b"])
def test_catalog_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    from src.asset_resolver.catalog import CatalogError

    with pytest.raises(CatalogError, match="run_id"):
        AssetCatalog(
            catalog_id="test-catalog",
            root=tmp_path,
            entries=(),
            run_id=run_id,
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
    assert manifest.items[0].pending_id
    assert manifest.items[0].metadata_path.endswith(".json")
    assert manifest.items[0].run_id == "run-42"
    assert manifest.items[0].candidate_rank == 1
    assert manifest.items[0].unresolved_safety_checks
    snapshot_path = tmp_path / str(manifest.items[0].license_snapshot)
    assert snapshot_path.is_file()
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == (
        manifest.items[0].license_snapshot_sha256
    )
    assert manifest.items[0].license_terms_url.startswith("https://")


def test_rerun_resumes_existing_pending_without_provider_calls(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2")],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])
    first = resolve_assets(texture_plan(), asset_catalog)
    calls_after_first = len(provider.search_calls)

    resumed = resolve_assets(texture_plan(), asset_catalog)

    assert len(provider.search_calls) == calls_after_first
    assert resumed.items[0].pending_id == first.items[0].pending_id


def test_pending_resume_requires_the_same_requirement_fingerprint(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import resolve_assets

    first_provider = FakeProvider("pexels", [candidate("pexels", "p1")])
    asset_catalog = empty_catalog(tmp_path, [first_provider])
    first = resolve_assets(texture_plan(), asset_catalog)
    changed_plan = texture_plan()
    changed_plan.required_assets[0].palette_tags = ["sage"]
    second_provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p2", color="sage")],
    )
    changed_catalog = empty_catalog(tmp_path, [second_provider])

    second = resolve_assets(changed_plan, changed_catalog)

    assert second.items[0].pending_id != first.items[0].pending_id
    assert second.items[0].requirement_fingerprint
    assert second.items[0].requirement_fingerprint != (
        first.items[0].requirement_fingerprint
    )
    assert len(second_provider.search_calls) == 1


def test_reject_returns_next_downloaded_candidate_in_rank_order(tmp_path: Path) -> None:
    from src.asset_resolver.lifecycle import list_pending_assets, reject_external_asset
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2"), candidate("pexels", "p3")],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])
    manifest = resolve_assets(texture_plan(), asset_catalog)
    pending = list_pending_assets(
        asset_catalog,
        slot_id="serum-slot",
        requirement_fingerprint=manifest.items[0].requirement_fingerprint,
    )

    assert [item.candidate_rank for item in pending] == [1, 2, 3]
    next_candidate = reject_external_asset(
        pending[0], reason="visible logo", catalog=asset_catalog
    )

    assert next_candidate is not None
    assert next_candidate.candidate_rank == 2


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


def test_terminal_resolution_error_preserves_complete_search_report(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    providers = [
        FailingProvider("pexels", TimeoutError("pexels timeout")),
        FailingProvider("unsplash", TimeoutError("unsplash timeout")),
    ]

    with pytest.raises(AssetResolutionError) as caught:
        resolve_assets(texture_plan(), empty_catalog(tmp_path, providers))

    report = caught.value.search_report
    assert report.search_triggered is True
    assert report.queries == ["serum texture drop ivory"]
    assert [item.error for item in report.provider_reports] == [
        "pexels timeout",
        "unsplash timeout",
    ]
    assert all(item.elapsed_ms is not None for item in report.provider_reports)


def test_provider_identity_mismatch_is_rejected_and_audited(tmp_path: Path) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    forged = candidate("unsplash", "u1")
    provider = FakeProvider("pexels", [forged])

    with pytest.raises(AssetResolutionError) as caught:
        resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    report = caught.value.search_report.provider_reports[0]
    assert report.status == "failed"
    assert "provider identity mismatch" in str(report.error)


def test_download_rejects_image_over_pixel_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    monkeypatch.setattr("src.asset_resolver.resolver.MAX_IMAGE_PIXELS", 100)
    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1")],
        downloads={"p1": image_bytes(0, size=(20, 20))},
    )
    plan = texture_plan()
    plan.required_assets[0].min_width = 1
    plan.required_assets[0].min_height = 1

    with pytest.raises(AssetResolutionError) as caught:
        resolve_assets(plan, empty_catalog(tmp_path, [provider]))

    assert "pixel limit" in caught.value.search_report.provider_reports[0].download_errors[0]


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

    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    assert len(provider.download_calls) == 3
    assert len(provider.record_calls) == 3
    audit_files = list(
        (tmp_path / "incoming" / "external" / "run-42").glob(
            "serum-slot-pexels-*.json"
        )
    )
    assert len(audit_files) == 3
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["source_type"] == "stock_photo"
    assert audit["acquired_at"]
    assert audit["provider_attribution"]
    assert audit["attempt_number"] in {1, 2, 3}
    assert audit["requirement_fingerprint"] == manifest.items[0].requirement_fingerprint


def test_download_attempt_budget_persists_across_rejections_and_reruns(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import list_pending_assets, reject_external_asset
    from src.asset_resolver.resolver import AssetResolutionError, requirement_fingerprint, resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", f"p{index}") for index in range(1, 7)],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])
    plan = texture_plan()
    resolve_assets(plan, asset_catalog)
    fingerprint = requirement_fingerprint(plan.required_assets[0])
    pending = list_pending_assets(
        asset_catalog,
        slot_id="serum-slot",
        requirement_fingerprint=fingerprint,
    )
    for item in pending:
        reject_external_asset(item, reason="not suitable", catalog=asset_catalog)
    attempts_after_first_run = len(provider.download_calls)

    with pytest.raises(AssetResolutionError):
        resolve_assets(plan, asset_catalog)

    assert attempts_after_first_run == 3
    assert len(provider.download_calls) == 3
    ledger = list(
        (
            tmp_path
            / "incoming"
            / "external"
            / "run-42"
            / ".attempt-ledgers"
        ).glob("*.json")
    )
    assert len(ledger) == 1
    assert len(json.loads(ledger[0].read_text())["attempts"]) == 3


def test_concurrent_resolves_reserve_unique_candidates_with_one_attempt_budget(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = FakeProvider(
        "pexels",
        [candidate("pexels", f"p{index}") for index in range(1, 7)],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])

    with ThreadPoolExecutor(max_workers=2) as executor:
        manifests = list(
            executor.map(
                lambda _: resolve_assets(texture_plan(), asset_catalog),
                range(2),
            )
        )

    run_root = tmp_path / "incoming" / "external" / "run-42"
    ledger_paths = [
        path
        for path in run_root.rglob("*.json")
        if path.name.startswith("attempts-")
    ]
    assert len(ledger_paths) == 1
    attempts = json.loads(ledger_paths[0].read_text())["attempts"]
    identities = [
        (item["provider"], item["provider_asset_id"], item["source_url"])
        for item in attempts
    ]
    assert len(identities) == len(set(identities)) == 3
    candidate_audits = [
        path
        for path in run_root.glob("*.json")
        if not path.name.startswith("attempts-")
    ]
    assert len(candidate_audits) == 3
    assert all(item.items[0].pending_id for item in manifests)
    assert len(provider.search_calls) == 1


def test_attempts_prefixed_slot_id_resumes_and_advances_normally(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.lifecycle import list_pending_assets, reject_external_asset
    from src.asset_resolver.resolver import requirement_fingerprint, resolve_assets

    plan = texture_plan()
    plan.required_assets[0].slot_id = "attempts-featured"
    provider = FakeProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2")],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])
    first = resolve_assets(plan, asset_catalog)
    resumed = resolve_assets(plan, asset_catalog)
    pending = list_pending_assets(
        asset_catalog,
        slot_id="attempts-featured",
        requirement_fingerprint=requirement_fingerprint(plan.required_assets[0]),
    )
    next_candidate = reject_external_asset(
        pending[0], reason="not suitable", catalog=asset_catalog
    )

    assert resumed.items[0].pending_id == first.items[0].pending_id
    assert next_candidate is not None
    assert next_candidate.candidate_rank == 2
    ledger_dir = (
        tmp_path
        / "incoming"
        / "external"
        / "run-42"
        / ".attempt-ledgers"
    )
    assert len(list(ledger_dir.glob("*.json"))) == 1


def test_attempt_ledger_directory_symlink_cannot_escape_incoming_root(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    outside = tmp_path.parent / f"{tmp_path.name}-ledger-outside"
    outside.mkdir()
    run_root = tmp_path / "incoming" / "external" / "run-42"
    run_root.mkdir(parents=True)
    (run_root / ".attempt-ledgers").symlink_to(
        outside, target_is_directory=True
    )
    provider = FakeProvider("pexels", [candidate("pexels", "p1")])

    with pytest.raises(AssetResolutionError, match="attempt ledger"):
        resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    assert list(outside.iterdir()) == []
    assert provider.download_calls == []


def test_concurrent_same_requirement_resolves_resume_one_pending_candidate(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    provider = DelayedThirdReservationProvider(
        "pexels",
        [candidate("pexels", "p1"), candidate("pexels", "p2"), candidate("pexels", "p3")],
    )
    asset_catalog = empty_catalog(tmp_path, [provider])

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(resolve_assets, texture_plan(), asset_catalog)
        assert provider.third_download_started.wait(timeout=1)
        second = executor.submit(resolve_assets, texture_plan(), asset_catalog)
        manifests = [first.result(), second.result()]

    assert manifests[0].items[0].pending_id == manifests[1].items[0].pending_id
    assert manifests[0].items[0].provider_asset_id == "p3"
    assert len(provider.search_calls) == 1


@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_resolution_lock_rejects_in_root_inode_alias_without_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias_kind: str
) -> None:
    import os

    from src.asset_resolver.resolver import (
        AssetResolutionError,
        requirement_fingerprint,
        resolve_assets,
    )

    plan = texture_plan()
    first_requirement = plan.required_assets[0].model_copy(
        update={"slot_id": "serum-a"}
    )
    second_requirement = plan.required_assets[0].model_copy(
        update={"slot_id": "serum-b"}
    )
    plan.required_assets = [first_requirement, second_requirement]
    lock_root = (
        tmp_path
        / "incoming"
        / "external"
        / "run-42"
        / ".resolution-locks"
    )
    lock_root.mkdir(parents=True)

    def lock_path(requirement: AssetRequirement) -> Path:
        fingerprint = requirement_fingerprint(requirement)
        identity = f"{requirement.slot_id}\0{fingerprint}"
        return lock_root / f"{hashlib.sha256(identity.encode()).hexdigest()}.lock"

    first_lock = lock_path(first_requirement)
    second_lock = lock_path(second_requirement)
    first_lock.touch()
    if alias_kind == "symlink":
        second_lock.symlink_to(first_lock.name)
    else:
        os.link(first_lock, second_lock)
    original_flock = __import__("fcntl").flock
    held_inodes: set[tuple[int, int]] = set()

    def nonblocking_deadlock_guard(descriptor: int, operation: int) -> None:
        identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
        if operation & __import__("fcntl").LOCK_UN:
            held_inodes.discard(identity)
            original_flock(descriptor, operation)
            return
        if identity in held_inodes:
            raise RuntimeError("resolution lock alias would self-deadlock")
        original_flock(descriptor, operation)
        held_inodes.add(identity)

    monkeypatch.setattr(
        "src.asset_resolver.resolver.fcntl.flock",
        nonblocking_deadlock_guard,
    )
    provider = FakeProvider("pexels", [candidate("pexels", "p1")])

    with pytest.raises(
        AssetResolutionError,
        match=r"resolution lock.*(symlink|hard.?link|alias)",
    ):
        resolve_assets(plan, empty_catalog(tmp_path, [provider]))


def test_resolution_lock_revalidates_path_after_blocking_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcntl
    import os

    from src.asset_resolver.resolver import (
        AssetResolutionError,
        _resolution_lock,
        requirement_fingerprint,
    )

    catalog = empty_catalog(tmp_path, [])
    requirement = texture_plan().required_assets[0]
    fingerprint = requirement_fingerprint(requirement)
    lock_name = hashlib.sha256(
        f"{requirement.slot_id}\0{fingerprint}".encode()
    ).hexdigest()
    lock_path = catalog.incoming_root / ".resolution-locks" / f"{lock_name}.lock"
    original_flock = fcntl.flock
    path_replaced = False
    lock_operations: list[int] = []

    def replace_path_before_lock_acquisition(
        descriptor: int, operation: int
    ) -> None:
        nonlocal path_replaced
        lock_operations.append(operation)
        if operation & fcntl.LOCK_EX and not path_replaced:
            lock_path.unlink()
            lock_path.touch()
            path_replaced = True
        original_flock(descriptor, operation)

    monkeypatch.setattr(
        "src.asset_resolver.resolver.fcntl.flock",
        replace_path_before_lock_acquisition,
    )
    entered_critical_section = False

    with pytest.raises(AssetResolutionError, match="resolution lock.*changed"):
        with _resolution_lock(catalog, requirement, fingerprint, set()):
            entered_critical_section = True

    assert path_replaced
    assert not entered_critical_section
    assert lock_operations[-1] & fcntl.LOCK_UN
    assert os.lstat(lock_path).st_nlink == 1


def test_resolver_rejects_non_allowlisted_candidate_urls_before_download(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from src.asset_resolver.resolver import AssetResolutionError, resolve_assets

    forged = replace(
        candidate("pexels", "p1"),
        source_file_url="https://evil.test/payload.png",
    )
    provider = FakeProvider("pexels", [forged])

    with pytest.raises(AssetResolutionError):
        resolve_assets(texture_plan(), empty_catalog(tmp_path, [provider]))

    assert provider.record_calls == []
    assert provider.download_calls == []
    run_root = tmp_path / "incoming" / "external" / "run-42"
    assert list(run_root.glob("*.json")) == []
    assert not (run_root / ".attempt-ledgers").exists()


def test_catalog_rejects_incoming_external_symlink_outside_root(tmp_path: Path) -> None:
    from src.asset_resolver.catalog import CatalogError

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "external").symlink_to(outside, target_is_directory=True)

    with pytest.raises(CatalogError, match="incoming/external"):
        empty_catalog(tmp_path, [])


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

    audits = list(
        (tmp_path / "incoming" / "external" / "run-42").glob(
            "serum-slot-*.json"
        )
    )
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

    audits = list(
        (tmp_path / "incoming" / "external" / "run-42").glob(
            "serum-slot-*.json"
        )
    )
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

    assert list(
        (tmp_path / "incoming" / "external" / "run-42").glob(
            "serum-slot-*.json"
        )
    ) == []


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

    audits = list(
        (tmp_path / "incoming" / "external" / "run-42").glob(
            "serum-slot-*.json"
        )
    )
    assert len(audits) == 1


def test_cross_run_id_url_dedupe_occurs_before_three_attempt_cap(
    tmp_path: Path,
) -> None:
    from src.asset_resolver.resolver import resolve_assets

    old_provider = FakeProvider(
        "pexels",
        [candidate("pexels", f"p{index}") for index in range(3)],
    )
    resolve_assets(
        texture_plan(), empty_catalog(tmp_path, [old_provider], run_id="run-old")
    )
    new_provider = FakeProvider(
        "pexels",
        [candidate("pexels", f"p{index}") for index in range(4)],
    )

    manifest = resolve_assets(
        texture_plan(), empty_catalog(tmp_path, [new_provider], run_id="run-new")
    )

    assert [item.provider_asset_id for item in new_provider.download_calls] == ["p3"]
    assert manifest.items[0].provider_asset_id == "p3"
    assert manifest.items[0].candidate_rank == 4
