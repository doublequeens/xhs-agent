from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest

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


def _visible_text(frame):
    values = []
    if frame.get("kicker"):
        values.append(frame["kicker"])
    values.append(frame["headline"])
    for block in frame["content_blocks"]:
        if block.get("heading"):
            values.append(block["heading"])
        if block.get("body"):
            values.append(block["body"])
        values.extend(block.get("items") or [])
    if frame.get("footer"):
        values.append(frame["footer"])
    return values


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


def _fixtures(root: Path):
    plan = _plan()
    frames = _storyboards()
    image_dir = root / "20260714-beauty-skincare-test" / "images"
    image_dir.mkdir(parents=True)

    pages = []
    for index, frame in enumerate(frames, start=1):
        filename = (
            "01-cover.png"
            if index == 1
            else f"{index:02d}-{frame['role'].replace('_', '-')}.png"
        )
        path = image_dir / filename
        path.write_bytes(_png())
        pages.append(
            RenderedPage(
                frame_id=frame["frame_id"],
                role=frame["role"],
                layout=frame["layout"],
                path=str(path),
                width=1080,
                height=1440,
            )
        )

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

    contact_sheet = image_dir / "contact-sheet.png"
    contact_sheet.write_bytes(_png(1320, 1145))
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
        source_asset_sha256={item.slot_id: item.sha256 for item in items},
    )
    package = {
        "draft_id": "draft_001",
        "topic_id": "tp_001",
        "title": "通勤底妆不搓泥",
        "content": "先给防晒成膜时间，再上底妆。",
        "cover_copy": "通勤底妆不搓泥",
        "storyboards": frames,
        "rendered_visible_text": {
            frame["frame_id"]: _visible_text(frame) for frame in frames
        },
        "render_diagnostics": [],
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
    package["rendered_visible_text"]["baseline"][-1] = "被改写的页脚"

    issues = validate_render(package, assets, manifest)

    issue = next(
        item for item in issues if item.rule_id == "rendered_visible_text_mismatch"
    )
    assert issue.frame_id == "baseline"
    assert issue.location_hint == "publish_package.rendered_visible_text.baseline"


def test_render_qa_rejects_font_fallback_dimensions_and_overflow(tmp_path):
    from src.nodes.node_p_render_qa import validate_render

    package, assets, manifest = _fixtures(tmp_path)
    Path(manifest.pages[1].path).write_bytes(_png(1080, 1080))
    package["render_diagnostics"] = [
        {"frame_id": "applicable-case", "kind": "overflow", "role": "headline"}
    ]
    manifest = manifest.model_copy(
        update={
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

    assert "asset_provenance_missing" in _rule_ids(issues)
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

    assert "partial_render_output" in _rule_ids(issues)
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

    drift = [item for item in issues if item.rule_id == "rendered_page_order_mismatch"]
    assert [item.frame_id for item in drift] == ["baseline", "applicable-case"]


def test_render_qa_routes_each_atomic_failure_to_r1(tmp_path):
    import src.nodes.node_p_render_qa as module

    package, assets, manifest = _fixtures(tmp_path)
    package["render_diagnostics"] = [
        {"frame_id": "baseline", "kind": "overflow", "role": "headline"}
    ]

    result = module.render_qa_node(
        {
            "publish_package": package,
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
        "asset_manifest": assets,
        "render_manifest": manifest,
    }

    first = render_qa_node(state)["render_qa_result"]
    second = render_qa_node(state)["render_qa_result"]

    assert getattr(first, metric) == getattr(second, metric)


def test_quality_proxy_hierarchy_drops_for_measured_page_dimension_failure(tmp_path):
    from src.nodes.node_p_render_qa import render_qa_node

    package, assets, manifest = _fixtures(tmp_path)
    state = {
        "publish_package": package,
        "asset_manifest": assets,
        "render_manifest": manifest,
    }
    baseline = render_qa_node(state)["render_qa_result"]

    Path(manifest.pages[1].path).write_bytes(_png(1080, 1080))
    degraded = render_qa_node(state)["render_qa_result"]

    assert degraded.visual_hierarchy < baseline.visual_hierarchy
    assert degraded.editorial_quality < baseline.editorial_quality
