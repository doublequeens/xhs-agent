"""Task 16: ``llm_scene_v3`` publish-artifact export tests.

The export consumes the final approved dynamic-visual contracts from a terminal
``StateSnapshot`` and emits the canonical local publish package:

    content_atom_set.json, visual_direction_plan.json, asset_manifest.json,
    carousel_design_plan.json, design_plan_qa.json, render_manifest.json,
    render_qa.json, visual_critique.json, content_lock.json,
    final_policy_attestation.json, pages/*.png, contact-sheet.png

plus a ``publish-attestation.json`` that binds the whole bundle. Every contract
AND every PNG is hashed. No ``storyboards`` / ``visual_plan`` / ``carousel_qa``
/ fixed-template variant fields are exported. AI provenance lives ONLY in the
internal asset JSON (``AssetManifestItem.internal_provenance``), never in
page-visible copy or a rendered PNG. Staging + atomic promotion only; an existing
canonical package is never overwritten by hand.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from langgraph.types import StateSnapshot

from src.publishing import artifacts as artifacts_module
from src.publishing.artifacts import (
    PublishAttestation,
    export_publish_package,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import (
    FontLoadReport,
    RenderManifest,
    RenderedElementProbe,
    RenderedPage,
)
from src.schemas.render_qa import RenderQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    PageScene,
    TextElement,
    TextStyle,
)
from src.schemas.visual_critique import VisualCritique
from src.schemas.visual_director import (
    PageDirection,
    VisualDirectionPlan,
)


# ---------------------------------------------------------------------------
# contract fixture builders (adapted from tests/visual_design/test_render_qa.py)
# ---------------------------------------------------------------------------

_BG = "#FFFFFF"
_INK = "#1A1A1A"
_PAGE_COUNT = 5


def _png_bytes(width: int = 1080, height: int = 1440, color: str = _BG) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _write_png(path: Path, **kwargs) -> str:
    payload = _png_bytes(**kwargs)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _atom_set(page_count: int = _PAGE_COUNT) -> ContentAtomSet:
    texts = tuple(f"发布第{index}页编辑文字内容。" for index in range(1, page_count + 1))
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def _fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def _direction(atom_set: ContentAtomSet) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    return VisualDirectionPlan(
        template_family="soft_pink",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="护肤编辑方向",
        palette=("#F4A7BF", "#1A1A1A", "#FFFFFF"),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("soft accents",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"job-{index}",
                fragment_ids=(f"fragment-{index}",),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(),
    )


def _design_plan(
    direction: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    for direction_page in direction.page_sequence:
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background=_BG,
                elements=(
                    TextElement(
                        element_id=f"text-{direction_page.page_id}",
                        layer=1,
                        box=Box(x=88, y=120, width=904, height=160),
                        content_ref=direction_page.fragment_ids[0],
                        style=TextStyle(
                            font_role="body",
                            font_size=28,
                            line_height=1.45,
                            color=_INK,
                            align="left",
                            weight=500,
                        ),
                    ),
                ),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
    )


def _text_probe(page_id: str, fragment_id: str, fragment_text: str) -> RenderedElementProbe:
    return RenderedElementProbe(
        element_id=f"text-{page_id}",
        kind="text",
        actual_box=Box(x=88, y=120, width=904, height=160),
        computed_font_family="Test Body",
        computed_font_size=28.0,
        computed_line_height=40.6,
        overflow=False,
        ink_clipped=False,
        layout_clipped=False,
        contrast_ratio=18.0,
        content_ref=fragment_id,
        asset_ref=None,
        rasterized_text_sha256=sha256_text(fragment_text),
        rendered_asset_sha256=None,
    )


def _render_manifest(
    design_plan: CarouselDesignPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
    direction: VisualDirectionPlan,
    *,
    render_dir: Path,
) -> RenderManifest:
    render_dir.mkdir(parents=True, exist_ok=True)
    fragment_by_id = {f.fragment_id: f for f in direction.content_fragments}
    pages: list[RenderedPage] = []
    for index, plan_page in enumerate(design_plan.pages, start=1):
        page_path = render_dir / f"page-{index:02d}.png"
        page_sha = _write_png(page_path)
        first_frag = next(
            el.content_ref for el in plan_page.elements if isinstance(el, TextElement)
        )
        pages.append(
            RenderedPage(
                page_id=plan_page.page_id,
                sequence=plan_page.sequence,
                path=str(page_path),
                width=1080,
                height=1440,
                sha256=page_sha,
                element_probes=(
                    _text_probe(
                        plan_page.page_id, first_frag, fragment_by_id[first_frag].text
                    ),
                ),
            )
        )
    contact_path = render_dir / "contact-sheet.png"
    contact_sha = _write_png(contact_path, width=1320, height=1145)
    return RenderManifest(
        design_plan_sha256=canonical_sha256(design_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
        fonts=FontLoadReport(
            all_loaded=True,
            computed_families=("Test Display", "Test Heading", "Test Body"),
        ),
        contact_sheet_path=str(contact_path),
        contact_sheet_sha256=contact_sha,
        source_asset_sha256={item.asset_id: item.sha256 for item in manifest.items},
    )


def _design_qa(design_plan: CarouselDesignPlan) -> DesignPlanQAResult:
    return DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _render_qa(render_manifest: RenderManifest) -> RenderQAResult:
    return RenderQAResult(
        passed=True,
        issues=(),
        render_manifest_sha256=canonical_sha256(render_manifest),
        content_attestation=True,
        geometry_attestation=True,
        asset_attestation=True,
    )


def _visual_critique(
    atom_set: ContentAtomSet,
    direction: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    render_manifest: RenderManifest,
) -> VisualCritique:
    return VisualCritique(
        content_atom_set_sha256=atom_set.canonical_sha256,
        direction_plan_sha256=canonical_sha256(direction),
        design_plan_sha256=canonical_sha256(design_plan),
        render_manifest_sha256=canonical_sha256(render_manifest),
        passed=True,
        revision_round=0,
        contains_images=False,
        overall=80,
        hierarchy=80,
        legibility=80,
        composition=80,
        family_consistency=80,
        page_variation=80,
        page_rhythm=80,
        color=80,
        spacing=80,
        image_relevance="not_applicable",
    )


def _asset_manifest(*, provenance: dict[str, str] | None = None) -> AssetManifest:
    return AssetManifest(
        items=(
            AssetManifestItem(
                asset_id="asset-internal",
                directive_id="directive-internal",
                page_id="page-1",
                source_kind="catalog",
                provider="catalog",
                license="project-owned",
                local_path="/assets/active/internal.svg",
                width=16,
                height=16,
                sha256=hashlib.sha256(b"internal").hexdigest(),
                subject_focal_point=(0.5, 0.5),
                crop_guidance="centered",
                security_status="approved",
                human_decision="pending",
                run_id="run-1",
                transaction_id="tx-1",
                internal_provenance=provenance or {"provider": "catalog"},
            ),
        )
    )


def _publish_package(**overrides) -> dict:
    package = {
        "focus_keyword": "分区护肤",
        "topic_id": "tp_001",
        "topic": "分区护肤怎么判断",
        "angle_id": "ag_001",
        "angle": "按肤质分区",
        "target_group": "通勤护肤人群",
        "core_pain": "分区不清",
        "title": "分区护肤指南",
        "cover_copy": "一张图看懂分区",
        "content": "正文第一段",
        "hashtags": ["#护肤", "#分区"],
        "domain": "beauty",
        "content_contract": {"first_screen_promise": "先看懂分区，再护肤"},
    }
    package.update(overrides)
    return package


def _contracts(tmp_path: Path, *, page_count: int = _PAGE_COUNT):
    atom_set = _atom_set(page_count)
    direction = _direction(atom_set)
    manifest = _asset_manifest()
    design_plan = _design_plan(direction, atom_set, manifest)
    render_dir = tmp_path / "run-output"
    render_manifest = _render_manifest(design_plan, atom_set, manifest, direction, render_dir=render_dir)
    return {
        "atom_set": atom_set,
        "direction": direction,
        "manifest": manifest,
        "design_plan": design_plan,
        "render_manifest": render_manifest,
        "design_qa": _design_qa(design_plan),
        "render_qa": _render_qa(render_manifest),
        "critique": _visual_critique(atom_set, direction, design_plan, render_manifest),
    }


def _state_snapshot(values: dict, *, next_nodes: tuple[str, ...] = ()) -> StateSnapshot:
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


def _completed_state(contracts, package: dict, *, render_dir: Path) -> StateSnapshot:
    values = {
        "publish_package": package,
        "review_status": "approved",
        "visual_aesthetic_override": None,
        "content_atom_set": contracts["atom_set"],
        "visual_direction_plan": contracts["direction"],
        "asset_manifest": contracts["manifest"],
        "carousel_design_plan": contracts["design_plan"],
        "design_plan_qa_result": contracts["design_qa"],
        "render_manifest": contracts["render_manifest"],
        "render_qa_result": contracts["render_qa"],
        "visual_critique": contracts["critique"],
        "r2_output": SimpleNamespace(
            compliance_audit=SimpleNamespace(
                compliance_status="fully_compliant", block_publish=False
            )
        ),
        "run_output_dir": str(render_dir),
        "focus_keyword": package["focus_keyword"],
        "focus_keyword_cli_present": True,
        "_now_for_test": datetime(2026, 7, 31, 10, 0, 0),
    }
    return _state_snapshot(values)


@pytest.fixture(autouse=True)
def _publish_root(monkeypatch, tmp_path):
    monkeypatch.setattr(artifacts_module, "PUBLISH_ROOT", tmp_path / "publish")


CANONICAL_CONTRACT_FILES = (
    "content_atom_set.json",
    "visual_direction_plan.json",
    "asset_manifest.json",
    "carousel_design_plan.json",
    "design_plan_qa.json",
    "render_manifest.json",
    "render_qa.json",
    "visual_critique.json",
    "content_lock.json",
    "final_policy_attestation.json",
)


def _export(tmp_path, **package_overrides):
    contracts = _contracts(tmp_path)
    package = _publish_package(**package_overrides)
    state = _completed_state(contracts, package, render_dir=tmp_path / "run-output")
    return export_publish_package(state), contracts, package


def _package_dir() -> Path:
    return artifacts_module.PUBLISH_ROOT / "20260731-beauty-分区护肤指南"


# ---------------------------------------------------------------------------
# Canonical package layout
# ---------------------------------------------------------------------------


def test_export_emits_canonical_package_file_list(tmp_path):
    result, contracts, package = _export(tmp_path)

    package_dir = _package_dir()
    assert result.package_directory == package_dir
    for name in CANONICAL_CONTRACT_FILES:
        assert (package_dir / name).is_file(), f"missing canonical file: {name}"
    assert (package_dir / "publish-attestation.json").is_file()
    page_files = sorted((package_dir / "pages").glob("*.png"))
    assert len(page_files) == _PAGE_COUNT
    assert page_files[0].name == "01-page-1.png"
    assert (package_dir / "contact-sheet.png").is_file()
    # No legacy support files; the v3 layout has no publish-copy/rescue prompt.
    assert not (package_dir / "publish-copy.txt").exists()
    assert not (package_dir / "images").exists()


def test_export_uses_staging_and_atomic_promotion_no_temp_left(tmp_path):
    result, _, _ = _export(tmp_path)

    package_dir = _package_dir()
    # No staging leftovers inside the publish root.
    assert not list(artifacts_module.PUBLISH_ROOT.glob(".-*-staging"))
    # The canonical directory is the promoted one (real dir, not a symlink).
    assert package_dir.is_dir()


def test_export_refuses_to_overwrite_existing_canonical_package(tmp_path):
    _export(tmp_path)
    # A second export of the same canonical package must not overwrite by hand.
    with pytest.raises(ValueError, match="exists|overwrite|canonical"):
        _export(tmp_path)


# ---------------------------------------------------------------------------
# PublishAttestation hash coverage
# ---------------------------------------------------------------------------


def test_attestation_hashes_every_contract_and_png(tmp_path):
    result, contracts, package = _export(tmp_path)
    package_dir = _package_dir()
    attestation = result.publish_attestation

    assert isinstance(attestation, PublishAttestation)
    assert attestation.workflow_version == "llm_scene_v3"
    # Every contract is hashed.
    assert attestation.content_atom_set_sha256 == canonical_sha256(contracts["atom_set"])
    assert attestation.visual_direction_plan_sha256 == canonical_sha256(contracts["direction"])
    assert attestation.asset_manifest_sha256 == canonical_sha256(contracts["manifest"])
    assert attestation.carousel_design_plan_sha256 == canonical_sha256(contracts["design_plan"])
    assert attestation.design_plan_qa_sha256 == canonical_sha256(contracts["design_qa"])
    assert attestation.render_manifest_sha256 == canonical_sha256(contracts["render_manifest"])
    assert attestation.render_qa_sha256 == canonical_sha256(contracts["render_qa"])
    assert attestation.visual_critique_sha256 == canonical_sha256(contracts["critique"])
    assert attestation.content_lock_sha256 == result.content_lock.canonical_sha256

    # Every PNG is hashed: pages/*.png + contact-sheet.png.
    expected_page_keys = {
        f"pages/0{seq}-page-{seq}.png" for seq in range(1, _PAGE_COUNT + 1)
    }
    expected_page_keys.add("contact-sheet.png")
    assert set(attestation.page_sha256) == expected_page_keys
    for key, digest in attestation.page_sha256.items():
        assert (package_dir / key).read_bytes()
        assert hashlib.sha256((package_dir / key).read_bytes()).hexdigest() == digest

    # The attestation file on disk matches the returned object.
    written = json.loads((package_dir / "publish-attestation.json").read_text(encoding="utf-8"))
    assert written["workflow_version"] == "llm_scene_v3"
    assert written["content_lock_sha256"] == attestation.content_lock_sha256
    assert written["page_sha256"] == attestation.page_sha256


def test_attestation_rejects_tampered_page_bytes(tmp_path):
    contracts = _contracts(tmp_path)
    package = _publish_package()
    # Tamper with a rendered source PNG after the RenderManifest was bound, and
    # do NOT update the manifest sha256 -> the export must detect that the page
    # bytes no longer match the persisted manifest attestation.
    page_path = Path(contracts["render_manifest"].pages[0].path)
    page_path.write_bytes(_png_bytes(color="#FF0000"))

    with pytest.raises(ValueError, match="sha256|page"):
        export_publish_package(_completed_state(contracts, package, render_dir=tmp_path / "run-output"))


# ---------------------------------------------------------------------------
# No legacy / fixed-template fields + AI-provenance internal-only
# ---------------------------------------------------------------------------


def test_exported_contracts_contain_no_storyboard_or_visual_plan_or_template_fields(tmp_path):
    result, _, _ = _export(tmp_path)
    package_dir = _package_dir()

    forbidden_substrings = ("storyboard", "visual_plan", "carousel_qa", "template_selection", "frame_plan")
    for json_file in (*CANONICAL_CONTRACT_FILES, "publish-attestation.json"):
        text = (package_dir / json_file).read_text(encoding="utf-8").lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in text, f"{json_file} leaks legacy field {forbidden}"


def test_ai_provenance_lives_only_in_internal_asset_json(tmp_path):
    # AI-generation provenance is injected into the asset item's internal_provenance.
    contracts = _contracts(tmp_path)
    package = _publish_package()
    provenance_marker = "ai-generated-marker-XYZ"
    # Replace the manifest with one carrying explicit AI provenance.
    ai_manifest = _asset_manifest(provenance={"provider": "gemini", "model": "x", "marker": provenance_marker})
    # Rebuild design + render contracts bound to the new manifest hash so bindings stay valid.
    direction = contracts["direction"]
    atom_set = contracts["atom_set"]
    design_plan = _design_plan(direction, atom_set, ai_manifest)
    render_dir = tmp_path / "run-output"
    render_manifest = _render_manifest(design_plan, atom_set, ai_manifest, direction, render_dir=render_dir)
    contracts["manifest"] = ai_manifest
    contracts["design_plan"] = design_plan
    contracts["render_manifest"] = render_manifest
    contracts["design_qa"] = _design_qa(design_plan)
    contracts["render_qa"] = _render_qa(render_manifest)
    contracts["critique"] = _visual_critique(atom_set, direction, design_plan, render_manifest)

    export_publish_package(_completed_state(contracts, package, render_dir=render_dir))
    package_dir = _package_dir()

    # The marker may appear ONLY inside asset_manifest.json (internal provenance).
    asset_text = (package_dir / "asset_manifest.json").read_text(encoding="utf-8")
    assert provenance_marker in asset_text
    for json_file in CANONICAL_CONTRACT_FILES:
        if json_file == "asset_manifest.json":
            continue
        assert provenance_marker not in (package_dir / json_file).read_text(encoding="utf-8")
    # And never in any rendered PNG (marker is text, not pixels).
    for png in (package_dir / "pages").glob("*.png"):
        assert provenance_marker.encode() not in png.read_bytes()


# ---------------------------------------------------------------------------
# Terminal-state / Final-Guard gates
# ---------------------------------------------------------------------------


def test_export_rejects_non_terminal_state(tmp_path):
    contracts = _contracts(tmp_path)
    package = _publish_package()
    state = _completed_state(contracts, package, render_dir=tmp_path / "run-output")
    active = state._replace(next=("content_writer",))

    with pytest.raises(ValueError, match="terminal|next"):
        export_publish_package(active)


def test_export_rejects_raw_dict_package(tmp_path):
    with pytest.raises(TypeError, match="StateSnapshot"):
        export_publish_package({"publish_package": {}})


def test_export_rejects_failed_final_guard(tmp_path):
    contracts = _contracts(tmp_path)
    package = _publish_package()
    # Keep review approved but fail the visual critique without an aesthetic
    # override so Final Guard hard-rejects on the recomputed issue list.
    values = dict(_completed_state(contracts, package, render_dir=tmp_path / "run-output").values)
    values["visual_critique"] = VisualCritique(
        content_atom_set_sha256=contracts["atom_set"].canonical_sha256,
        direction_plan_sha256=canonical_sha256(contracts["direction"]),
        design_plan_sha256=canonical_sha256(contracts["design_plan"]),
        render_manifest_sha256=canonical_sha256(contracts["render_manifest"]),
        passed=False,
        revision_round=2,
        contains_images=False,
        overall=40,
        hierarchy=40,
        legibility=40,
        composition=40,
        family_consistency=40,
        page_variation=40,
        page_rhythm=40,
        color=40,
        spacing=40,
        image_relevance="not_applicable",
        issues=(
            {
                "rule": "composition",
                "message": "weak hierarchy",
                "revision_instruction": "strengthen",
                "page_id": "page-1",
            },
        ),
        revision_instructions=("strengthen hierarchy",),
    )
    values["visual_aesthetic_override"] = None
    state = _state_snapshot(values)

    with pytest.raises(ValueError, match="Final Guard|final_policy"):
        export_publish_package(state)


def test_export_rejects_rejected_asset(tmp_path):
    contracts = _contracts(tmp_path)
    package = _publish_package()
    # Mark the manifest item security-rejected so Final Guard hard-fails.
    rejected_item = contracts["manifest"].items[0].model_copy(
        update={"security_status": "rejected"}
    )
    contracts["manifest"] = AssetManifest(items=(rejected_item,))
    values = dict(_completed_state(contracts, package, render_dir=tmp_path / "run-output").values)
    values["asset_manifest"] = contracts["manifest"]
    state = _state_snapshot(values)

    with pytest.raises(ValueError, match="Final Guard|final_policy|asset"):
        export_publish_package(state)


def test_export_rejects_wrong_page_dimensions(tmp_path):
    contracts = _contracts(tmp_path)
    package = _publish_package()
    page_path = Path(contracts["render_manifest"].pages[0].path)
    page_path.write_bytes(_png_bytes(width=100, height=100))
    contracts["render_manifest"].pages[0].__dict__["sha256"] = hashlib.sha256(
        page_path.read_bytes()
    ).hexdigest()

    with pytest.raises(ValueError, match="1080 x 1440|dimension|page"):
        export_publish_package(_completed_state(contracts, package, render_dir=tmp_path / "run-output"))
