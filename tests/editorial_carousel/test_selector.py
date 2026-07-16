import hashlib

from src.schemas.editorial_templates import TemplateFamily


def selector_input(**overrides):
    from src.editorial_carousel.selector import SelectorInput

    values = {
        "topic_id": "topic-001",
        "angle_id": "angle-001",
        "narrative_form": "scenario_story",
        "content_job": "understand_and_notice",
        "page_archetypes": (
            "cover",
            "scene",
            "story_beat",
            "explanation",
            "save",
        ),
        "estimated_density": "sparse",
        "proof_mode": "none",
    }
    values.update(overrides)
    return SelectorInput(**values)


def canonical_signature(input_value, family, **overrides):
    signature = {
        "narrative_form": input_value.narrative_form,
        "template_family": family,
        "frame_plan_signature": list(input_value.page_archetypes),
        "frame_count": input_value.frame_count,
    }
    signature.update(overrides)
    return signature


def family_reasons(selection, family):
    if selection.template_family == family:
        return selection.reasons
    return selection.rejected_families[family][1:]


def test_selector_returns_only_approved_family_and_is_deterministic():
    from src.editorial_carousel.selector import select_template

    first = select_template(selector_input(), recent_signatures=[])
    second = select_template(selector_input(), recent_signatures=[])

    assert first == second
    assert first.template_family in TemplateFamily.__args__  # type: ignore[attr-defined]
    assert set(first.rejected_families) == (
        set(TemplateFamily.__args__) - {first.template_family}  # type: ignore[attr-defined]
    )
    assert all(first.rejected_families.values())


def test_recent_family_penalty_changes_equal_fit_tie_without_changing_page_count():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input(
        narrative_form="diagnostic_qa",
        content_job="understand_and_notice",
        page_archetypes=(
            "cover",
            "scene",
            "diagnostic",
            "qa",
            "save",
        ),
        estimated_density="standard",
        proof_mode="none",
    )
    original_pages = selector_value.page_archetypes
    baseline = select_template(selector_value, recent_signatures=[])
    repeated = select_template(
        selector_value,
        recent_signatures=[
            canonical_signature(
                selector_value,
                baseline.template_family,
                narrative_form="comparison",
            )
        ],
    )

    assert repeated.template_family != baseline.template_family
    assert selector_value.page_archetypes == original_pages
    assert selector_value.frame_count == 5


def test_exact_combination_penalty_is_additional_and_deterministic():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    baseline = select_template(selector_value, recent_signatures=[])
    signature = {
        "narrative_form": selector_value.narrative_form,
        "template_family": baseline.template_family,
        "frame_plan_signature": list(selector_value.page_archetypes),
        "frame_count": selector_value.frame_count,
    }

    first = select_template(selector_value, recent_signatures=[signature])
    second = select_template(selector_value, recent_signatures=[signature])

    assert first == second
    assert first.template_family != baseline.template_family
    assert selector_value.page_archetypes == tuple(
        signature["frame_plan_signature"]
    )


def test_noncanonical_signature_aliases_are_ignored():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    baseline = select_template(selector_value, recent_signatures=[])
    aliases = [
        {
            "narrative_form": selector_value.narrative_form,
            "template_family": baseline.template_family,
            alias: list(selector_value.page_archetypes),
            "frame_count": selector_value.frame_count,
        }
        for alias in ("page_archetypes", "ordered_archetypes", "frame_plan")
    ]
    aliases.extend(
        [
            {"template_family": baseline.template_family},
            {
                "narrative_form": selector_value.narrative_form,
                "template_family": baseline.template_family,
                "frame_plan_signature": "|".join(
                    selector_value.page_archetypes
                ),
                "frame_count": selector_value.frame_count,
            },
        ]
    )

    assert select_template(selector_value, aliases) == baseline


