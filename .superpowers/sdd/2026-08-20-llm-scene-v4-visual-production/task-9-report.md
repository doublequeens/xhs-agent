# Task 9 report: candidate/revision artifact identity and v4 asset resolution

## Status

`DONE_WITH_CONCERNS`

Task 9 is implemented in the four requested source modules, four requested
test modules, and this report.  v3 resolver callers remain on the existing
`transaction_root + transaction_id` path; v4 uses an explicit validated
`asset_root` transaction directory under the run/candidate/revision identity.

## Requirements mapping

- `src/visual_runtime/artifact_identity.py` adds strict frozen
  `ArtifactIdentity`, exact `run_id/candidate_id/revision_id` path derivation,
  lexical and resolved containment checks, no-follow ancestor checks, secure
  path establishment, and immutable `ArtifactBinding` reuse.  Identity
  components are rejected rather than sanitized when empty, traversal-like,
  absolute, control-bearing, non-ASCII, or separator-bearing.
- Reused artifacts are read through `lstat` + `O_NOFOLLOW` + descriptor
  identity checks, verified against the declared byte SHA-256, written through
  an exclusive temporary file with fsync and an atomic no-overwrite hard-link
  publication, followed by parent-directory fsync.  Source bytes are not
  changed; symlink, source-swap, destination-escape, and existing-target
  cases fail closed.
- `src/asset_resolver/v4.py` revalidates `AssetDirectiveV4` and maps only the
  approved provider fields to the existing `AssetDirective`.  Controlled
  composite source strategies become an explicit preferred/fallback pair;
  `purpose` and `supports_fragment_refs` never enter provider requests.
- `src/asset_resolver/resolver.py` keeps the v3 API/default behavior while
  adding mutually exclusive complete `artifact_paths` mode; bare
  `transaction_directory` input is rejected.  Explicit v4 directories
  receive no-follow/containment checks and immutable destination writes.
  Existing provider identity, licensing, allowlists, dimensions, orientation,
  safety checks, journal preservation, pending human review, and byte-hash
  semantics remain in the shared path.
- `src/nodes/v4/assets.py` recomputes the Task 8 Q1 route before identity,
  filesystem, or provider work; stale/missing/failed Q1 returns
  `visual_authoring`.  A passed plan is revalidated, bound to a strict
  `ArtifactIdentity`, established under the default
  `data/asset_transactions` root (or an injected non-publish root), resolved
  once, and returned with immutable manifest/evidence/path objects and the
  `composition_planning` route.  Required failures retain
  `VisualProductionInterrupted` recovery evidence; optional failures remain
  unresolved and are never fabricated as approved.
- `test_live_providers.py` gates imports/provider construction behind
  `RUN_LIVE_ASSET_PROVIDER_TESTS=1` and credentials.  The default suite made
  no network calls.

## TDD evidence

RED before production implementation:

```text
pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/nodes/v4/test_assets.py
2 collection errors: ModuleNotFoundError for the not-yet-created artifact identity and v4 resolver modules
```

GREEN focused tests after implementation:

```text
pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/nodes/v4/test_assets.py
22 passed
```

## Verification commands

