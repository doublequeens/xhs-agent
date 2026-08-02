"""Golden 24-case harness for the ``llm_scene_v3`` dynamic visual pipeline.

This module is the shared backbone of ``tests/dynamic_visual/test_golden_set.py``
and ``tests/integration/test_dynamic_visual_workflow.py``. It drives the REAL
``create_graph()`` (LangGraph state-merge, counter persistence, conditional-edge
routing and the deterministic design-plan / render QA gates are all production)
with the research/topic/writing chain replaced by no-op passthroughs and the
four structured-model visual nodes (``visual_director`` /
``asset_resolver`` / ``page_designer`` / ``visual_critic``) replaced by scripted
fakes that build schema-valid contracts against the REAL ``ContentAtomSet`` the
``content_atomizer`` produces at runtime.

Design rules (see ``.superpowers/sdd/task-18-brief.md``):

* Deterministic + offline. No Gemini, no network. Real Chromium is available
  but the golden tests inject a deterministic ``render_page_fn`` (real 1080x1440
  PNG bytes via PIL, probes parsed from the compiled HTML) so the produced
  ``RenderManifest`` is byte-stable. The review script
  (``render_dynamic_visual_review.py``) deliberately uses the real Chromium path
  for human visual inspection.
* Real end-to-end, not snapshots. Assertions are on the produced v3 contracts
  (atoms / direction / manifest / design plan / render manifest / critique) and
  the deterministic QA verdicts, never on canned HTML.
* No QA-threshold weakening. The scripted design plans are constructed to pass
  the REAL ``design_plan_qa`` and ``render_qa`` gates on their own merits
  (non-overlapping in-canvas boxes, WCAG contrast, >=min font sizes, every
  fragment rendered exactly once, every approved asset rendered). If a fixture
  would fail real QA, the fixture is wrong, not the gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from langgraph.checkpoint.memory import InMemorySaver

from src import graph as graph_module
from src.nodes.node_p_generic_scene_renderer import (
    generic_scene_renderer_node as _real_generic_scene_renderer_node,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.decision import (
    R2ContentSnapShoot,
    RevisionMeta,
)
from src.schemas.narrative import NarrativeBeat, NarrativePlan
from src.schemas.r2_output import R2ComplianceAudit, R2Output
from src.schemas.design_qa import DesignPlanQAResult  # noqa: F401  (render_fn kwarg type)
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    ShapeElement,
    TextElement,
    TextStyle,
)
from src.schemas.visual_critique import VisualCritique
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily
from src.rendering.scene.renderer import render_carousel_scenes
from src.rendering.scene.compiler import CompiledPage
from src.rendering.scene.probes import build_element_probes  # noqa: F401  (re-export sanity)
from src.rendering.scene.renderer import RenderedPageDraft
from src.visual_design.plan_qa import FORBIDDEN_LABEL_PATTERNS
from src.visual_design.style_registry import load_style_registry

# ---------------------------------------------------------------------------
# Fixture discovery
# ---------------------------------------------------------------------------

FIXTURES_DIR = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "dynamic_visual"
)
CASES_DIR = FIXTURES_DIR / "cases"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    family: TemplateFamily
    page_count: int
    density: str
    copy_shape: str
    asset_mode: str
    note: str
    publish_package: dict
    human_review_payload: dict


def _load_registry() -> dict[str, FamilyStyleProfile]:
    return load_style_registry()


FAMILY_PROFILES: dict[str, FamilyStyleProfile] = _load_registry()


# A readable accent color per family (drawn from the production palette) used
# for the decorative top band so the review contact sheets are family-distinct.
ACCENT_COLOR: dict[str, str] = {
    "pink_red": "#DC2333",
    "deep_teal": "#0E5A5A",
    "soft_pink": "#EE5C5C",
    "coral_impact": "#F45A5A",
    "green_catalog": "#1E5A2E",
    "white_quote": "#2A4A8C",
}
# A light page background per family (kept light so #1A1A1A body text clears the
# WCAG contrast threshold against it).
PAGE_BACKGROUND: dict[str, str] = {
    "pink_red": "#FFF7F8",
    "deep_teal": "#F3FFFF",
    "soft_pink": "#FFF9F8",
    "coral_impact": "#FFF9F5",
    "green_catalog": "#FBF8EF",
    "white_quote": "#FFFFFF",
}

TEXT_COLOR = "#1A1A1A"
CANVAS_W = 1080
CANVAS_H = 1440
SAFE = 84  # plan_qa safe-margin exclusion for text/icon


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def all_case_ids() -> list[str]:
    return [entry["case_id"] for entry in load_manifest()["cases"]]


def load_case(case_id: str) -> CaseSpec:
    raw = json.loads((CASES_DIR / f"{case_id}.json").read_text(encoding="utf-8"))
    return CaseSpec(
        case_id=raw["case_id"],
        family=raw["family"],
        page_count=int(raw["page_count"]),
        density=raw["density"],
        copy_shape=raw["copy_shape"],
        asset_mode=raw["asset_mode"],
        note=raw.get("note", ""),
        publish_package=raw["publish_package"],
        human_review_payload=raw.get("human_review", {"approved": True}),
    )


# ---------------------------------------------------------------------------
# Asset-mode plan: directives + resolved items + optional-unresolved set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssetDirectiveSpec:
    directive_id: str
    page_index: int  # 0-based page index the directive attaches to
    role: str
    required: bool
    preferred_source: str
    fallback_source: str
    # resolution outcome:
    resolved: bool
    source_kind: str = ""
    provider: str = ""
    license: str = ""


def _asset_plan(spec: CaseSpec) -> list[AssetDirectiveSpec]:
    """Translate the case's ``asset_mode`` into concrete directive specs."""
    mode = spec.asset_mode
    page_count = spec.page_count
    # default asset page = the 3rd page (index 2), clamped so it never collides
    # with the last page; keep it well inside the carousel.
    mid = max(1, min(2, page_count - 2))
    if mode == "text-only":
        return []
    if mode == "searched photo":
        return [
            AssetDirectiveSpec(
                directive_id="dir-search-photo",
                page_index=mid,
                role="evidence_example",
                required=True,
                preferred_source="search",
                fallback_source="generate",
                resolved=True,
                source_kind="search",
                provider="pexels",
                license="Pexels License",
            )
        ]
    if mode == "generated photoreal skin example":
        return [
            AssetDirectiveSpec(
                directive_id="dir-gen-skin",
                page_index=mid,
                role="skin_example",
                required=True,
                preferred_source="generate",
                fallback_source="none",
                resolved=True,
                source_kind="generated",
                provider="gemini",
                license="Generated",
            )
        ]
    if mode == "texture":
        return [
            AssetDirectiveSpec(
                directive_id="dir-texture",
                page_index=mid,
                role="texture",
                required=True,
                preferred_source="either",
                fallback_source="none",
                resolved=True,
                source_kind="catalog",
                provider="local",
                license="project_internal",
            )
        ]
    if mode == "mixed optional asset loss":
        return [
            AssetDirectiveSpec(
                directive_id="dir-mixed-required",
                page_index=mid,
                role="object",
                required=True,
                preferred_source="search",
                fallback_source="generate",
                resolved=True,
                source_kind="search",
                provider="pexels",
                license="Pexels License",
            ),
            AssetDirectiveSpec(
                directive_id="dir-mixed-optional",
                page_index=min(mid + 1, page_count - 1),
                role="decorative",
                required=False,
                preferred_source="search",
                fallback_source="none",
                resolved=False,  # optional loss: no asset produced
            ),
        ]
    raise ValueError(f"unknown asset_mode: {mode}")


