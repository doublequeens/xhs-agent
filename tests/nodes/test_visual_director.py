from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest
from pydantic import BaseModel, ValidationError

from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.content_contract import ContentContract
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.nodes.node_p_visual_director import (
    FragmentAssignment,
    VisualDirectionDraft,
    visual_director_node,
)
from src.visual_ai import StructuredVisualResponseError
from src.visual_design.model_retry import (
    MAX_GENERATION_ATTEMPTS,
    VisualProductionInterrupted,
)
from src.visual_design.style_registry import load_style_registry


class ScriptedVisualModel:
    def __init__(
        self,
        responses: Sequence[BaseModel | Exception],
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate_json(
        self,
        prompt: str,
        response_model: type[BaseModel],
        image_paths: Sequence[Path] = (),
    ) -> BaseModel:
        self.calls.append(
            {
                "prompt": prompt,
                "response_model": response_model,
                "image_paths": tuple(image_paths),
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _atom_set(page_count: int = 5, *, persistent_pain: bool = False) -> ContentAtomSet:
    texts = [f"第{index}页内容。" for index in range(1, page_count + 1)]
    if persistent_pain:
        texts[2] = "出现持续刺痛、明显泛红或第二天仍然紧绷时，先停用并观察。"
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


def _contract(page_count_hint: int | None = None) -> ContentContract:
    return ContentContract(
        audience="通勤护肤女性",
        trigger_situation="换季护肤后皮肤不舒服",
        decision_problem="如何判断应该继续还是停用",
        first_screen_promise="看懂皮肤发出的停用信号",
        screenshot_asset="停用信号清单",
        proof_asset="真实皮肤状态旁证",
        visual_mode="text_plus_real_proof",
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        primary_visual_subject="skin_macro",
        proof_mode="real_photo",
        page_count_hint=page_count_hint,
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


def _valid_plan(
    atom_set: ContentAtomSet,
    *,
    page_count: int | None = None,
    template_family: str = "pink_red",
    asset_directives: tuple[AssetDirective, ...] = (),
) -> VisualDirectionPlan:
    count = page_count or len(atom_set.atoms)
    fragments = _fragments(atom_set)
    directive_ids_by_page = {
        directive.page_id: (directive.directive_id,)
        for directive in asset_directives
    }
    return VisualDirectionPlan(
        template_family=template_family,
        page_count=count,
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="内容驱动的护肤编辑设计",
        palette=("#F4A7BF", "#DC2333"),
        typography_direction={
            "display": "醒目但不拥挤",
            "body": "清晰易读",
        },
        motifs=("red underlines",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个信息重点",
                visual_job=f"visual-job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=directive_ids_by_page.get(
                    f"page-{index}", ()
                ),
            )
            for index in range(1, count + 1)
        ),
        asset_directives=asset_directives,
        recent_visual_context=(),
    )


def _valid_draft(
    atom_set: ContentAtomSet,
    *,
    page_count: int | None = None,
    template_family: str = "pink_red",
    asset_directives: tuple[AssetDirective, ...] = (),
) -> VisualDirectionDraft:
    count = page_count or len(atom_set.atoms)
    directive_ids_by_page = {
        directive.page_id: (directive.directive_id,)
        for directive in asset_directives
    }
    return VisualDirectionDraft(
        template_family=template_family,
        art_direction="内容驱动的护肤编辑设计",
        palette=("#F4A7BF", "#DC2333"),
        typography_direction={
            "display": "醒目但不拥挤",
            "body": "清晰易读",
        },
        motifs=("red underlines",),
        content_fragment_assignments=tuple(
            FragmentAssignment(
                fragment_id=f"fragment-{index}",
                source_atom_id=f"atom-{index}",
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个信息重点",
                visual_job=f"visual-job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=directive_ids_by_page.get(
                    f"page-{index}", ()
                ),
            )
            for index in range(1, count + 1)
        ),
        asset_directives=asset_directives,
    )


def _state(
    atom_set: ContentAtomSet,
    *,
    page_count_hint: int | None = None,
) -> dict:
    return {
        "content_atom_set": atom_set,
        "publish_package": {
            "content_contract": _contract(page_count_hint).model_dump(mode="json"),
            "topic": "换季护肤停用信号",
        },
        "memory_context": {
            "recent_visual_signatures": [
                {
                    "template_family": "deep_teal",
                    "frame_count": 6,
                }
            ]
        },
        "domain_context": {
            "domain": "beauty",
            "profile_version": "beauty-v1",
        },
    }


@pytest.mark.parametrize("page_count", [5, 11, 18])
def test_director_accepts_content_driven_page_counts_independent_of_sample_count(
    page_count,
):
    atom_set = _atom_set(page_count)
    model = ScriptedVisualModel([_valid_draft(atom_set, page_count=page_count)])

    result = visual_director_node(
        _state(atom_set, page_count_hint=5),
        model=model,
    )

    plan = result["visual_direction_plan"]
    assert plan.page_count == page_count
    assert len(plan.page_sequence) == page_count
    registry = load_style_registry()
    assert len(model.calls[0]["image_paths"]) == sum(
        len(profile.reference_image_paths) for profile in registry.values()
    )
    assert set(plan.palette).issubset(registry[plan.template_family].palette)


def test_director_prompt_sends_all_six_profiles_atoms_contract_and_recent_usage():
    atom_set = _atom_set()
    model = ScriptedVisualModel([_valid_draft(atom_set)])

    visual_director_node(_state(atom_set), model=model)

    prompt = str(model.calls[0]["prompt"])
    assert all(f'"family": "{family}"' in prompt for family in load_style_registry())
    assert atom_set.canonical_sha256 in prompt
    assert '"proof_mode": "real_photo"' in prompt
    assert '"template_family": "deep_teal"' in prompt
    assert "5–18" in prompt


@pytest.mark.parametrize("page_count", [4, 19])
def test_director_retries_out_of_range_page_count(page_count):
    atom_set = _atom_set()
    invalid = _valid_draft(atom_set, page_count=page_count)
    valid = _valid_draft(atom_set)
    model = ScriptedVisualModel([invalid, valid])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert len(model.calls) == 2
    assert "page_count" in str(model.calls[1]["prompt"])


@pytest.mark.parametrize(
    "invalid_pages",
    [
        lambda pages: (
            pages[0],
            pages[1].model_copy(update={"visual_job": ""}),
            *pages[2:],
        ),
        lambda pages: (
            pages[0],
            pages[1].model_copy(update={"visual_job": pages[0].visual_job}),
            *pages[2:],
        ),
    ],
)
def test_director_retries_empty_or_duplicate_page_jobs(invalid_pages):
    atom_set = _atom_set()
    draft = _valid_draft(atom_set)
    invalid = draft.model_copy(
        update={"page_sequence": tuple(invalid_pages(draft.page_sequence))}
    )
    model = ScriptedVisualModel([invalid, draft])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert "visual_job" in str(model.calls[1]["prompt"])


@pytest.mark.parametrize("preferred_source", ["search", "generate"])
def test_director_allows_photo_evidence_for_persistent_pain_example(
    preferred_source,
):
    atom_set = _atom_set(persistent_pain=True)
    directive = AssetDirective(
        directive_id="skin-proof",
        page_id="page-3",
        role="skin_example",
        required=True,
        preferred_source=preferred_source,
        fallback_source="generate" if preferred_source == "search" else "search",
        query_or_prompt=(
            "真实摄影风格：泛红且不适的面部皮肤局部，无文字、无标签"
        ),
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    plan = _valid_draft(atom_set, asset_directives=(directive,))
    model = ScriptedVisualModel([plan])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"].asset_directives == (directive,)


def test_director_requires_skin_photo_evidence_for_persistent_pain_example():
    atom_set = _atom_set(persistent_pain=True)
    without_evidence = _valid_draft(atom_set)
    directive = AssetDirective(
        directive_id="skin-proof",
        page_id="page-3",
        role="skin_example",
        required=True,
        preferred_source="either",
        fallback_source="generate",
        query_or_prompt="真实摄影风格的皮肤泛红局部，无文字、无标签",
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    with_evidence = _valid_draft(atom_set, asset_directives=(directive,))
    model = ScriptedVisualModel([without_evidence, with_evidence])

    result = visual_director_node(_state(atom_set), model=model)

    assert (
        result["visual_direction_plan"]
        == _valid_plan(atom_set, asset_directives=(directive,))
    )
    assert "persistent-pain content requires" in str(model.calls[1]["prompt"])


def test_director_prompt_defines_licensed_generated_diagram_and_no_asset_choices():
    atom_set = _atom_set()
    model = ScriptedVisualModel([_valid_draft(atom_set)])

    visual_director_node(_state(atom_set), model=model)

    prompt = str(model.calls[0]["prompt"])
    assert "searched/licensed" in prompt
    assert "generated photoreal" in prompt
    assert "diagrammatic" in prompt
    assert "no asset" in prompt
    assert "embedded text" in prompt
    assert "AI disclosure" in prompt
    assert "disclaimer" in prompt


def test_director_retries_adapter_json_and_schema_failures_then_recovers():
    atom_set = _atom_set()
    valid = _valid_draft(atom_set)
    with pytest.raises(ValidationError) as exc_info:
        VisualDirectionDraft.model_validate({"template_family": "not-a-family"})
    model = ScriptedVisualModel(
        [
            StructuredVisualResponseError(
                "response did not contain valid JSON",
                raw_response="not-json",
            ),
            exc_info.value,
            valid,
        ]
    )

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert len(model.calls) == 3
    assert "response did not contain valid JSON" in str(model.calls[1]["prompt"])
    assert "template_family" in str(model.calls[2]["prompt"])


def test_exhausted_attempts_interrupt_and_retain_only_available_raw_outputs():
    atom_set = _atom_set()
    raw = "not-json-1"
    model = ScriptedVisualModel(
        [StructuredVisualResponseError("invalid JSON", raw_response=raw)]
        * MAX_GENERATION_ATTEMPTS
    )

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        visual_director_node(_state(atom_set), model=model)

    interruption = exc_info.value
    assert len(interruption.errors) == MAX_GENERATION_ATTEMPTS
    assert interruption.raw_outputs == (raw,) * MAX_GENERATION_ATTEMPTS
    assert len(model.calls) == MAX_GENERATION_ATTEMPTS
    assert "invalid JSON" in str(model.calls[1]["prompt"])


def test_unexpected_model_runtime_error_is_not_hidden_as_repairable_output():
    atom_set = _atom_set()
    model = ScriptedVisualModel([RuntimeError("provider transport crashed")])

    with pytest.raises(RuntimeError, match="provider transport crashed"):
        visual_director_node(_state(atom_set), model=model)

    assert len(model.calls) == 1


def test_director_retries_asset_prompt_requesting_forbidden_visible_copy():
    atom_set = _atom_set()
    malicious = AssetDirective(
        directive_id="malicious-image",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt=(
            "生成真实皮肤图片，并在图片中嵌入文字“AI 生成示意图，"
            "仅供参考，不构成医疗建议”"
        ),
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    invalid = _valid_draft(atom_set, asset_directives=(malicious,))
    valid = _valid_draft(atom_set)
    model = ScriptedVisualModel([invalid, valid])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert "forbidden visible image copy" in str(model.calls[1]["prompt"])


def test_director_keeps_factual_skin_subject_matter_without_visible_boilerplate():
    atom_set = _atom_set()
    factual = AssetDirective(
        directive_id="factual-skin",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="search",
        fallback_source="none",
        query_or_prompt="真实皮肤摄影，呈现可观察的面部泛红和干燥紧绷状态",
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    draft = _valid_draft(atom_set, asset_directives=(factual,))
    model = ScriptedVisualModel([draft])

    result = visual_director_node(_state(atom_set), model=model)

    assert (
        result["visual_direction_plan"]
        == _valid_plan(atom_set, asset_directives=(factual,))
    )


@pytest.mark.parametrize(
    "query_or_prompt",
    [
        "show textural skin detail with observable redness",
        "show a textured skin surface with observable dryness",
    ],
)
def test_director_allows_english_texture_descriptions(query_or_prompt):
    atom_set = _atom_set()
    factual = AssetDirective(
        directive_id="english-texture",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt=query_or_prompt,
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    draft = _valid_draft(atom_set, asset_directives=(factual,))
    model = ScriptedVisualModel([draft])

    result = visual_director_node(_state(atom_set), model=model)

    assert (
        result["visual_direction_plan"]
        == _valid_plan(atom_set, asset_directives=(factual,))
    )


def test_director_still_retries_explicit_english_embedded_text_command():
    atom_set = _atom_set()
    embedded_text = AssetDirective(
        directive_id="english-embedded-text",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt=(
            "show realistic skin and overlay text reading 'skin check'"
        ),
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    invalid = _valid_draft(atom_set, asset_directives=(embedded_text,))
    valid = _valid_draft(atom_set)
    model = ScriptedVisualModel([invalid, valid])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert "forbidden visible image copy" in str(model.calls[1]["prompt"])


@pytest.mark.parametrize(
    "query_or_prompt",
    [
        "include labels on the skin image",
        "overlay captions on the image",
        "put text on the image",
        "insert captions on the image",
        "place labels on the image",
        "superimpose words on the image",
        "draw text on the image",
        "print captions on the image",
    ],
)
def test_director_retries_plural_english_visible_copy_commands(
    query_or_prompt,
):
    atom_set = _atom_set()
    visible_copy = AssetDirective(
        directive_id="english-visible-copy",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt=query_or_prompt,
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    invalid = _valid_draft(atom_set, asset_directives=(visible_copy,))
    valid = _valid_draft(atom_set)
    model = ScriptedVisualModel([invalid, valid])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert "forbidden visible image copy" in str(model.calls[1]["prompt"])


@pytest.mark.parametrize(
    "query_or_prompt",
    [
        "show skin with no text",
        "show skin without text",
        "show a label-free skin image",
        "do not include text",
        "never include text",
        "must not add labels",
        "DON'T overlay labels",
        "don’t   insert captions",
        "SHOULD   NOT place words",
        "mustn't add labels",
        "shouldn’t place words",
        "CAN'T print captions",
        "can   not   print text",
    ],
)
def test_director_allows_explicit_english_no_text_constraints(
    query_or_prompt,
):
    atom_set = _atom_set()
    no_visible_copy = AssetDirective(
        directive_id="english-no-visible-copy",
        page_id="page-1",
        role="skin_example",
        required=True,
        preferred_source="generate",
        fallback_source="none",
        query_or_prompt=query_or_prompt,
        negative_constraints=(
            "no embedded text",
            "no AI disclosure label",
            "no disclaimer copy",
        ),
        orientation="portrait",
        min_width=1080,
        min_height=1440,
    )
    draft = _valid_draft(atom_set, asset_directives=(no_visible_copy,))
    model = ScriptedVisualModel([draft])

    result = visual_director_node(_state(atom_set), model=model)

    assert (
        result["visual_direction_plan"]
        == _valid_plan(atom_set, asset_directives=(no_visible_copy,))
    )


@pytest.mark.parametrize(
    ("make_invalid", "feedback"),
    [
        (
            lambda plan: plan.model_copy(update={"art_direction": ""}),
            "art_direction",
        ),
        (
            lambda plan: plan.model_copy(update={"palette": ()}),
            "palette",
        ),
        (
            lambda plan: plan.model_copy(update={"typography_direction": {}}),
            "typography_direction",
        ),
        (
            lambda plan: plan.model_copy(
                update={
                    "page_sequence": (
                        plan.page_sequence[0].model_copy(
                            update={"purpose": "   "}
                        ),
                        *plan.page_sequence[1:],
                    )
                }
            ),
            "purpose",
        ),
    ],
)
def test_director_retries_empty_shell_direction_fields(make_invalid, feedback):
    atom_set = _atom_set()
    valid = _valid_draft(atom_set)
    model = ScriptedVisualModel([make_invalid(valid), valid])

    result = visual_director_node(_state(atom_set), model=model)

    assert result["visual_direction_plan"] == _valid_plan(atom_set)
    assert feedback in str(model.calls[1]["prompt"])


def test_exhausted_validation_failures_raise_resumable_interruption_with_evidence():
    atom_set = _atom_set()
    invalid_responses = [
        _valid_draft(atom_set, page_count=4),
        _valid_draft(atom_set, page_count=19),
    ] * (MAX_GENERATION_ATTEMPTS // 2)
    model = ScriptedVisualModel(invalid_responses)

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        visual_director_node(_state(atom_set), model=model)

    interruption = exc_info.value
    assert interruption.stage == "visual_director"
    assert len(interruption.raw_outputs) == MAX_GENERATION_ATTEMPTS
    assert len(interruption.errors) == MAX_GENERATION_ATTEMPTS
    assert len(model.calls) == MAX_GENERATION_ATTEMPTS
    assert "page_count" in str(model.calls[1]["prompt"])
    assert "page_count" in str(model.calls[2]["prompt"])
    assert interruption.resumable is True


def test_director_rejects_missing_content_atom_set_before_calling_model():
    model = ScriptedVisualModel([])

    with pytest.raises(ValueError, match="content_atom_set"):
        visual_director_node(
            {
                "publish_package": {
                    "content_contract": _contract().model_dump(mode="json")
                },
                "domain_context": {
                    "domain": "beauty",
                    "profile_version": "beauty-v1",
                },
            },
            model=model,
        )

    assert model.calls == []


def test_director_derives_fragments_deterministically_from_atom_assignments():
    atom_set = _atom_set()
    draft = _valid_draft(atom_set)
    model = ScriptedVisualModel([draft])

    result = visual_director_node(_state(atom_set), model=model)

    plan = result["visual_direction_plan"]
    # The model never emitted text/bounds; the system derived them per whole atom.
    atoms_by_id = {atom.atom_id: atom for atom in atom_set.atoms}
    assert len(plan.content_fragments) == len(atom_set.atoms)
    for fragment in plan.content_fragments:
        atom = atoms_by_id[fragment.source_atom_id]
        assert fragment.text == atom.text
        assert fragment.start == 0
        assert fragment.end == len(atom.text)
    # The derived fragments satisfy the canonical exact-reconstruction validator.
    atom_set.validate_complete_fragments(plan.content_fragments)
    registry = load_style_registry()
    plan.validate_against(atom_set, registry[plan.template_family])
    # The fragment_ids the LLM chose survive into the derived plan unchanged.
    assert {f.fragment_id for f in plan.content_fragments} == {
        f"fragment-{i}" for i in range(1, len(atom_set.atoms) + 1)
    }


def test_director_retries_when_assignment_misses_an_atom():
    atom_set = _atom_set()
    incomplete = _valid_draft(atom_set).model_copy(
        update={
            "content_fragment_assignments": _valid_draft(
                atom_set
            ).content_fragment_assignments[:-1]
        }
    )
    complete = _valid_draft(atom_set)
    model = ScriptedVisualModel([incomplete, complete])

    result = visual_director_node(_state(atom_set), model=model)

    plan = result["visual_direction_plan"]
    atom_set.validate_complete_fragments(plan.content_fragments)
    assert len(model.calls) == 2
    assert "missing atoms" in str(model.calls[1]["prompt"])