```text
pytest -q tests/asset_resolver tests/nodes/test_asset_resolver.py tests/nodes/v4/test_assets.py tests/visual_runtime/test_artifact_identity.py
33 passed, 1 skipped

pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py
30 passed

pytest -q
1558 passed, 3 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

The three live skips are the new provider smoke and the existing live Gemini
smokes.  The four warnings are the existing two Pydantic tampered-model
serializer warnings and two macOS pytest temporary-directory cleanup
warnings.

## Self-review

- Confirmed stale Q1 returns before the injected provider is touched and
  leaves the injected artifact root empty.
- Confirmed a real passed Task 8 plan resolves one generated asset once,
  records `run-1/revision-1`, stores it below
  `run-1/candidate-1/revision-1/assets`, and returns `approved` plus
  `human_decision=pending`.
- Confirmed required and optional provider failures preserve the v4 journal
  or unresolved entry respectively, and an empty directive set does not call
  either provider.
- Confirmed v3 directive-resolution and node tests remain green, and no
  graph, schema, AgentState, publishing, output, or data files were changed.
- Confirmed no credentials, provider raw responses, or provider-visible v4
  authoring-only fields are copied into the adapter request.

## Concerns

- Runtime manifests retain the existing absolute `local_path` handle needed
  by renderer consumers; it is not provider-visible prompt data or AI
  provenance, and transaction evidence is emitted only from the validated
  identity-bound lease.
- The full offline suite retains four unrelated warnings described above;
  none is associated with Task 9 assertions.

## Fix round 1: security review closure

### Status

`DONE_WITH_CONCERNS` — the seven Important findings are addressed in the
Task 9 files.  The remaining concerns are limited to intentionally skipped
external smoke tests and pre-existing warning output.

### Review finding mapping

- Bare explicit-directory mode is rejected by both the shared resolver and
  the v4 wrapper.  Explicit resolution accepts only a revalidated
  `ArtifactPaths`, reconstructs the exact identity-derived path, checks the
  trusted base identity, and binds run/revision evidence to that identity;
  the candidate remains in the established path boundary.
- `artifact_identity.py` now owns the shared descriptor-relative primitives:
  trusted ancestor traversal, `O_DIRECTORY|O_NOFOLLOW` open/mkdir, pinned
  lease identity checks, descriptor-relative reads/publication, and staging
  cleanup.  Source, destination, staging, journal, and final publication do
  not use a path check followed by an unrelated path write.
- Every descriptor owner is cleared before its one close attempt.  Close
  errors are aggregated as cleanup facts without retrying or reusing a
  numeric fd; required failures preserve the primary
  `VisualProductionInterrupted` error.
- Legacy transaction IDs are validated before root creation and established
  through a trusted root dirfd; `../escaped`, separators, control,
  non-ASCII, and dot components have zero side effects.
- Atomic publication converts write/fsync/link/unlink/parent-fsync/close
  failures to `AssetResolutionError`; required failures retain the recovery
  journal path or chain journal failure as the cause without masking the
  directive's primary errors.
- Generated providers receive an exclusive `.staging-*` directory only.
  Resolver-owned final names are published no-overwrite, then safety-checked
  and descriptor-reread for final inode/size/hash equality before manifest
  construction.  Provider/safety mutation and final-collision regressions
  are covered.
- Composite v4 sources expand deterministically to
  `search->generate` or `generate->search`; conflicting explicit fallbacks
  are rejected as ambiguous.

### RED-GREEN and attack coverage

The fix-round attack tests cover bare-directory rejection, identity/evidence
drift, symlink source/ancestor and destination escape, source SHA mismatch,
existing target preservation, close-failure fd non-reuse, legacy traversal
zero-side-effect behavior, journal close failure with primary-error
preservation, staging-only generation, safety mutation, final collision,
empty directives, immutable approved/pending status, optional unresolved
assets, and composite source pairs.  The original focused suite was RED on
the bare API/close/staging/mutation regressions before the implementation;
the fresh focused run is GREEN.

### Fresh verification

```text
pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/nodes/v4/test_assets.py
36 passed, 2 warnings

pytest -q tests/asset_resolver tests/nodes/test_asset_resolver.py tests/nodes/v4/test_assets.py tests/visual_runtime/test_artifact_identity.py
46 passed, 1 skipped, 2 warnings

pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py tests/visual_ai/test_v4_worker.py
47 passed, 2 warnings

pytest -q
1571 passed, 3 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

The three skips are the opt-in Pexels/Unsplash smoke and two existing Gemini
smokes; no live provider or network path was constructed by the default suite.
The four warnings are the existing two Pydantic tampered-model warnings and
two macOS pytest temporary-directory cleanup warnings.

### Self-review and concerns

- The legacy/v4 split occurs only while constructing the pinned transaction
  handle; search, generation, final publication, safety reread, journal, and
  evidence all share the same resolver path.
- The descriptor helper audit found no repeated fd ownership: leases and
  temporary/file descriptors are set to `None` before close, including close
  exceptions, and no close path uses a previously failed numeric descriptor.