def _resolved_specs(spec: CaseSpec) -> list[AssetDirectiveSpec]:
    return [d for d in _asset_plan(spec) if d.resolved]


# ---------------------------------------------------------------------------
# Real 1080x1440 PNG bytes (offline, no Chromium).
# ---------------------------------------------------------------------------


def _blank_png_bytes() -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (CANVAS_W, CANVAS_H), "#FFFFFF").save(buffer, format="PNG")
    return buffer.getvalue()


def _asset_png_bytes() -> bytes:
    """A small, valid PNG written to disk for each resolved asset so the real
    renderer (``_used_source_assets``) and render QA (``source_asset_file_hash``)
    can read and hash it."""

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (256, 256), "#C7C7C7").save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Deterministic render_page_fn: parses the compiled HTML and emits one
# non-overlapping probe per planned element. Real renderer assembles the
# hash-bound RenderManifest + contact sheet.
# ---------------------------------------------------------------------------


import re

_ELEMENT_RE = re.compile(
    r'data-element-id="([^"]+)"(?:[^>]*?data-content-ref="([^"]*)")?'
    r'(?:[^>]*?data-asset-ref="([^"]*)")?'
)


class DeterministicPageRenderer:
    """A ``render_page_fn`` that produces real 1080x1440 PNG bytes and probes.

    Boxes are stacked in non-overlapping bands inside the safe area so the real
    render QA geometry/overlap rules pass regardless of how many elements a page
    carries. Text probes report #1A1A1A on #FFFFFF (contrast ~16:1) at 48px, so
    the typography attestation clears the display/heading thresholds.
    """

    def __init__(self) -> None:
        self.calls: list[CompiledPage] = []

    def __call__(self, compiled_page: CompiledPage) -> RenderedPageDraft:
        self.calls.append(compiled_page)
        page_id = compiled_page.page_id
        elements: list[tuple[str, str | None, str | None]] = []
        seen: set[str] = set()
        for match in _ELEMENT_RE.finditer(compiled_page.html):
            element_id = match.group(1)
            if element_id in seen:
                continue
            seen.add(element_id)
            content_ref = match.group(2) or None
            asset_ref = match.group(3) or None
            elements.append((element_id, content_ref, asset_ref))

        n = max(len(elements), 1)
        band_h = (CANVAS_H - 2 * SAFE) // n
        raw_probes: list[dict] = []
        for index, (element_id, content_ref, asset_ref) in enumerate(elements):
            x = float(SAFE)
            y = float(SAFE + index * band_h)
            w = float(CANVAS_W - 2 * SAFE)
            h = float(max(band_h - 20, 40))
            raw = {
                "element_id": element_id,
                "content_ref": content_ref,
                "asset_ref": asset_ref,
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "scroll_width": w - 20,
                "scroll_height": max(h - 20, 10),
                "client_width": w,
                "client_height": h,
                "font_family": '"Source Han Sans SC", sans-serif',
                "font_size": 48.0,
                "line_height": 62.4,
                "color": "rgb(26, 26, 26)",
                "background_color": "rgb(255, 255, 255)",
            }
            if asset_ref:
                raw["natural_width"] = 256
                raw["natural_height"] = 256
                raw["rendered_image_width"] = w
                raw["rendered_image_height"] = h
            raw_probes.append(raw)
        return RenderedPageDraft(
            page_id=page_id,
            png_bytes=_blank_png_bytes(),
            raw_probes=raw_probes,
        )


