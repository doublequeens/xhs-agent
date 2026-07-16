# Task 6 implementation report

## Scope

Task 6 now generates and validates v2 archetype-based storyboards:

- storyboard output preserves ordered `(frame_id, role, page_archetype)` bindings,
  supports `content_density_hint`, allows planned text-only frames, and keeps emoji
  unchanged as visible Unicode text;
- Carousel QA validates narrative metadata, 5–7-page plan equality, cover position,
  narrative beat/saveable-purpose coverage, one of six template families, exact recent
  combination reuse, exact declared slot bindings, and the specified three-page
  fixed-cardinality filler rule;
- visible-text extraction, R1/decision prompts, Human Review structural signatures,
  R2 recheck input, Final Guard bindings, publish summaries, and rescue prompts use
  v2 `page_archetype`/density fields;
- ContentLock canonical fields and all provenance, review, QA, containment, no-follow,
  transaction, and byte-hash safety checks remain intact.

Task 7 resolver/catalog/renderer empty-manifest behavior was not implemented. The only
temporary production bridge is a Final Guard view that presents
`AssetRequirement.page_archetype` as the old eligibility API's `layout` attribute so
Task 6 does not weaken eligibility checks before Task 7 migrates that API.

## Audit corrections

- Removed all four Task 6 skips. The graph-routing test now isolates the later
  `render_qa` import dependency, while the three reused-asset tests construct v2
  canonical catalog state and continue to exercise acceptance, conflicting
  declarations, and forged provenance.
- Restored v2 coverage for independent issue accumulation, invalid-frame cascade
  suppression, duplicate identity handling, count/cover failures, and atomic asset
  role/archetype drift.
- Fixed exact slot ownership so overlapping frame-ID prefixes cannot cross-bind a
  requirement.
- Made malformed non-null narrative plans produce deterministic QA failure instead
  of crashing while building an R1 decision.
- Replaced stale `layout` fields in the R1 reflector and decision-engine visible-text
  prompt contracts.
- Corrected the committed density gap by adding required `DensityHint` metadata to
  `StoryboardVisibleText`, emitting it during extraction, and preserving authoritative
  archetype/density values while merge/apply operations edit only `text_blocks`.
- Updated R1 and decision prompt rules/examples so both `page_archetype` and
  `content_density_hint` are copied as structural metadata through the R1/R2 boundary.

## TDD RED/GREEN evidence

The first implementer's original RED output is not recoverable: the inherited report
described an unrelated renderer task. No historical result is claimed here.

Continuation RED for the QA audit:

```text
pytest -q tests/nodes/test_carousel_qa.py \
  -k 'exact_frame_identity_not_prefix or invalid_asset_frame_does_not_emit_dependent_slot_cascade or reports_invalid_narrative_without_crashing or length_mismatch_does_not_hide or duplicate_identity_does_not_hide or asset_requirement_role_and_archetype_drift'

3 failed, 3 passed, 22 deselected
```

After the scoped QA fixes:

```text
6 passed, 22 deselected
```

Continuation RED for stale visible-text prompt fields:

```text
pytest -q tests/prompts/test_composer.py \
  -k visible_text_revision_prompts

2 failed, 49 deselected
```

After replacing `layout` with `page_archetype`:

```text
2 passed, 49 deselected
```

Required density-metadata correction RED:

```text
pytest -q \
  tests/schemas/test_editorial_carousel.py::test_storyboard_visible_text_preserves_structural_metadata \
  tests/nodes/test_final_policy_guard.py::test_visible_text_extraction_preserves_emoji_and_v2_structure \
  tests/nodes/test_final_policy_guard.py::test_r2_merges_partial_visible_text_with_all_cards_before_policy_scan

3 failed in 2.96s
```

The failures independently showed that the typed contract rejected density, extraction
omitted it, and the R2 typed boundary rejected it. After adding the shared
`DensityHint` field and extraction metadata:

```text
3 passed in 2.87s
```

Prompt-rule correction RED/GREEN:

```text
pytest -q tests/prompts/test_composer.py \
  -k visible_text_revision_prompts

2 failed, 49 deselected in 0.07s
2 passed, 49 deselected in 0.02s
```

## Verification

Exact Task 6 focused command:

```text
pytest -q tests/nodes/test_carousel_qa.py tests/nodes/test_metadata_flow.py \
  tests/nodes/test_final_policy_guard.py tests/publishing/test_artifacts.py \
  tests/prompts/test_composer.py

283 passed, 2 warnings in 18.90s
```

The warnings were pytest cleanup warnings for an already stale macOS temporary
directory (`OSError: [Errno 66] Directory not empty`); no Task 6 test was skipped.

Relevant schema contracts:

```text
pytest -q tests/schemas/test_editorial_carousel.py \
  tests/schemas/test_editorial_templates.py tests/schemas/test_narrative.py \
  tests/schemas/test_content_contract.py

44 passed in 0.08s
```

Static verification:

```text
python -m compileall -q src main.py
git diff --check
```

Both exited successfully with no output.

Full offline suite:

```text
pytest -q

6 errors during collection in 7.33s
```

All six errors have the same deferred root cause:

```text
src/nodes/node_p_render_qa.py:14
ModuleNotFoundError: No module named 'src.editorial_carousel.strategy'
```

Affected collection modules:

- `tests/integration/test_beauty_account_workflow.py`
- `tests/integration/test_domain_workflow.py`
- `tests/integration/test_editorial_carousel_workflow.py`
- `tests/integration/test_legacy_editorial_resume.py`
- `tests/nodes/test_render_qa.py`
- `tests/test_graph.py`

`strategy.py` was removed by the earlier v2 planning task; migrating Render QA and
the renderer away from `ASSET_ADAPTER`/v1 signatures is owned by later tasks.
These failures were not skipped or disguised.

## Files changed

Production:

- `src/schemas/decision.py`
- `src/nodes/node_o_storyboards_generator.py`
- `src/nodes/node_p_carousel_qa.py`
- `src/nodes/node_q_01_final_policy_guard.py`
- `src/nodes/node_q_human_review.py`
- `src/nodes/publish_patch.py`
- `src/prompts/base/decision_engine.txt`
- `src/prompts/base/r1_reflector.txt`
- `src/prompts/base/storyboards_generator.txt`
- `src/publishing/artifacts.py`
- `src/publishing/templates/codex_image_regeneration_prompt.txt`

Tests:

- `tests/schemas/test_editorial_carousel.py`
- `tests/nodes/test_carousel_qa.py`
- `tests/nodes/test_final_policy_guard.py`
- `tests/nodes/test_metadata_flow.py`
- `tests/prompts/test_composer.py`
- `tests/publishing/test_artifacts.py`

Report:

- `.superpowers/sdd/task-6-report.md`