- Manifest hashes are reread from the resolver-owned final bytes.  Absolute
  local paths remain runtime-internal resolution handles required by the
  existing renderer contract; no provider credentials, raw responses, or
  local paths are copied into provider-visible prompts or AI provenance.
- External live smoke remains intentionally unrun because the gate was not
  enabled; this is not an offline-test failure.

## Fix round 2: independent security review closure

### Status

`DONE_WITH_CONCERNS` — all five Important findings are addressed in the
Task 9 source and test files.  Live provider calls remain intentionally
skipped; the remaining test warnings are pre-existing macOS/Pydantic output.

### Finding mapping

- Safety validation now prefers a narrow `check_bytes` contract.  The default
  checker verifies the resolver's immutable snapshot bytes, never reopening a
  validated pathname.  Existing `check(path, directive)` checkers are adapted
  through `_open_file_at` and a duplicated `/proc/self/fd` or `/dev/fd` path
  held only while the checker runs; final descriptor-relative reread still
  verifies inode, size, and hash after the check.  The ancestor-swap test
  proves a legacy checker cannot observe the outside replacement bytes.
- `_read_file_at` captures the body/regular-file/read primary before closing
  the owned fd, transfers ownership to `None`, and records close failure as a
  note on that primary.  Close attempts do not retry or reuse a numeric fd;
  the regression injects a read failure plus close failure and preserves the
  read exception as the cause.
- Canonicalization accepts only the actual macOS `/var -> /private/var`
  system alias, then performs all no-follow checks on `/private/var`.  Other
  symlinked roots remain rejected; the platform-conditional regression covers
  both behaviors.
- `_atomic_write_at` now has an explicit descriptor-relative
  `replace_existing` mode.  Only legacy `transaction_root + transaction_id`
  resolution enables it, preserving v3 reentry and recovery-journal updates;
  explicit v4 `ArtifactPaths` retains exclusive no-overwrite publication.  A
  same-transaction legacy run succeeds twice even with an existing journal,
  while the v4 collision regression remains fail-closed.
- Generated provider outputs are normalized by `_validated_generated_image`
  before any metadata attribute is used.  Path, lowercase SHA-256 fields,
  provider/model, MIME, timestamp, and exact internal provenance are checked;
  malformed `None`, non-string, and provenance results become
  `AssetResolutionError`, enter the required recovery journal, and surface as
  `VisualProductionInterrupted` rather than raw `AttributeError`/`TypeError`.

### RED-GREEN evidence

The new attack regressions were run before the round-2 implementation:

```text
pytest -q tests/visual_runtime/test_artifact_identity.py::test_read_primary_error_survives_file_close_error tests/nodes/v4/test_assets.py::test_safety_checker_legacy_path_adapter_reads_pinned_bytes_during_ancestor_swap tests/nodes/v4/test_assets.py::test_malformed_generated_image_is_normalized_to_required_vpi_with_journal tests/asset_resolver/test_v4_resolution.py::test_legacy_transaction_reentry_replaces_final_after_existing_journal
6 failed, 2 passed
```

After the shared primitive, safety adapter, legacy mode, and metadata
validator changes:

```text
pytest -q tests/visual_runtime/test_artifact_identity.py::test_read_primary_error_survives_file_close_error tests/nodes/v4/test_assets.py::test_safety_checker_legacy_path_adapter_reads_pinned_bytes_during_ancestor_swap tests/nodes/v4/test_assets.py::test_malformed_generated_image_is_normalized_to_required_vpi_with_journal tests/asset_resolver/test_v4_resolution.py::test_legacy_transaction_reentry_replaces_final_after_existing_journal
8 passed, 2 warnings
```

### Verification

