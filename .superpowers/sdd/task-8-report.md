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
- Closed the second Task 8 review without loosening the modern artifact contract:
  - Final Guard now permits intentional reuse of one catalog asset across unique slots while requiring each slot's exact requirement/layout/role/hash/provenance binding. A real beauty catalog -> strategy -> resolver -> guard integration covers background and skin-detail reuse; conflicting declarations for the same path/inode fail closed.
  - Exact pre-Task-8 checkpoints at `storyboard_generator`, `carousel_qa`, and `render_qa` resume in an isolated `legacy_v1` lane without invoking the asset resolver. An R1 regeneration that produces a modern plan emits an explicit `modern_v2` transition, clears legacy state, invalidates downstream artifacts, and immediately returns to the full modern resolver/guard path.
  - Batch, standalone approval/rejection, and direct catalog append operations share one catalog-review lock. Batch recovery is journaled durably; compensation attempts every asset/audit restoration, restores the manifest under its own lock with compare-and-swap, preserves a concurrent manifest write, retains the original exception, and retries incomplete recovery before later review work.
  - Final Guard walks every trusted-root path component by directory file descriptor with `O_DIRECTORY | O_NOFOLLOW`, then validates and reads the final regular file from the same descriptor chain. An intermediate-directory symlink swap is rejected.
  - Human Review's render-structure signature now includes the canonical complete `ContentContract`, so any planner/render contract edit invalidates downstream artifacts and routes through R2. Batch decision lookup accepts only the displayed canonical pending ID.
