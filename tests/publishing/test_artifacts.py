from __future__ import annotations

import json
import hashlib
import os
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from src.publishing import artifacts as artifacts_module
from src.publishing.artifacts import (
    build_codex_rescue_prompt,
    build_content_lock,
    build_publish_copy,
    export_publish_package,
)


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
        "focus_keyword_cli_present": True,
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
        Image.new("RGB", (1080, 1440), (index, 2, 3)).save(path, "PNG")
        page_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        paths.append(path)
        pages.append(
            {
                "frame_id": frame["frame_id"],
                "role": frame["role"],
                "layout": frame["layout"],
                "path": str(path),
                "width": 1080,
                "height": 1440,
                "sha256": page_sha256,
                "probe": _probe(frame["headline"]),
            }
        )
    contact_sheet = image_dir / "contact-sheet.png"
    Image.new("RGB", (540, 720), (9, 8, 7)).save(contact_sheet, "PNG")
    contact_sheet_sha256 = hashlib.sha256(contact_sheet.read_bytes()).hexdigest()
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
                "contact_sheet_sha256": contact_sheet_sha256,
                "contact_sheet_page_sha256": [page["sha256"] for page in pages],
                "source_asset_sha256": {},
            },
            "reference_paths": [str(path) for path in REFERENCE_PATHS],
            "publish_authorization": {
                "workflow_completed": True,
                "review_status": "approved",
                "final_policy_issues": [],
                "carousel_qa_result": {"passed": True, "issues": []},
                "render_qa_result": {"passed": True, "issues": []},
                "focus_keyword_cli_present": True,
                "focus_keyword": package["focus_keyword"],
            },
            "expected_artifact_generation": 0,
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


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda package: package.pop("publish_authorization"), "authorization"),
        (
            lambda package: package["publish_authorization"].update(
                workflow_completed=False
            ),
            "completed",
        ),
        (
            lambda package: package["publish_authorization"].update(
                review_status="pending"
            ),
            "approved",
        ),
        (
            lambda package: package["publish_authorization"].update(
                final_policy_issues=None
            ),
            "final_policy_issues",
        ),
        (
            lambda package: package["publish_authorization"].update(
                final_policy_issues=()
            ),
            "final_policy_issues",
        ),
        (
            lambda package: package["publish_authorization"].update(
                final_policy_issues=[{"rule_id": "unsafe"}]
            ),
            "final_policy_issues",
        ),
        (
            lambda package: package["publish_authorization"].update(
                carousel_qa_result={"passed": False, "issues": []}
            ),
            "Carousel QA",
        ),
        (
            lambda package: package["publish_authorization"].update(
                render_qa_result={"passed": False, "issues": []}
            ),
            "Render QA",
        ),
        (
            lambda package: package["asset_manifest"]["items"].append(
                {
                    "asset_id": "pending",
                    "slot_id": "slot-1",
                    "role": "texture",
                    "layout": "editorial_cover",
                    "source_type": "stock",
                    "path": "/tmp/pending.png",
                    "status": "pending_external",
                    "license": "pending",
                    "width": 1080,
                    "height": 1440,
                    "sha256": "c" * 64,
                }
            ),
            "pending",
        ),
    ],
)
def test_export_requires_explicit_publishability_authorization(
    tmp_path, mutation, message
):
    package, _ = exportable_package(tmp_path)
    mutation(package)

    with pytest.raises((TypeError, ValueError), match=message):
        export_publish_package(package)


def test_export_uses_one_immutable_package_snapshot(monkeypatch, tmp_path):
    package, _ = exportable_package(tmp_path)
    original_content = package["content"]

    def mutate_live_package_after_snapshot():
        package["content"] = "快照后被并发篡改"
        package["storyboards"][1]["headline"] = "快照后被并发篡改"
        return tuple(REFERENCE_PATHS)

    monkeypatch.setattr(
        artifacts_module,
        "_approved_reference_paths",
        mutate_live_package_after_snapshot,
    )

    result = export_publish_package(package)
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))

    assert package["content"] == "快照后被并发篡改"
    assert audit["content"] == original_content
    assert original_content in result.publish_copy_path.read_text(encoding="utf-8")
    assert "快照后被并发篡改" not in result.rescue_prompt_path.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize(
    "title",
    [".", "..", "bad/name", r"bad\name", "bad\x00name", "bad\nname", "bad\rname", "bad\x1fname"],
)
def test_export_rejects_unsafe_audit_title_components(tmp_path, title):
    package, _ = exportable_package(tmp_path)
    package["title"] = title

    with pytest.raises(ValueError, match="title"):
        export_publish_package(package)