```text
pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/asset_resolver/test_live_providers.py tests/nodes/v4/test_assets.py
45 passed, 1 skipped, 2 warnings

pytest -q tests/asset_resolver tests/nodes/test_asset_resolver.py
23 passed, 1 skipped, 2 warnings

pytest -q tests/nodes/v4/test_authoring.py tests/nodes/v4/test_content.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_authoring_qa.py tests/schemas/v4/test_direction.py
55 passed, 1 warning

pytest -q
1580 passed, 3 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

### Self-review and concerns

- Legacy/v4 behavior still branches only at transaction-handle mode selection;
  source selection, staging, descriptor reads, safety, final publication,
  journal, and evidence use the shared resolver path.  The v4 flag cannot be
  accidentally enabled by passing a bare directory.
- Every new fd has one owner: the pinned file fd, checker duplicate, temp fd,
  and transient directory fds are set to `None` before their only close.  A
  close error is attached to the active primary and never causes a numeric fd
  retry.
- The default resolver safety path does not call the compatibility
  `DefaultAssetSafetyChecker.check(Path, ...)`; it calls `check_bytes`.  The
  compatibility method remains for direct legacy callers, while external
  resolver checkers receive only immutable bytes or a pinned descriptor path.
- Full offline verification has three opt-in live skips and four existing
  warnings; no network/provider construction occurred with the live flag
  unset.  No data, outputs, schemas, graph, publishing, or AgentState files
  were changed.

## Fix round 3: provenance binding and v3 compatibility

### Status

`DONE_WITH_CONCERNS` — the two Important provenance findings and the two
low-risk review minors are addressed in the Task 9 files.  Live provider
smokes remain opt-in and were not enabled.

### Finding mapping

- `_validated_generated_image` now receives an explicit
  `strict_provenance` mode.  The resolver sets it only from
  `artifact_paths is not None`, so v4 cannot accidentally inherit legacy
  permissiveness from metadata contents.  Strict v4 timestamps must parse as
  aware ISO-8601 datetimes; naive, empty, and malformed values fail closed.
- In strict v4 mode, `prompt_sha256` must equal the current
  `ImageGenerationRequest.prompt_sha256`, while `response_sha256` and the
  provider `sha256` must equal the SHA-256 of the resolver's pinned staging
  bytes.  The exact internal provenance map is checked before final
  publication/manifest approval.
- Legacy v3 retains its frozen `GeneratedImage` defaults: empty
  `prompt_sha256`, `response_sha256`, and `generated_at` are accepted.  It
  still validates path/MIME/provider/model, requires a valid declared
  `sha256`, and compares that digest to the pinned staging bytes.  A repeated
  legacy resolution with default-empty provenance remains successful.
- Metadata property access now catches `Exception`, preserving cancellation,
  `KeyboardInterrupt`, and `SystemExit` semantics.  `_descriptor_path` now
  documents that its fd-backed pathname is synchronous-call-only and must not
  be retained or used after fd ownership closes.

### RED-GREEN evidence

The new v4 provenance and v3 compatibility tests were run before the round-3
implementation:

```text
pytest -q tests/nodes/v4/test_assets.py::test_v4_generated_provenance_binding_failure_is_required_vpi_with_journal tests/asset_resolver/test_v4_resolution.py::test_legacy_generated_image_accepts_default_empty_provenance_on_reentry
5 failed
```

After explicit mode propagation, aware timestamp validation, request/staging
hash binding, and legacy default handling:

```text
pytest -q tests/nodes/v4/test_assets.py::test_v4_generated_provenance_binding_failure_is_required_vpi_with_journal tests/asset_resolver/test_v4_resolution.py::test_legacy_generated_image_accepts_default_empty_provenance_on_reentry
5 passed, 2 warnings
```

### Verification

```text
pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/asset_resolver/test_live_providers.py tests/nodes/v4/test_assets.py tests/asset_resolver tests/nodes/test_asset_resolver.py tests/nodes/v4/test_authoring.py tests/nodes/v4/test_content.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_authoring_qa.py tests/schemas/v4/test_direction.py
115 passed, 1 skipped, 3 warnings

pytest -q --disable-warnings
1585 passed, 3 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

### Self-review and concerns

- Strictness is an explicit resolver-mode argument threaded through the shared
  generation path; it is not inferred from field emptiness or provider names.
- Provenance checks happen before resolver-owned final publication and before
  any approved manifest item is built.  Required failures therefore retain the
  existing journal/VPI path; optional failures remain unresolved.
- The only remaining concerns are the intentionally disabled live provider
  calls and the existing macOS temporary-directory/Pydantic warnings.
