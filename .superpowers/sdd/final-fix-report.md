# Final Review Fix Report

Date: 2026-07-13

## Fixed findings

- Removed the CLI's in-stream export after `human_review`. Export now happens only after `graph.get_state()` reports a terminal checkpoint with an approved review and no `final_policy_issues`.
- Added an integration regression using real local PNG fixtures: an approved review followed by a final-policy failure produces no audit JSON and no additional image export.
- Replaced `decision_rule.condition` / `recommendation` with a strict 2--3 item `conditions` list of `{situation, recommendation}` pairs. Prompting, schema, renderer, visible-text extraction/reapplication, and final-policy scanning use those atoms.
- Made `kicker` and `footer` optional/empty-safe and omit their HTML elements when absent.
- Added shared leaf validation that rejects emoji in all visible card-copy atoms, including list and nested fields.
- Enforced the 76 px / 1.18 semibold title contract by splitting at 14 codepoints per line into a fixed two-line title area. The cover now renders its title once. Body and footer CSS use the approved 36 px / 1.45 and 28 px / 1.35 tokens.
- Added fixed muted comparison tokens: wrong `#B06A6A`, right `#6F9275`, with separate classes and assertions.
- Removed trailing whitespace from the approved implementation plan.

## Verification

| Command | Result |
| --- | --- |
| `python -m pytest tests/schemas/test_text_card.py tests/rendering/test_text_cards.py tests/nodes/test_carousel_qa.py tests/nodes/test_text_card_renderer.py tests/nodes/test_render_qa.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/test_main.py tests/integration/test_beauty_account_workflow.py tests/integration/test_domain_workflow.py -q` | 115 passed |
| `python -m pytest tests/integration/test_beauty_account_workflow.py tests/test_main.py tests/nodes/test_final_policy_guard.py -q` | 59 passed |
| `python -m pytest tests/rendering/test_text_cards.py tests/schemas/test_text_card.py -q` | 27 passed |
| `python -m pytest tests/nodes/test_final_policy_guard.py::test_decision_condition_visible_atoms_are_extracted_and_reapplied_by_frame_id tests/rendering/test_text_cards.py::test_boundary_length_chinese_headline_stays_within_two_lines_in_real_browser -q` | 2 passed; local Chromium boundary test executed |
| `python -m pytest` | exit 0; 720 tests collected |
| `git diff --check` | exit 0; no whitespace errors |

The test runs emitted pre-existing pytest temporary-directory cleanup warnings and two legacy-checkpoint fallback warnings; none were test failures. No image API, external image service, or network image/material service was called.
