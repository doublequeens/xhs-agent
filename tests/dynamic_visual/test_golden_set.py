"""The 24-case golden matrix for the ``llm_scene_v3`` dynamic visual pipeline.

Every case drives the REAL ``create_graph()`` end-to-end (offline, scripted
fakes for the four structured-model visual nodes; a deterministic PIL
``render_page_fn`` seam so the produced PNGs are byte-stable without Chromium)
and asserts the full per-case contract from ``task-18-brief.md`` Step 2:

* exact atom reconstruction + coverage
* exactly one family
* page count 5..18 and no empty page
* asset provenance / safety / hash binding
* Design Plan QA and Render QA pass (the REAL deterministic gates, unweakened)
* PNG dimensions / order / count
* no visible AI / disclaimer text
* no structural Human Review edit required for approved fixtures (the approved
  path reaches ``final_policy_guard -> content_writer`` without human rework)

A separate matrix-coverage test proves the 24 cases jointly exercise every
family (>=3), page count, copy shape, density and asset mode required by the
brief.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256
from src.nodes.node_p_content_atomizer import build_content_atoms
from tests.dynamic_visual.golden_fixtures import (
    GoldenHarness,
    all_case_ids,
    forbidden_visible_text_hits,
    load_case,
    load_manifest,
)

CASE_IDS = all_case_ids()


def _run_case(case_id: str, tmp_path: Path, monkeypatch):
    spec = load_case(case_id)
    harness = GoldenHarness(spec=spec, tmp_path=tmp_path)
    state = harness.run(monkeypatch)
    return spec, harness, state


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_golden_case_reaches_content_writer_approved(case_id, tmp_path, monkeypatch):
    """Every golden fixture is an approved run: it must reach the content_writer
    sentinel with an empty Final Guard issue list and no human rework."""
    spec, harness, state = _run_case(case_id, tmp_path, monkeypatch)

    # 9. No structural Human Review edit required: approved + clean guard +
    #    terminal state captured (content_writer sentinel).
    assert state.get("review_status") == "approved", case_id
    assert state.get("final_policy_issues") == [], case_id
    assert state.get("review_route") == "final_policy_guard", case_id
    atom_set = state["content_atom_set"]
    direction = state["visual_direction_plan"]
    design_plan = state["carousel_design_plan"]
    manifest = state["asset_manifest"]
    render_manifest = state["render_manifest"]
    critique = state["visual_critique"]

    # 1. Exact atom reconstruction + coverage.
    expected_atoms = build_content_atoms(
        title=spec.publish_package["title"],
        cover_copy=spec.publish_package["cover_copy"],
        content=spec.publish_package["content"],
    )
    actual_texts = [atom.text for atom in atom_set.atoms]
    expected_texts = [atom.text for atom in expected_atoms]
    assert actual_texts == expected_texts, f"{case_id}: atom reconstruction mismatch"
    # every atom is owned by exactly one fragment and one page
    fragment_atom_ids = {frag.source_atom_id for frag in direction.content_fragments}
    assert fragment_atom_ids == {atom.atom_id for atom in atom_set.atoms}, case_id
    # every fragment is rendered exactly once on its owning page
    rendered_refs = [
        el.content_ref
        for page in design_plan.pages
        for el in page.elements
        if getattr(el, "content_ref", None)
    ]
    owned_fragment_ids = {frag.fragment_id for frag in direction.content_fragments}
    assert sorted(rendered_refs) == sorted(owned_fragment_ids), case_id

    # 2. Exactly one family.
    assert direction.template_family == spec.family, case_id
    assert design_plan.pages and all(
        page.background for page in design_plan.pages
    ), case_id

    # 3. Page count 5..18 and no empty page.
    assert 5 <= len(design_plan.pages) <= 18, case_id
    assert len(design_plan.pages) == spec.page_count, case_id
    assert all(len(page.elements) >= 1 for page in design_plan.pages), case_id

    # 4. Asset provenance / safety / hash binding.
    items = list(manifest.items) if isinstance(manifest, AssetManifest) else []
    assert all(item.security_status == "approved" for item in items), case_id
    assert all(item.human_decision != "rejected" for item in items), case_id
    # design-plan <-> manifest hash binding
    assert design_plan.asset_manifest_sha256 == canonical_sha256(manifest), case_id
    # render-manifest <-> manifest hash binding + per-asset source-file binding
    assert render_manifest.asset_manifest_sha256 == canonical_sha256(manifest), case_id
    for item in items:
        declared = render_manifest.source_asset_sha256.get(item.asset_id)
        assert declared == item.sha256, case_id
        assert Path(item.local_path).is_file(), case_id
        assert canonical_sha256_path(item.local_path) == item.sha256, case_id
    # every REQUIRED directive must be covered by an approved manifest item
    required_directive_ids = {
        d.directive_id for d in direction.asset_directives if d.required
    }
    covered = {item.directive_id for item in items}
    assert required_directive_ids <= covered, case_id
    # every approved manifest item must be rendered by an image element
    rendered_asset_refs = {
        el.asset_ref
        for page in design_plan.pages
        for el in page.elements
        if getattr(el, "asset_ref", None)
    }
    assert {item.asset_id for item in items} == rendered_asset_refs, case_id

    # 5. Design Plan QA passes (the REAL deterministic gate).
    assert state["design_plan_qa_result"].passed is True, case_id

    # 6. Render QA passes (the REAL deterministic gate).
    assert state["render_qa_result"].passed is True, case_id

    # 7. PNG dimensions / order / count.
    assert len(render_manifest.pages) == spec.page_count, case_id
    for index, page in enumerate(render_manifest.pages, start=1):
        assert page.sequence == index, case_id
        assert page.width == 1080 and page.height == 1440, case_id
        assert Path(page.path).is_file(), case_id
        assert canonical_sha256_path(page.path) == page.sha256, case_id
    assert Path(render_manifest.contact_sheet_path).is_file(), case_id

    # 8. No visible AI / disclaimer text anywhere in the visible source copy.
    assert forbidden_visible_text_hits(state) == [], case_id

    # Critique hash bindings + approval semantics.
    assert critique.passed is True, case_id
    assert critique.content_atom_set_sha256 == atom_set.canonical_sha256, case_id
    assert critique.design_plan_sha256 == canonical_sha256(design_plan), case_id


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_golden_case_atoms_have_no_forbidden_role_spill(case_id, tmp_path, monkeypatch):
    """The real content_atomizer must route clean copy to visual_director
    (never r2_compliance) for every approved golden fixture."""
    spec, harness, state = _run_case(case_id, tmp_path, monkeypatch)
    assert state.get("content_atomization_route") == "visual_director", case_id


def test_golden_matrix_covers_every_required_axis():
    """The 24 cases jointly cover every family (>=3), every page-count value,
    every copy shape, every density and every asset mode the brief requires."""
    entries = load_manifest()["cases"]
    assert len(entries) == 24

    required_families = {
        "pink_red", "deep_teal", "soft_pink", "coral_impact",
        "green_catalog", "white_quote",
    }
    required_page_counts = {5, 6, 8, 10, 12, 15, 18}
    required_shapes = {
        "tutorial", "checklist", "comparison", "Q&A", "diagnostic",
        "narrative", "myth correction", "saveable-reference",
    }
    required_densities = {"sparse", "standard", "dense"}
    required_asset_modes = {
        "text-only", "searched photo", "generated photoreal skin example",
        "texture", "mixed optional asset loss",
    }

    def counts(key):
        result = {}
        for entry in entries:
            result[entry[key]] = result.get(entry[key], 0) + 1
        return result

    family_counts = counts("family")
    assert set(family_counts) == required_families
    assert all(count >= 3 for count in family_counts.values()), family_counts

    assert required_page_counts <= {e["page_count"] for e in entries}
    assert required_shapes <= {e["copy_shape"] for e in entries}
    assert required_densities <= {e["density"] for e in entries}
    assert required_asset_modes <= {e["asset_mode"] for e in entries}

    # The brief's required copy specialties must each appear somewhere.
    all_notes = " ".join(e.get("note", "") for e in entries)
    for specialty in (
        "Latin ingredient",
        "persistent pain",
        "ordered steps",
        "emoji",
        "long Chinese",
    ):
        assert specialty in all_notes, f"missing copy specialty: {specialty}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def canonical_sha256_path(path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
