from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.publishing import artifacts as artifacts_module
from src.publishing.artifacts import (
    build_codex_rescue_prompt,
    build_content_lock,
    build_publish_copy,
    export_publish_package,
)


PNG = b"\x89PNG\r\n\x1a\nrendered"
LOCKED_TOP_LEVEL_FIELDS = (
    "focus_keyword",
    "topic",
    "topic_id",
    "angle",
    "angle_id",
    "target_group",
    "core_pain",
    "title",
    "cover_copy",
    "content",
    "hashtags",
)
REFERENCE_PATHS = [
    Path("/quality-anchors/editorial-cover-anchor.png"),
    Path("/quality-anchors/face-diagram-anchor.png"),
    Path("/quality-anchors/save-card-anchor.png"),
]


def _storyboards(count: int = 5) -> list[dict]:
    layouts = [
        "editorial_cover",
        "texture_baseline",
        "front_face_zone",
        "saveable_checklist",
        "saveable_reference",
        "decision_tree",
        "three_state_diagnostic",
    ]
    return [
        {
            "frame_id": f"frame-{index}",
            "role": "cover" if index == 1 else f"detail-{index}",
            "layout": layouts[index - 1],
            "headline": "精华用量判断" if index == 1 else f"第{index}页判断",
            "kicker": f"第{index}页眉题",
            "content_blocks": [
                {
                    "block_type": "text",
                    "heading": f"第{index}页小标题",
                    "body": f"第{index}页正文",
                    "items": [f"第{index}页条目"],
                }
            ],
            "emphasis": [f"第{index}页强调"],
            "visual_slots": [],
            "footer": f"第{index}页页脚",
        }
        for index in range(1, count + 1)
    ]


def _content_contract(frame_count: int = 5) -> dict:
    return {
        "audience": "通勤护肤人群",
        "trigger_situation": "早晨护肤",
        "decision_problem": "精华到底用多少",
        "first_screen_promise": "一张图判断精华该用多少",
        "screenshot_asset": "精华用量判断卡",
        "proof_asset": "精华液质地图",
        "visual_mode": "text_card",
        "content_job": "diagnose_and_adjust",
        "primary_visual_family": "beauty_editorial",
        "primary_visual_subject": "serum_texture",
        "proof_mode": "product_texture",
        "recommended_frame_count": frame_count,
    }


def package_payload(frame_count: int = 5) -> dict:
    return {
        "focus_keyword": "精华用量",
        "topic": "精华用量怎么判断",
        "topic_id": "topic-current-package",
        "angle": "按肤感判断用量",
        "angle_id": "angle-current-package",
        "target_group": "通勤护肤人群",
        "core_pain": "精华用多黏腻、用少又没底",
        "title": "精华用量判断",
        "cover_copy": "一张图判断该用多少",
        "content": "正文第一段",
        "hashtags": ["#护肤", "#精华"],
        "storyboards": _storyboards(frame_count),
        "content_contract": _content_contract(frame_count),
        "internal_notes": "精华按1泵还是2泵",
    }


def _probe(text: str) -> dict:
    return {
        "canvas_width": 1080,
        "canvas_height": 1440,
        "safe_margin": 72,
        "text_results": [
            {
                "role": "headline",
                "text": text,
                "visible": True,
                "overflow": False,
                "ink_clipped": False,
                "layout_clipped": False,
                "font_family": "Source Han Serif SC",
                "font_size": 64,
                "line_height": 78,
                "line_count": 1,
                "x": 100,
                "y": 100,
                "width": 600,
                "height": 80,
            }
        ],
        "asset_results": [],
        "issues": [],
    }