def test_explicit_cli_focus_keyword_cannot_be_cleared_or_changed(tmp_path):
    package, _ = exportable_package(tmp_path)
    package["focus_keyword"] = "被人工替换"

    with pytest.raises(ValueError, match="focus_keyword"):
        export_publish_package(package)


def test_empty_focus_keyword_is_allowed_only_without_cli_keyword(tmp_path):
    package, _ = exportable_package(tmp_path)
    package["focus_keyword"] = ""
    package["focus_keyword_cli_present"] = False
    package["publish_authorization"].update(
        focus_keyword_cli_present=False,
        focus_keyword="",
    )

    result = export_publish_package(package)

    assert result.content_lock.focus_keyword == ""


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
    assert audit["render_manifest"] == {
        **package["render_manifest"],
        "pages": [
            {
                **page,
                "path": Path(page["path"]).relative_to(package_dir).as_posix(),
            }
            for page in package["render_manifest"]["pages"]
        ],
        "contact_sheet_path": "images/contact-sheet.png",
    }
    assert audit["rendered_image_paths"] == [
        Path(path).relative_to(package_dir).as_posix()
        for path in package["rendered_image_paths"]
    ]
    assert [page["path"] for page in audit["render_manifest"]["pages"]] == [
        Path(path).relative_to(package_dir).as_posix()
        for path in package["rendered_image_paths"]
    ]
    assert audit["render_manifest"]["contact_sheet_path"] == "images/contact-sheet.png"
    assert result.artifact_generation == 1


def test_export_rejects_page_bytes_changed_after_render_manifest(tmp_path):
    package, _ = exportable_package(tmp_path)
    page = Path(package["rendered_image_paths"][0])
    Image.new("RGB", (1080, 1440), (200, 10, 10)).save(page, "PNG")

    with pytest.raises(ValueError, match="sha256"):
        export_publish_package(package)


def test_export_rejects_page_replaced_during_secure_snapshot(monkeypatch, tmp_path):
    package, _ = exportable_package(tmp_path)
    page = Path(package["rendered_image_paths"][0])
    replacement = page.with_name("replacement.png")
    Image.new("RGB", (1080, 1440), (220, 10, 10)).save(replacement, "PNG")
    real_read = artifacts_module.os.read
    replaced = False

    def replace_named_page_after_read(descriptor, size):
        nonlocal replaced
        data = real_read(descriptor, size)
        if data and not replaced:
            replaced = True
            os.replace(replacement, page)
        return data

    monkeypatch.setattr(artifacts_module.os, "read", replace_named_page_after_read)

    with pytest.raises(ValueError, match="changed during snapshot"):
        export_publish_package(package)


