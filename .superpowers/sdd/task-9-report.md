# Task 9 Implementation Report

## Outcome

Implemented the content-locked final publishing package and manual Codex visual-rescue prompt. The final exporter writes `publish-copy.txt`, `codex-image-regeneration-prompt.txt`, and `<title>.json` while preserving approved renderer output. Follow-up hardening extracted Final Guard's existing semantics into a shared pure validator so graph execution and completed-state export enforce the same deep policy without duplicating it; Task 10 and legacy behavior remain out of scope.

## TDD Evidence

### RED

Command:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/publishing/test_artifacts.py tests/test_main.py tests/integration/test_beauty_account_workflow.py -q
```

Observed failure before production implementation:

```text
ModuleNotFoundError: No module named 'src.publishing'
1 error during collection
```

This was the expected Task 9 seam: the publishing module and deep artifact exporter did not exist.

### GREEN

Focused Task 9 suite:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/publishing/test_artifacts.py tests/test_main.py tests/integration/test_beauty_account_workflow.py -q
```

Result: `97 passed`.

Full repository suite:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Result: `1243 passed, 2 skipped`. The skipped tests are the existing opt-in live Pexels/Unsplash tests. Existing LangGraph pending-deprecation and legacy-checkpoint warnings remain.

Static verification:

- `/opt/anaconda3/envs/xhs-agent/bin/python -m compileall -q src main.py` passed.
- `git diff --check` passed.
- Ruff and Mypy are not installed in the project environment, so no Ruff/Mypy result is claimed.

## ContentLock Coverage

`build_content_lock` locks, in canonical order:

- `focus_keyword`
- `topic`
- `topic_id`
- `angle`
- `angle_id`
- `target_group`
- `core_pain`
- `title`
- `cover_copy`
- `first_screen_promise`
- `content`
- `hashtags`
- the complete validated `storyboards`

`first_screen_promise` is taken only from a fully validated `ContentContract`; missing locked fields are rejected rather than synthesized. Canonical bytes use UTF-8 JSON with `sort_keys=True` and compact separators, so top-level and nested dict insertion order do not affect the hash.

Tests prove the hash changes for every locked top-level value, the contract promise, and each visible storyboard text location: headline, kicker, block heading, block body, block item, emphasis, and footer. The assembler deterministically propagates the CLI/state `focus_keyword`, including the allowed empty-string case.

## Rescue Prompt and Manual-Only Boundary

- The template is byte-for-byte identical to the complete template in `.superpowers/sdd/task-9-brief.md`; verified with a direct `diff` against the brief code block.
- The prompt embeds only the current canonical ContentLock, its SHA-256, the current frame text table, current package paths, and exactly three approved `reference_only` anchors.
- The three production anchors are loaded from the reference manifest and checked for `usage`, path containment, existence, and SHA-256.
- Unrelated package notes, golden fixture names, and the example title do not enter the prompt.
- Prompt generation is a pure local text operation. A test makes any `requests.post` call fail, proving this path does not call an image API.

## Atomic Export and Failure Tests

Each support artifact is first written to a sibling temporary file, flushed, `fsync`ed, closed, and then installed with `os.replace`. The package directory is also `fsync`ed. Re-export backs up existing support files and restores them if replacement fails.

Failure coverage includes:

- failure on the second replacement of a first export: no partial support files remain;
- failure during replacement of an existing export: prior support files are restored;
- in both cases, all Render-QA-approved page PNGs and the manifest-listed contact sheet remain byte-for-byte unchanged;
- temporary and backup support files are cleaned up.

The audit JSON contains the serialized `content_lock`, `visual_plan`, `asset_manifest`, and `render_manifest`, plus package-relative ordered page paths.

## Main Export Validation

`main.py` no longer imports or validates the legacy fixed-six `output_paths`. It validates the 5–7 ordered `RenderManifest.pages`, requires the publish-package paths to preserve that order, requires every page to be a readable PNG in one package `images/` directory, and rejects any PNG not listed by the manifest.

`contact-sheet.png` is accepted only as the separately listed `RenderManifest.contact_sheet_path`; any additional PNG is rejected as unlisted. After validation, `main.py` delegates artifact creation to `src.publishing.artifacts.export_publish_package`. Terminal graph export injects the state-level visual, asset, and render manifests without mutating the graph's publish package.

## Self-Review

### Standards axis

- New publishing responsibilities are isolated behind one module and a small immutable result type.
- Main remains the path/profile safety boundary and delegates serialization/write details.
- No duplicate fixed-six naming logic remains in main.
- No unrelated refactor or workflow/QA/legacy modification was introduced.
- No Golden/Task 10 fixture or behavior was added.

### Spec axis