def exportable_package(tmp_path: Path, frame_count: int = 5) -> tuple[dict, Path]:
    package = package_payload(frame_count)
    package_dir = tmp_path / "outputs" / "publish" / "20260714-beauty-skincare-current"
    image_dir = package_dir / "images"
    image_dir.mkdir(parents=True)
    paths = []
    pages = []
    for index, frame in enumerate(package["storyboards"], start=1):
        filename = "01-cover.png" if index == 1 else f"{index:02d}-{frame['role']}.png"
        path = image_dir / filename
        path.write_bytes(PNG)
        paths.append(path)
        pages.append(
            {
                "frame_id": frame["frame_id"],
                "role": frame["role"],
                "layout": frame["layout"],
                "path": str(path),
                "width": 1080,
                "height": 1440,
                "sha256": "a" * 64,
                "probe": _probe(frame["headline"]),
            }
        )
    contact_sheet = image_dir / "contact-sheet.png"
    contact_sheet.write_bytes(PNG)
    package.update(
        {
            "domain": "beauty",
            "subdomain": "skincare",
            "profile_version": "beauty-v1",
            "rendered_image_paths": [str(path) for path in paths],
            "visual_plan": {
                "design_system": "beauty_editorial_v1",
                "content_job": "diagnose_and_adjust",
                "primary_visual_family": "beauty_editorial",
                "supporting_families": [],
                "frame_plan": [
                    {
                        "frame_id": frame["frame_id"],
                        "role": frame["role"],
                        "layout": frame["layout"],
                        "purpose": frame["headline"],
                        "asset_roles": [],
                    }
                    for frame in package["storyboards"]
                ],
                "required_assets": [],
            },
            "asset_manifest": {
                "items": [],
                "search_report": {
                    "search_triggered": False,
                    "queries": [],
                    "provider_reports": [],
                    "selection_reasons": {},
                },
            },
            "render_manifest": {
                "pages": pages,
                "fonts": {
                    "all_loaded": True,
                    "computed_families": [
                        "Source Han Serif SC",
                        "Source Han Sans SC",
                        "Bodoni Moda",
                    ],
                },
                "contact_sheet_path": str(contact_sheet),
                "contact_sheet_sha256": "b" * 64,
                "contact_sheet_page_sha256": ["a" * 64] * frame_count,
                "source_asset_sha256": {},
            },
            "reference_paths": [str(path) for path in REFERENCE_PATHS],
        }
    )
    return package, package_dir


def test_publish_copy_is_directly_pasteable():
    assert build_publish_copy(package_payload()) == (
        "精华用量判断\n\n正文第一段\n\n#护肤 #精华\n"
    )


@pytest.mark.parametrize("field", LOCKED_TOP_LEVEL_FIELDS)
def test_content_lock_hash_changes_for_every_locked_top_level_field(field):
    package = package_payload()
    first = build_content_lock(package)
    changed = deepcopy(package)
    if field == "hashtags":
        changed[field].append("#通勤护肤")
    else:
        changed[field] = f"{changed[field]}-被改写"

    assert first.canonical_sha256 != build_content_lock(changed).canonical_sha256


def test_content_lock_uses_validated_contract_promise_and_locks_it():
    package = package_payload()
    first = build_content_lock(package)
    changed = deepcopy(package)
    changed["content_contract"]["first_screen_promise"] = "三步判断精华该用多少"

    assert first.first_screen_promise == "一张图判断精华该用多少"
    assert first.canonical_sha256 != build_content_lock(changed).canonical_sha256


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("headline", "被改写的标题"),
        ("kicker", "被改写的眉题"),
        ("content_heading", "被改写的小标题"),
        ("content_body", "被改写的正文"),
        ("content_item", "被改写的条目"),
        ("emphasis", "被改写的强调"),
        ("footer", "被改写的页脚"),
    ],
)
def test_content_lock_hash_changes_for_every_visible_storyboard_string(
    key, replacement
):
    package = package_payload()
    changed = deepcopy(package)
    frame = changed["storyboards"][1]
    if key == "content_heading":
        frame["content_blocks"][0]["heading"] = replacement
    elif key == "content_body":
        frame["content_blocks"][0]["body"] = replacement
    elif key == "content_item":
        frame["content_blocks"][0]["items"][0] = replacement
    elif key == "emphasis":
        frame["emphasis"][0] = replacement
    else:
        frame[key] = replacement

    assert (
        build_content_lock(package).canonical_sha256
        != build_content_lock(changed).canonical_sha256
    )


def test_content_lock_hash_is_independent_of_nested_dict_insertion_order():
    package = package_payload()
    reordered = dict(reversed(list(package.items())))
    reordered["storyboards"] = [
        dict(reversed(list(frame.items()))) for frame in package["storyboards"]
    ]
    reordered["content_contract"] = dict(
        reversed(list(package["content_contract"].items()))
    )

    assert (
        build_content_lock(package).canonical_sha256
        == build_content_lock(reordered).canonical_sha256
    )


@pytest.mark.parametrize("missing", [*LOCKED_TOP_LEVEL_FIELDS, "content_contract", "storyboards"])
def test_content_lock_rejects_missing_locked_fields(missing):
    package = package_payload()
    package.pop(missing)

    with pytest.raises((TypeError, ValueError, KeyError)):
        build_content_lock(package)


