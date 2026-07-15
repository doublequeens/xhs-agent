# Task 2 report: deterministic visual strategy and semantic storyboards

## Status

Implemented on `feature/editorial-carousel-workflow` from required base
`853e803a9ac947131aa1c3eaf51028c5c4a70533`.

Delivered:

- Deterministic, versioned `beauty_editorial_v1` recipes for all five content jobs.
- Exact six-frame `diagnose_and_adjust` recipe from the approved specification.
- Five-frame recipes for the four non-zone jobs: this is the smallest frame count
  allowed by Task 1 while still preserving cover-first, three-layout, and saveable-page
  invariants.
- Deterministic anti-repetition selection that changes a non-cover/non-save auxiliary
  layout when the base signature recently appeared, without changing the content job
  or primary family.
- `required_assets` derived from recipe asset roles and layouts only; topic/title text
  is never inspected.
- An isolated pre-editorial checkpoint content-contract hydration adapter.
- A visual-strategy planner node exported through `src.nodes`.
- A semantic storyboard prompt for strict `CarouselPayload` JSON.
- Storyboard validation before state write, including exact frame ID/order/layout
  matching against `VisualPlan.frame_plan`, plus revalidation after pending patches.
- A transitional no-`visual_plan` checkpoint branch so the existing graph and old
  persisted structured-card checkpoints remain resumable until the later graph task
  inserts the planner node. New states carrying `visual_plan` always use the strict
  semantic branch.

## TDD evidence

### RED 1: strategy and planner imports

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel/test_strategy.py tests/nodes/test_visual_strategy_planner.py -q
```

Exact terminal result:

```text
FFFFFFFFFFFFF                                                            [100%]
...
E       ModuleNotFoundError: No module named 'src.editorial_carousel'
...
E       ModuleNotFoundError: No module named 'src.nodes.node_p_visual_strategy_planner'
...
13 failed in 0.09s
```

This was the expected failure mode: the new strategy package and planner node did not
exist yet.

### GREEN 1: strategy and planner

Same command after the minimal implementation:

```text
.............                                                            [100%]
13 passed in 0.05s
```

### RED 2: semantic storyboard validation and prompt

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/nodes/test_metadata_flow.py tests/prompts/test_composer.py -q
```

Exact terminal result:

```text
............FF......F...........................                         [100%]
...
FAILED tests/nodes/test_metadata_flow.py::test_storyboard_generator_rejects_invalid_payload_before_state_write
FAILED tests/nodes/test_metadata_flow.py::test_storyboard_generator_rejects_frame_order_or_layout_drift
FAILED tests/prompts/test_composer.py::test_storyboard_prompt_requires_semantic_carousel_contract
3 failed, 45 passed in 2.29s
```

The failures proved that the old node accepted invalid/unordered payloads and the old
prompt still described fixed text cards.

### GREEN 2: semantic storyboard validation and prompt

Same command after implementation:

```text
................................................                         [100%]
48 passed in 2.24s
```

The environment additionally emitted macOS pytest temporary-directory cleanup
warnings after the successful exit.

### RED 3: smallest valid non-zone recipes

Self-review identified the brief's explicit minimum-size requirement and added this
test before trimming recipes.

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel/test_strategy.py::test_non_zone_recipes_use_the_smallest_schema_valid_frame_count -q
```

Exact terminal result:

```text
FFFF                                                                     [100%]
...
E       AssertionError: assert 6 == 5
...
FAILED tests/editorial_carousel/test_strategy.py::test_non_zone_recipes_use_the_smallest_schema_valid_frame_count[follow_steps]
FAILED tests/editorial_carousel/test_strategy.py::test_non_zone_recipes_use_the_smallest_schema_valid_frame_count[compare_and_choose]
FAILED tests/editorial_carousel/test_strategy.py::test_non_zone_recipes_use_the_smallest_schema_valid_frame_count[save_and_check]
FAILED tests/editorial_carousel/test_strategy.py::test_non_zone_recipes_use_the_smallest_schema_valid_frame_count[understand_and_notice]
4 failed in 0.08s
```

### GREEN 3: smallest valid non-zone recipes

Same command after trimming the four recipes:

```text
....                                                                     [100%]
4 passed in 0.05s
```

## Final focused verification

Command required by the brief:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel tests/nodes/test_visual_strategy_planner.py tests/nodes/test_metadata_flow.py tests/prompts/test_composer.py -q
```

