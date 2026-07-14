from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import struct
from pathlib import Path

import pytest
from PIL import Image

from src.editorial_carousel.strategy import ASSET_ADAPTER, build_visual_plan
from src.schemas.assets import AssetManifest, AssetManifestItem, AssetSearchReport
from src.schemas.content_contract import ContentContract
from src.schemas.render_manifest import FontLoadReport, RenderManifest, RenderedPage
from src.schemas.render_qa import RenderQAIssue


EXPECTED_FONTS = ["Source Han Serif SC", "Source Han Sans SC", "Bodoni Moda"]


def _contract() -> ContentContract:
    return ContentContract.model_validate(
        {
            "audience": "通勤女性",
            "trigger_situation": "早高峰上班前",
            "decision_problem": "防晒和底妆如何不打架",
            "first_screen_promise": "通勤前3步避开防晒搓泥",
            "screenshot_asset": "防晒与底妆搭配清单",
            "proof_asset": "产品质地实拍",
            "visual_mode": "text_plus_real_proof",
            "content_job": "diagnose_and_adjust",
            "primary_visual_family": "face_zone_map",
            "primary_visual_subject": "face_map",
            "proof_mode": "product_texture",
            "recommended_frame_count": 6,
        }
    )


def _plan():
    return build_visual_plan(_contract(), recent_signatures=[])


def _storyboards():
    plan = _plan()
    requirements = {(item.layout, item.role): item for item in plan.required_assets}
    frames = []
    for index, planned in enumerate(plan.frame_plan):
        semantic_role = planned.asset_roles[0]
        concrete_role = ASSET_ADAPTER[(planned.layout, semantic_role)][0]
        requirement = requirements[(planned.layout, concrete_role)]
        frames.append(
            {
                "frame_id": planned.frame_id,
                "role": planned.role,
                "layout": planned.layout,
                "headline": (
                    _contract().first_screen_promise
                    if index == 0
                    else planned.purpose
                ),
                "kicker": "分区护肤",
                "content_blocks": [
                    {"block_type": "text", "body": planned.purpose}
                ],
                "emphasis": ["分区"],
                "visual_slots": [
                    {
                        "slot_id": requirement.slot_id,
                        "role": semantic_role,
                        "semantic_tags": ["skincare"],
                    }
                ],
                "footer": "按肤感微调",
            }
        )
    return frames


def _png(width=1080, height=1440):
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I4sII", 13, b"IHDR", width, height)
        + b"\x08\x02\x00\x00\x00"
    )


def _asset_file(path: Path, width: int, height: int):
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"></svg>',
        encoding="utf-8",
    )