- Closed the final Task 8 security/crash-consistency review:
  - Recovery journals are strict Pydantic `version=1` records bound to transaction ID, catalog ID/root, run ID, and manifest path. Recovery verifies a non-symlink journal directory and journal inode, quarantines unknown/corrupt records, and validates every original/target manifest and audit snapshot hash, strict audit schema, source inode/hash, and incoming/active path containment before any mutation.
  - Batch review is a real write-ahead transaction. The complete target manifest digest and target audits are durable before mutation; audit, asset move, manifest, and every reverse operation persist+fsync `intent`, perform the idempotent CAS/move plus file/parent fsync, then persist+fsync `done`. Journal rename/unlink and newly created/moved parent entries are fsynced. A previously committed approval is excluded from later transaction ownership and cannot be rolled back by a failed retry.
  - The catalog review lock opens with `O_NOFOLLOW` and requires a stable regular single-link inode before and after `flock`, rejecting symlinks, hardlink aliases, and replacement races while preserving the global lock order.
  - `modern_v2` is decisive over old shapes and spoofed legacy markers. Unknown versions fail closed; versionless legacy inference requires a strict old shape at one exact old successor; partial modern checkpoints remain modern and surface missing-artifact issues.
  - Final Guard opens the absolute trusted root from `/` one component at a time with `O_DIRECTORY | O_NOFOLLOW`, retains every directory descriptor, and rechecks each parent/name inode after reading. It also verifies every final asset against the canonical active catalog; licensed stock additionally requires one matching strict approved audit with exact run/review/safety/reviewed-at/hash bindings. Project-original seed assets follow an explicit local canonical-catalog rule.

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
- Second-review catalog reuse: two RED failures showed that physical reuse was rejected categorically and conflicting same-file declarations were not detected. The production catalog/strategy/resolver integration and conflict regression are GREEN.
- Exact legacy resume: four RED integration failures exposed checkpoint-successor drift and unconditional modern resolver routing. Typed hydration with predecessor-aware `update_state(..., as_node=...)`, conditional storyboard routing, and the same-run `legacy_v1 -> modern_v2` transition made all four real-checkpointer cases GREEN.
- Content-contract invalidation: the new contract-edit regression was RED because Human Review approved stale artifacts; canonical contract participation in the render-structure signature made it GREEN.
- Lifecycle concurrency/recovery: the initial lifecycle run had one stale failure-injection seam after global locking moved below the public wrapper. The updated suite proves batch/standalone serialization, manifest CAS preservation under a simulated concurrent writer, aggregated move-plus-audit rollback failures, durable journal retention, successful recovery on retry, and canonical-ID-only decisions (`43 passed`).
- Descriptor-chain traversal: focused regressions cover both final-file replacement after open and an intermediate directory swapped to a symlink; both fail closed under component-wise `openat` traversal.
- Second-review combined focused verification passed with `179 passed`; the first subsequent full run found one stale exact-key assertion for the newly typed planner transition. Updating that contract assertion yielded the final clean run.
- Final-review journal trust boundary: the external symlink journal directory test was RED because attacker-controlled recovery executed a move; path escape, unknown schema, and tampered audit snapshots were also RED. All four public retry regressions are GREEN under strict pre-mutation validation and quarantine.
- Final-review crash protocol: 13 forward transition crash points and 9 rollback transition crash points simulate process death with a `BaseException`; every public retry converges to exactly one approved catalog entry and no journal. A separate retry-finalize failure proves a preexisting approval remains active, and the rollback-internal failure regression proves the original exception remains primary with aggregated compensation notes (`23 passed`).
- Final-review lock boundary: symlink, hardlink-alias, and post-flock replacement tests were RED and are GREEN alongside the existing concurrent batch/standalone cases.
- Final-review version boundary: `modern_v2 + old shape + marker`, unknown-version marker spoof, and Final Guard partial-modern marker bypass were all RED; all three are GREEN with version-first classification.
- Final-review root/provenance boundary: a trusted-root parent replacement through a symlink was readable before the `/`-anchored descriptor chain; consistent forged provenance across every reused item passed before canonical lookup. Both are now rejected while the real catalog reuse integration remains GREEN.
- The first final-review full run found three domain integration fixtures without canonical catalogs. Those fixtures now generate valid SVG project-original assets plus a validated canonical manifest; the exact regressions pass.
- Transaction-ledger replay closure: a forged empty-operation journal could rewrite the manifest on recovery before the new test failed. Recovery now requires a durable catalog/run-bound transaction registry, a fresh non-reusable transaction ID, and an immutable plan hash covering both manifest snapshots and every operation. Registry state is authoritative: only `prepared` may roll back, while `committed` and `aborted` transactions can never be replayed as rollback work. Recovery directory/journal/registry ownership and modes plus bounded journal/base64/snapshot sizes fail closed.
- Standalone lifecycle closure: approval and rejection previously used separate non-WAL mutation paths. Both now enter the same public batch transaction engine; the boolean lock bypass and direct catalog append writer were deleted. The standalone crash matrices cover 15 approval and 12 rejection forward points (`27 passed`), including registry, audit, move, manifest, finalize, and commit-ledger boundaries.
- Descriptor-relative mutation closure: journal, registry, audit, manifest, move, and unlink writes use held component-wise `openat(O_NOFOLLOW)` directory descriptors, durable temp-file rename, parent fsync, and post-operation directory-binding validation. The catalog lock also validates owner/mode/link/identity before and after `flock` and after the critical section without masking a primary body exception.
- Canonical Guard closure: the manifest parser now consumes the exact bytes from the Guard's secure descriptor snapshot rather than reopening its pathname. External audit comparison covers the complete canonical provenance/review record; project-original assets additionally bind ownership, production usage, tags, dimensions, layout, and active/fallback role semantics.
- The first ledger-hardening full run found three domain integration fixtures missing newly enforced manifest dimensions; adding their real 1080x1440 declarations made the focused regressions and the fresh full run GREEN.

## Final verification

- Review-closure core files:
  `pytest tests/test_main.py tests/asset_resolver/test_lifecycle.py tests/nodes/test_domain_nodes.py tests/nodes/test_final_policy_guard.py -q`
  -> `162 passed` before the last CLI safety and secure-path additions.
- Modern domain compiled-graph integration:
  `pytest tests/integration/test_domain_workflow.py -q`
  -> `8 passed`.
- Full suite:
  `pytest -q`
  -> `1127 passed, 2 skipped, 4 warnings` in 29.48s.
