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
  adding mutually exclusive `transaction_directory` mode.  Explicit v4
  directories receive no-follow/containment checks and immutable destination
  writes.  Existing provider identity, licensing, allowlists, dimensions,
  orientation, safety checks, journal preservation, pending human review, and
  byte-hash semantics remain in the shared path.
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

- The shared resolver's explicit directory API still accepts the caller's
  `transaction_id` as a required evidence label; the v4 node binds it to the
  `ArtifactIdentity.revision_id` and passes the validated `asset_root`, while
  direct callers should use `artifact_paths`/the v4 wrapper when they need the
  stronger identity cross-check.
- The full offline suite retains four unrelated warnings described above;
  none is associated with Task 9 assertions.
