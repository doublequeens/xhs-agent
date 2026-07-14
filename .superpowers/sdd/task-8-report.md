# Task 8 Report: Editorial carousel graph integration

## Scope completed

- Added thin `asset_resolver` and `editorial_carousel_renderer` graph adapters.
- Rewired the production graph to
  `assembler -> visual_strategy_planner -> storyboard_generator -> asset_resolver -> carousel_qa -> editorial_carousel_renderer -> render_qa -> human_review -> final_policy_guard -> content_writer`, while retaining the old text-card node only as an exact-successor checkpoint target.
- Added Human Review render/contact-sheet/QA/pending-asset payloads and explicit `asset_decisions` handling.
- Integrated approval promotion and rejection routing. Rejection reloads the same run-scoped catalog with external providers disabled, so resolution advances to an already-downloaded pending candidate or an explicit local fallback without another provider call.
- Allowed audited `pending_external` assets through pre-review Render QA only; pending assets remain blocked from Final Policy Guard.
- Added legacy checkpoint hydration through `editorial_carousel.legacy`; modern checkpoints with the three editorial state slots resume untouched.
- Strengthened Final Policy Guard to require human approval, passed Carousel/Render QA, no pending assets, active/fallback catalog paths, current asset/page/contact-sheet byte hashes, exact source-hash binding, visual-plan/storyboard/render page order, distinct complete 5–7 PNG paths, and contact-sheet page bindings.
- Updated `ContentRecord.image_paths` persistence to use ordered final `RenderManifest.pages` paths.
- Added CLI collection of one explicit approve/reject decision per pending asset.
- Migrated compiled-graph integration fixtures to the modern semantic storyboard/editorial seams. Tests of the retired text-card path use the explicit legacy marker only.

## TDD evidence

### Inherited RED

- Previous implementer recorded the valid initial RED as `10 failed, 63 passed` for the Task 8 focused suite.
- On takeover, the Task 8 four-file suite was already GREEN (`75 passed`), but `tests/test_main.py tests/nodes/test_render_qa.py` exposed one remaining old-checkpoint regression: `1 failed, 79 passed`. The terminal checkpoint fake had no `update_state`, and Task 8 hydration was unnecessarily trying to rewrite an already-terminal checkpoint.
- First full-suite run after that fix exposed stale pre-Task-8 fixtures: `11 failed, 1045 passed, 2 skipped`.

### Additional RED/GREEN cycles

- Terminal legacy checkpoint hydration: RED `1 failed`; GREEN exact regression `1 passed`, then main/Render QA `80 passed`.
- Final Guard ordered binding: reversing pages, package paths, and contact-sheet page bindings originally produced no issue; after the fix the focused test passed and the guard suite passed.
- Final Guard distinct path completeness: duplicating one page path while updating all stored hashes originally passed; after the fix the focused test passed and the guard suite passed.
- Human Review lifecycle orchestration: approve promotion routes to Render QA; rejection reloads the catalog twice with `allow_external=False` and routes through the renderer. Focused result: `2 passed`.
- Real resolver evidence for reject-next and pending resume without provider calls: `2 passed`.
- Asset resolver suite: `115 passed, 2 skipped` (the two opt-in live provider API tests).
- Modern beauty compiled-graph integration: `5 passed`.
- Modern domain compiled-graph integration: `8 passed`.

## Final verification

- Task 8 brief suite:
  `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/test_graph.py tests/nodes/test_domain_nodes.py tests/nodes/test_final_policy_guard.py tests/nodes/test_content_writer.py -q`
  -> `79 passed`.
- Main and Render QA:
  `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/test_main.py tests/nodes/test_render_qa.py -q`
  -> `80 passed`.
- Modern compiled-graph integrations:
  `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/integration/test_beauty_account_workflow.py tests/integration/test_domain_workflow.py -q`
  -> `13 passed`.
- Full suite:
  `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q`
  -> `1057 passed, 2 skipped, 3 warnings` in 28.98s.
- `git diff --check` -> clean.

## Self-review

### Standards

- No repository coding-standard document exists beyond the supplied agent/issue/domain workflow instructions; no issue-tracker mutation was required.
- The new graph nodes remain thin adapters and do not duplicate resolver ranking, download, rendering, or lifecycle hash logic.
- Legacy compatibility is centralized in `src/editorial_carousel/legacy.py`; modern tests do not use the marker.
- Manual smell review found no blocking duplicated policy logic or hidden provider calls. The Human Review node is necessarily orchestration-heavy, but lifecycle mutations remain delegated to the resolver/lifecycle modules.

### Spec

- Verified explicit asset approval and rejection lifecycle, already-downloaded next/fallback resolution without repeat external calls, pending-asset exclusion from Final Guard, R1/R2/review routes, checkpoint resume without repeated resolution, current-byte hash recomputation and ordered bindings, final PNG persistence, and CLI asset decision input.
- No Task 8 requirement remains partial.

## Concerns and follow-up boundaries

- The two live provider tests remain intentionally skipped unless `RUN_LIVE_ASSET_PROVIDER_TESTS=1`; default tests make no network calls as required.
- The three warnings are an upstream LangGraph pending-deprecation warning plus two explicit legacy storyboard fallback warnings.
- `main.py` still owns the pre-existing fixed-six-page export validator. The plan assigns dynamic 5–7 path validation and the new publish artifact exporter to Task 9, so Task 8 deliberately does not implement that later scope.
