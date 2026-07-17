from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from typing import Any, Final, get_args

from src.schemas.content_contract import ContentContract
from src.schemas.editorial_templates import (
    Density,
    PageArchetype,
    TemplateFamily,
    TemplateSelection,
)
from src.schemas.narrative import NarrativeForm, NarrativePlan
from src.schemas.visual_plan import ContentJob, FramePlanItem


@dataclass(frozen=True)
class SelectorInput:
    topic_id: str
    angle_id: str
    narrative_form: NarrativeForm
    content_job: ContentJob
    page_archetypes: tuple[PageArchetype, ...]
    estimated_density: Density
    proof_mode: str

    @property
    def frame_count(self) -> int:
        return len(self.page_archetypes)

    @classmethod
    def from_content(
        cls,
        contract: ContentContract,
        narrative_plan: NarrativePlan,
        publish_package: Mapping[str, Any],
        frame_plan: Sequence[FramePlanItem],
    ) -> "SelectorInput":
        copy_size = len(
            str(publish_package.get("title") or "")
            + str(publish_package.get("content") or "")
        )
        estimated_density: Density = (
            "sparse"
            if copy_size <= 350
            else "standard"
            if copy_size <= 900
            else "dense"
        )
        return cls(
            topic_id=str(publish_package.get("topic_id") or ""),
            angle_id=str(publish_package.get("angle_id") or ""),
            narrative_form=narrative_plan.narrative_form,
            content_job=contract.content_job,
            page_archetypes=tuple(
                frame.page_archetype for frame in frame_plan
            ),
            estimated_density=estimated_density,
            proof_mode=contract.proof_mode,
        )


@dataclass(frozen=True)
class RecentVisualSignature:
    narrative_form: NarrativeForm
    template_family: TemplateFamily
    frame_plan_signature: tuple[PageArchetype, ...]
    frame_count: int


_SIGNATURE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "narrative_form",
        "template_family",
        "frame_plan_signature",
        "frame_count",
    }
)


def canonical_recent_signature(
    signature: Any,
) -> RecentVisualSignature | None:
    if not isinstance(signature, Mapping):
        return None
    if not _SIGNATURE_FIELDS <= set(signature):
        return None
    narrative_form = signature.get("narrative_form")
    template_family = signature.get("template_family")
    raw_archetypes = signature.get("frame_plan_signature")
    frame_count = signature.get("frame_count")
    if (
        narrative_form not in get_args(NarrativeForm)
        or template_family not in get_args(TemplateFamily)
        or not isinstance(raw_archetypes, list)
        or not raw_archetypes
        or any(
            archetype not in get_args(PageArchetype)
            for archetype in raw_archetypes
        )
        or type(frame_count) is not int
        or frame_count != len(raw_archetypes)
    ):
        return None
    return RecentVisualSignature(
        narrative_form=narrative_form,
        template_family=template_family,
        frame_plan_signature=tuple(raw_archetypes),
        frame_count=frame_count,
    )


FORM_AFFINITY: Final[dict[TemplateFamily, dict[NarrativeForm, int]]] = {
    "pink_red": {
        "cognitive_correction": 28,
        "step_tutorial": 24,
        "checklist_collection": 18,
    },
    "deep_teal": {
        "step_tutorial": 24,
        "checklist_collection": 24,
        "diagnostic_qa": 20,
        "reflective_editorial": 18,
    },
    "soft_pink": {
        "scenario_story": 26,
        "diagnostic_qa": 24,
        "reflective_editorial": 20,
    },
    "coral_impact": {
        "story_reversal": 28,
        "cognitive_correction": 26,
        "step_tutorial": 22,
    },
    "green_catalog": {
        "checklist_collection": 30,
        "comparison": 26,
        "diagnostic_qa": 20,
    },
    "white_quote": {
        "reflective_editorial": 30,
        "scenario_story": 26,
        "story_reversal": 18,
    },
}
DENSITY_AFFINITY: Final[dict[TemplateFamily, dict[Density, int]]] = {
    "pink_red": {"sparse": 12, "standard": 18, "dense": 12},
    "deep_teal": {"sparse": 18, "standard": 20, "dense": 18},
    "soft_pink": {"sparse": 18, "standard": 18, "dense": 12},
    "coral_impact": {"sparse": 20, "standard": 18, "dense": 8},
    "green_catalog": {"sparse": 10, "standard": 20, "dense": 24},
    "white_quote": {"sparse": 26, "standard": 16, "dense": 4},
}
CONTENT_JOB_AFFINITY: Final[
    dict[TemplateFamily, dict[ContentJob, int]]
] = {
    "pink_red": {
        "diagnose_and_adjust": 18,
        "follow_steps": 20,
        "compare_and_choose": 12,
        "save_and_check": 18,
        "understand_and_notice": 14,
    },
    "deep_teal": {
        "diagnose_and_adjust": 18,
        "follow_steps": 20,
        "compare_and_choose": 12,
        "save_and_check": 18,
        "understand_and_notice": 20,
    },
    "soft_pink": {
        "diagnose_and_adjust": 20,
        "follow_steps": 12,
        "compare_and_choose": 14,
        "save_and_check": 14,
        "understand_and_notice": 20,
    },
    "coral_impact": {
        "diagnose_and_adjust": 16,
        "follow_steps": 20,
        "compare_and_choose": 14,
        "save_and_check": 12,
        "understand_and_notice": 10,
    },
    "green_catalog": {
        "diagnose_and_adjust": 16,
        "follow_steps": 14,
        "compare_and_choose": 20,
        "save_and_check": 20,
        "understand_and_notice": 12,
    },
    "white_quote": {
        "diagnose_and_adjust": 8,
        "follow_steps": 8,
        "compare_and_choose": 8,
        "save_and_check": 10,
        "understand_and_notice": 20,
    },
}
PROOF_AFFINITY: Final[dict[TemplateFamily, dict[str, int]]] = {
    "pink_red": {
        "diagram": 8,
        "real_photo": 6,
        "product_texture": 8,
        "comparison": 8,
        "none": 6,
    },
    "deep_teal": {
        "diagram": 10,
        "real_photo": 4,
        "product_texture": 6,
        "comparison": 6,
        "none": 10,
    },
    "soft_pink": {
        "diagram": 8,
        "real_photo": 10,
        "product_texture": 8,
        "comparison": 6,
        "none": 8,
    },
    "coral_impact": {
        "diagram": 8,
        "real_photo": 8,
        "product_texture": 6,
        "comparison": 8,
        "none": 6,
    },
    "green_catalog": {
        "diagram": 8,
        "real_photo": 4,
        "product_texture": 8,
        "comparison": 10,
        "none": 6,
    },
    "white_quote": {
        "diagram": 4,
        "real_photo": 6,
        "product_texture": 4,
        "comparison": 2,
        "none": 10,
    },
}