Exact terminal result:

```text
.................................................................        [100%]
65 passed in 2.24s
```

The command exited 0. Pytest subsequently reported two non-failing macOS temporary
directory cleanup warnings.

## Full-suite verification

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Exact terminal result:

```text
........................................................................ [  9%]
........................................................................ [ 18%]
........................................................................ [ 27%]
........................................................................ [ 36%]
........................................................................ [ 46%]
........................................................................ [ 55%]
........................................................................ [ 64%]
........................................................................ [ 73%]
........................................................................ [ 83%]
........................................................................ [ 92%]
...........................................................              [100%]
=============================== warnings summary ===============================
../../../../../../../../opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5
  /opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5: LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version. Pass an explicit value (e.g., allowed_objects='messages' or allowed_objects='core') to suppress this warning.
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_reapply_visible_text_patch
tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_apply_complete_r2_visible_text_without_human_patch
  /Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.worktrees/editorial-carousel-workflow/src/nodes/node_o_storyboards_generator.py:66: UserWarning: storyboards_generator is falling back to beauty-v1 for a legacy checkpoint without domain_context.
    system_prompt = compose_prompt_for_state("storyboards_generator", state)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
779 passed, 3 warnings in 19.04s
```

The command exited 0. Pytest subsequently reported two non-failing macOS temporary
directory cleanup warnings.

## Files

Created:

- `src/editorial_carousel/__init__.py`
- `src/editorial_carousel/strategy.py`
- `src/editorial_carousel/legacy.py`
- `src/nodes/node_p_visual_strategy_planner.py`
- `tests/editorial_carousel/test_strategy.py`
- `tests/nodes/test_visual_strategy_planner.py`

Modified:

- `src/nodes/__init__.py`
- `src/nodes/node_o_storyboards_generator.py`
- `src/prompts/base/storyboards_generator.txt`
- `tests/nodes/test_metadata_flow.py`
- `tests/prompts/test_composer.py`

No Task 3 assets, Task 4 resolver, Task 6 renderer, Task 9 publishing, graph rewiring,
or external provider behavior was implemented.

## Self-review

- Re-read every Task 2 checklist item against the diff.
- Confirmed the diagnostic recipe tuple is exact and its six semantic roles/layouts
  are locked by a test.
- Confirmed every recipe starts with `editorial_cover`, has at least three layouts,
  has 5-7 frames, and includes a saveable layout through both tests and strict
  `VisualPlan` construction.
- Confirmed family selection comes from `content_job`; topic/title substrings are not
  used.
- Confirmed asset requirements are generated directly from each recipe's asset role
  and layout.
- Confirmed malformed new contracts fail Pydantic validation and never invoke legacy
  hydration.
- Confirmed the prompt forbids HTML, CSS, coordinates, URLs, image-generation
  prompts, topic changes, and extra frames.
- Confirmed strict semantic output is validated once before merge and once after
  pending human/R2 patches, so invalid patched state cannot be written.
- Confirmed `git diff --check` exits 0.
- Ruff is not installed in the supplied `/opt/anaconda3/envs/xhs-agent` environment;
  no Ruff claim is made. The repository has no Ruff configuration/dependency in the
  inspected project files.

## Concerns

- The graph-plumbing task is later in the workflow, so an absent `visual_plan` is
  treated as a pre-migration checkpoint and retains old card behavior. Once graph
  rewiring is complete, normal new executions must always reach the strict semantic
  branch. This compatibility branch is intentionally narrow and does not hydrate or
  repair new content contracts.
- The final suite's three warnings are unrelated to Task 2 correctness: one
  third-party LangGraph deprecation warning and two expected legacy checkpoint
  domain-context fallback warnings. Pytest also prints non-failing macOS temp cleanup
  warnings after some successful commands.

## Review-fix follow-up

### Findings resolved

- Added `storyboards_generator_legacy.txt` and a minimal composer task entry. A state
  without `visual_plan` now receives the original fixed-six `TextCardPayload` prompt,
  omits a fabricated visual plan from its human prompt, preserves the old raw handoff,
  and leaves validation/R1 routing with the current carousel QA. A state with a real
  `visual_plan` continues to receive only the strict semantic prompt and
  `CarouselPayload` validation.