def test_export_rejects_noncanonical_dotdot_page_path(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    canonical = Path(package["rendered_image_paths"][0])
    noncanonical = package_dir / "images" / ".." / "images" / canonical.name
    package["rendered_image_paths"][0] = str(noncanonical)
    package["render_manifest"]["pages"][0]["path"] = str(noncanonical)

    with pytest.raises(ValueError, match="canonical"):
        export_publish_package(package)


def test_export_rejects_page_path_through_a_symlinked_ancestor(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    alias_root = tmp_path / "publish-alias"
    alias_root.symlink_to(package_dir.parent, target_is_directory=True)
    alias_package = alias_root / package_dir.name
    aliased_paths = [
        alias_package / "images" / Path(path).name
        for path in package["rendered_image_paths"]
    ]
    package["rendered_image_paths"] = [str(path) for path in aliased_paths]
    for page, path in zip(
        package["render_manifest"]["pages"], aliased_paths, strict=True
    ):
        page["path"] = str(path)
    package["render_manifest"]["contact_sheet_path"] = str(
        alias_package / "images" / "contact-sheet.png"
    )

    with pytest.raises(ValueError, match="canonical|symlink"):
        export_publish_package(package)


def test_export_rejects_signature_only_fake_png(tmp_path):
    package, _ = exportable_package(tmp_path)
    page = Path(package["rendered_image_paths"][0])
    page.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-decodable-image")
    package["render_manifest"]["pages"][0]["sha256"] = hashlib.sha256(
        page.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="decode"):
        export_publish_package(package)


def test_export_rejects_wrong_page_dimensions_even_when_manifest_claims_1080x1440(
    tmp_path,
):
    package, _ = exportable_package(tmp_path)
    page = Path(package["rendered_image_paths"][0])
    Image.new("RGB", (100, 100), (1, 2, 3)).save(page, "PNG")
    package["render_manifest"]["pages"][0]["sha256"] = hashlib.sha256(
        page.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="1080 x 1440"):
        export_publish_package(package)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_export_rejects_linked_page_files(tmp_path, link_kind):
    package, package_dir = exportable_package(tmp_path)
    page = Path(package["rendered_image_paths"][0])
    linked_source = package_dir / "linked-source.png"
    linked_source.write_bytes(page.read_bytes())
    page.unlink()
    if link_kind == "symlink":
        page.symlink_to(linked_source)
    else:
        os.link(linked_source, page)

    with pytest.raises(ValueError, match="symlink|hardlink|regular"):
        export_publish_package(package)


def test_export_rejects_contact_sheet_aliasing_a_page_inode(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    contact = package_dir / "images" / "contact-sheet.png"
    page = Path(package["rendered_image_paths"][0])
    contact.unlink()
    os.link(page, contact)
    package["render_manifest"]["contact_sheet_sha256"] = hashlib.sha256(
        contact.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="distinct|hardlink"):
        export_publish_package(package)


def test_export_requires_fixed_contact_sheet_filename(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    contact = package_dir / "images" / "contact-sheet.png"
    renamed = contact.with_name("overview.png")
    contact.rename(renamed)
    package["render_manifest"]["contact_sheet_path"] = str(renamed)

    with pytest.raises(ValueError, match="contact-sheet.png"):
        export_publish_package(package)


def test_package_lock_must_be_a_canonical_regular_file(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    target = package_dir / "attacker-lock"
    target.write_text("", encoding="utf-8")
    (package_dir / ".publish-artifacts.lock").symlink_to(target)

    with pytest.raises(ValueError, match="lock"):
        export_publish_package(package)


def test_export_rejects_package_directory_rebinding_before_return(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    displaced = package_dir.with_name(f"{package_dir.name}-displaced")
    real_transaction = artifacts_module._transactional_replace_artifacts

    def commit_then_rebind_package(*args, **kwargs):
        real_transaction(*args, **kwargs)
        package_dir.rename(displaced)
        package_dir.mkdir()

    monkeypatch.setattr(
        artifacts_module,
        "_transactional_replace_artifacts",
        commit_then_rebind_package,
    )

    with pytest.raises(ValueError, match="package directory binding changed"):
        export_publish_package(package)


def test_export_generation_is_compare_and_swap_guarded(tmp_path):
    package, _ = exportable_package(tmp_path)
    first = export_publish_package(package)

    assert first.artifact_generation == 1
    with pytest.raises(ValueError, match="generation|compare-and-swap"):
        export_publish_package(package)


def test_concurrent_first_exports_cannot_publish_a_mixed_package(tmp_path):
    first, package_dir = exportable_package(tmp_path)
    second = deepcopy(first)
    first["content"] = "并发版本甲"
    second["content"] = "并发版本乙"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(export_publish_package, package)
            for package in (first, second)
        ]
    results = []
    errors = []
    for future in futures:
        try:
            results.append(future.result())
        except ValueError as exc:
            errors.append(exc)

    assert len(results) == 1
    assert len(errors) == 1
    audit = json.loads(results[0].audit_json_path.read_text(encoding="utf-8"))
    copy = results[0].publish_copy_path.read_text(encoding="utf-8")
    assert audit["content"] in {"并发版本甲", "并发版本乙"}
    assert audit["content"] in copy
    assert audit["content_lock"]["canonical_sha256"] == results[0].content_lock.canonical_sha256
    assert not list(package_dir.glob(".*.tmp"))


def test_title_changing_reexport_is_rejected_and_keeps_one_audit(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    changed = deepcopy(package)
    changed["expected_artifact_generation"] = first.artifact_generation
    changed["title"] = "另一个标题"

    with pytest.raises(ValueError, match="title"):
        export_publish_package(changed)

    assert [
        path for path in package_dir.glob("*.json") if not path.name.startswith(".")
    ] == [first.audit_json_path]


def test_first_versioned_export_rejects_a_different_legacy_title_audit(tmp_path):
    package, package_dir = exportable_package(tmp_path)
    legacy_audit = package_dir / "旧标题.json"
    legacy_audit.write_text('{"title":"旧标题"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="title|audit"):
        export_publish_package(package)

    assert legacy_audit.read_text(encoding="utf-8") == '{"title":"旧标题"}\n'
    assert not (package_dir / f"{package['title']}.json").exists()


def test_atomic_replace_failure_removes_support_files_but_preserves_approved_images(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    images_before = {
        path.name: path.read_bytes() for path in package_dir.glob("images/*.png")
    }
    real_replace = artifacts_module.os.replace
    replace_calls = 0

    def fail_second_replace(source, destination, **kwargs):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("simulated atomic replacement failure")
        return real_replace(source, destination, **kwargs)

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
    changed["expected_artifact_generation"] = first.artifact_generation
    real_replace = artifacts_module.os.replace
    replace_calls = 0

    def fail_second_artifact_commit(source, destination, **kwargs):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 4:
            raise OSError("simulated reexport replacement failure")
        return real_replace(source, destination, **kwargs)

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


def test_failed_backup_restore_preserves_the_only_old_copy_for_recovery(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    old_copy = first.publish_copy_path.read_bytes()
    changed = deepcopy(package)
    changed["content"] = "会触发回滚的新正文"
    changed["expected_artifact_generation"] = first.artifact_generation
    real_replace = artifacts_module.os.replace

    def fail_commit_and_publish_copy_restore(source, destination, **kwargs):
        source = Path(source)
        destination = Path(destination)
        if source.suffix == ".tmp" and destination.name == "codex-image-regeneration-prompt.txt":
            raise OSError("simulated commit failure")
        if source.suffix == ".backup" and destination.name == "publish-copy.txt":
            raise OSError("simulated restore failure")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(
        artifacts_module.os,
        "replace",
        fail_commit_and_publish_copy_restore,
    )

    with pytest.raises(Exception, match="recovery|restore"):
        export_publish_package(changed)

    assert not first.publish_copy_path.exists()
    recovery_files = list(package_dir.glob("*.backup")) + list(
        package_dir.glob("*.recovery-*")
    )
    assert recovery_files
    assert any(path.read_bytes() == old_copy for path in recovery_files)


def test_legacy_prompt_removal_is_rolled_back_with_artifact_transaction(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    legacy = package_dir / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME
    legacy.write_text("legacy prompt bytes", encoding="utf-8")
    real_replace = artifacts_module.os.replace

    def fail_audit_commit(source, destination, **kwargs):
        source = Path(source)
        destination = Path(destination)
        if source.suffix == ".tmp" and destination.suffix == ".json":
            raise OSError("simulated audit commit failure")
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(artifacts_module.os, "replace", fail_audit_commit)

    with pytest.raises(OSError, match="simulated audit commit failure"):
        export_publish_package(package)

    assert legacy.read_text(encoding="utf-8") == "legacy prompt bytes"