def test_rescue_prompt_locks_current_content_and_forbids_rewriting():
    package = package_payload()
    lock = build_content_lock(package)
    prompt = build_codex_rescue_prompt(package, lock, REFERENCE_PATHS)

    assert package["focus_keyword"] in prompt
    assert package["topic"] in prompt
    assert lock.canonical_sha256 in prompt
    assert "这是一次 visual-only regeneration，不是内容创作" in prompt
    assert "禁止重新选题" in prompt
    assert "每张图片的所有可见文字必须逐字来自对应 storyboard" in prompt
    assert "images-codex-vN" in prompt
    assert all(str(path) in prompt for path in REFERENCE_PATHS)


def test_rescue_prompt_contains_no_unrelated_golden_or_example_title():
    package = package_payload()
    prompt = build_codex_rescue_prompt(
        package, build_content_lock(package), REFERENCE_PATHS
    )

    assert "zone_diagnosis_fixture" not in prompt
    assert package["internal_notes"] not in prompt


def test_rescue_prompt_requires_exactly_three_reference_only_anchors():
    package = package_payload()
    lock = build_content_lock(package)

    with pytest.raises(ValueError, match="exactly three"):
        build_codex_rescue_prompt(package, lock, REFERENCE_PATHS[:2])


def test_rescue_prompt_build_is_manual_only_and_never_calls_image_api(monkeypatch):
    package = package_payload()
    monkeypatch.setattr(
        "requests.post",
        lambda *_args, **_kwargs: pytest.fail("manual prompt generation called an API"),
    )

    build_codex_rescue_prompt(
        package, build_content_lock(package), REFERENCE_PATHS
    )


@pytest.mark.parametrize("frame_count", [5, 7])
def test_export_writes_complete_portable_publish_artifacts(tmp_path, frame_count):
    package, package_dir = exportable_package(tmp_path, frame_count)

    result = export_publish_package(package)

    assert result.package_directory == package_dir.resolve()
    assert result.publish_copy_path.read_text(encoding="utf-8").endswith("\n")
    assert result.rescue_prompt_path.is_file()
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    assert audit["content_lock"]["canonical_sha256"] == result.content_lock.canonical_sha256
    assert audit["visual_plan"] == package["visual_plan"]
    assert audit["asset_manifest"] == package["asset_manifest"]
    assert audit["render_manifest"] == package["render_manifest"]
    assert audit["rendered_image_paths"] == [
        Path(path).relative_to(package_dir).as_posix()
        for path in package["rendered_image_paths"]
    ]


def test_atomic_replace_failure_removes_support_files_but_preserves_approved_images(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    images_before = {
        path.name: path.read_bytes() for path in package_dir.glob("images/*.png")
    }
    real_replace = artifacts_module.os.replace
    replace_calls = 0

    def fail_second_replace(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("simulated atomic replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts_module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="simulated atomic replacement failure"):
        export_publish_package(package)

    assert {
        path.name: path.read_bytes() for path in package_dir.glob("images/*.png")
    } == images_before
    assert not (package_dir / "publish-copy.txt").exists()
    assert not (package_dir / "codex-image-regeneration-prompt.txt").exists()
    assert not (package_dir / f"{package['title']}.json").exists()
    assert not list(package_dir.glob(".*.tmp"))


def test_atomic_reexport_failure_restores_prior_support_artifacts_and_images(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    support_before = {
        path: path.read_bytes()
        for path in (
            first.publish_copy_path,
            first.rescue_prompt_path,
            first.audit_json_path,
        )
    }
    images_before = {
        path.name: path.read_bytes() for path in package_dir.glob("images/*.png")
    }
    changed = deepcopy(package)
    changed["content"] = "本次重导出的新正文"
    real_replace = artifacts_module.os.replace
    replace_calls = 0

    def fail_second_artifact_commit(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 4:
            raise OSError("simulated reexport replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(
        artifacts_module.os, "replace", fail_second_artifact_commit
    )

    with pytest.raises(OSError, match="simulated reexport replacement failure"):
        export_publish_package(changed)

    assert {path: path.read_bytes() for path in support_before} == support_before
    assert {
        path.name: path.read_bytes() for path in package_dir.glob("images/*.png")
    } == images_before
    assert not list(package_dir.glob(".*.tmp"))
    assert not list(package_dir.glob(".*.backup"))
