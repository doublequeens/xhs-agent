"""Deterministic render QA over the rendered scene/PNG output (Task 12).

Pure rules — no LLM, no network, no clock, no randomness. ``evaluate_render``
hard-gates a ``RenderManifest`` (and its persisted probes / PNG files) against
the source atoms / direction / asset manifest / QA-approved design plan and
returns a ``RenderQAResult`` with actionable, deterministically-ordered issues.
The render-reviser loop (Task 14 wiring) and ``route_after_render_qa`` consume
the result; the 3-strike budget is exposed via ``render_qa_exhausted``.

Issue rule prefixes are ``content.`` / ``geometry.`` / ``asset.``; the three
attestations key off those prefixes exactly as the brief specifies. This module
mirrors ``src/visual_design/plan_qa.py`` (Task 9): pure, deterministic, stable
walk order, never force-pass.

The thresholds (font sizes, WCAG contrast ratios, canvas geometry) are reused
verbatim from ``plan_qa`` so design-plan QA and render QA apply one consistent
readability bar.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import ContentAtomSet, canonical_sha256, sha256_text
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import RenderManifest, RenderedElementProbe, RenderedPage
from src.schemas.render_qa import RenderIssue, RenderQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    TextElement,
)
from src.schemas.visual_director import VisualDirectionPlan
from src.visual_design.plan_qa import (
    _FORBIDDEN_LABEL_PATTERNS,
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    LARGE_TEXT_CONTRAST,
    MIN_BODY_FONT_PX,
    MIN_DISPLAY_FONT_PX,
    NORMAL_TEXT_CONTRAST,
)

# The render-reviser loop may consume at most this many failing QA results; on
# the third failure the render-QA stage interrupts with checkpointable details.
MAX_RENDER_QA_FAILURES = 3

_EPS = 1e-9
# Rendered focal points are passed through deterministically from the design
# plan; allow a tiny float tolerance rather than bit-exact comparison.
_FOCAL_POINT_TOLERANCE = 1e-6

# Sentinel location for manifest-level issues (RenderIssue requires a location).
_PLAN_LEVEL = "__manifest__"


# --- inputs ---------------------------------------------------------------


@dataclass(frozen=True)
class RenderQAInputs:
    atoms: ContentAtomSet
    direction: VisualDirectionPlan
    assets: AssetManifest
    design_plan: CarouselDesignPlan
    design_plan_qa: DesignPlanQAResult
    render_manifest: RenderManifest


# --- 3-strike budget ------------------------------------------------------


def render_qa_exhausted(prior_failures: int) -> bool:
    """Return True when a fresh failing result reaches the 3-strike budget.

    ``prior_failures`` is the count of consecutive failing render-QA results
    already recorded in state *before* the current attempt. The current attempt
    is itself a failure, so exhaustion happens when ``prior_failures + 1``
    reaches ``MAX_RENDER_QA_FAILURES``.
    """
    return prior_failures + 1 >= MAX_RENDER_QA_FAILURES


# --- geometry helpers (mirror plan_qa, kept local for self-containment) ----


def _box_right(box: Box) -> float:
    return box.x + box.width


def _box_bottom(box: Box) -> float:
    return box.y + box.height


def _boxes_intersect(a: Box, b: Box) -> bool:
    # Touching edges (<=) do not count as an overlap.
    return not (
        _box_right(a) <= b.x + _EPS
        or _box_right(b) <= a.x + _EPS
        or _box_bottom(a) <= b.y + _EPS
        or _box_bottom(b) <= a.y + _EPS
    )


# --- file helpers ---------------------------------------------------------


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    """Return ``(width, height)`` from the PNG IHDR, or ``None`` if unreadable."""
    try:
        header = path.read_bytes()[:24]
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


# --- issue factory --------------------------------------------------------


def _issue(
    rule: str,
    message: str,
    repair_instruction: str,
    *,
    page_id: str | None = None,
    element_id: str | None = None,
    atom_id: str | None = None,
) -> RenderIssue:
    return RenderIssue(
        rule=rule,
        message=message,
        repair_instruction=repair_instruction,
        page_id=page_id,
        element_id=element_id,
        atom_id=atom_id,
    )


# --- manifest hash bindings -----------------------------------------------


def verify_manifest_bindings(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    manifest = inputs.render_manifest

    if manifest.design_plan_sha256 != canonical_sha256(inputs.design_plan):
        issues.append(
            _issue(
                "content.design_plan_hash_mismatch",
                "render manifest design_plan_sha256 does not match the source design plan",
                "regenerate the render manifest against the current CarouselDesignPlan",
                page_id=_PLAN_LEVEL,
            )
        )
    if manifest.content_atom_set_sha256 != inputs.atoms.canonical_sha256:
        issues.append(
            _issue(
                "content.atom_set_hash_mismatch",
                "render manifest content_atom_set_sha256 does not match the source atom set",
                "rebind the manifest to the current ContentAtomSet",
                page_id=_PLAN_LEVEL,
            )
        )
    if manifest.asset_manifest_sha256 != canonical_sha256(inputs.assets):
        issues.append(
            _issue(
                "asset.manifest_hash_mismatch",
                "render manifest asset_manifest_sha256 does not match the source asset manifest",
                "rebind the manifest to the current AssetManifest",
                page_id=_PLAN_LEVEL,
            )
        )

    qa = inputs.design_plan_qa
    if not qa.passed:
        issues.append(
            _issue(
                "content.design_plan_qa_not_passing",
                "render QA requires a passing design plan QA result",
                "route the design plan back through the design reviser until QA passes",
                page_id=_PLAN_LEVEL,
            )
        )
    if qa.design_plan_sha256 != canonical_sha256(inputs.design_plan):
        issues.append(
            _issue(
                "content.design_plan_qa_hash_stale",
                "design plan QA result is bound to a stale design plan hash",
                "re-run design plan QA against the current CarouselDesignPlan",
                page_id=_PLAN_LEVEL,
            )
        )
    return issues


# --- page files / order / canvas ------------------------------------------


def verify_page_files(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    plan = inputs.design_plan
    manifest = inputs.render_manifest

    plan_page_ids = tuple(page.page_id for page in plan.pages)
    manifest_page_ids = tuple(page.page_id for page in manifest.pages)
    if len(manifest_page_ids) != len(plan_page_ids):
        issues.append(
            _issue(
                "content.page_count_mismatch",
                (
                    f"render manifest has {len(manifest_page_ids)} pages; "
                    f"design plan has {len(plan_page_ids)}"
                ),
                "render exactly as many pages as the design plan declares",
                page_id=_PLAN_LEVEL,
            )
        )
    # Order check: compare the shared prefix so a count mismatch does not also
    # emit a cascade of order issues for the missing tail.
    comparable = min(len(plan_page_ids), len(manifest_page_ids))
    if manifest_page_ids[:comparable] != plan_page_ids[:comparable]:
        issues.append(
            _issue(
                "content.page_order_mismatch",
                "render manifest page order does not match the design plan page order",
                "render the pages in the design plan's page-id sequence",
                page_id=_PLAN_LEVEL,
            )
        )

    for rendered in manifest.pages:
        page_id = rendered.page_id
        path = Path(rendered.path)
        file_hash = _file_sha256(path)
        if file_hash is None:
            issues.append(
                _issue(
                    "content.page_file_missing",
                    f"rendered page {page_id} file is missing or unreadable",
                    f"write the PNG for page {page_id} to the manifest path",
                    page_id=page_id,
                )
            )
            continue
        if file_hash != rendered.sha256:
            issues.append(
                _issue(
                    "content.page_hash_mismatch",
                    f"rendered page {page_id} sha256 does not match its PNG bytes",
                    f"re-render page {page_id} or correct the manifest hash",
                    page_id=page_id,
                )
            )
        dimensions = _png_dimensions(path)
        if dimensions != (CANVAS_WIDTH, CANVAS_HEIGHT):
            issues.append(
                _issue(
                    "content.page_png_dimensions_mismatch",
                    (
                        f"rendered page {page_id} PNG must be "
                        f"{CANVAS_WIDTH}x{CANVAS_HEIGHT}; got {dimensions}"
                    ),
                    f"re-render page {page_id} at the exact canvas size",
                    page_id=page_id,
                )
            )

    issues.extend(_verify_contact_sheet(inputs))
    issues.extend(_verify_source_asset_hashes(inputs))
    return issues


def _verify_contact_sheet(inputs: RenderQAInputs) -> list[RenderIssue]:
    manifest = inputs.render_manifest
    path = Path(manifest.contact_sheet_path)
    file_hash = _file_sha256(path)
    if file_hash is None:
        return [
            _issue(
                "asset.contact_sheet_missing",
                "render manifest contact sheet file is missing or unreadable",
                "write the contact-sheet PNG to the manifest path",
                page_id=_PLAN_LEVEL,
            )
        ]
    if file_hash != manifest.contact_sheet_sha256:
        return [
            _issue(
                "asset.contact_sheet_hash_mismatch",
                "render manifest contact_sheet_sha256 does not match its PNG bytes",
                "regenerate the contact sheet or correct the manifest hash",
                page_id=_PLAN_LEVEL,
            )
        ]
    return []


def _verify_source_asset_hashes(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    manifest = inputs.render_manifest
    declared_map = dict(manifest.source_asset_sha256)
    for item in inputs.assets.items:
        declared = declared_map.get(item.asset_id)
        if declared is None or declared != item.sha256:
            issues.append(
                _issue(
                    "asset.source_asset_hash_mismatch",
                    (
                        f"render manifest source_asset_sha256[{item.asset_id}] "
                        "does not match the AssetManifestItem sha256"
                    ),
                    f"bind source_asset_sha256[{item.asset_id}] to the asset's declared hash",
                    page_id=item.page_id,
                    element_id=item.asset_id,
                )
            )
            continue
        file_hash = _file_sha256(Path(item.local_path))
        if file_hash is None or file_hash != declared:
            issues.append(
                _issue(
                    "asset.source_asset_file_hash_mismatch",
                    (
                        f"render manifest source_asset_sha256[{item.asset_id}] "
                        "does not match the asset's source file bytes"
                    ),
                    f"re-resolve asset {item.asset_id} so the file bytes match the manifest",
                    page_id=item.page_id,
                    element_id=item.asset_id,
                )
            )
    return issues


# --- element probes: geometry / typography / overlap ----------------------


def _bearing_probes(page: RenderedPage) -> tuple[RenderedElementProbe, ...]:
    # Lines have a start/end rather than a filling box; they do not participate
    # in the bounding-box geometry/overlap attestation.
    return tuple(p for p in page.element_probes if p.kind != "line")


def verify_element_probes(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    plan_page_by_id = {page.page_id: page for page in inputs.design_plan.pages}
    rendered_page_by_id = {page.page_id: page for page in inputs.render_manifest.pages}

    for plan_page in inputs.design_plan.pages:
        rendered = rendered_page_by_id.get(plan_page.page_id)
        if rendered is None:
            # Count/order mismatch is already attested by verify_page_files.
            continue
        issues.extend(_probe_binding_issues(plan_page, rendered))
        issues.extend(_probe_geometry_issues(plan_page, rendered))
    return issues


def _probe_binding_issues(
    plan_page: PageScene, rendered: RenderedPage
) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    plan_element_ids = {element.element_id for element in plan_page.elements}
    probe_ids = {probe.element_id for probe in rendered.element_probes}

    for element in plan_page.elements:
        if element.element_id not in probe_ids:
            issues.append(
                _issue(
                    "geometry.missing_probe",
                    (
                        f"design plan element {element.element_id} on page "
                        f"{plan_page.page_id} has no rendered probe"
                    ),
                    f"emit a probe for element {element.element_id}",
                    page_id=plan_page.page_id,
                    element_id=element.element_id,
                )
            )
    for probe in rendered.element_probes:
        if probe.element_id not in plan_element_ids:
            issues.append(
                _issue(
                    "geometry.extra_probe",
                    (
                        f"probe {probe.element_id} on page {plan_page.page_id} "
                        "has no corresponding design plan element"
                    ),
                    f"drop the orphan probe {probe.element_id}",
                    page_id=plan_page.page_id,
                    element_id=probe.element_id,
                )
            )
    return issues


def _probe_geometry_issues(
    plan_page: PageScene, rendered: RenderedPage
) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    plan_element_by_id = {element.element_id: element for element in plan_page.elements}
    for probe in rendered.element_probes:
        plan_element = plan_element_by_id.get(probe.element_id)
        if plan_element is None:
            continue  # extra-probe rule already flags this
        if probe.overflow:
            issues.append(
                _issue(
                    "geometry.overflow",
                    f"probe {probe.element_id} reports content overflow",
                    "reduce the element content or enlarge its box",
                    page_id=plan_page.page_id,
                    element_id=probe.element_id,
                )
            )
        if probe.ink_clipped:
            issues.append(
                _issue(
                    "geometry.ink_clipped",
                    f"probe {probe.element_id} reports ink clipping",
                    "enlarge the box or reduce the ink area",
                    page_id=plan_page.page_id,
                    element_id=probe.element_id,
                )
            )
        if probe.layout_clipped:
            issues.append(
                _issue(
                    "geometry.layout_clipped",
                    f"probe {probe.element_id} reports layout clipping",
                    "resize the box so the layout is not clipped",
                    page_id=plan_page.page_id,
                    element_id=probe.element_id,
                )
            )
        box = probe.actual_box
        if _box_right(box) > CANVAS_WIDTH + _EPS or _box_bottom(box) > CANVAS_HEIGHT + _EPS:
            issues.append(
                _issue(
                    "geometry.box_out_of_bounds",
                    (
                        f"probe {probe.element_id} actual box "
                        f"({box.x},{box.y},{box.width},{box.height}) exceeds the "
                        f"{CANVAS_WIDTH}x{CANVAS_HEIGHT} canvas"
                    ),
                    "fit the rendered element box inside the canvas",
                    page_id=plan_page.page_id,
                    element_id=probe.element_id,
                )
            )
        if isinstance(plan_element, TextElement):
            issues.extend(_typography_issues(plan_page, plan_element, probe))

    issues.extend(_rendered_overlap_issues(plan_page, rendered, plan_element_by_id))
    return issues


def _typography_issues(
    plan_page: PageScene,
    plan_element: TextElement,
    probe: RenderedElementProbe,
) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    role = plan_element.style.font_role
    size_threshold = (
        MIN_DISPLAY_FONT_PX if role in ("display", "heading") else MIN_BODY_FONT_PX
    )
    if probe.computed_font_size is not None and probe.computed_font_size < size_threshold - _EPS:
        issues.append(
            _issue(
                "geometry.undersized_font",
                (
                    f"probe {probe.element_id} rendered font size "
                    f"{probe.computed_font_size}px is below the {size_threshold}px "
                    f"minimum for role {role}"
                ),
                f"raise the rendered font size to at least {size_threshold}px",
                page_id=plan_page.page_id,
                element_id=probe.element_id,
            )
        )
    # Classify large vs normal text by the DESIGN plan's intended font size so
    # the WCAG threshold is deterministic and matches design-plan QA (plan_qa).
    is_large = plan_element.style.font_size >= MIN_DISPLAY_FONT_PX - _EPS
    threshold = LARGE_TEXT_CONTRAST if is_large else NORMAL_TEXT_CONTRAST
    if probe.contrast_ratio < threshold - _EPS:
        classification = "large" if is_large else "normal"
        issues.append(
            _issue(
                "geometry.low_contrast",
                (
                    f"probe {probe.element_id} contrast ratio {probe.contrast_ratio:.2f}:1 "
                    f"is below {threshold}:1 for {classification} text"
                ),
                "choose a text/background pair that meets the WCAG threshold",
                page_id=plan_page.page_id,
                element_id=probe.element_id,
            )
        )
    return issues


def _rendered_overlap_issues(
    plan_page: PageScene,
    rendered: RenderedPage,
    plan_element_by_id: dict[str, Any],
) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    bearing = _bearing_probes(rendered)
    for i, first in enumerate(bearing):
        first_element = plan_element_by_id.get(first.element_id)
        for second in bearing[i + 1:]:
            if not _boxes_intersect(first.actual_box, second.actual_box):
                continue
            second_element = plan_element_by_id.get(second.element_id)
            if _declared_intentional(first_element, second.element_id):
                continue
            if _declared_intentional(second_element, first.element_id):
                continue
            issues.append(
                _issue(
                    "geometry.unintended_overlap",
                    (
                        f"rendered probes {first.element_id} and {second.element_id} "
                        f"overlap on page {plan_page.page_id} without intentional_overlap_with"
                    ),
                    "declare intentional_overlap_with or separate the rendered elements",
                    page_id=plan_page.page_id,
                    element_id=second.element_id,
                )
            )
    return issues


def _declared_intentional(element: Any, other_id: str) -> bool:
    if element is None:
        return False
    return other_id in getattr(element, "intentional_overlap_with", ())


# --- text attestation -----------------------------------------------------


def verify_text_attestation(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    fragment_by_id = {f.fragment_id: f for f in inputs.direction.content_fragments}
    atom_by_id = {atom.atom_id: atom for atom in inputs.atoms.atoms}

    for rendered in inputs.render_manifest.pages:
        for probe in rendered.element_probes:
            if probe.kind != "text":
                continue
            fragment_id = probe.content_ref
            fragment = fragment_by_id.get(fragment_id) if fragment_id else None
            if fragment is None:
                issues.append(
                    _issue(
                        "content.unknown_content_ref",
                        (
                            f"text probe {probe.element_id} references unknown "
                            f"content fragment {fragment_id}"
                        ),
                        f"point content_ref at a fragment owned by page {rendered.page_id}",
                        page_id=rendered.page_id,
                        element_id=probe.element_id,
                    )
                )
                continue
            expected_hash = sha256_text(fragment.text)
            if probe.rasterized_text_sha256 != expected_hash:
                issues.append(
                    _issue(
                        "content.rasterized_text_hash_mismatch",
                        (
                            f"text probe {probe.element_id} rasterized_text_sha256 "
                            "does not match the referenced fragment text"
                        ),
                        f"re-render element {probe.element_id} so its rasterized text matches the fragment",
                        page_id=rendered.page_id,
                        element_id=probe.element_id,
                    )
                )
            atom = atom_by_id.get(fragment.source_atom_id)
            if atom is not None:
                lowered = atom.text.lower()
                if any(pattern in lowered for pattern in _FORBIDDEN_LABEL_PATTERNS):
                    issues.append(
                        _issue(
                            "content.forbidden_visible_label",
                            (
                                f"atom {atom.atom_id} renders a forbidden visible "
                                "label/disclaimer/AI disclosure"
                            ),
                            "remove the disclaimer/AI-disclosure text from the content atom",
                            page_id=rendered.page_id,
                            element_id=probe.element_id,
                            atom_id=atom.atom_id,
                        )
                    )
    return issues


# --- image crop / focal point / asset hash --------------------------------


def verify_image_crops(inputs: RenderQAInputs) -> list[RenderIssue]:
    issues: list[RenderIssue] = []
    asset_by_id = {item.asset_id: item for item in inputs.assets.items}
    plan_element_by_id = {
        element.element_id: element
        for page in inputs.design_plan.pages
        for element in page.elements
    }
    rendered_asset_refs: set[str] = set()

    for rendered in inputs.render_manifest.pages:
        for probe in rendered.element_probes:
            if probe.kind != "image":
                continue
            asset_id = probe.asset_ref
            if asset_id:
                rendered_asset_refs.add(asset_id)
            asset = asset_by_id.get(asset_id) if asset_id else None
            if asset is None:
                issues.append(
                    _issue(
                        "asset.unknown_asset_ref",
                        (
                            f"image probe {probe.element_id} references asset "
                            f"{asset_id} not in the manifest"
                        ),
                        "point asset_ref at an approved manifest asset",
                        page_id=rendered.page_id,
                        element_id=probe.element_id,
                    )
                )
                continue
            if probe.rendered_asset_sha256 != asset.sha256:
                issues.append(
                    _issue(
                        "asset.rendered_hash_mismatch",
                        (
                            f"image probe {probe.element_id} rendered_asset_sha256 "
                            "does not match the asset's declared sha256"
                        ),
                        f"re-render element {probe.element_id} from the approved asset bytes",
                        page_id=rendered.page_id,
                        element_id=probe.element_id,
                    )
                )
            plan_element = plan_element_by_id.get(probe.element_id)
            if isinstance(plan_element, ImageElement) and probe.actual_focal_point is not None:
                dx = abs(probe.actual_focal_point[0] - plan_element.focal_point[0])
                dy = abs(probe.actual_focal_point[1] - plan_element.focal_point[1])
                if dx > _FOCAL_POINT_TOLERANCE or dy > _FOCAL_POINT_TOLERANCE:
                    issues.append(
                        _issue(
                            "asset.focal_point_mismatch",
                            (
                                f"image probe {probe.element_id} actual focal point "
                                f"{probe.actual_focal_point} does not match the design "
                                f"focal point {plan_element.focal_point}"
                            ),
                            "re-render the image with the design plan's focal point",
                            page_id=rendered.page_id,
                            element_id=probe.element_id,
                        )
                    )

    for item in inputs.assets.items:
        if item.security_status == "approved" and item.asset_id not in rendered_asset_refs:
            issues.append(
                _issue(
                    "asset.unrendered_asset",
                    (
                        f"approved asset {item.asset_id} is not rendered by any image probe"
                    ),
                    f"add an image element that renders asset {item.asset_id}",
                    page_id=item.page_id,
                    element_id=item.asset_id,
                )
            )
    return issues


# --- composition ----------------------------------------------------------


def evaluate_render(inputs: RenderQAInputs) -> RenderQAResult:
    """Run every deterministic rule and return a hard-gate QA result.

    Issue order is stable: manifest bindings -> page files -> element probes
    (geometry/typography/overlap) -> text attestation -> image crops. Within
    each validator, issues are emitted in a deterministic page-sequence /
    element-order / asset-order walk. Same inputs always yield the same issue
    tuple in the same order. The gate never force-passes.
    """
    issues: Iterable[RenderIssue] = (
        verify_manifest_bindings(inputs)
        + verify_page_files(inputs)
        + verify_element_probes(inputs)
        + verify_text_attestation(inputs)
        + verify_image_crops(inputs)
    )
    issue_tuple = tuple(issues)

    return RenderQAResult(
        passed=not issue_tuple,
        issues=issue_tuple,
        render_manifest_sha256=canonical_sha256(inputs.render_manifest),
        content_attestation=not any(
            issue.rule.startswith("content.") for issue in issue_tuple
        ),
        geometry_attestation=not any(
            issue.rule.startswith("geometry.") for issue in issue_tuple
        ),
        asset_attestation=not any(
            issue.rule.startswith("asset.") for issue in issue_tuple
        ),
    )


__all__ = [
    "MAX_RENDER_QA_FAILURES",
    "RenderQAInputs",
    "evaluate_render",
    "render_qa_exhausted",
    "verify_element_probes",
    "verify_image_crops",
    "verify_manifest_bindings",
    "verify_page_files",
    "verify_text_attestation",
]
