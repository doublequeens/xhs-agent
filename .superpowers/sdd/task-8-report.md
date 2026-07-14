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
- Closed the Task 8 review findings across all six groups:
  - CLI review omits empty asset decisions, supports a second approval after pending-asset handling, displays provenance, and records explicit decisions for every unresolved safety check.
  - Modern `content_blocks` and emphasis atoms participate in visible-text extraction/reapplication and policy scanning; content/layout/slot edits invalidate every downstream plan/asset/QA/render artifact before R2 regeneration.
  - Multi-asset review is a lifecycle deep-module operation with complete canonical preflight, a catalog-wide batch lock, snapshot compensation across incoming/promoted bytes, audits, and catalog manifest, and an in-boundary resolver finalize step.
  - Legacy hydration now requires an explicit old editorial version/marker or a strict old-template shape at an old checkpoint seam. Partial or corrupt modern state is never downgraded, and stale legacy markers are cleared on modern hydration.
  - Human decisions bind pending ID, slot, provider ID, requirement fingerprint, SHA-256, and canonical metadata path; a generic approval cannot synthesize safety clearance.
  - Final Guard uses one `O_NOFOLLOW` file-descriptor snapshot for inode checks, SHA-256, and Pillow decoding, enforces trusted render-root containment and distinct canonical paths/inodes, binds ordered frame/role/layout/text probes, and rebinds unique asset slots across plan/storyboard/manifest.

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
- CLI lifecycle control: two initial failures showed empty decisions entering lifecycle and blocking the approved-to-guard transition; the real CLI-to-node-to-router tests now cover both no-pending and pending-then-second-review flows.
- Modern storyboard visibility/invalidation: six focused failures reproduced missing `content_blocks` extraction/policy coverage and stale artifact reuse; all six pass after canonical visible atoms plus render-structure signatures and downstream invalidation.
- Batch lifecycle closure: focused coverage proves rollback after the second approval, rollback of mixed approve/reject when final resolution fails, successful mixed commit plus idempotent retry, and rejection of stale bindings or implicit safety approval.
- Legacy classification closure: corrupt/partial states and stale marker tests pass without weakening modern artifact requirements.
- Secure Final Guard closure: focused tests cover valid artifacts, corrupt bytes, duplicate raw paths, symlinked active assets, symlink and hardlink page aliases, paths outside the trusted root, ordered role/layout mismatch, stale visible-text probes, duplicate/rebound slots, and path replacement after open.
- The first closure full-suite run was `1076 passed, 2 skipped, 3 failed`; all three failures were modern integration fixtures with placeholder PNGs and incomplete bindings. The fixtures were upgraded to consistent modern artifacts rather than marked legacy. The fresh full run passed.

## Final verification

- Review-closure core files:
  `pytest tests/test_main.py tests/asset_resolver/test_lifecycle.py tests/nodes/test_domain_nodes.py tests/nodes/test_final_policy_guard.py -q`
  -> `162 passed` before the last CLI safety and secure-path additions.
- Modern domain compiled-graph integration:
  `pytest tests/integration/test_domain_workflow.py -q`
  -> `8 passed`.
- Full suite:
  `pytest -q`
  -> `1080 passed, 2 skipped, 4 warnings` in 26.58s.
- Bytecode compilation:
  `python -m compileall -q main.py src tests`
  -> passed.
- `git diff --check` -> clean.

## Self-review

### Standards

- No repository coding-standard document exists beyond the supplied agent/issue/domain workflow instructions; no issue-tracker mutation was required.
- The graph nodes remain thin adapters. Batch decision matching, canonical audit verification, safety review, mutation, rollback, retry semantics, and resolver-finalize compensation live in `asset_resolver.lifecycle`.
- Legacy compatibility is centralized in `src/editorial_carousel/legacy.py`; modern tests do not use the marker.
- Manual smell review found no blocking duplicated policy logic or hidden provider calls. Human Review now prepares state and delegates the complete mutation boundary to the lifecycle module.

### Spec

- Verified explicit asset approval and rejection lifecycle, canonical provenance/safety binding, whole-batch rollback and retry, already-downloaded next/fallback resolution without repeat external calls, pending-asset exclusion from Final Guard, R1/R2/review routes, checkpoint resume without repeated resolution, modern visible-text invalidation, secure current-byte snapshots and ordered bindings, final PNG persistence, and CLI asset decision input.
- No Task 8 requirement remains partial.

## Concerns and follow-up boundaries

- The two live provider tests remain intentionally skipped unless `RUN_LIVE_ASSET_PROVIDER_TESTS=1`; default tests make no network calls as required.
- The default run's warnings are two explicit legacy storyboard fallback warnings plus transient pytest temporary-directory cleanup warnings on this macOS runner.
- `main.py` still owns the pre-existing fixed-six-page export validator. The plan assigns dynamic 5–7 path validation and the new publish artifact exporter to Task 9, so Task 8 deliberately does not implement that later scope.