def make_deterministic_render_fn() -> tuple[Any, DeterministicPageRenderer]:
    """Return a node-level ``render_fn`` + the underlying page renderer."""

    page_renderer = DeterministicPageRenderer()

    def render_fn(
        design_plan: CarouselDesignPlan,
        *,
        fragments: Mapping[str, ContentFragment],
        assets: Mapping[str, AssetManifestItem],
        style: FamilyStyleProfile,
        design_plan_qa_result: DesignPlanQAResult,
        output_dir: Any,
    ) -> Any:
        return render_carousel_scenes(
            design_plan,
            fragments=fragments,
            assets=assets,
            style=style,
            design_plan_qa_result=design_plan_qa_result,
            output_dir=output_dir,
            render_page_fn=page_renderer,
        )

    return render_fn, page_renderer


# ---------------------------------------------------------------------------
# Scripted visual contracts (built against the runtime ContentAtomSet).
# ---------------------------------------------------------------------------


def _build_fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    """One whole-atom fragment per atom (1:1 page<->atom<->fragment mapping)."""
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{atom.atom_id}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for atom in atom_set.atoms
    )


def _build_direction_plan(
    spec: CaseSpec, atom_set: ContentAtomSet
) -> VisualDirectionPlan:
    profile = FAMILY_PROFILES[spec.family]
    fragments = _build_fragments(atom_set)
    asset_specs = _asset_plan(spec)

    page_to_directive_ids: dict[int, list[str]] = {}
    for d in asset_specs:
        page_to_directive_ids.setdefault(d.page_index + 1, []).append(d.directive_id)

    page_sequence = tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"{spec.copy_shape} 第 {index} 页",
            visual_job=f"visual-job-{index}",
            fragment_ids=(f"fragment-{atom_set.atoms[index - 1].atom_id}",),
            asset_directive_ids=tuple(page_to_directive_ids.get(index, ())),
        )
        for index in range(1, spec.page_count + 1)
    )

    asset_directives = tuple(
        AssetDirective(
            directive_id=d.directive_id,
            page_id=f"page-{d.page_index + 1}",
            role=d.role,  # type: ignore[arg-type]
            required=d.required,
            preferred_source=d.preferred_source,  # type: ignore[arg-type]
            fallback_source=d.fallback_source,  # type: ignore[arg-type]
            query_or_prompt=_asset_query(spec, d),
            negative_constraints=(
                "no embedded text",
                "no AI disclosure",
                "no disclaimer",
            ),
            orientation="square",
            min_width=256,
            min_height=256,
        )
        for d in asset_specs
    )

    return VisualDirectionPlan(
        template_family=spec.family,
        page_count=spec.page_count,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction=f"{profile.composition_principles[0]} · {spec.copy_shape} · {spec.density}",
        palette=profile.palette,
        typography_direction={
            "display": profile.font_roles["display"],
            "heading": profile.font_roles["heading"],
            "body": profile.font_roles["body"],
        },
        motifs=profile.allowed_motifs[:1],
        content_fragments=fragments,
        page_sequence=page_sequence,
        asset_directives=asset_directives,
        recent_visual_context=(),
    )


