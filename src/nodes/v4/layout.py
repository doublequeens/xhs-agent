"""Pure v4 layout compilation and carousel-plan aggregation node."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas.assets import AssetManifest
from src.schemas.content_atoms import canonical_sha256 as canonical_sha256_v3
from src.schemas.scene_graph import ImageElement, TextElement
from src.schemas.v4.content import ContentAtomSetV4, canonical_sha256_v4
from src.schemas.v4.direction import PageBriefSetV4
from src.schemas.v4.layout import (
    CarouselDesignPlanV4,
    CompiledPageV4,
    FamilyTokensV4,
)
from src.schemas.v4.semantic import SemanticContentModelV4
from src.visual_design.v4.compiler import (
    LayoutCompilerInputsV4,
    compile_layout,
)
from src.visual_design.v4.tokens import get_family_tokens


def _tupleize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _tupleize(item) for key, item in value.items()}
    if isinstance(value, list):
        return tuple(_tupleize(item) for item in value)
    return value


def _coerce(model_type, value: Any, label: str):
    raw = value.model_dump(mode="python") if isinstance(value, model_type) else value
    if not isinstance(raw, Mapping):
        raise TypeError(f"v4 layout requires persisted {label}")
    try:
        checked = model_type.model_validate(_tupleize(raw))
        validate_integrity = getattr(checked, "validate_integrity", None)
        if callable(validate_integrity):
            validate_integrity()
        return checked
    except Exception as exc:
        raise ValueError(f"v4 layout {label} is stale or invalid") from exc


def _coerce_pages(value: Sequence[Any]) -> tuple[CompiledPageV4, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("v4 layout compiled page set must be ordered")
    result: list[CompiledPageV4] = []
    for page in value:
        result.append(_coerce(CompiledPageV4, page, "compiled page"))
    return tuple(result)


def _check_page_bindings(
    pages: tuple[CompiledPageV4, ...],
    *,
    atom_set: ContentAtomSetV4,
    semantic_model: SemanticContentModelV4,
    page_brief_set: PageBriefSetV4,
    manifest: AssetManifest,
    family_tokens: FamilyTokensV4,
) -> None:
    if not 5 <= len(pages) <= 18:
        raise ValueError("v4 layout aggregation requires 5-18 compiled pages")
    if len(pages) != page_brief_set.page_count or len(pages) != len(page_brief_set.pages):
        raise ValueError("compiled page count does not match durable page brief set")
    page_ids = tuple(page.page_id for page in pages)
    brief_ids = tuple(page.page_id for page in page_brief_set.pages)
    page_sequences = tuple(page.sequence for page in pages)
    brief_sequences = tuple(page.sequence for page in page_brief_set.pages)
    if page_ids != brief_ids or page_sequences != brief_sequences:
        raise ValueError("compiled pages must match durable page brief IDs and order")
    if page_sequences != tuple(range(1, len(pages) + 1)):
        raise ValueError("compiled page sequences must be contiguous and one-based")
    if page_brief_set.template_family != family_tokens.family:
        raise ValueError("page brief family does not match canonical family tokens")
    atom_by_id = {atom.atom_id: atom for atom in atom_set.atoms}
    fragment_by_id = {fragment.fragment_id: fragment for fragment in semantic_model.fragments}
    asset_by_id = {item.asset_id: item for item in manifest.items}
    directive_by_id = {directive.directive_id: directive for directive in page_brief_set.asset_directives}
    for page, brief in zip(pages, page_brief_set.pages):
        program = page.layout_program
        if program.page_id != brief.page_id or program.page_brief_sha256 != brief.canonical_sha256:
            raise ValueError("compiled page program does not bind exactly one durable page brief")
        if program.template_family != family_tokens.family:
            raise ValueError("compiled page family does not match page brief family")
        if program.family_tokens_sha256 != family_tokens.canonical_sha256:
            raise ValueError("compiled page family token hash does not match plan")
        text_refs = tuple(
            element.content_ref
            for element in page.scene.elements
            if isinstance(element, TextElement)
        )
        if text_refs != tuple(brief.fragment_refs):
            raise ValueError("compiled page does not represent every page brief fragment exactly once")
        for ref in brief.fragment_refs:
            fragment = fragment_by_id.get(ref)
            if fragment is None:
                raise ValueError("page brief references an unknown semantic fragment")
            atom = atom_by_id.get(fragment.source_atom_id)
            if atom is None or not 0 <= fragment.start < fragment.end <= len(atom.text):
                raise ValueError("semantic fragment source binding is invalid")
            if fragment.exact_text != atom.text[fragment.start : fragment.end]:
                raise ValueError("semantic fragment exact text is not the atom source slice")
        image_elements = tuple(
            element for element in page.scene.elements if isinstance(element, ImageElement)
        )
        expected_directives = tuple(item.directive_id for item in program.asset_placements)
        actual_asset_ids = {element.asset_ref for element in image_elements}
        expected_asset_ids: set[str] = set()
        for directive_id in expected_directives:
            directive = directive_by_id.get(directive_id)
            asset = next(
                (item for item in manifest.items if item.directive_id == directive_id),
                None,
            )
            if directive is None or asset is None:
                raise ValueError("compiled page asset placement has no exact directive/manifest binding")
            if asset.page_id != brief.page_id or asset.security_status != "approved":
                raise ValueError("compiled page asset is not same-page and security-approved")
            expected_asset_ids.add(asset.asset_id)
        if actual_asset_ids != expected_asset_ids:
            raise ValueError("compiled page image references do not match approved asset placements")


def aggregate_layout_plan(
    compiled_pages: Sequence[CompiledPageV4 | Mapping[str, Any]],
    *,
    content_atom_set: ContentAtomSetV4 | Mapping[str, Any],
    semantic_content_model: SemanticContentModelV4 | Mapping[str, Any],
    page_brief_set: PageBriefSetV4 | Mapping[str, Any],
    asset_manifest: AssetManifest | Mapping[str, Any],
    family_tokens: FamilyTokensV4 | str,
    revision: int = 0,
) -> CarouselDesignPlanV4:
    """Aggregate an already compiled ordered 5-18 page set deterministically."""

    if type(revision) is not int or revision < 0:
        raise ValueError("v4 layout revision must be a non-negative integer")
    atom_set = _coerce(ContentAtomSetV4, content_atom_set, "content atom set")
    semantic_model = _coerce(SemanticContentModelV4, semantic_content_model, "semantic content model")
    page_set = _coerce(PageBriefSetV4, page_brief_set, "page brief set")
    manifest = _coerce(AssetManifest, asset_manifest, "asset manifest")
    if isinstance(family_tokens, str):
        family = get_family_tokens(family_tokens)
    else:
        family = _coerce(FamilyTokensV4, family_tokens, "family tokens")
    pages = _coerce_pages(compiled_pages)
    if semantic_model.content_atom_set_sha256 != atom_set.canonical_sha256:
        raise ValueError("semantic model does not bind content atom set")
    _check_page_bindings(
        pages,
        atom_set=atom_set,
        semantic_model=semantic_model,
        page_brief_set=page_set,
        manifest=manifest,
        family_tokens=family,
    )
    payload = {
        "content_atom_set_sha256": atom_set.canonical_sha256,
        "semantic_content_model_sha256": semantic_model.canonical_sha256,
        "page_brief_set_sha256": page_set.canonical_sha256,
        "asset_manifest_sha256": canonical_sha256_v3(manifest),
        "family_tokens_sha256": family.canonical_sha256,
        "revision": revision,
        "pages": pages,
    }
    return CarouselDesignPlanV4(
        **payload,
        canonical_sha256=canonical_sha256_v4(payload),
    )


def layout_node(state: Mapping[str, Any]) -> dict[str, Any]:
    """Compile/aggregate v4 pages from pure state; no side effects are allowed."""

    if not isinstance(state, Mapping):
        raise TypeError("v4 layout node requires a state mapping")
    atom_set = state.get("content_atom_set", state.get("atom_set"))
    semantic_model = state.get(
        "semantic_content_model",
        state.get("semantic_model"),
    )
    page_set = state.get("page_brief_set", state.get("page_briefs"))
    manifest = state.get("asset_manifest", state.get("assets"))
    family_tokens = state.get("family_tokens")
    revision = state.get("revision", 0)
    if any(value is None for value in (atom_set, semantic_model, page_set, manifest, family_tokens)):
        raise ValueError("v4 layout node requires all upstream contracts")
    page_set_checked = _coerce(PageBriefSetV4, page_set, "page brief set")
    programs = state.get("layout_programs")
    compiled_pages = state.get("compiled_pages")
    if compiled_pages is None:
        if programs is None:
            single = state.get("layout_program")
            programs = (single,) if single is not None else None
        if programs is None or isinstance(programs, (str, bytes)):
            raise ValueError("v4 layout node requires layout programs or compiled pages")
        program_values = tuple(programs)
        if len(program_values) != len(page_set_checked.pages):
            raise ValueError("layout program count does not match durable page brief set")
        compiled: list[CompiledPageV4] = []
        for program in program_values:
            program_page_id = (
                program.page_id if hasattr(program, "page_id") else program.get("page_id")
            )
            brief = next(
                (item for item in page_set_checked.pages if item.page_id == program_page_id),
                None,
            )
            if brief is None:
                raise ValueError("layout program does not match exactly one durable page brief")
            compiled.append(
                compile_layout(
                    program,
                    LayoutCompilerInputsV4(
                        page_brief=brief,
                        semantic_content_model=semantic_model,
                        content_atom_set=atom_set,
                        asset_manifest=manifest,
                        family_tokens=family_tokens if isinstance(family_tokens, FamilyTokensV4) else None,
                    ),
                )
            )
        compiled_pages = tuple(compiled)
    plan = aggregate_layout_plan(
        compiled_pages,
        content_atom_set=atom_set,
        semantic_content_model=semantic_model,
        page_brief_set=page_set_checked,
        asset_manifest=manifest,
        family_tokens=family_tokens,
        revision=revision,
    )
    return {
        "carousel_design_plan_v4": plan,
        "carousel_design_plan": plan,
        "current_node": "V4_LAYOUT",
        "route": "render",
    }


build_carousel_design_plan = aggregate_layout_plan
v4_layout_node = layout_node


__all__ = [
    "aggregate_layout_plan",
    "build_carousel_design_plan",
    "layout_node",
    "v4_layout_node",
]