def _valid_png(width=1080, height=1440, color=(247, 242, 234)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _fixtures(root: Path):
    plan = _plan()
    frames = _storyboards()
    image_dir = root / "20260714-beauty-skincare-test" / "images"
    image_dir.mkdir(parents=True)

    items = []
    for index, requirement in enumerate(plan.required_assets):
        path = image_dir / f"asset-{index}.svg"
        _asset_file(path, requirement.min_width, requirement.min_height)
        items.append(
            AssetManifestItem(
                slot_id=requirement.slot_id,
                role=requirement.role,
                layout=requirement.layout,
                status="active",
                path=str(path),
                asset_id=f"asset-{index}",
                source_type="local_catalog",
                license="project-owned",
                width=requirement.min_width,
                height=requirement.min_height,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )

    requirements_by_slot = {item.slot_id: item for item in plan.required_assets}
    pages = []
    for index, frame in enumerate(frames, start=1):
        filename = (
            "01-cover.png"
            if index == 1
            else f"{index:02d}-{frame['role'].replace('_', '-')}.png"
        )
        path = image_dir / filename
        page_bytes = _valid_png()
        path.write_bytes(page_bytes)
        probe = _probe_for_frame(frame)
        for geometry in probe["asset_results"]:
            requirement = requirements_by_slot[geometry["slot_id"]]
            geometry.update(
                natural_width=requirement.min_width,
                natural_height=requirement.min_height,
                rendered_width=requirement.min_width / 3,
                rendered_height=requirement.min_height / 3,
            )
        pages.append(
            RenderedPage(
                frame_id=frame["frame_id"],
                role=frame["role"],
                layout=frame["layout"],
                path=str(path),
                width=1080,
                height=1440,
                sha256=hashlib.sha256(page_bytes).hexdigest(),
                probe=probe,
            )
        )

    contact_sheet = image_dir / "contact-sheet.png"
    contact_bytes = _valid_png(1320, 1145)
    contact_sheet.write_bytes(contact_bytes)
    asset_manifest = AssetManifest(
        items=items,
        search_report=AssetSearchReport(
            search_triggered=False,
            queries=[],
            provider_reports=[],
            selection_reasons={},
        ),
    )
    render_manifest = RenderManifest(
        pages=pages,
        fonts=FontLoadReport(
            all_loaded=True,
            computed_families=EXPECTED_FONTS,
        ),
        contact_sheet_path=str(contact_sheet),
        contact_sheet_sha256=hashlib.sha256(contact_bytes).hexdigest(),
        contact_sheet_page_sha256=[page.sha256 for page in pages],
        source_asset_sha256={item.slot_id: item.sha256 for item in items},
    )
    package = {
        "draft_id": "draft_001",
        "topic_id": "tp_001",
        "title": "通勤底妆不搓泥",
        "content": "先给防晒成膜时间，再上底妆。",
        "cover_copy": "通勤底妆不搓泥",
        "storyboards": frames,
    }
    return package, asset_manifest, render_manifest


def _rule_ids(issues):
    return [issue.rule_id for issue in issues]


def test_render_qa_issue_rejects_unstable_rule_id():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RenderQAIssue(
            rule_id="Rendered Asset Hash Mismatch",
            message="unstable identifier",
            location_hint="render_manifest.source_asset_sha256",
        )


def test_render_qa_accepts_complete_editorial_manifests_and_labels_proxy_metrics(
    tmp_path,
):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    issues = validate_render(package, assets, manifest)

    assert issues == []

    from src.nodes.node_p_render_qa import render_qa_node

    result = render_qa_node(
        {
            "publish_package": package,
            "visual_plan": _plan(),
            "asset_manifest": assets,
            "render_manifest": manifest,
        }
    )["render_qa_result"]
    assert result.metric_kind == "deterministic_proxy"
    assert "do not replace human aesthetic review" in result.metric_note
    assert {
        result.editorial_quality,
        result.beauty_category_fit,
        result.visual_hierarchy,
        result.saveability,
        result.cross_page_consistency,
        result.template_stiffness,
    } <= set(range(101))


def test_render_qa_rejects_source_hash_mismatch(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    manifest = manifest.model_copy(
        update={
            "source_asset_sha256": {
                **manifest.source_asset_sha256,
                assets.items[0].slot_id: "b" * 64,
            }
        }
    )

    issues = validate_render(package, assets, manifest)

    issue = next(
        item for item in issues if item.rule_id == "rendered_asset_hash_mismatch"
    )
    assert issue.frame_id == "cover"
    assert issue.location_hint.endswith(assets.items[0].slot_id)


def test_render_qa_rejects_visible_text_mismatch(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)
    probe = pages[1].probe.model_copy(deep=True)
    probe.text_results[-1].text = "被改写的页脚"
    pages[1] = pages[1].model_copy(update={"probe": probe})
    manifest = manifest.model_copy(update={"pages": pages})

    issues = validate_render(package, assets, manifest)

    issue = next(
        item for item in issues if item.rule_id == "rendered_visible_text_mismatch"
    )
    assert issue.frame_id == "baseline"
    assert issue.location_hint == "render_manifest.pages[1].probe.text_results"


def test_render_qa_rejects_font_fallback_dimensions_and_overflow(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    wrong_size = _valid_png(1080, 1080)
    Path(manifest.pages[1].path).write_bytes(wrong_size)
    pages = list(manifest.pages)
    pages[1] = pages[1].model_copy(
        update={"sha256": hashlib.sha256(wrong_size).hexdigest()}
    )
    probe = pages[2].probe.model_copy(deep=True)
    probe.text_results[1].overflow = True
    pages[2] = pages[2].model_copy(update={"probe": probe})
    manifest = manifest.model_copy(
        update={
            "pages": pages,
            "fonts": manifest.fonts.model_copy(
                update={
                    "all_loaded": False,
                    "computed_families": ["Arial"],
                }
            )
        }
    )

    issues = validate_render(package, assets, manifest)

    assert "font_family_mismatch" in _rule_ids(issues)
    assert "png_dimensions_invalid" in _rule_ids(issues)
    overflow = next(item for item in issues if item.rule_id == "text_overflow")
    assert overflow.frame_id == "applicable-case"


def test_render_qa_rejects_missing_provenance_and_asset_stretching(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    first = assets.items[0]
    _asset_file(Path(first.path), first.width + 1, first.height)
    broken = first.model_copy(
        update={
            "source_type": "",
            "license": "",
            "sha256": hashlib.sha256(Path(first.path).read_bytes()).hexdigest(),
        }
    )
    assets = assets.model_copy(update={"items": [broken, *assets.items[1:]]})
    manifest = manifest.model_copy(
        update={
            "source_asset_sha256": {
                **manifest.source_asset_sha256,
                broken.slot_id: broken.sha256,
            }
        }
    )

    issues = validate_render(package, assets, manifest)

    assert "asset_source_type_provenance_missing" in _rule_ids(issues)
    assert "asset_license_provenance_missing" in _rule_ids(issues)
    stretching = next(
        item for item in issues if item.rule_id == "asset_stretching_detected"
    )
    assert stretching.frame_id == "cover"


def test_render_qa_rejects_missing_contact_sheet_and_partial_output(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    Path(manifest.pages[2].path).unlink()
    Path(manifest.contact_sheet_path).unlink()

    issues = validate_render(package, assets, manifest)

    assert "partial_render_output" not in _rule_ids(issues)
    missing = next(item for item in issues if item.rule_id == "rendered_page_missing")
    assert missing.frame_id == "applicable-case"
    assert "contact_sheet_missing" in _rule_ids(issues)


def test_render_qa_rejects_manifest_page_order_drift(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)
    pages[1], pages[2] = pages[2], pages[1]
    manifest = manifest.model_copy(update={"pages": pages})

    issues = validate_render(package, assets, manifest)

    drift = [
        item for item in issues if item.rule_id == "rendered_page_frame_id_mismatch"
    ]
    assert [item.frame_id for item in drift] == ["baseline", "applicable-case"]


def test_render_qa_routes_each_atomic_failure_to_r1(tmp_path):
    import src.nodes.node_p_render_qa as module

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)
    probe = pages[1].probe.model_copy(deep=True)
    probe.text_results[1].overflow = True
    pages[1] = pages[1].model_copy(update={"probe": probe})
    manifest = manifest.model_copy(update={"pages": pages})

    result = module.render_qa_node(
        {
            "publish_package": package,
            "visual_plan": _plan(),
            "asset_manifest": assets,
            "render_manifest": manifest,
        }
    )

    assert result["render_qa_result"].passed is False
    assert result["decision_output"].next_node == "R1_REFLECTOR"
    tasks = result[
        "decision_output"
    ].normalized_input.r1_input.editorial_tasks.mandatory
    assert len(tasks) == len(result["render_qa_result"].issues)
    assert {task.source for task in tasks} == {"render_qa"}
    assert module.route_after_render_qa(result) == "r1_reflector"


@pytest.mark.parametrize("metric", [
    "editorial_quality",
    "beauty_category_fit",
    "visual_hierarchy",
    "saveability",
    "cross_page_consistency",
    "template_stiffness",
])
def test_quality_proxy_metrics_are_deterministic_measured_facts(tmp_path, metric):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, manifest = _fixtures(tmp_path)
    state = {
        "publish_package": package,
        "visual_plan": _plan(),
        "asset_manifest": assets,
        "render_manifest": manifest,
    }

    first = render_qa_node(state)["render_qa_result"]
    second = render_qa_node(state)["render_qa_result"]

    assert getattr(first, metric) == getattr(second, metric)


def test_quality_proxy_hierarchy_is_not_a_relabelled_hard_failure_count(tmp_path):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, manifest = _fixtures(tmp_path)
    state = {
        "publish_package": package,
        "visual_plan": _plan(),
        "asset_manifest": assets,
        "render_manifest": manifest,
    }
    baseline = render_qa_node(state)["render_qa_result"]

    Path(manifest.pages[1].path).write_bytes(_png(1080, 1080))
    degraded = render_qa_node(state)["render_qa_result"]

    assert degraded.passed is False
    assert baseline.metrics_available is True
    assert degraded.metrics_available is False
    assert degraded.visual_hierarchy is None


def test_render_qa_rejects_truncated_png_with_valid_ihdr_prefix(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    Path(manifest.pages[0].path).write_bytes(_png())

    issues = validate_render(package, assets, manifest)

    assert any(issue.rule_id == "rendered_page_corrupt" for issue in issues)


def test_render_qa_rejects_decodable_same_size_page_tamper_by_hash(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    path = Path(manifest.pages[0].path)
    original = _valid_png(color=(247, 242, 234))
    path.write_bytes(original)
    page = manifest.pages[0].model_copy(
        update={"sha256": hashlib.sha256(original).hexdigest()}
    )
    manifest = manifest.model_copy(update={"pages": [page, *manifest.pages[1:]]})
    path.write_bytes(_valid_png(color=(41, 38, 37)))

    issues = validate_render(package, assets, manifest)

    assert any(issue.rule_id == "rendered_page_hash_mismatch" for issue in issues)


def test_render_qa_rejects_missing_persisted_probe_attestation(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    page = manifest.pages[0].model_copy(update={"probe": None})
    manifest = manifest.model_copy(update={"pages": [page, *manifest.pages[1:]]})

    issues = validate_render(package, assets, manifest)

    assert any(issue.rule_id == "page_probe_missing" for issue in issues)


def test_render_qa_reports_corrupt_contact_sheet_atomically(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    Path(manifest.contact_sheet_path).write_bytes(_png(1320, 1145))

    issues = validate_render(package, assets, manifest)
    contact_issues = [
        issue for issue in issues if issue.location_hint == "render_manifest.contact_sheet_path"
    ]

    assert [issue.rule_id for issue in contact_issues] == ["contact_sheet_corrupt"]


def test_render_qa_rejects_duplicate_asset_manifest_slot_before_mapping(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    duplicate = assets.items[0].model_copy()
    assets = assets.model_copy(update={"items": [*assets.items, duplicate]})

    issues = validate_render(package, assets, manifest)

    issue = next(item for item in issues if item.rule_id == "duplicate_asset_manifest_slot_id")
    assert issue.location_hint == f"asset_manifest.items[{len(assets.items) - 1}].slot_id"


def test_missing_page_produces_one_atomic_issue_not_count_and_partial(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    manifest = manifest.model_copy(update={"pages": manifest.pages[:-1]})

    issues = validate_render(package, assets, manifest)
    missing = [
        issue.rule_id
        for issue in issues
        if issue.frame_id == package["storyboards"][-1]["frame_id"]
    ]

    assert missing == ["rendered_page_missing"]
    assert "rendered_page_count_mismatch" not in _rule_ids(issues)
    assert "partial_render_output" not in _rule_ids(issues)


def test_external_provenance_fields_are_atomic_and_nonduplicated(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    external = assets.items[0].model_copy(
        update={
            "source_type": "stock_photo",
            "provider": None,
            "source_url": None,
            "author": None,
        }
    )
    assets = assets.model_copy(update={"items": [external, *assets.items[1:]]})

    issues = validate_render(package, assets, manifest)
    provenance = [
        (issue.rule_id, issue.location_hint)
        for issue in issues
        if issue.frame_id == "cover" and "provenance" in issue.rule_id
    ]

    assert provenance == [
        ("asset_provider_provenance_missing", "asset_manifest.items[0].provider"),
        ("asset_source_url_provenance_missing", "asset_manifest.items[0].source_url"),
        ("asset_author_provenance_missing", "asset_manifest.items[0].author"),
    ]


def test_pre_review_render_qa_allows_audited_pending_external_asset(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    first = assets.items[0].model_copy(
        update={
            "status": "pending_external",
            "source_type": "stock_photo",
            "provider": "pexels",
            "provider_asset_id": "42",
            "source_url": "https://www.pexels.com/photo/42",
            "source_file_url": "https://images.pexels.com/photos/42/image.jpeg",
            "author": "Photographer",
            "pending_id": "run-slot-pexels-42",
            "metadata_path": str(tmp_path / "pending.json"),
            "run_id": "run",
            "unresolved_safety_checks": ["allowed_for_publishing"],
        }
    )
    assets = assets.model_copy(update={"items": [first, *assets.items[1:]]})

    strict_issues = validate_render(package, assets, manifest)
    preview_issues = validate_render(
        package,
        assets,
        manifest,
        allow_pending_external=True,
    )

    assert "asset_publishing_review_not_approved" in _rule_ids(strict_issues)
    assert preview_issues == []


def test_approved_external_asset_accepts_fully_resolved_safety_review(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    first = assets.items[0].model_copy(
        update={
            "source_type": "stock_photo",
            "provider": "unsplash",
            "provider_asset_id": "approved-42",
            "source_url": "https://unsplash.com/photos/approved-42",
            "source_file_url": "https://images.unsplash.com/approved-42",
            "author": "Photographer",
            "review_status": "approved",
            "review_disposition": "approved_for_publishing",
            "unresolved_safety_checks": [
                "has_logo",
                "has_watermark",
                "allowed_for_publishing",
            ],
            "safety_review_decisions": {
                "has_logo": False,
                "has_watermark": False,
                "allowed_for_publishing": True,
            },
            "safety_reviewed_at": "2026-07-14T12:00:00+00:00",
        }
    )
    assets = assets.model_copy(update={"items": [first, *assets.items[1:]]})

    issues = validate_render(package, assets, manifest, _plan())

    assert "asset_safety_checks_unresolved" not in _rule_ids(issues)


def test_editorial_state_missing_render_manifest_never_falls_back_to_legacy(tmp_path):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, _manifest = _fixtures(tmp_path)
    state = {
        "publish_package": package,
        "visual_plan": _plan(),
        "asset_manifest": assets,
        "render_manifest": None,
        "trends": [{"topic_id": "tp_001", "content_contract": _contract()}],
    }

    result = render_qa_node(state)

    assert [issue.rule_id for issue in result["render_qa_result"].issues] == [
        "render_manifest_missing"
    ]


def test_editorial_state_missing_visual_plan_never_falls_back_to_legacy(tmp_path):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, manifest = _fixtures(tmp_path)
    result = render_qa_node(
        {
            "publish_package": package,
            "asset_manifest": assets,
            "render_manifest": manifest,
        }
    )

    assert [issue.rule_id for issue in result["render_qa_result"].issues] == [
        "visual_plan_missing"
    ]


def test_render_r1_task_identity_does_not_depend_on_issue_order():
    from src.nodes.node_p_render_qa import _build_r1_decision

    cover = RenderQAIssue(
        rule_id="rendered_page_hash_mismatch",
        message="page mismatch",
        location_hint="render_manifest.pages[0].sha256",
        frame_id="cover",
    )
    unrelated = RenderQAIssue(
        rule_id="contact_sheet_missing",
        message="contact missing",
        location_hint="render_manifest.contact_sheet_path",
    )
    package = {"draft_id": "draft", "storyboards": []}

    alone = _build_r1_decision(package, [cover]).normalized_input.r1_input.editorial_tasks.mandatory[0].task_id
    reordered = _build_r1_decision(package, [unrelated, cover]).normalized_input.r1_input.editorial_tasks.mandatory[1].task_id

    assert alone == reordered


def _probe_for_frame(
    frame,
    *,
    headline_size=64.0,
    body_size=29.0,
    asset_dimensions=None,
):
    texts = []
    for role, text in [
        ("kicker", frame.get("kicker")),
        ("headline", frame.get("headline")),
    ]:
        if text:
            texts.append(
                {
                    "role": role,
                    "text": text,
                    "visible": True,
                    "overflow": False,
                    "ink_clipped": False,
                    "layout_clipped": False,
                    "font_family": (
                        "Source Han Serif SC" if role == "headline" else "Source Han Sans SC"
                    ),
                    "font_size": headline_size if role == "headline" else 25.0,
                    "line_height": (headline_size * 1.17 if role == "headline" else 32.5),
                    "line_count": 1,
                    "x": 84.0,
                    "y": 84.0,
                    "width": 600.0,
                    "height": 80.0,
                }
            )
    for block_index, block in enumerate(frame["content_blocks"]):
        for field in ("heading", "body"):
            text = block.get(field)
            if text:
                texts.append(
                    {
                        "role": f"content_blocks[{block_index}].{field}",
                        "text": text,
                        "visible": True,
                        "overflow": False,
                        "ink_clipped": False,
                        "layout_clipped": False,
                        "font_family": "Source Han Sans SC",
                        "font_size": body_size,
                        "line_height": body_size * 1.45,
                        "line_count": 1,
                        "x": 84.0,
                        "y": 300.0,
                        "width": 500.0,
                        "height": 50.0,
                    }
                )
        for item_index, text in enumerate(block.get("items") or []):
            texts.append(
                {
                    "role": f"content_blocks[{block_index}].items[{item_index}]",
                    "text": text,
                    "visible": True,
                    "overflow": False,
                    "ink_clipped": False,
                    "layout_clipped": False,
                    "font_family": "Source Han Sans SC",
                    "font_size": body_size,
                    "line_height": body_size * 1.45,
                    "line_count": 1,
                    "x": 84.0,
                    "y": 300.0,
                    "width": 500.0,
                    "height": 50.0,
                }
            )
    if frame.get("footer"):
        texts.append(
            {
                "role": "footer",
                "text": frame["footer"],
                "visible": True,
                "overflow": False,
                "ink_clipped": False,
                "layout_clipped": False,
                "font_family": "Source Han Sans SC",
                "font_size": 22.0,
                "line_height": 29.7,
                "line_count": 1,
                "x": 84.0,
                "y": 1300.0,
                "width": 500.0,
                "height": 40.0,
            }
        )
    requirements = {item.slot_id: item for item in _plan().required_assets}
    asset_dimensions = asset_dimensions or {}
    return {
        "canvas_width": 1080,
        "canvas_height": 1440,
        "safe_margin": 84.0,
        "text_results": texts,
        "asset_results": [
            {
                "slot_id": slot["slot_id"],
                "natural_width": asset_dimensions.get(
                    slot["slot_id"],
                    (
                        requirements[slot["slot_id"]].min_width,
                        requirements[slot["slot_id"]].min_height,
                    ),
                )[0],
                "natural_height": asset_dimensions.get(
                    slot["slot_id"],
                    (
                        requirements[slot["slot_id"]].min_width,
                        requirements[slot["slot_id"]].min_height,
                    ),
                )[1],
                "rendered_width": asset_dimensions.get(
                    slot["slot_id"],
                    (
                        requirements[slot["slot_id"]].min_width,
                        requirements[slot["slot_id"]].min_height,
                    ),
                )[0] / 3,
                "rendered_height": asset_dimensions.get(
                    slot["slot_id"],
                    (
                        requirements[slot["slot_id"]].min_width,
                        requirements[slot["slot_id"]].min_height,
                    ),
                )[1] / 3,
                "object_fit": "contain",
                "cropped": False,
                "aspect_ratio_error": 0.0,
            }
            for slot in frame.get("visual_slots") or []
        ],
        "issues": [],
    }


def _manifest_with_probes(manifest, package, assets=None, **probe_overrides):
    asset_dimensions = {
        item.slot_id: (item.width, item.height) for item in (assets.items if assets else [])
    }
    return manifest.model_copy(
        update={
            "pages": [
                page.model_copy(
                    update={
                        "probe": _probe_for_frame(
                            frame,
                            asset_dimensions=asset_dimensions,
                            **probe_overrides,
                        )
                    }
                )
                for page, frame in zip(
                    manifest.pages, package["storyboards"], strict=True
                )
            ]
        }
    )


def _metric_result(package, assets, manifest, plan=None):
    from src.nodes.node_p_render_qa import render_qa_node

    return render_qa_node(
        {
            "publish_package": package,
            "visual_plan": plan or _plan(),
            "asset_manifest": assets,
            "render_manifest": manifest,
        }
    )["render_qa_result"]


def _assert_proxy_available(*results):
    assert all(result.passed is True for result in results)
    assert all(result.metrics_available is True for result in results)


def test_proxy_editorial_quality_rewards_lower_measured_text_density(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    manifest = _manifest_with_probes(manifest, package)
    concise = _metric_result(package, assets, manifest)

    dense_package = deepcopy(package)
    dense_package["storyboards"][1]["content_blocks"][0]["body"] *= 6
    dense_manifest = _manifest_with_probes(manifest, dense_package)
    dense = _metric_result(dense_package, assets, dense_manifest)

    _assert_proxy_available(concise, dense)
    assert concise.editorial_quality > dense.editorial_quality


def test_proxy_beauty_category_fit_rewards_asset_dimension_headroom(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    baseline = _metric_result(package, assets, _manifest_with_probes(manifest, package))
    first = assets.items[0]
    _asset_file(Path(first.path), first.width * 2, first.height * 2)
    larger = first.model_copy(
        update={
            "width": first.width * 2,
            "height": first.height * 2,
            "sha256": hashlib.sha256(Path(first.path).read_bytes()).hexdigest(),
        }
    )
    assets = assets.model_copy(update={"items": [larger, *assets.items[1:]]})
    manifest = manifest.model_copy(
        update={
            "source_asset_sha256": {
                **manifest.source_asset_sha256,
                larger.slot_id: larger.sha256,
            }
        }
    )

    headroom = _metric_result(
        package, assets, _manifest_with_probes(manifest, package, assets=assets)
    )

    _assert_proxy_available(baseline, headroom)
    assert headroom.beauty_category_fit > baseline.beauty_category_fit


def test_proxy_visual_hierarchy_rewards_headline_body_scale_separation(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    flat = _metric_result(
        package,
        assets,
        _manifest_with_probes(manifest, package, headline_size=40.0, body_size=34.0),
    )
    hierarchical = _metric_result(
        package,
        assets,
        _manifest_with_probes(manifest, package, headline_size=64.0, body_size=29.0),
    )

    _assert_proxy_available(flat, hierarchical)
    assert hierarchical.visual_hierarchy > flat.visual_hierarchy


def test_proxy_saveability_rewards_more_actionable_checklist_items(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    sparse_package = deepcopy(package)
    sparse_package["storyboards"][-1]["content_blocks"] = [
        {"block_type": "checklist", "items": ["只做一项"]}
    ]
    rich_package = deepcopy(package)
    rich_package["storyboards"][-1]["content_blocks"] = [
        {"block_type": "checklist", "items": ["第一项", "第二项", "第三项", "第四项"]}
    ]

    sparse = _metric_result(
        sparse_package, assets, _manifest_with_probes(manifest, sparse_package)
    )
    rich = _metric_result(
        rich_package, assets, _manifest_with_probes(manifest, rich_package)
    )

    _assert_proxy_available(sparse, rich)
    assert rich.saveability > sparse.saveability


def test_proxy_cross_page_consistency_penalizes_measured_type_scale_variance(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    consistent_manifest = _manifest_with_probes(manifest, package, headline_size=64.0)
    varied_pages = list(consistent_manifest.pages)
    varied_pages[2] = varied_pages[2].model_copy(
        update={"probe": _probe_for_frame(package["storyboards"][2], headline_size=44.0)}
    )
    varied_manifest = consistent_manifest.model_copy(update={"pages": varied_pages})

    consistent = _metric_result(package, assets, consistent_manifest)
    varied = _metric_result(package, assets, varied_manifest)

    _assert_proxy_available(consistent, varied)
    assert consistent.cross_page_consistency > varied.cross_page_consistency


def test_proxy_template_stiffness_penalizes_nonadjacent_layout_reuse(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    diverse = _metric_result(package, assets, _manifest_with_probes(manifest, package))
    repeated_package = deepcopy(package)
    repeated_plan = deepcopy(_plan())
    repeated_package["storyboards"][1]["layout"] = "three_state_diagnostic"
    repeated_package["storyboards"][1]["visual_slots"][0]["role"] = "comparison"
    repeated_plan.frame_plan[1].layout = "three_state_diagnostic"
    repeated_plan.frame_plan[1].asset_roles = ["comparison"]
    slot_id = repeated_package["storyboards"][1]["visual_slots"][0]["slot_id"]
    requirement = next(
        item for item in repeated_plan.required_assets if item.slot_id == slot_id
    )
    requirement.layout = "three_state_diagnostic"
    requirement.role = "skin_detail"
    repeated_items = list(assets.items)
    item_index = next(
        index for index, item in enumerate(repeated_items) if item.slot_id == slot_id
    )
    repeated_items[item_index] = repeated_items[item_index].model_copy(
        update={"layout": "three_state_diagnostic", "role": "skin_detail"}
    )
    repeated_assets = assets.model_copy(update={"items": repeated_items})
    repeated_pages = list(manifest.pages)
    repeated_pages[1] = repeated_pages[1].model_copy(
        update={"layout": "three_state_diagnostic"}
    )
    repeated_manifest = manifest.model_copy(update={"pages": repeated_pages})

    repeated = _metric_result(
        repeated_package,
        repeated_assets,
        _manifest_with_probes(repeated_manifest, repeated_package),
        repeated_plan,
    )

    _assert_proxy_available(diverse, repeated)
    assert repeated.template_stiffness > diverse.template_stiffness


def test_render_qa_checks_source_snapshot_against_requirement_minimums(tmp_path):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, manifest = _fixtures(tmp_path)
    first = assets.items[0]
    _asset_file(Path(first.path), 100, 100)
    undersized = first.model_copy(
        update={
            "width": 100,
            "height": 100,
            "sha256": hashlib.sha256(Path(first.path).read_bytes()).hexdigest(),
        }
    )
    assets = assets.model_copy(update={"items": [undersized, *assets.items[1:]]})
    manifest = manifest.model_copy(
        update={
            "source_asset_sha256": {
                **manifest.source_asset_sha256,
                undersized.slot_id: undersized.sha256,
            }
        }
    )

    result = render_qa_node(
        {
            "publish_package": package,
            "visual_plan": _plan(),
            "asset_manifest": assets,
            "render_manifest": _manifest_with_probes(manifest, package),
        }
    )

    assert any(
        issue.rule_id == "asset_min_dimensions_unmet"
        for issue in result["render_qa_result"].issues
    )


def test_render_qa_uses_persisted_dom_geometry_for_stretch_detection(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    manifest = _manifest_with_probes(manifest, package)
    first_page = manifest.pages[0]
    probe = deepcopy(first_page.probe)
    probe["asset_results"][0].update(
        rendered_width=500.0,
        rendered_height=500.0,
        aspect_ratio_error=0.25,
    )
    first_page = first_page.model_copy(update={"probe": probe})
    manifest = manifest.model_copy(update={"pages": [first_page, *manifest.pages[1:]]})

    result = _metric_result(package, assets, manifest)

    assert any(
        issue.rule_id == "asset_render_stretched" for issue in result.issues
    )


def _probe_dict(page):
    probe = page.probe
    return probe.model_dump(mode="python") if hasattr(probe, "model_dump") else deepcopy(probe)


def test_probe_assets_must_match_each_frame_slots_exactly_once(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)

    missing_probe = _probe_dict(pages[0])
    missing_probe["asset_results"] = []
    pages[0] = pages[0].model_copy(update={"probe": missing_probe})

    duplicate_probe = _probe_dict(pages[1])
    duplicate_probe["asset_results"].append(
        deepcopy(duplicate_probe["asset_results"][0])
    )
    pages[1] = pages[1].model_copy(update={"probe": duplicate_probe})

    extra_probe = _probe_dict(pages[2])
    extra_probe["asset_results"].append(
        {
            **deepcopy(extra_probe["asset_results"][0]),
            "slot_id": "unexpected-probe-slot",
        }
    )
    pages[2] = pages[2].model_copy(update={"probe": extra_probe})
    manifest = manifest.model_copy(update={"pages": pages})

    issues = validate_render(package, assets, manifest, _plan())
    probe_identity = [
        (issue.rule_id, issue.location_hint)
        for issue in issues
        if issue.rule_id
        in {
            "probe_asset_slot_missing",
            "duplicate_probe_asset_slot_id",
            "unexpected_probe_asset_slot",
        }
    ]

    assert probe_identity == [
        (
            "probe_asset_slot_missing",
            "render_manifest.pages[0].probe.asset_results.cover-beauty-subject",
        ),
        (
            "duplicate_probe_asset_slot_id",
            "render_manifest.pages[1].probe.asset_results[1].slot_id",
        ),
        (
            "unexpected_probe_asset_slot",
            "render_manifest.pages[2].probe.asset_results[1].slot_id",
        ),
    ]


def test_render_qa_recomputes_aspect_and_crop_from_raw_dom_geometry(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)
    probe = _probe_dict(pages[0])
    geometry = probe["asset_results"][0]
    geometry.update(
        rendered_width=500.0,
        rendered_height=500.0,
        object_fit="cover",
        cropped=False,
        aspect_ratio_error=0.0,
    )
    pages[0] = pages[0].model_copy(update={"probe": probe})
    manifest = manifest.model_copy(update={"pages": pages})

    issues = validate_render(package, assets, manifest, _plan())

    assert "asset_aspect_ratio_attestation_mismatch" in _rule_ids(issues)
    assert "asset_crop_attestation_mismatch" in _rule_ids(issues)
    assert "asset_render_stretched" in _rule_ids(issues)


def test_render_qa_rechecks_canvas_safe_margin_fonts_and_text_tokens(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    pages = list(manifest.pages)
    probe = _probe_dict(pages[0])
    probe["canvas_width"] = 1079
    probe["safe_margin"] = 80
    headline = next(
        item for item in probe["text_results"] if item["role"] == "headline"
    )
    headline["font_family"] = "Arial"
    headline["line_count"] = 3
    body = next(
        item for item in probe["text_results"] if item["role"].endswith(".body")
    )
    body["line_height"] = body["font_size"] * 1.2
    pages[0] = pages[0].model_copy(update={"probe": probe})
    manifest = manifest.model_copy(update={"pages": pages})

    issues = validate_render(package, assets, manifest, _plan())

    assert {
        "probe_canvas_geometry_mismatch",
        "probe_safe_margin_mismatch",
        "text_font_family_mismatch",
        "headline_line_count_invalid",
        "body_line_height_invalid",
    } <= set(_rule_ids(issues))


def test_duplicate_storyboard_slot_does_not_overwrite_or_hide_unrelated_asset_issue(
    tmp_path,
):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    package["storyboards"][1]["visual_slots"][0]["slot_id"] = package[
        "storyboards"
    ][0]["visual_slots"][0]["slot_id"]
    Path(assets.items[-1].path).write_bytes(b"corrupt asset")

    issues = validate_render(package, assets, manifest, _plan())

    assert "duplicate_storyboard_slot_id" in _rule_ids(issues)
    assert any(
        issue.rule_id == "asset_file_corrupt" and issue.frame_id == "save"
        for issue in issues
    )


def test_duplicate_asset_group_does_not_hide_unconflicted_item_audit(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    duplicate = assets.items[0].model_copy()
    unrelated = assets.items[2].model_copy(update={"license": ""})
    assets = assets.model_copy(
        update={"items": [assets.items[0], assets.items[1], unrelated, *assets.items[3:], duplicate]}
    )

    issues = validate_render(package, assets, manifest, _plan())

    assert "duplicate_asset_manifest_slot_id" in _rule_ids(issues)
    assert any(
        issue.rule_id == "asset_license_provenance_missing"
        and issue.frame_id == "applicable-case"
        for issue in issues
    )


def test_duplicate_asset_occurrences_each_keep_item_local_audits_and_unique_tasks(
    tmp_path,
):
    from src.nodes.node_p_render_qa import _build_r1_decision, validate_render

    package, assets, manifest = _fixtures(tmp_path)
    first = assets.items[0].model_copy(
        update={
            "source_type": "stock_photo",
            "license": "",
            "provider": None,
            "source_url": None,
            "author": None,
        }
    )
    second = assets.items[0].model_copy(
        update={
            "sha256": "f" * 64,
            "unresolved_safety_checks": ["has_logo"],
        }
    )
    duplicate_index = len(assets.items)
    assets = assets.model_copy(
        update={"items": [first, *assets.items[1:], second]}
    )

    issues = validate_render(package, assets, manifest, _plan())
    findings = {(issue.rule_id, issue.location_hint) for issue in issues}

    assert (
        "duplicate_asset_manifest_slot_id",
        f"asset_manifest.items[{duplicate_index}].slot_id",
    ) in findings
    assert (
        "asset_license_provenance_missing",
        "asset_manifest.items[0].license",
    ) in findings
    assert (
        "asset_provider_provenance_missing",
        "asset_manifest.items[0].provider",
    ) in findings
    assert (
        "asset_source_url_provenance_missing",
        "asset_manifest.items[0].source_url",
    ) in findings
    assert (
        "asset_author_provenance_missing",
        "asset_manifest.items[0].author",
    ) in findings
    assert (
        "asset_safety_checks_unresolved",
        f"asset_manifest.items[{duplicate_index}].unresolved_safety_checks",
    ) in findings
    assert (
        "asset_source_hash_mismatch",
        f"asset_manifest.items[{duplicate_index}].sha256",
    ) in findings

    tasks = _build_r1_decision(
        package, issues
    ).normalized_input.r1_input.editorial_tasks.mandatory
    task_ids = [task.task_id for task in tasks]
    assert len(task_ids) == len(set(task_ids))


def test_failed_render_qa_does_not_publish_proxy_metrics(tmp_path):
    package, assets, manifest = _fixtures(tmp_path)
    broken = manifest.pages[0].model_copy(update={"sha256": "f" * 64})
    manifest = manifest.model_copy(update={"pages": [broken, *manifest.pages[1:]]})

    result = _metric_result(package, assets, manifest)

    assert result.passed is False
    assert result.metrics_available is False
    assert result.editorial_quality is None
    assert result.beauty_category_fit is None
    assert result.visual_hierarchy is None
    assert result.saveability is None
    assert result.cross_page_consistency is None
    assert result.template_stiffness is None
