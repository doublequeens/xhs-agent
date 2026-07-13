# Task 2: Local text-card renderer report

## Delivered scope

- Added `src.rendering.text_cards` with immutable approved theme and canvas tokens.
- Added standalone, asset-free HTML/CSS templates for all six structured text-card frame types.
- Added `render_text_cards`, which uses one local Playwright Chromium session, captures the fixed six-file sequence, checks every `data-card-copy` element for overflow before capture, and wraps renderer failures as `TextCardRenderError`.
- Added cleanup that removes files already attempted when a later capture fails.
- Added focused tests for tokenized HTML, escaping, filename order, partial-output cleanup, and a real local Chromium smoke render with PNG IHDR dimensions.

## TDD evidence

The initial focused test run failed as expected with `ModuleNotFoundError: No module named 'src.rendering'`. The implementation was then added and the same test target was rerun until green.

The first local-browser smoke run exposed actual fixed-layout overflow on the supplied Chinese copy. CSS line boxes and wrapping were adjusted without changing font sizes dynamically; the renderer's required overflow check now passes for the valid payload fixture.

## Verification

Command run:

```bash
python -m pytest tests/rendering/test_text_cards.py -v
```

Result: `5 passed` (including real local Chromium rendering of six `1080 x 1440` PNGs).

The environment emitted two unrelated pytest temporary-directory cleanup warnings from an existing macOS temp path; the command exited successfully.

## Dependencies and constraints

- Local Playwright Chromium is installed and was used by the smoke test.
- No network, image API, external font, or external image asset is used.
- The requested implementation commit stages only the three Task 2 source/test paths; this report remains uncommitted task documentation unless a later task explicitly includes it.

## Review-fix follow-up

### Findings resolved

- Constrained `TextCardTheme` in the Pydantic schema to exactly `warm_neutral` and `cool_sage`, and changed the storyboard-generator prompt to advertise only those two values. All schema-valid payloads are now renderer-valid with respect to theme tokens. Existing structured-card fixtures and patch expectations were migrated from retired free-form theme names to the approved values.
- Changed partial-output cleanup to collect unlink failures and raise `TextCardRenderError` with the original rendering error as its direct cause. A failed cleanup is therefore observable instead of being silently suppressed.
- Removed the question-card-local footer; the shared card footer is the single rendered footer for every template, including `question_closer`.

### Regression coverage

- Schema rejects `soft_blue`, `warm_orange`, and other unsupported themes.
- Generator prompt no longer declares `theme` as an arbitrary string and names both approved values.
- Question closer HTML has exactly one footer copy role and one footer value.
- A later screenshot failure combined with an unlink failure raises a cleanup `TextCardRenderError` whose cause retains the original screenshot error.

### Exact verification output

Command:

```bash
python -m pytest tests/schemas/test_text_card.py tests/rendering/test_text_cards.py -q
```

```text
...............                                                          [100%]
=============================== warnings summary ===============================
../../../../../../opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-f339fd16-f6b1-4beb-aa7f-173d0a0b78e8/test_plist_mode_is_0600_under_0
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-f339fd16-f6b1-4beb-aa7f-173d0a0b78e8/test_plist_mode_is_0600_under_0'
    warnings.warn(

../../../../../../opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-f339fd16-f6b1-4beb-aa7f-173d0a0b78e8
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-f339fd16-f6b1-4beb-aa7f-173d0a0b78e8'
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
15 passed, 2 warnings in 0.85s
```

Command:

```bash
python -m pytest -q
```

```text
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 31%]
........................................................................ [ 41%]
........................................................................ [ 51%]
........................................................................ [ 62%]
........................................................................ [ 72%]
........................................................................ [ 82%]
........................................................................ [ 93%]
...............................................                          [100%]
=============================== warnings summary ===============================
tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_reapply_visible_text_patch
tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_apply_complete_r2_visible_text_without_human_patch
  /Users/qinqiang/Documents/Workspace/Projects/xhs-agent/src/nodes/node_o_storyboards_generator.py:58: UserWarning: storyboards_generator is falling back to beauty-v1 for a legacy checkpoint without domain_context.
    system_prompt = compose_prompt_for_state("storyboards_generator", state)

../../../../../../opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-eaf14fac-d6e4-49d1-b1c6-8d66b4df55f3/test_plist_mode_is_0600_under_0
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-eaf14fac-d6e4-49d1-b1c6-8d66b4df55f3/test_plist_mode_is_0600_under_0'
    warnings.warn(

../../../../../../opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /opt/anaconda3/envs/daily/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-eaf14fac-d6e4-49d1-b1c6-8d66b4df55f3
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/nr/cxbz58_577dfp3053flt_t4r0000gn/T/pytest-of-qinqiang/garbage-eaf14fac-d6e4-49d1-b1c6-8d66b4df55f3'
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
695 passed, 4 warnings in 15.01s
```