def test_score_arithmetic_and_reason_strings_follow_the_exact_tables():
    from src.editorial_carousel.selector import (
        CONTENT_JOB_AFFINITY,
        DENSITY_AFFINITY,
        FORM_AFFINITY,
        PROOF_AFFINITY,
        select_template,
    )

    selector_value = selector_input()
    signatures = [
        canonical_signature(selector_value, "white_quote"),
        canonical_signature(selector_value, "white_quote"),
        canonical_signature(
            selector_value,
            "deep_teal",
            narrative_form="comparison",
        ),
        canonical_signature(
            selector_value,
            "white_quote",
            narrative_form="comparison",
        ),
        canonical_signature(selector_value, "white_quote"),
    ]
    selection = select_template(selector_value, signatures)
    expected_scores = {}
    expected_reasons = {}
    for family in TemplateFamily.__args__:  # type: ignore[attr-defined]
        form_score = FORM_AFFINITY[family].get(
            selector_value.narrative_form,
            0,
        )
        job_score = CONTENT_JOB_AFFINITY[family].get(
            selector_value.content_job,
            0,
        )
        density_score = DENSITY_AFFINITY[family][
            selector_value.estimated_density
        ]
        proof_score = PROOF_AFFINITY[family][selector_value.proof_mode]
        reasons = [
            f"narrative form affinity +{form_score}",
            f"content job affinity +{job_score}",
            f"density affinity +{density_score}",
            f"proof compatibility +{proof_score}",
        ]
        score = form_score + job_score + density_score + proof_score
        repeats = sum(
            signature["template_family"] == family
            for signature in signatures[-3:]
        )
        if repeats:
            score -= 18 * repeats
            reasons.append(f"recent family repetition -{18 * repeats}")
        exact = any(
            signature["narrative_form"] == selector_value.narrative_form
            and signature["template_family"] == family
            and tuple(signature["frame_plan_signature"])
            == selector_value.page_archetypes
            and signature["frame_count"] == selector_value.frame_count
            for signature in signatures
        )
        if exact:
            score -= 28
            reasons.append("exact combination repetition -28")
        expected_scores[family] = score
        expected_reasons[family] = reasons

    expected_family = min(
        expected_scores,
        key=lambda family: (
            -expected_scores[family],
            hashlib.sha256(
                (
                    f"{selector_value.topic_id}|"
                    f"{selector_value.angle_id}|{family}"
                ).encode("utf-8")
            ).hexdigest(),
        ),
    )

    assert selection.template_family == expected_family
    assert selection.score == expected_scores[expected_family]
    for family in TemplateFamily.__args__:  # type: ignore[attr-defined]
        assert family_reasons(selection, family) == expected_reasons[family]
        if family == expected_family:
            continue
        expected_comparison = (
            f"score {expected_scores[family]} was lower than "
            f"selected score {expected_scores[expected_family]}"
            if expected_scores[family] < expected_scores[expected_family]
            else "equal score lost the stable SHA-256 tie-break"
        )
        assert selection.rejected_families[family][0] == expected_comparison


def test_family_penalty_uses_only_the_last_three_signatures_at_18_each():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    signatures = [
        canonical_signature(
            selector_value,
            "deep_teal",
            narrative_form="comparison",
        )
        for _ in range(5)
    ]

    selection = select_template(selector_value, signatures)

    assert "recent family repetition -54" in family_reasons(
        selection,
        "deep_teal",
    )
    assert all(
        "recent family repetition -90" not in reason
        for reason in family_reasons(selection, "deep_teal")
    )


def test_duplicate_exact_signatures_apply_one_exact_combination_penalty():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    exact = canonical_signature(selector_value, "white_quote")

    selection = select_template(selector_value, [exact, exact])
    reasons = family_reasons(selection, "white_quote")

    assert reasons.count("exact combination repetition -28") == 1
    assert "recent family repetition -36" in reasons


def test_exact_matching_requires_ordered_archetypes_and_frame_count():
    from src.editorial_carousel.selector import select_template

    selector_value = selector_input()
    reordered = list(selector_value.page_archetypes)
    reordered[1], reordered[2] = reordered[2], reordered[1]
    signatures = [
        canonical_signature(
            selector_value,
            "white_quote",
            frame_plan_signature=reordered,
        ),
        canonical_signature(
            selector_value,
            "white_quote",
            frame_plan_signature=[
                *selector_value.page_archetypes,
                "boundary",
            ],
            frame_count=selector_value.frame_count + 1,
        ),
    ]

    selection = select_template(selector_value, signatures)
    reasons = family_reasons(selection, "white_quote")

    assert "recent family repetition -36" in reasons
    assert "exact combination repetition -28" not in reasons


def test_equal_top_score_uses_the_stable_sha256_tie_break():
    from src.editorial_carousel.selector import select_template

    selection = select_template(
        selector_input(
            narrative_form="cognitive_correction",
            content_job="follow_steps",
            estimated_density="standard",
            proof_mode="real_photo",
        ),
        recent_signatures=[],
    )

    assert selection.template_family == "pink_red"
    assert selection.score == 72
    assert selection.rejected_families["coral_impact"][0] == (
        "equal score lost the stable SHA-256 tie-break"
    )


def test_selector_estimates_density_from_final_publish_copy():
    from src.editorial_carousel.selector import SelectorInput
    from src.schemas.visual_plan import FramePlanItem

    from tests.editorial_carousel.test_strategy import (
        contract_for,
        narrative_plan_for,
    )

    contract = contract_for("understand_and_notice", proof_mode="none")
    narrative_plan = narrative_plan_for("scenario_story")
    frame_plan = [
        FramePlanItem(
            frame_id=f"frame-{index:02d}-{archetype}",
            role=archetype,
            page_archetype=archetype,
            purpose="承载叙事任务",
            allowed_density=["sparse", "standard", "dense"],
            asset_roles=[],
        )
        for index, archetype in enumerate(
            ("cover", "scene", "story_beat", "explanation", "save"),
            start=1,
        )
    ]

    sparse = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"topic_id": "t", "angle_id": "a", "title": "短标题", "content": "短正文"},
        frame_plan,
    )
    standard = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"title": "题", "content": "中" * 400},
        frame_plan,
    )
    dense = SelectorInput.from_content(
        contract,
        narrative_plan,
        {"title": "题", "content": "长" * 901},
        frame_plan,
    )

    assert (sparse.estimated_density, standard.estimated_density, dense.estimated_density) == (
        "sparse",
        "standard",
        "dense",
    )