def _asset_query(spec: CaseSpec, d: AssetDirectiveSpec) -> str:
    if d.role == "skin_example":
        return "photoreal close-up of cheek skin texture, even lighting, no text"
    if d.role == "texture":
        return "abstract cream texture background, macro, no text"
    if d.role == "evidence_example":
        return "sunscreen application on back of hand, daylight, no text"
    if d.role == "object":
        return "minimal skincare bottle on neutral surface, no text"
    return "soft decorative background, no text"


def _build_asset_manifest(
    spec: CaseSpec, asset_dir: Path
) -> tuple[AssetManifest, list[dict]]:
    """Write real asset files and build the manifest + unresolved-optional list."""
    items: list[AssetManifestItem] = []
    unresolved: list[dict] = []
    asset_dir.mkdir(parents=True, exist_ok=True)
    for d in _asset_plan(spec):
        if not d.resolved:
            unresolved.append(
                {
                    "directive_id": d.directive_id,
                    "page_id": f"page-{d.page_index + 1}",
                    "reason": "optional directive skipped offline (golden fixture)",
                }
            )
            continue
        asset_bytes = _asset_png_bytes()
        asset_path = asset_dir / f"{d.directive_id}.png"
        asset_path.write_bytes(asset_bytes)
        asset_id = f"asset-{d.directive_id}"
        items.append(
            AssetManifestItem(
                asset_id=asset_id,
                directive_id=d.directive_id,
                page_id=f"page-{d.page_index + 1}",
                source_kind=d.source_kind,  # type: ignore[arg-type]
                provider=d.provider,
                license=d.license,
                local_path=str(asset_path),
                width=256,
                height=256,
                sha256=hashlib.sha256(asset_bytes).hexdigest(),
                subject_focal_point=(0.5, 0.5),
                crop_guidance="centered",
                security_status="approved",
                human_decision="approved",
                run_id=f"{spec.case_id}-run",
                transaction_id=f"{spec.case_id}-txn",
                internal_provenance={
                    "provider": d.provider,
                    "source_kind": d.source_kind,
                },
            )
        )
    return AssetManifest(items=tuple(items)), unresolved