- Removed `diagnose_and_adjust` from anti-repetition alternatives. Its exact six roles
  and layouts, including `three_state_diagnostic`, are now immutable even if the same
  signature was recently published. The deterministic alternative test uses
  `follow_steps` instead.
- Made `publish_package.content_contract` the only semantic-path contract source.
  It is validated before the model call and must match the visual plan's content job
  and primary visual family. Legacy no-plan checkpoints retain topic lookup.
- Added one shared semantic payload validator used both immediately after model output
  and after pending/R2/human patch application. It enforces schema, exact frame
  ID/order/layout alignment, and cover headline equality to the final package
  contract's `first_screen_promise` at both gates.

### Review-fix RED evidence

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel/test_strategy.py tests/nodes/test_visual_strategy_planner.py tests/nodes/test_metadata_flow.py tests/prompts/test_composer.py -q
```

Exact terminal result before fixes:

```text
..........F..................FFF..FF........F........................... [100%]
...
FAILED tests/editorial_carousel/test_strategy.py::test_recent_identical_signature_never_changes_diagnostic_recipe
FAILED tests/nodes/test_metadata_flow.py::test_storyboard_generator_without_plan_uses_legacy_prompt_and_payload
FAILED tests/nodes/test_metadata_flow.py::test_semantic_storyboard_uses_final_package_contract_when_trend_is_stale
FAILED tests/nodes/test_metadata_flow.py::test_semantic_storyboard_rejects_package_contract_that_disagrees_with_plan
FAILED tests/nodes/test_metadata_flow.py::test_semantic_storyboard_rejects_cover_promise_mismatch_before_state_write
FAILED tests/nodes/test_metadata_flow.py::test_semantic_storyboard_rejects_cover_promise_mismatch_after_r2_patch
FAILED tests/prompts/test_composer.py::test_legacy_storyboard_prompt_is_isolated_from_semantic_contract
7 failed, 65 passed in 2.31s
```

The seven failures corresponded one-to-one with the requested review fixes: mutated
diagnostic layout, wrong prompt branch, stale trend contract overwrite, missing
plan/contract consistency gate, two missing cover gates, and the absent isolated
legacy prompt.

### Review-fix GREEN evidence

Same focused command after fixes:

```text
........................................................................ [100%]
72 passed in 2.20s
```

The command exited 0. Pytest subsequently emitted two non-failing macOS temporary
directory cleanup warnings.

Current downstream legacy compatibility command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/nodes/test_carousel_qa.py tests/schemas/test_text_card.py -q
```

Exact output:

```text
..................                                                       [100%]
18 passed in 0.05s
```

### Review-fix full-suite verification

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Exact terminal result:

```text
........................................................................ [  9%]
........................................................................ [ 18%]
........................................................................ [ 27%]
........................................................................ [ 36%]
........................................................................ [ 45%]
........................................................................ [ 54%]
........................................................................ [ 64%]
........................................................................ [ 73%]
........................................................................ [ 82%]
........................................................................ [ 91%]
..................................................................       [100%]
=============================== warnings summary ===============================
../../../../../../../../opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5
  /opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5: LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version. Pass an explicit value (e.g., allowed_objects='messages' or allowed_objects='core') to suppress this warning.
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_reapply_visible_text_patch
tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_apply_complete_r2_visible_text_without_human_patch
  /Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.worktrees/editorial-carousel-workflow/src/nodes/node_o_storyboards_generator.py:142: UserWarning: storyboards_generator_legacy is falling back to beauty-v1 for a legacy checkpoint without domain_context.
    SystemMessage(content=compose_prompt_for_state(prompt_task, state)),

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
786 passed, 3 warnings in 19.10s
```

The full suite exited 0. Pytest subsequently emitted two non-failing macOS temporary
directory cleanup warnings.

### Review-fix self-review

- Confirmed the semantic prompt file was not weakened or mixed with legacy rules.
- Confirmed only the no-plan branch can select `storyboards_generator_legacy`.
- Confirmed semantic contract disagreement fails before `get_model()` executes.
- Confirmed semantic generated and post-patch storyboards traverse the same validator.
- Confirmed diagnostic anti-repetition returns the exact base tuple and the non-zone
  alternative remains deterministic and schema-valid.
- Confirmed `git diff --check` exits 0.
- No new concerns beyond the existing expected third-party/legacy warning notes.