- Second-review focused suite:
  `pytest tests/test_main.py tests/test_graph.py tests/nodes/test_domain_nodes.py tests/integration/test_legacy_editorial_resume.py tests/nodes/test_final_policy_guard.py tests/asset_resolver/test_lifecycle.py -q`
  -> `179 passed`.
- Lifecycle concurrency/recovery suite:
  `pytest tests/asset_resolver/test_lifecycle.py -q`
  -> `73 passed`.
- Final-review targeted lifecycle/guard/resume suite:
  `pytest tests/asset_resolver/test_lifecycle.py tests/nodes/test_final_policy_guard.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py -q`
  -> `186 passed, 4 warnings`.
- Final-review broader focused suite:
  `pytest tests/asset_resolver tests/nodes/test_final_policy_guard.py tests/nodes/test_domain_nodes.py tests/nodes/test_visual_strategy_planner.py tests/test_main.py tests/test_graph.py tests/integration/test_legacy_editorial_resume.py -q`
  -> `298 passed, 2 skipped, 4 warnings`.
- Bytecode compilation:
  `python -m compileall -q main.py src tests`
  -> passed.
- `git diff --check` -> clean.
- Transaction-ledger/standalone lifecycle suite:
  `pytest tests/asset_resolver/test_lifecycle.py -q`
  -> `102 passed`.
- Hardened lifecycle/Guard combined suite:
  `pytest tests/asset_resolver/test_lifecycle.py tests/nodes/test_final_policy_guard.py -q`
  -> `164 passed, 4 warnings` after rerunning the one transient lock-create race regression.
- Latest broader focused suite:
  `pytest tests/asset_resolver tests/nodes/test_final_policy_guard.py tests/nodes/test_domain_nodes.py tests/nodes/test_visual_strategy_planner.py tests/test_main.py tests/test_graph.py tests/integration/test_legacy_editorial_resume.py -q`
  -> `327 passed, 2 skipped, 4 warnings`.
- Latest full suite:
  `pytest -q`
  -> `1156 passed, 2 skipped` (`1158 tests collected`).
- Latest bytecode/diff verification:
  `python -m compileall -q main.py src tests` and `git diff --check`
  -> passed/clean.

## Self-review

### Standards

- No repository coding-standard document exists beyond the supplied agent/issue/domain workflow instructions; no issue-tracker mutation was required.
- The graph nodes remain thin adapters. Batch decision matching, canonical audit verification, safety review, mutation, rollback, retry semantics, and resolver-finalize compensation live in `asset_resolver.lifecycle`.
- Legacy compatibility is centralized in `src/editorial_carousel/legacy.py`; modern tests do not use the marker.
- Manual smell review found no blocking duplicated policy logic or hidden provider calls. Human Review now prepares state and delegates the complete mutation boundary to the lifecycle module.

### Spec

- Verified explicit asset approval and rejection lifecycle, strict catalog/run-bound recovery records, crash-resumable write-ahead apply/rollback, canonical provenance/safety binding, hardened globally serialized writers, compare-and-swap rollback, durable recovery and retry, already-downloaded next/fallback resolution without repeat external calls, pending-asset exclusion from Final Guard, R1/R2/review routes, decisive modern versioning, exact legacy checkpoint resume, same-run legacy-to-modern transition, complete contract invalidation, intentional audited catalog reuse, `/`-anchored component-wise secure current-byte snapshots and ordered bindings, final PNG persistence, and CLI asset decision input.
- No Task 8 requirement remains partial.

## Concerns and follow-up boundaries

- The two live provider tests remain intentionally skipped unless `RUN_LIVE_ASSET_PROVIDER_TESTS=1`; default tests make no network calls as required.
- The default run's warnings are two explicit legacy storyboard fallback warnings plus transient pytest temporary-directory cleanup warnings on this macOS runner.
- `main.py` still owns the pre-existing fixed-six-page export validator. The plan assigns dynamic 5–7 path validation and the new publish artifact exporter to Task 9, so Task 8 deliberately does not implement that later scope.
