# Modernize Stale Editorial Integration Tests Design

## Problem

Commit `fea4844` replaced `src/editorial_carousel/strategy.py` with the modern
blueprint planner in `src/editorial_carousel/planner.py`. The production graph,
planner unit tests, and newer integration tests moved to the v2 contracts, but
these two older integration files did not:

- `tests/integration/test_beauty_account_workflow.py`
- `tests/integration/test_domain_workflow.py`

Both files import the deleted module during pytest collection. Their storyboard
helpers also depend on the removed v1 `ASSET_ADAPTER`, the old two-argument
planner call, and the deleted `FramePlanItem.layout` field. As a result, pytest
stops during collection before either file can exercise its workflow behavior.

## Decision

Migrate the two integration tests to the existing modern editorial contracts.
Do not restore `strategy.py`, add a compatibility re-export, or route test data
through legacy contracts. `src/editorial_carousel/legacy.py` remains the only
v1 checkpoint migration boundary.

The tests will import the public planner from `src.editorial_carousel`, construct
a schema-valid `NarrativePlan`, pass the complete
`(contract, narrative_plan, publish_package, recent_signatures)` input, and
generate storyboard frames with `page_archetype` and optional `visual_slots`.

## Test-fixture shape

Each affected workflow fixture must carry one canonical `NarrativePlan` through
every schema that requires it, including `HashTagInput`, `R2ContentSnapShoot`,
and the assembler publish package. Test data must use four to eight unique
beats, an exact `saveable_beat` member, and a supported `narrative_form`.

Storyboard helpers consume a modern `VisualPlan` instead of reconstructing v1
asset mappings:

1. Copy `frame_id`, `role`, `purpose`, and `page_archetype` from each
   `FramePlanItem`.
2. Pin the cover headline to `ContentContract.first_screen_promise`.
3. Build content blocks suitable for the page archetype.
4. Build a visual slot only when the plan has a matching `AssetRequirement`;
   text-only frames keep `visual_slots=[]`.
5. Preserve deliberate invalid-fixture mutations used by the existing negative
   tests, but express those mutations against the modern fields.

If both files need identical narrative/storyboard builders, place the shared
test-only helpers under `tests/integration/` and keep domain-specific copy in the
calling fixture. Do not add production helpers solely for test migration.

## Alternatives rejected

### Restore `src/editorial_carousel/strategy.py`

Rejected because a re-export cannot supply the removed `ASSET_ADAPTER`, old
planner signature, or old frame schema. Recreating those contracts would revive
the fixed-recipe path that the adaptive workflow intentionally deleted.

### Delete the two integration tests

Rejected because they cover beauty-account routing, multi-domain workflow
partitioning, Human Review, Final Guard, and write-safety behavior not fully
replaced by planner unit tests.

## Scope

Allowed changes:

- the two affected integration tests;
- a focused shared helper under `tests/integration/` if it removes genuine
  duplication;
- documentation index and this design/implementation plan.

Out of scope:

- production workflow, schemas, planner, renderer, asset resolver, or legacy
  migration code;
- unrelated existing test failures;
- external providers or live browser/API calls.

## Verification

The migration is complete when all of the following are true:

1. `pytest -q --collect-only` for both affected files succeeds.
2. Both affected integration files execute successfully offline.
3. Focused modern planner and workflow tests remain green.
4. Plain `pytest -q` no longer reports either deleted-strategy collection error.
5. `python -m compileall -q src main.py` and `git diff --check` pass.

Any remaining suite failures must be compared by exact node ID against the
pre-change baseline; the migration must introduce no new failure.