def _page_elements(
    page_index: int,
    fragment_id: str,
    spec: CaseSpec,
    asset_by_page: Mapping[int, str],
) -> tuple:
    """One accent shape + one heading text (+ optional image) per page."""
    accent = ShapeElement(
        element_id=f"shape-band-{page_index}",
        layer=0,
        box=Box(x=0, y=0, width=1080, height=120),
        shape="rectangle",
        fill=ACCENT_COLOR[spec.family],
        stroke=None,
    )
    text = TextElement(
        element_id=f"text-{page_index}",
        layer=1,
        box=Box(x=SAFE, y=160, width=CANVAS_W - 2 * SAFE, height=300),
        content_ref=fragment_id,
        style=TextStyle(
            font_role="heading",
            font_size=48,
            line_height=1.3,
            color=TEXT_COLOR,
            align="left",
            weight=700,
            emphasis_ranges=(),
        ),
    )
    elements: list = [accent, text]
    asset_id = asset_by_page.get(page_index)
    if asset_id is not None:
        image = ImageElement(
            element_id=f"image-{page_index}",
            layer=2,
            box=Box(x=SAFE, y=520, width=CANVAS_W - 2 * SAFE, height=836),
            asset_ref=asset_id,
            fit="cover",
            focal_point=(0.5, 0.5),
            corner_radius=0,
        )
        elements.append(image)
    return tuple(elements)


def _build_design_plan(
    spec: CaseSpec,
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest: AssetManifest,
) -> CarouselDesignPlan:
    asset_id_by_page: dict[int, str] = {}
    directive_page: dict[str, int] = {}
    for d in _asset_plan(spec):
        directive_page[d.directive_id] = d.page_index + 1
    for item in manifest.items:
        page_num = directive_page.get(item.directive_id)
        if page_num is not None:
            asset_id_by_page[page_num] = item.asset_id

    pages: list[PageScene] = []
    for index, direction_page in enumerate(direction_plan.page_sequence, start=1):
        fragment_id = direction_page.fragment_ids[0]
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background=PAGE_BACKGROUND[spec.family],
                elements=_page_elements(index, fragment_id, spec, asset_id_by_page),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(manifest),
        revision=0,
        pages=tuple(pages),
    )


def _build_critique(
    spec: CaseSpec,
    atom_set: ContentAtomSet,
    direction_plan: VisualDirectionPlan,
    design_plan: CarouselDesignPlan,
    render_manifest: Any,
) -> VisualCritique:
    contains_images = len(_resolved_specs(spec)) > 0
    return VisualCritique(
        content_atom_set_sha256=atom_set.canonical_sha256,
        direction_plan_sha256=canonical_sha256(direction_plan),
        design_plan_sha256=canonical_sha256(design_plan),
        render_manifest_sha256=canonical_sha256(render_manifest),
        passed=True,
        revision_round=0,
        contains_images=contains_images,
        overall=90,
        hierarchy=88,
        legibility=92,
        composition=87,
        family_consistency=92,
        page_variation=85,
        page_rhythm=86,
        color=90,
        spacing=88,
        image_relevance="not_applicable" if not contains_images else 82,
        issues=(),
        revision_instructions=(),
    )


