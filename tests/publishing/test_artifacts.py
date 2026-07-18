from __future__ import annotations

import json
import hashlib
import os
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from langgraph.types import StateSnapshot

from src.publishing import artifacts as artifacts_module
from src.publishing.artifacts import (
    build_codex_rescue_prompt,
    build_content_lock,
    build_publish_copy,
    export_publish_package as export_completed_state,
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
    page_archetypes = [
        "cover",
        "scene",
        "explanation",
        "checklist",
        "save",
        "qa",
        "boundary",
    ]
    return [
        {
            "frame_id": f"frame-{index}",
            "role": "cover" if index == 1 else f"detail-{index}",
            "page_archetype": page_archetypes[index - 1],
            "content_density_hint": (
                "dense" if index in {4, 5} else "standard"
            ),
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
    narrative_plan = {
        "narrative_form": "diagnostic_qa",
        "beats": [
            {"beat_id": "hook", "kind": "hook", "purpose": "建立阅读承诺"},
            {"beat_id": "scene", "kind": "scene", "purpose": "呈现使用场景"},
            {"beat_id": "diagnose", "kind": "diagnostic", "purpose": "给出判断标准"},
            {"beat_id": "save", "kind": "summary", "purpose": "保存判断清单"},
        ],
        "saveable_beat": {
            "beat_id": "save",
            "kind": "summary",
            "purpose": "保存判断清单",
        },
        "closing_mode": "none",
    }
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
        "narrative_plan": narrative_plan,
        "narrative_form": narrative_plan["narrative_form"],
        "internal_notes": "精华按1泵还是2泵",
    }


def _probe(frame: dict) -> dict:
    visible_text = [
        ("kicker", frame.get("kicker")),
        ("headline", frame["headline"]),
        ("footer", frame.get("footer")),
    ]
    for block_index, block in enumerate(frame.get("content_blocks", [])):
        visible_text.extend(
            [
                (f"content_blocks[{block_index}].heading", block.get("heading")),
                (f"content_blocks[{block_index}].body", block.get("body")),
                *[
                    (f"content_blocks[{block_index}].items[{item_index}]", item)
                    for item_index, item in enumerate(block.get("items", []))
                ],
            ]
        )
    # Emphasis phrases are rendered visible text (the editorial renderer draws
    # them and the page probe captures them), so the probe must carry them for
    # the Final Guard binding check to pass.
    visible_text.extend(
        (f"emphasis[{index}]", value)
        for index, value in enumerate(frame.get("emphasis", []))
    )
    return {
        "canvas_width": 1080,
        "canvas_height": 1440,
        "safe_margin": 72,
        "text_results": [
            {
                "role": role,
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
            for role, text in visible_text
            if text
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
                "page_archetype": frame["page_archetype"],
                "template_family": "deep_teal",
                "density": frame["content_density_hint"],
                "composition_variant": "stacked",
                "path": str(path),
                "width": 1080,
                "height": 1440,
                "sha256": page_sha256,
                "probe": _probe(frame),
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
                "design_system": "beauty_editorial_v2",
                "template_family": "deep_teal",
                "template_selection": {
                    "template_family": "deep_teal",
                    "score": 100,
                    "reasons": ["test fixture"],
                    "rejected_families": {
                        "pink_red": ["lower score"],
                        "soft_pink": ["lower score"],
                        "coral_impact": ["lower score"],
                        "green_catalog": ["lower score"],
                        "white_quote": ["lower score"],
                    },
                },
                "narrative_form": package["narrative_form"],
                "content_job": "diagnose_and_adjust",
                "frame_plan": [
                    {
                        "frame_id": frame["frame_id"],
                        "role": frame["role"],
                        "page_archetype": frame["page_archetype"],
                        "purpose": (
                            package["narrative_plan"]["saveable_beat"]["purpose"]
                            if frame["page_archetype"] == "save"
                            else frame["headline"]
                        ),
                        "allowed_density": ["sparse", "standard", "dense"],
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


@pytest.fixture(autouse=True)
def final_guard_render_root(monkeypatch, tmp_path):
    from src.nodes import node_q_01_final_policy_guard

    monkeypatch.setattr(
        node_q_01_final_policy_guard,
        "RENDER_OUTPUT_ROOT",
        tmp_path / "outputs" / "publish",
    )


def _completed_state(package: dict) -> SimpleNamespace:
    authorization = package.get("publish_authorization") or {}
    return SimpleNamespace(
        values={
            "publish_package": package,
            "visual_plan": package.get("visual_plan"),
            "asset_manifest": package.get("asset_manifest"),
            "render_manifest": package.get("render_manifest"),
            "review_status": authorization.get("review_status"),
            "carousel_qa_result": authorization.get("carousel_qa_result"),
            "render_qa_result": authorization.get("render_qa_result"),
            "focus_keyword_cli_present": authorization.get(
                "focus_keyword_cli_present"
            ),
            "focus_keyword": authorization.get("focus_keyword"),
        },
        next=(),
    )


def _real_completed_state(
    package: dict,
    *,
    next_nodes: tuple[str, ...] = (),
    workflow_version: str = "modern_v2",
    legacy_marker: bool = False,
) -> StateSnapshot:
    values = dict(_completed_state(package).values)
    values.update(
        editorial_workflow_version=workflow_version,
        legacy_editorial_checkpoint=legacy_marker,
    )
    return StateSnapshot(
        values=values,
        next=next_nodes,
        config={},
        metadata=None,
        created_at=None,
        parent_config=None,
        tasks=(),
        interrupts=(),
    )


def export_publish_package(package: dict):
    return export_completed_state(_real_completed_state(package))


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
    package["visual_plan"] = {"template_family": "deep_teal"}
    package["storyboards"][1]["headline"] = "防晒别急着叠✨"
    lock = build_content_lock(package)
    prompt = build_codex_rescue_prompt(package, lock, REFERENCE_PATHS)

    assert package["focus_keyword"] in prompt
    assert package["topic"] in prompt
    assert lock.canonical_sha256 in prompt
    assert "这是一次 visual-only regeneration，不是内容创作" in prompt
    assert "禁止重新选题" in prompt
    assert "每张图片的所有可见文字必须逐字来自对应 storyboard" in prompt
    assert "template_family=deep_teal" in prompt
    assert "page_archetype=scene" in prompt
    assert "density=standard" in prompt
    assert "防晒别急着叠✨" in prompt
    assert "layout=" not in prompt
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
    ("title", "references"),
    [
        (".hidden", REFERENCE_PATHS),
        ("安全标题", [REFERENCE_PATHS[0], "bad\npath", REFERENCE_PATHS[2]]),
        ("安全标题", [REFERENCE_PATHS[0], "bad\x00path", REFERENCE_PATHS[2]]),
    ],
)
def test_standalone_rescue_prompt_rejects_hidden_title_and_reference_injection(
    title, references
):
    package = package_payload()
    package["title"] = title

    with pytest.raises(ValueError, match="title|reference|CR|LF|NUL"):
        build_codex_rescue_prompt(package, build_content_lock(package), references)


def test_final_export_rejects_raw_self_authorized_package(tmp_path):
    package, _ = exportable_package(tmp_path)
    package["publish_authorization"] = {
        "workflow_completed": True,
        "review_status": "approved",
        "final_policy_issues": [],
        "carousel_qa_result": {"passed": True, "issues": []},
        "render_qa_result": {"passed": True, "issues": []},
        "focus_keyword_cli_present": True,
        "focus_keyword": package["focus_keyword"],
    }

    with pytest.raises(TypeError, match="StateSnapshot"):
        export_completed_state(package)


@pytest.mark.parametrize(
    "state",
    [
        SimpleNamespace(values={}, next=()),
        SimpleNamespace(values={}),
    ],
)
def test_final_export_rejects_duck_typed_state_wrappers(state):
    with pytest.raises(TypeError, match="StateSnapshot"):
        export_completed_state(state)


@pytest.mark.parametrize(
    ("workflow_version", "legacy_marker"),
    [
        ("legacy_v1", True),
        ("modern_v2", True),
        ("legacy_v1", False),
    ],
)
def test_final_export_rejects_legacy_and_hybrid_snapshots(
    tmp_path, workflow_version, legacy_marker
):
    package, _ = exportable_package(tmp_path)
    state = _real_completed_state(
        package,
        workflow_version=workflow_version,
        legacy_marker=legacy_marker,
    )

    with pytest.raises(ValueError, match="modern_v2|legacy"):
        export_completed_state(state)


def test_final_export_requires_exact_empty_tuple_next(tmp_path):
    package, _ = exportable_package(tmp_path)
    active = _real_completed_state(package, next_nodes=("content_writer",))
    malformed = _real_completed_state(package)._replace(next=[])

    with pytest.raises(ValueError, match="terminal.*next|empty tuple"):
        export_completed_state(active)
    with pytest.raises(ValueError, match="terminal.*next|empty tuple"):
        export_completed_state(malformed)


def test_final_export_recomputes_guard_and_rejects_stale_render_qa(tmp_path):
    package, _ = exportable_package(tmp_path)
    state = _real_completed_state(package)
    package["storyboards"][0]["headline"] = "QA 后改写但伪装已授权"

    with pytest.raises(ValueError, match="recomputed Final Guard"):
        export_completed_state(state)


def test_attestation_is_result_only_and_binds_current_inputs(tmp_path):
    package, _ = exportable_package(tmp_path)
    package["publish_attestation"] = {"canonical_sha256": "forged"}

    result = export_completed_state(_real_completed_state(package))
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))

    assert result.publish_attestation.canonical_sha256 != "forged"
    assert audit["publish_attestation"]["canonical_sha256"] == (
        result.publish_attestation.canonical_sha256
    )
    assert "forged" not in json.dumps(audit, ensure_ascii=False)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda package: package["publish_authorization"].update(
                review_status="pending"
            ),
            "approved",
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
                    "page_archetype": "cover",
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
def test_export_requires_completed_state_review_qa_and_no_pending_assets(
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
    # The audit serializes the validated ``RenderManifest`` pydantic model
    # (``model_dump(mode="json")``), which normalises the package's raw int
    # probes into their declared float fields and coerces ``None`` sequences
    # to empty lists. Build the expected dict by validating through the same
    # model so the assertion compares the same normalised shape and only
    # verifies the path-rewriting + contact_sheet_path portability transform.
    from src.schemas.render_manifest import RenderManifest

    expected_render_manifest = RenderManifest.model_validate(
        package["render_manifest"]
    ).model_dump(mode="json")
    for page, raw_page in zip(
        expected_render_manifest["pages"], package["render_manifest"]["pages"]
    ):
        page["path"] = Path(raw_page["path"]).relative_to(package_dir).as_posix()
    expected_render_manifest["contact_sheet_path"] = "images/contact-sheet.png"
    assert audit["render_manifest"] == expected_render_manifest
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

    with pytest.raises(ValueError, match="changed during snapshot|recomputed Final Guard"):
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

    with pytest.raises(ValueError, match="decode|recomputed Final Guard"):
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

    with pytest.raises(ValueError, match="1080 x 1440|recomputed Final Guard"):
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

    with pytest.raises(ValueError, match="distinct|hardlink|recomputed Final Guard"):
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
    target = package_dir.parent / "attacker-lock"
    target.write_text("", encoding="utf-8")
    lock_path = package_dir.parent / f".{package_dir.name}.publish-artifacts.lock"
    lock_path.symlink_to(target)

    with pytest.raises(ValueError, match="lock"):
        export_publish_package(package)


def test_second_export_rejects_sibling_lock_unlink_and_recreate(monkeypatch, tmp_path):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    support_before = {
        path.name: path.read_bytes()
        for path in package_dir.iterdir()
        if path.is_file() and not path.name.startswith(".")
    }
    original_verify = artifacts_module._ExportLock.verify
    replaced = False

    def replace_lock_path(export_lock):
        nonlocal replaced
        if not replaced:
            replaced = True
            os.unlink(export_lock.lock_name, dir_fd=export_lock.parent_fd)
            replacement_fd = os.open(
                export_lock.lock_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=export_lock.parent_fd,
            )
            os.close(replacement_fd)
        original_verify(export_lock)

    monkeypatch.setattr(artifacts_module._ExportLock, "verify", replace_lock_path)

    with pytest.raises(ValueError, match="lock.*binding changed"):
        export_publish_package(package)

    assert first.artifact_generation == 1
    assert {
        path.name: path.read_bytes()
        for path in package_dir.iterdir()
        if path.is_file() and not path.name.startswith(".")
    } == support_before


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


def test_root_rebind_while_backups_exist_rolls_back_before_cleanup(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    legacy = package_dir / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME
    legacy.write_text("legacy must survive", encoding="utf-8")
    old_copy = first.publish_copy_path.read_bytes()
    changed = deepcopy(package)
    changed["content"] = "must not commit into displaced root"
    displaced = package_dir.with_name(f"{package_dir.name}-displaced")
    original_verify = artifacts_module._ExportLock.verify
    rebound = False

    def rebind_once_backups_exist(export_lock):
        nonlocal rebound
        names = os.listdir(export_lock.package_fd)
        if not rebound and any(name.endswith(".backup") for name in names):
            rebound = True
            package_dir.rename(displaced)
            package_dir.mkdir()
        original_verify(export_lock)

    monkeypatch.setattr(
        artifacts_module._ExportLock, "verify", rebind_once_backups_exist
    )

    with pytest.raises(ValueError, match="package directory binding changed"):
        export_publish_package(changed)

    assert not list(package_dir.glob("publish-copy.txt"))
    assert (displaced / "publish-copy.txt").read_bytes() == old_copy
    assert (displaced / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME).read_text(
        encoding="utf-8"
    ) == "legacy must survive"
    assert not list(displaced.glob(".*.backup"))


def test_package_parent_rebind_is_detected_and_rolls_back(monkeypatch, tmp_path):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    old_copy = first.publish_copy_path.read_bytes()
    changed = deepcopy(package)
    changed["content"] = "must not commit through a displaced parent"
    parent = package_dir.parent
    displaced_parent = parent.with_name(f"{parent.name}-displaced")
    original_verify = artifacts_module._ExportLock.verify
    rebound = False

    def rebind_parent_once_backups_exist(export_lock):
        nonlocal rebound
        if not rebound and any(
            name.endswith(".backup") for name in os.listdir(export_lock.package_fd)
        ):
            rebound = True
            parent.rename(displaced_parent)
            parent.mkdir()
        original_verify(export_lock)

    monkeypatch.setattr(
        artifacts_module._ExportLock, "verify", rebind_parent_once_backups_exist
    )

    with pytest.raises(ValueError, match="parent.*binding changed"):
        export_publish_package(changed)

    assert not (package_dir / artifacts_module.PUBLISH_COPY_FILENAME).exists()
    assert (
        displaced_parent / package_dir.name / artifacts_module.PUBLISH_COPY_FILENAME
    ).read_bytes() == old_copy


def test_rebind_after_fsync_before_backup_cleanup_still_rolls_back(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    old_copy = first.publish_copy_path.read_bytes()
    changed = deepcopy(package)
    changed["content"] = "must rollback before backup cleanup"
    displaced = package_dir.with_name(f"{package_dir.name}-displaced")
    original_verify = artifacts_module._ExportLock.verify
    original_fsync = artifacts_module._fsync_directory_fd
    fsynced = False
    verify_after_fsync = 0

    def mark_fsync(package_fd):
        nonlocal fsynced
        original_fsync(package_fd)
        fsynced = True

    def rebind_on_second_post_fsync_verify(export_lock):
        nonlocal verify_after_fsync
        if fsynced:
            verify_after_fsync += 1
            if verify_after_fsync == 2:
                package_dir.rename(displaced)
                package_dir.mkdir()
        original_verify(export_lock)

    monkeypatch.setattr(artifacts_module, "_fsync_directory_fd", mark_fsync)
    monkeypatch.setattr(
        artifacts_module._ExportLock,
        "verify",
        rebind_on_second_post_fsync_verify,
    )

    with pytest.raises(ValueError, match="package directory binding changed"):
        export_publish_package(changed)

    assert not (package_dir / artifacts_module.PUBLISH_COPY_FILENAME).exists()
    assert (displaced / artifacts_module.PUBLISH_COPY_FILENAME).read_bytes() == old_copy
    assert not list(displaced.glob(".*.backup"))


def test_rebind_inside_backup_unlink_rolls_back_old_artifacts_and_legacy(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    first = export_publish_package(package)
    legacy = package_dir / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME
    legacy.write_text("legacy survives unlink race", encoding="utf-8")
    old_copy = first.publish_copy_path.read_bytes()
    changed = deepcopy(package)
    changed["content"] = "must rollback from backup bytes"
    displaced = package_dir.with_name(f"{package_dir.name}-displaced")
    original_unlink = artifacts_module.os.unlink
    rebound = False

    def unlink_backup_then_rebind(path, **kwargs):
        nonlocal rebound
        result = original_unlink(path, **kwargs)
        if not rebound and Path(path).name.endswith(".backup"):
            rebound = True
            package_dir.rename(displaced)
            package_dir.mkdir()
        return result

    monkeypatch.setattr(artifacts_module.os, "unlink", unlink_backup_then_rebind)

    with pytest.raises(ValueError, match="package directory binding changed"):
        export_publish_package(changed)

    assert not (package_dir / artifacts_module.PUBLISH_COPY_FILENAME).exists()
    assert (displaced / artifacts_module.PUBLISH_COPY_FILENAME).read_bytes() == old_copy
    assert (displaced / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME).read_text(
        encoding="utf-8"
    ) == "legacy survives unlink race"
    assert not list(displaced.glob(".*.backup"))


def test_return_reattestation_reopens_committed_support_bytes(monkeypatch, tmp_path):
    package, package_dir = exportable_package(tmp_path)
    original_transaction = artifacts_module._transactional_replace_artifacts

    def commit_then_tamper_support(*args, **kwargs):
        original_transaction(*args, **kwargs)
        (package_dir / artifacts_module.PUBLISH_COPY_FILENAME).write_text(
            "tampered after commit", encoding="utf-8"
        )

    monkeypatch.setattr(
        artifacts_module,
        "_transactional_replace_artifacts",
        commit_then_tamper_support,
    )

    with pytest.raises(ValueError, match="support artifact.*changed"):
        export_publish_package(package)


def test_return_reattestation_rejects_recreated_legacy_prompt(monkeypatch, tmp_path):
    package, package_dir = exportable_package(tmp_path)
    original_transaction = artifacts_module._transactional_replace_artifacts

    def commit_then_recreate_legacy(*args, **kwargs):
        original_transaction(*args, **kwargs)
        (package_dir / artifacts_module.LEGACY_IMAGE_PROMPT_FILENAME).write_text(
            "recreated after cleanup", encoding="utf-8"
        )

    monkeypatch.setattr(
        artifacts_module,
        "_transactional_replace_artifacts",
        commit_then_recreate_legacy,
    )

    with pytest.raises(ValueError, match="legacy.*recreated|delete path"):
        export_publish_package(package)


def test_terminal_retry_ignores_package_generation_and_uses_locked_current_value(tmp_path):
    package, _ = exportable_package(tmp_path)
    first = export_publish_package(package)
    package["expected_artifact_generation"] = 0
    second = export_publish_package(package)

    assert first.artifact_generation == 1
    assert second.artifact_generation == 2


def test_concurrent_exports_are_serialized_without_a_mixed_package(tmp_path):
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

    assert not errors, [str(error) for error in errors]
    assert len(results) == 2
    assert {result.artifact_generation for result in results} == {1, 2}
    audit = json.loads(results[-1].audit_json_path.read_text(encoding="utf-8"))
    copy = results[-1].publish_copy_path.read_text(encoding="utf-8")
    assert audit["content"] in {"并发版本甲", "并发版本乙"}
    assert audit["content"] in copy
    assert audit["content_lock"]["canonical_sha256"] in {
        result.content_lock.canonical_sha256 for result in results
    }
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


def test_first_export_rollback_records_unlink_failure_and_keeps_cleaning(
    monkeypatch, tmp_path
):
    package, package_dir = exportable_package(tmp_path)
    real_replace = artifacts_module.os.replace
    real_unlink = artifacts_module.os.unlink

    def fail_audit_commit(source, destination, **kwargs):
        if Path(source).suffix == ".tmp" and Path(destination).suffix == ".json":
            raise OSError("simulated first-export commit failure")
        return real_replace(source, destination, **kwargs)

    def fail_publish_copy_rollback(path, **kwargs):
        if Path(path).name == artifacts_module.PUBLISH_COPY_FILENAME:
            raise OSError("simulated rollback unlink failure")
        return real_unlink(path, **kwargs)

    monkeypatch.setattr(artifacts_module.os, "replace", fail_audit_commit)
    monkeypatch.setattr(artifacts_module.os, "unlink", fail_publish_copy_rollback)

    with pytest.raises(artifacts_module.ArtifactRollbackError) as exc_info:
        export_publish_package(package)

    assert package_dir / artifacts_module.PUBLISH_COPY_FILENAME in (
        exc_info.value.recovery_paths
    )
    assert not (package_dir / artifacts_module.RESCUE_PROMPT_FILENAME).exists()
    assert not (package_dir / artifacts_module.PACKAGE_VERSION_FILENAME).exists()
    assert not (package_dir / f"{package['title']}.json").exists()


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