def _is_exact_combination(
    signature: RecentVisualSignature,
    input_value: SelectorInput,
    family: TemplateFamily,
) -> bool:
    return (
        signature.narrative_form == input_value.narrative_form
        and signature.template_family == family
        and signature.frame_plan_signature == input_value.page_archetypes
        and signature.frame_count == input_value.frame_count
    )


def _score_family(
    family: TemplateFamily,
    input_value: SelectorInput,
    recent_signatures: Sequence[RecentVisualSignature],
) -> tuple[int, list[str]]:
    form_score = FORM_AFFINITY[family].get(input_value.narrative_form, 0)
    density_score = DENSITY_AFFINITY[family][input_value.estimated_density]
    job_score = CONTENT_JOB_AFFINITY[family].get(input_value.content_job, 0)
    proof_score = PROOF_AFFINITY[family].get(input_value.proof_mode, 0)
    reasons = [
        f"narrative form affinity +{form_score}",
        f"content job affinity +{job_score}",
        f"density affinity +{density_score}",
        f"proof compatibility +{proof_score}",
    ]
    score = form_score + density_score + job_score + proof_score

    family_repeats = sum(
        signature.template_family == family
        for signature in recent_signatures[-3:]
    )
    if family_repeats:
        penalty = 18 * family_repeats
        score -= penalty
        reasons.append(f"recent family repetition -{penalty}")

    exact_repetition = any(
        _is_exact_combination(signature, input_value, family)
        for signature in recent_signatures
    )
    if exact_repetition:
        score -= 28
        reasons.append("exact combination repetition -28")
    return score, reasons


def _tie_break(input_value: SelectorInput, family: TemplateFamily) -> str:
    return hashlib.sha256(
        f"{input_value.topic_id}|{input_value.angle_id}|{family}".encode(
            "utf-8"
        )
    ).hexdigest()


def select_template(
    input_value: SelectorInput,
    recent_signatures: Sequence[Any],
) -> TemplateSelection:
    canonical_signatures = tuple(
        canonical
        for signature in recent_signatures
        if (canonical := canonical_recent_signature(signature)) is not None
    )
    candidates = {
        family: _score_family(family, input_value, canonical_signatures)
        for family in get_args(TemplateFamily)
    }
    selected_family = min(
        candidates,
        key=lambda family: (
            -candidates[family][0],
            _tie_break(input_value, family),
        ),
    )
    selected_score, selected_reasons = candidates[selected_family]
    rejected_families: dict[TemplateFamily, list[str]] = {}
    for family, (score, reasons) in candidates.items():
        if family == selected_family:
            continue
        comparison = (
            f"score {score} was lower than selected score {selected_score}"
            if score < selected_score
            else "equal score lost the stable SHA-256 tie-break"
        )
        rejected_families[family] = [comparison, *reasons]

    return TemplateSelection(
        template_family=selected_family,
        score=selected_score,
        reasons=selected_reasons,
        rejected_families=rejected_families,
    )
