# Task 1 report: structured text-card contract

## Delivered

- Added a strict Pydantic text-card schema with six discriminated templates, fixed order, one-theme validation, and card-copy limits.
- Re-exported the new payload from the storyboard schema module and package exports.
- Replaced legacy three-field storyboard review text with `frame_id`, `template`, and precise `text_blocks` locations.
- Added extraction and nested reapplication of visible text, including list entries such as `checklist_items[1]` and timeline fields such as `steps[1].hint`.
- Updated R1/R2, human review, decision routing, policy scanning, and prompts to preserve and review every displayed text atom.
- Replaced the storyboard generation prompt with the JSON-only six-card contract; the generator intentionally continues to pass model output through for deterministic QA.

## Verification

Focused required suite passed:

```text
python -m pytest tests/schemas/test_text_card.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py -v
47 passed, 1 warning
```

Additional regression check:

```text
python -m pytest -q
671 passed, 12 failed, 3 warnings
```

The 12 failures are outside Task 1: legacy carousel QA and integration tests still instantiate and assert the retired image-prompt/card-role schema. They are the follow-on deterministic carousel QA migration; no production workaround was added because Task 1 requires the old schema to be replaced.

## Notes

- The sample headline/footer strings in the task brief were shorter than their stated limits, so the new schema tests use genuinely over-limit fixtures.
- The focused generator test confirms malformed LLM output remains unvalidated at generation time, as required.

## Review follow-up fixes

- Migrated deterministic carousel QA to the structured six-card contract. It now accepts a schema-valid `TextCardPayload` and produces distinct actionable tasks for invalid schema, exact six-card count, fixed template order, one-theme enforcement, cover-headline/first-screen-promise equality, and the required `saveable_checklist` template. Retired `card_role`, `on_image_copy`, `is_screenshot_asset`, per-card `visual_mode`, and image-prompt/decorative checks were removed.
- Made visible-text reapplication frame-ID-only. A non-empty unknown `frame_id` now raises `ValueError` instead of falling back to the same list position; empty IDs are ignored rather than positionally applied.
- Added `merge_storyboard_visible_text` and used it before R2 deterministic policy scanning, after R2 output parsing, and before regenerated storyboards consume an R2 patch. The merge starts from the complete visible-text snapshot, overlays only matching frame IDs and supplied block changes, and retains every prior display atom.
- Replaced stale legacy carousel and integration fixtures with the real six-template payload. Added regression coverage for: valid structured carousel QA routing to human review; precise structured QA failures; unknown frame-ID rejection; regeneration retaining omitted checklist text; and a partial R2 payload retaining all six cards before scanning the dosage-bearing checklist atom.

## Review follow-up verification

- RED: `python -m pytest tests/nodes/test_carousel_qa.py -v` initially produced `2 failed, 1 passed`; the valid six-card payload was rejected for retired `card_role`, `on_image_copy`, `is_screenshot_asset`, and `visual_mode` fields.
- RED: `python -m pytest tests/nodes/test_final_policy_guard.py -v -k 'unknown_nonempty_frame_id or regenerated_storyboards_reapply_visible_text_patch or r2_merges_partial_visible_text'` initially produced `3 failed`; it demonstrated positional unknown-ID mutation and missing-card/atom retention.
- GREEN regression check: the same focused final-policy command passed `3 passed, 1 warning`.
- Required focused suite: `python -m pytest tests/schemas/test_text_card.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/nodes/test_carousel_qa.py -v` passed `52 passed, 1 warning`.
- Directly affected integration suites: `python -m pytest tests/integration/test_beauty_account_workflow.py tests/integration/test_domain_workflow.py -q` passed `10 passed, 2 warnings`.
- Full suite: `python -m pytest -q` passed `682 passed, 3 warnings`.

## Review follow-up warnings

- The remaining warnings are pre-existing test-environment cleanup warnings plus the generator's intentional legacy-checkpoint fallback warning; no test failed.