- All Task 9 public functions are implemented and exported.
- Publish copy format is exact UTF-8/LF pasteable text.
- ContentLock covers every required field and all storyboard content.
- The rescue prompt is exact, current-package-only, three-anchor, and manual-only.
- Export is sibling-temp, `fsync`, atomic-replace, rollback tested, and image-preserving.
- Main accepts dynamic 5- and 7-page manifests and rejects ordering/path/unlisted-PNG violations.
- Audit JSON contains all four required manifests/locks and relative page paths.

### Concerns

No blocking concerns. As with any filesystem transaction, recovery from a persistent filesystem failure that also prevents rollback cannot be guaranteed; the implemented rollback covers ordinary staged-write and atomic-replace failures and is exercised for both first export and re-export. Live stock-provider tests remain intentionally skipped and are unrelated to this manual-only local exporter.

## Review Closure (2026-07-14)

The independent Task 9 review initially rejected the change with seven Important and four Minor findings. This follow-up closes A-H without changing Task 10, the complete rescue template, the current-package-only rule, the three reference anchors, or the manual/no-API boundary.

### Additional RED evidence

Five RED batches were observed before their corresponding production changes:

- Initial authorization/snapshot/filesystem/transaction/focus/title suite: `43 failed, 132 passed`.
- Canonical path, read-time replacement, and exact-list authorization follow-up: `3 failed, 8 passed`.
- Legacy different-title audit migration: `1 failed`.
- Independent-review fixes for restore failure, terminal retry generation, and symlinked ancestors: `3 failed`.
- Final package-directory rebinding review: `1 failed`.

The failures were the expected missing behaviors: no explicit export authorization, repeated live-dict reads, signature-only image checks, no generation CAS, unsafe rollback cleanup, absent CLI-keyword authority, weak title/path rules, non-transactional legacy cleanup, and the three independent-review gaps.

### A-H closure

- **A — immutable snapshot:** public export detaches and deep-freezes one package snapshot at entry. ContentLock, publish copy, rescue prompt, audit, authorization, and manifests derive only from that snapshot. A test mutates the caller's live dict during anchor loading and proves every output remains on the frozen version.
- **B — publishability at the boundary:** one shared validator requires an explicit completed authorization, `review_status == "approved"`, an actual empty list for `final_policy_issues`, passed Carousel QA, passed Render QA, no pending assets, and authoritative focus-keyword binding. Both main and the public artifact exporter apply it.
- **C — secure final-image snapshot:** page and contact paths must be canonical absolute paths without dot-dot or symlinked components. Package/image directories and files are opened through anchored descriptors with no-follow checks and binding revalidation, including a final package-root inode check before returning pathname-based results. Files must be regular, single-link, inode-distinct PNGs; Pillow fully decodes them; page dimensions are 1080 x 1440; current hashes must match RenderManifest; contact must be the distinct fixed `contact-sheet.png`. Tamper, replacement-during-read, package-directory rebinding, fake PNG, wrong size, symlink, hardlink, alias, and unlisted PNG cases fail closed.
- **D — lock/version/CAS:** a hardened package lock is flocked and inode-revalidated. A durable version file records generation, audit filename, and ContentLock hash. Every export uses compare-and-swap; terminal checkpoint retries read the current generation under the same hardened lock. Concurrent first exports produce exactly one winner and never a mixed package.
- **E — rollback safety:** all support artifacts and the version marker participate in one transaction. Existing files become retained backups until commit and directory fsync complete. Restore failure removes the newly committed destination, preserves the only old backup, and raises an error containing recovery paths. Post-commit cleanup failure has an explicit `committed = True` exception and never pretends rollback succeeded.
- **F — focus-keyword authority:** `focus_keyword_cli_present` is persisted from CLI parsing through state and assembler metadata. Explicit empty CLI values are rejected; an explicit keyword cannot be cleared or changed at export. Human edits to the keyword or presence flag invalidate visual/render artifacts and route through R2; assembler reasserts the state-authoritative value.
- **G — title and portable audit:** titles must be a single safe component and reject slash, backslash, NUL, CR/LF, controls, dot, and dot-dot. Title-changing re-export is rejected, including a different pre-version legacy audit, so exactly one non-hidden audit JSON remains. Package-owned paths in top-level fields and nested render/asset manifests are package-relative.
- **H — legacy cleanup:** obsolete prompt removal is part of the same backup/commit/rollback transaction. Failed export restores it; successful backup deletion is followed by directory fsync; cleanup failure reports committed state explicitly.

### Final GREEN evidence

