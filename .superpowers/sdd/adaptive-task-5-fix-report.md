# Adaptive Task 5 Review Fix Report

## Status and commit

All actionable findings in `adaptive-task-5-review.md` are fixed without
starting Task 6 or restoring the deleted recipe strategy module.

- Subject: `fix: harden adaptive visual planning`
- Fixed point: `fea48449662667c86ff83732a677a56d904d66b5`
- Final SHA: reported in the delivery handoff because this report is part of
  that commit and a Git commit cannot embed its own final object ID.

## RED evidence

The first test-only run covered the exact corrected catalog, strict
materialization at every supported page count, the reflective five-page
runtime regression, rejection of non-canonical signature aliases, and the
previously untested selector score and penalty boundaries.

```text
$ pytest -q tests/editorial_carousel/test_blueprints.py \
>   tests/editorial_carousel/test_selector.py \
>   tests/editorial_carousel/test_strategy.py
FF.....F..............F.......
4 failed, 26 passed in 0.09s
```

The four failures were:

1. The authoritative catalog still contained the contradictory
   `editorial-story` tuple.
2. The same blueprint failed strict `VisualPlan` validation when materialized
   at five pages.
3. Selector aliases changed the result instead of being ignored.
4. The reflective five-page runtime plan raised the strict saveable-archetype
   validation error.

The new score arithmetic, last-three `-18` boundary, single `-28` exact
penalty, ordered/count matching, reason truthfulness, and selector SHA-256
tie-break tests passed during this RED run. They close missing coverage rather
than conceal a scoring implementation defect.

A second vertical slice exposed that generic saveability made the prescribed
saveable-beat ranking criterion ineffective:

```text
$ pytest -q tests/editorial_carousel/test_strategy.py
..............F..........
1 failed, 24 passed in 0.08s
```

The failing case held required-beat fit equal and expected a directly
compatible `steps` blueprint to win.

## GREEN implementation

- Corrected `editorial-story` in both the active plan and production catalog
  to require `("cover", "scene", "story_beat", "quote", "save")` and make
  `("explanation", "boundary")` optional.
- Kept strict `VisualPlan` validation unchanged.
- Added one canonical recent-signature parser in `selector.py`. It accepts
  only mappings containing exactly `narrative_form`, `template_family`,
  `frame_plan_signature` as an ordered list of valid archetypes, and a
  matching integer `frame_count`.
- Reused that parser in blueprint ranking and template scoring; removed the
  duplicated alias parsers and blueprint-ID shortcut.
- Restricted the node adapter to strict embedded v2 `visual_plan` values under
  current recent-content records. It no longer reads speculative alias keys
  or the future Task 11 `recent_visual_signatures` key.
- Made saveable-beat ranking prefer direct beat-to-archetype compatibility;
  strict standalone saveability remains a separate schema invariant.

Focused GREEN:

```text
$ pytest -q tests/editorial_carousel/test_blueprints.py \
>   tests/editorial_carousel/test_selector.py \
>   tests/editorial_carousel/test_strategy.py \
>   tests/nodes/test_visual_strategy_planner.py \
>   tests/schemas/test_editorial_templates.py \
>   tests/schemas/test_editorial_carousel.py
........................................................................ [ 83%]
..............                                                           [100%]
86 passed in 0.08s
```

Static verification:

```text
$ python -m compileall -q src main.py
# exit 0

$ git diff --check
# exit 0
```

## Review finding to fix mapping

### High: reflective five/six-page strict validation failure

- Corrected the authoritative and production blueprint tuple.
- Added an exact 24-blueprint catalog assertion.
- Validated every blueprint through strict `VisualPlan` construction at five,
  six, and seven pages.
- Added the reflective `hook`/`scene`/`tension`/saveable-`quote` five-page
  runtime regression.

### Medium: unrequested modern compatibility aliases

- Replaced planner/selector duplicate parsers with one canonical helper.
- Non-canonical `page_archetypes`, `ordered_archetypes`, raw `frame_plan`,
  string signatures, family-only records, `visual_signature`,
  `recent_frame_plan_signatures`, `frame_plan_signatures`, and
  `recent_visual_signatures` are ignored.
- Embedded history is accepted only after complete strict v2 `VisualPlan`
  validation and is normalized to the four canonical fields.

### Medium: insufficient behavioral contract coverage

- Covered required-beat fit, direct saveable-beat fit, exact recent blueprint
  penalty, and stable blueprint SHA-256 ordering through observable frame
  archetypes.
- Independently recomputed all six family scores and exact reason strings from
  the exported affinity tables.
- Covered last-three-only same-family penalties at `-18` per occurrence,
  exactly one `-28` exact-combination penalty, ordered archetype and frame
  count matching, stable selector SHA-256 ties, and truthful rejected-family
  comparisons.
- Proved separately matched `primary_visual_family` contracts do not affect
  frames.
- Proved family-history changes and misleading template/mockup/page-count
  package metadata cannot rematerialize the finalized page count or archetype
  order.
- Covered all five proof modes and rejected mismatched asset-role/page-
  archetype bindings.

## Changed files

Production and active plan:

- `docs/superpowers/plans/2026-07-16-adaptive-six-template-content-workflow.md`
- `src/editorial_carousel/blueprints.py`
- `src/editorial_carousel/planner.py`
- `src/editorial_carousel/selector.py`
- `src/nodes/node_p_visual_strategy_planner.py`

Tests:

- `tests/editorial_carousel/test_blueprints.py`
- `tests/editorial_carousel/test_selector.py`
- `tests/editorial_carousel/test_strategy.py`
- `tests/nodes/test_visual_strategy_planner.py`

Report:

- `.superpowers/sdd/adaptive-task-5-fix-report.md`

No Task 6+ consumer, strict schema, generated output, state database, or
`src/editorial_carousel/strategy.py` was added or modified.

## Full offline suite

```text
$ pytest -q
9 errors during collection in 6.45s
```

All nine errors are the expected deferred
`ModuleNotFoundError: No module named 'src.editorial_carousel.strategy'`:

1. `tests/integration/test_beauty_account_workflow.py`
2. `tests/integration/test_domain_workflow.py`
3. `tests/integration/test_editorial_carousel_workflow.py`
4. `tests/integration/test_legacy_editorial_resume.py`
5. `tests/nodes/test_carousel_qa.py`
6. `tests/nodes/test_final_policy_guard.py`
7. `tests/nodes/test_render_qa.py`
8. `tests/publishing/test_artifacts.py`
9. `tests/test_graph.py`

They originate in deferred Task 6+/10/11 consumers of the intentionally
deleted v1 strategy module. Task 5-owned imports and behavior pass the focused
suite; those consumers were not edited and no compatibility module was
restored.