# ---------------------------------------------------------------------------
# Graph harness: install fakes, drive the real graph, capture terminal state.
# ---------------------------------------------------------------------------


class ContentWriterReached(Exception):
    """Sentinel raised by the faked content_writer to capture terminal state."""

    def __init__(self, state: Mapping[str, Any]) -> None:
        self.state = state


class _NullModel:
    def generate_json(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("golden fakes must not invoke the visual model")


def _passthrough(_state, **_kwargs):
    return {}


def _install_noop_upstream(monkeypatch) -> None:
    pre_visual = (
        "domain_router_node",
        "domain_confirmation_node",
        "retrieve_memory_node",
        "topic_signal_collector_node",
        "creative_brief_builder_node",
        "topic_ideator_node",
        "topic_diversity_filter_node",
        "angle_strategist_node",
        "novelty_guard_node",
        "virality_scorer_node",
        "evidence_brief_node",
        "outline_architect_node",
        "draft_writer_node",
        "title_lab_node",
        "title_ranker_node",
        "hashtag_node",
        "assembler_node",
    )
    for node_name in pre_visual:
        monkeypatch.setattr(graph_module.nodes, node_name, _passthrough)

    def decision_route(_state):
        from src.schemas.decision import DecisionOutput, NormalizedInput

        return {
            "decision_output": DecisionOutput(
                next_node="HASHTAG_SEO",
                normalized_input=NormalizedInput(),
            )
        }

    monkeypatch.setattr(graph_module.nodes, "decision_engine_node", decision_route)


@dataclass
class GoldenHarness:
    """Wires a CaseSpec into the real graph and captures every produced artifact.

    ``terminal_state`` is the state snapshot at ``content_writer`` (the sentinel
    stops the graph cleanly without writing to SQLite / chromadb). ``captured``
    holds the scripted contracts the fakes built, for direct assertion.
    """

    spec: CaseSpec
    tmp_path: Path
    asset_dir: Path = field(init=False)
    render_output_dir: Path = field(init=False)
    deterministic_render: bool = True
    captured: dict[str, Any] = field(default_factory=dict)
    terminal_state: Mapping[str, Any] = field(default_factory=dict)
    # Extra ``graph_module.nodes.<name>`` overrides applied AFTER the standard
    # golden fakes during ``install`` (workflow tests use these to plant route
    # sentinels or a failing critic/QA without rebuilding the harness).
    overrides: dict[str, Any] = field(default_factory=dict)
    # When set, used as the human-review interrupt resume payload instead of the
    # case's default approval payload.
    interrupt_payload: dict | None = None

    def __post_init__(self) -> None:
        self.asset_dir = self.tmp_path / "assets"
        self.render_output_dir = self.tmp_path / "render"

    # -- fake node implementations -----------------------------------------

    def _fake_visual_director(self, state, *, model, style_profiles=None):
        atom_set = state["content_atom_set"]
        plan = _build_direction_plan(self.spec, atom_set)
        self.captured["visual_direction_plan"] = plan
        return {"visual_direction_plan": plan, "current_node": "VISUAL_DIRECTOR"}

    def _fake_asset_resolver(
        self, state, *, search_provider, generation_provider,
        safety_checker=None, transaction_root, transaction_id,
    ):
        manifest, unresolved = _build_asset_manifest(self.spec, self.asset_dir)
        self.captured["asset_manifest"] = manifest
        self.captured["unresolved_optional_assets"] = unresolved
        return {
            "asset_manifest": manifest,
            "unresolved_optional_assets": unresolved,
            "current_node": "ASSET_RESOLVER",
        }

    def _fake_page_designer(self, state, *, model, style_profiles=None):
        atom_set = state["content_atom_set"]
        direction_plan = state["visual_direction_plan"]
        manifest = state["asset_manifest"] or AssetManifest(items=())
        plan = _build_design_plan(self.spec, direction_plan, atom_set, manifest)
        self.captured["carousel_design_plan"] = plan
        return {"carousel_design_plan": plan, "current_node": "PAGE_DESIGNER"}

    def _fake_visual_critic(self, state, *, model, style_profiles=None):
        atom_set = state["content_atom_set"]
        direction_plan = state["visual_direction_plan"]
        design_plan = state["carousel_design_plan"]
        render_manifest = state["render_manifest"]
        critique = _build_critique(
            self.spec, atom_set, direction_plan, design_plan, render_manifest
        )
        self.captured["visual_critique"] = critique
        return {
            "visual_critique": critique,
            "visual_critic_round": 1,
            "current_node": "VISUAL_CRITIC",
        }

    # -- public API --------------------------------------------------------

    def install(self, monkeypatch) -> None:
        _install_noop_upstream(monkeypatch)
        # Structured-model fakes (bound by the wrappers at create_graph time).
        monkeypatch.setattr(
            graph_module.nodes, "visual_director_node", self._fake_visual_director
        )
        monkeypatch.setattr(
            graph_module.nodes, "asset_resolver_node", self._fake_asset_resolver
        )
        monkeypatch.setattr(
            graph_module.nodes, "page_designer_node", self._fake_page_designer
        )
        monkeypatch.setattr(
            graph_module.nodes, "visual_critic_node", self._fake_visual_critic
        )
        # Safety: the fakes never call the model, but ensure no Gemini client is
        # ever built.
        monkeypatch.setattr(graph_module, "_get_visual_model", lambda: _NullModel())
        monkeypatch.setattr(graph_module, "_VISUAL_MODEL", _NullModel())

        if self.deterministic_render:
            render_fn, page_renderer = make_deterministic_render_fn()
            self.captured["_page_renderer"] = page_renderer

            def renderer_with_seam(state):
                return _real_generic_scene_renderer_node(
                    state, render_fn=render_fn
                )

            monkeypatch.setattr(
                graph_module.nodes,
                "generic_scene_renderer_node",
                renderer_with_seam,
            )

        def content_writer_sentinel(state):
            raise ContentWriterReached(state)

        monkeypatch.setattr(
            graph_module.nodes, "content_writer_node", content_writer_sentinel
        )
        # Workflow-test overrides win over the standard fakes (applied last).
        for node_name, fake in self.overrides.items():
            monkeypatch.setattr(graph_module.nodes, node_name, fake)

    def initial_state(self) -> dict[str, Any]:
        self.render_output_dir.mkdir(parents=True, exist_ok=True)
        return {
            "publish_package": {
                **self.spec.publish_package,
                # human_review's R2-recheck path rebuilds an R2ContentSnapShoot
                # from publish_package.narrative_plan; carry one so the visible-
                # text-edit route is exercisable. Unused on the happy path.
                "narrative_plan": _default_narrative_plan(),
            },
            "run_output_dir": str(self.render_output_dir),
            "domain_context": {
                "domain": self.spec.publish_package.get("domain", "beauty"),
                "profile_version": "beauty-v1",
                "subdomain": self.spec.publish_package.get("subdomain", "skincare"),
            },
            "unresolved_optional_assets": [],
            "review_round": 0,
            "r2_output": _build_r2_output(self.spec),
        }

    def run(self, monkeypatch, *, thread_id: str | None = None) -> Mapping[str, Any]:
        # Run from tmp so the asset-resolver wrapper's ``data/asset_transactions``
        # scratch tree and any other CWD-relative writes stay out of the repo.
        monkeypatch.chdir(self.tmp_path)
        self.install(monkeypatch)
        # Human-review interrupt resume payload (approval by default).
        payload = dict(
            self.interrupt_payload
            if self.interrupt_payload is not None
            else self.spec.human_review_payload
        )
        monkeypatch.setattr(
            "src.nodes.node_q_human_review.interrupt", lambda _msg: payload
        )
        graph = graph_module.create_graph(checkpointer=InMemorySaver())
        config = {
            "configurable": {"thread_id": thread_id or self.spec.case_id},
            "recursion_limit": 120,
        }
        try:
            graph.invoke(self.initial_state(), config=config)
        except ContentWriterReached as captured:
            self.terminal_state = captured.state
            return captured.state
        # If the graph terminated without hitting the sentinel, return the
        # checkpointed state for the test to inspect (likely a route that did not
        # reach content_writer; the workflow tests handle those explicitly).
        state = graph.get_state(config).values
        self.terminal_state = state
        return state


# ---------------------------------------------------------------------------
# Machine-checkable forbidden-text guard (defense-in-depth on top of the real
# design_plan_qa / render_qa FORBIDDEN_LABEL_PATTERNS gate).
# ---------------------------------------------------------------------------


def _default_narrative_plan() -> NarrativePlan:
    beats = [
        NarrativeBeat(beat_id="hook", kind="hook", purpose="建立阅读承诺"),
        NarrativeBeat(beat_id="scene", kind="scene", purpose="呈现通勤场景"),
        NarrativeBeat(beat_id="reveal", kind="reveal", purpose="揭示关键做法"),
        NarrativeBeat(beat_id="lesson", kind="summary", purpose="总结可保存结论"),
    ]
    return NarrativePlan(
        narrative_form="scenario_story",
        beats=beats,
        saveable_beat=beats[-1],
        closing_mode="reflection",
    )


def _build_r2_output(spec: CaseSpec) -> R2Output:
    """A minimal, passing R2 compliance result so Final Guard's r2 attestation
    is satisfied. Final Guard only reads ``compliance_audit.block_publish``; the
    content snapshot carries the publish copy for the human-review R2-recheck
    path (not exercised on the happy path)."""

    pkg = spec.publish_package
    narrative_plan = _default_narrative_plan()
    snapshot = R2ContentSnapShoot(
        draft_id=f"{spec.case_id}-draft",
        revised_title=pkg["title"],
        revised_md=pkg["content"],
        topic_id=pkg["topic_id"],
        topic=pkg["topic"],
        angle_id=pkg["angle_id"],
        angle=pkg["angle"],
        target_group=pkg["target_group"],
        core_pain=pkg["core_pain"],
        best_cover_copy=pkg["cover_copy"],
        narrative_plan=narrative_plan,
    )
    return R2Output(
        content_snapshot=snapshot,
        compliance_audit=R2ComplianceAudit(
            compliance_status="pass",
            block_publish=False,
        ),
        revision_meta=RevisionMeta(
            revision_id=f"{spec.case_id}-r0",
            round=0,
            diff_summary=[],
            next_actions=[],
        ),
    )


def visible_text_fragments(state: Mapping[str, Any]) -> list[str]:
    """Collect every visible text string the carousel was rendered from."""
    out: list[str] = []
    atom_set = state.get("content_atom_set")
    if atom_set is not None:
        for atom in getattr(atom_set, "atoms", ()):
            out.append(atom.text)
    package = state.get("publish_package") or {}
    for field_name in ("title", "cover_copy", "content"):
        value = package.get(field_name)
        if isinstance(value, str):
            out.append(value)
    return out


def forbidden_visible_text_hits(state: Mapping[str, Any]) -> list[str]:
    hits: list[str] = []
    for text in visible_text_fragments(state):
        lowered = text.lower()
        for pattern in FORBIDDEN_LABEL_PATTERNS:
            if pattern in lowered:
                hits.append(text)
                break
    return hits


__all__ = [
    "CASES_DIR",
    "ContentWriterReached",
    "FAMILY_PROFILES",
    "GoldenHarness",
    "MANIFEST_PATH",
    "all_case_ids",
    "forbidden_visible_text_hits",
    "load_case",
    "load_manifest",
    "make_deterministic_render_fn",
    "visible_text_fragments",
]