Focused Task 9 plus metadata/human-review integration suite:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/publishing/test_artifacts.py tests/test_main.py tests/nodes/test_metadata_flow.py tests/nodes/test_domain_nodes.py tests/integration/test_beauty_account_workflow.py -q
```

Result: `187 passed`.

Fresh full repository suite:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Result: `1290 passed, 2 skipped`. The two skips remain the opt-in live stock-provider tests. The three warnings are the existing LangGraph pending-deprecation warning and two legacy storyboard fallback warnings.

## Second Review Closure: Completed-State Authorization and Transaction Binding

The follow-up review found that the package could still self-report authorization and generation, and that the package-local lock/root checks left commit-time rebinding gaps. This round replaces those boundaries rather than adding another package flag.

### RED evidence

The new authorization regression was verified against a temporary restoration of the former raw-package branch:

```bash
python -m pytest tests/publishing/test_artifacts.py::test_final_export_rejects_raw_self_authorized_package -q
```

Observed result: `1 failed`, with `Failed: DID NOT RAISE TypeError`. The temporary old-behavior branch was then removed. The same test passes against the completed-state-only implementation.

The first run of the new attestation test also failed because the fixture's render probe did not bind every current storyboard-visible field. The fixture was corrected to exercise the real shared Final Guard rather than weakening validation.

### Authorization and attestation

- Public final export now accepts only a terminal graph state with `next == ()`; a raw package dict is rejected even when it carries a forged `publish_authorization`.
- One detached state snapshot is taken at entry. State-level `visual_plan`, `asset_manifest`, and `render_manifest` replace any package copies, while package-provided authorization, attestation, and expected generation fields are discarded.
- `validate_final_policy(state)` is the single pure policy/deep-artifact validator. The graph node and exporter both call it; a parity test proves the node returns the exact pure-validator issue list.
- Review approval, passed Carousel QA, passed Render QA, authoritative focus-keyword binding, and zero recomputed Final Guard issues are required from the current snapshot. A storyboard rewrite after stale QA is rejected by the recomputed visible-text binding.
- `PublishAttestation` is generated only as an export result and recorded in the audit. It binds canonical package, visual plan, asset manifest, render manifest, both QA results, ContentLock, rendered page/contact hashes, publish-copy bytes, and rescue-prompt bytes under one canonical digest. Any package-supplied attestation is ignored.

### Generation, lock, and commit-time revalidation

- High-level terminal retry never reads `publish_package.expected_artifact_generation`. It reads the durable current generation while holding the export lock, so two exports of the same terminal checkpoint produce generations 1 then 2. The private low-level writer retains an explicit expected-generation option for CAS testing.
- The lock is now a sibling in the trusted package parent, opened with no-follow checks and verified as a regular single-link inode before and after `flock` and throughout the transaction.
- The package-root and lock pathname/inode bindings are rechecked before every staged replacement and before backup cleanup. Rendered pages and the contact sheet are securely reopened and re-attested at those commit points and again before return.
- A lock unlink/recreate during the second export fails closed without changing the prior support files. A package-root rebind while backups exist rolls back the displaced root, leaves the replacement root without support artifacts, and preserves the legacy prompt.
- Unix `flock` is advisory: these checks coordinate cooperating exporters and detect observed same-uid pathname replacement, but cannot prevent a non-cooperating same-uid process from mutating files after the final verification.

### Rollback and input hardening

- First-export rollback handles every `OSError` per destination, continues best-effort cleanup and directory fsync, and raises `ArtifactRollbackError` with every path whose recovery action failed. A targeted test forces one destination unlink failure and proves the remaining support artifacts are still cleaned.
- Titles beginning with `.` are rejected. The standalone rescue-prompt builder now reuses the same title-component validator, and reference paths containing CR, LF, or NUL are rejected before template interpolation.

### Final verification

Focused publishing, main, Final Guard, metadata, domain, and beauty-workflow suite:

```bash
python -m pytest tests/publishing/test_artifacts.py tests/test_main.py tests/nodes/test_final_policy_guard.py tests/nodes/test_metadata_flow.py tests/nodes/test_domain_nodes.py tests/integration/test_beauty_account_workflow.py -q
```

Result: `265 passed`.

Fresh full repository suite:

```bash
python -m pytest -q
```

Result: `1297 passed, 2 skipped`. The skips are still the opt-in live stock-provider tests. The four warnings are two existing legacy-storyboard warnings plus pytest temporary-directory cleanup warnings outside Task 9.

Static checks:

- `python -m compileall -q src main.py tests/publishing/test_artifacts.py tests/nodes/test_final_policy_guard.py tests/test_main.py` passed.
- `git diff --check` passed.
- Ruff is not installed in the active environment, so no Ruff result is claimed.

### Independent re-review closure

The independent reviewer found two final commit-window gaps and one return-attestation gap. Targeted RED tests reproduced all three before the fixes:

- replacing the entire publish parent escaped the package-relative root/lock checks;
- rebinding after commit fsync but immediately before the first backup cleanup produced `ArtifactCleanupError` instead of rollback;
- tampering a committed support file after the transaction was not detected before return.

The export lock now stores and continuously verifies the parent pathname inode. Commit and pre-cleanup verification both run while all backups remain available inside the rollback scope. After transaction completion, every committed support payload is securely reopened through the package descriptor and compared byte-for-byte with its expected payload before returning.

The three exact regressions pass, the focused/full results above include them, and the independent re-review concluded: `Ready: Yes`.
