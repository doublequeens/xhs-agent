# Task 8 report: v4 authoring and Q1 hard gate

## Status

`DONE_WITH_CONCERNS`

Task 8 is implemented in the seven requested source/test/prompt files. The
implementation remains isolated from v3 and from Task 6/7 source files.

## Requirements mapping

- `direction.py` defines frozen, `extra="forbid"` contracts for
  `CarouselNarrativeV4`, `PageBriefV4`, `PageBriefSetV4`,
  `VisualDirectionPlanV4`, `AssetDirectiveV4`, provider drafts,
  `AuthoringIssueV4`, and `AuthoringQAResultV4`.
- Narrative family values are exactly the six approved families; page counts
  are 5–18; beats and density curves bind to page count.
- Page briefs persist only semantic responsibilities, fragment IDs, density,
  composition candidates, continuity and asset requests. No visible-copy,
  coordinate, pixel-box, HTML, CSS or DOM field is accepted.
- Provider drafts have no source/canonical hash or fragment-text fields.
  `visual_authoring_node` reconstructs canonical hashes and source bindings
  from the revalidated Task 7 semantic model and ContentLock.
- `VisualDirectionPlanV4` embeds the exact revalidated semantic model,
  narrative and page-brief set objects and checks their family, page-count,
  source-hash and canonical-hash bindings.
- The authoring node uses one injected `invoke_structured` call with
  `InvocationRequest(node="visual_authoring", operation_kind="visual_authoring",
  page_ids=("carousel",))`; it owns no retry, timeout, provider or fallback.
- Q0 is recomputed through the Task 7 fresh route before gateway invocation.
  Q1 checks fragment ownership, page/rhythm consistency, family/hash drift,
  repeated signatures/compositions, note priority, asset ownership/alignment,
  and forbidden system copy. `passed` is structurally equivalent to
  `issues == ()`.

## TDD evidence

- RED: the required focused collection initially failed during collection with
  `ModuleNotFoundError` for the not-yet-created v4 direction/authoring modules.
- GREEN focused authoring suite: `16 passed`.
- Focused authoring plus existing v3 Visual Director regression:
  `65 passed`.
- Task 6/7 semantic regression plus gateway suite: `87 passed, 4 warnings`.
- Full offline suite: `1521 passed, 2 skipped, 4 warnings`.

## Verification commands

```text
pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py
16 passed

pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py tests/nodes/test_visual_director.py
65 passed

pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_gateway.py
87 passed, 4 warnings

pytest -q
1521 passed, 2 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

## Self-review

- Confirmed clean starting worktree and only the requested Task 8 files plus
  this report are changed.
- Revalidated a real successful node result: plan nested model identity is
  the same object as the node's semantic/narrative/page-brief outputs, and all
  plan hashes match their nested contracts.
- Confirmed stale Q0 prevents gateway calls, unknown provider fragment IDs
  produce a Q1 fail route, gateway failures propagate after exactly one call,
  and stale Q1 results are rejected by the route helper.
- Shared canonical direction payload/hash helpers are used by all durable
  direction/Q1 contracts; nested provider output is revalidated before use.

## Concerns

- The full suite retains four pre-existing warnings: two serializer warnings
  from Task 7 tampered-model tests and two macOS pytest temporary-directory
  cleanup warnings. No authoring test failed because of them.
- The Q1 evaluator deliberately accepts a `PageBriefSetV4` with an invalid
  `page_count` value so it can emit deterministic `PAGE_COUNT_INVALID` evidence;
  durable plan construction remains bounded to 5–18 pages.

## Fix round 2

### Status

`DONE_WITH_CONCERNS`

The second review round is addressed in the same seven Task8 files. The
candidate preflight and durable Q1 result are now distinct states, and durable
construction is no longer converted into a retryable authoring failure when a
programming invariant breaks.

### Fix mapping

- Replaced free-form beat responsibility with controlled `task_kind`, required
  non-empty `fragment_refs`, optional semantic `group_refs`, and deterministic
  semantic-role compatibility checks. Each page's `fragment_refs` must exactly
  equal its referenced beat's fragments; unknown/missing/mismatched beat and
  group references produce stable Q1 issues.
- Kept `PageBriefSetV4` strict for 5–18 pages, exact length, and continuous
  one-based sequence. Standalone/minimal `evaluate_authoring` calls return the
  internal `AuthoringCandidatePreflightV4` when durable narrative/plan hashes
  are unavailable, while node candidates never become durable until that
  preflight passes.
- Made public `AuthoringQAResultV4` reject passed results with missing hashes,
  candidate hashes, or zero sentinels. Candidate failures carry only a
  non-zero candidate hash and no durable page/plan hashes; the authoring route
  accepts only a hash-complete durable result.
- Narrowed the node's provider/candidate recovery boundary to
  `pydantic.ValidationError`. Gateway failures and all post-preflight durable
  construction exceptions propagate instead of being disguised as retries.
- Updated the provider prompt to describe typed task kinds and exact beat/page
  fragment ownership without permitting visible copy or geometry.

### TDD evidence

RED before implementation: the focused round-2 collection failed because the
new `AuthoringCandidatePreflightV4` seam was not yet implemented. After the
vertical fixes, the focused Task8 suite passed.

### Verification commands

```text
pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py
30 passed

pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py tests/nodes/test_visual_director.py
79 passed

pytest -q tests/nodes/v4/test_semantic.py tests/schemas/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_factory.py tests/visual_ai/test_gateway.py tests/visual_ai/test_gemini_adapter.py tests/visual_ai/test_v4_worker.py
109 passed, 4 warnings

pytest -q
1535 passed, 2 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

### Fix-round self-review and concerns

- `VisualDirectionPlanV4` is still built from the exact revalidated semantic
  model, narrative, and strict page-brief set objects; its embedded objects and
  all canonical/source hashes are checked again by the durable model validator.
- The candidate preflight is an in-memory dataclass with a non-zero canonical
  candidate hash and cannot be serialized as a durable Q1 result. Public pass
  results require all six durable bindings and no candidate hash.
- The full suite remains green. The four warnings are pre-existing Pydantic
  serializer/tampered-model and macOS pytest temporary-directory cleanup
  warnings; no authoring assertion is associated with them.

## Fix round 1

### Status

`DONE_WITH_CONCERNS`

Reviewer findings were addressed without changing Task 6/7, gateway, v3,
graph, publishing, or AgentState files.

### Fix mapping

- Added typed `NarrativeBeatV4`/`beat_ref` and deterministic one-to-one beat
  ownership checks. Durable pages now require a fragment, priority and
  composition; relaxed candidates report `PAGE_BRIEF_DUTY_EMPTY` instead of
  throwing during durable construction.
- Restored strict durable `PageBriefSetV4` bounds, exact length and contiguous
  sequence validation. Added explicit `PageBriefCandidateV4`/
  `PageBriefSetCandidateV4` preflight DTOs; no `model_construct` recovery path
  remains in the authoring implementation.
- Fragment ownership now reports duplicate, missing and unknown IDs together;
  duplicate-only fixtures preserve all fragments and add one duplicate.
- Adjacent composition checks compare only each page's first preferred
  composition; duplicate signatures remain role + first composition + density.
- Removed dimensions from `AssetDirectiveDraftV4`; shared draft/durable
  forbidden-copy validation rejects visible-label requests. Durable assets
  retain the controlled 1080x1440 safety minimum, injected by the application.
- Added controlled asset role/purpose and page-bound
  `supports_fragment_refs` checks, including missing, unknown and cross-page
  findings. Note-only priorities now fail `NOTES_CANNOT_BE_PRIMARY`.
- Node preflights candidates before durable page-set/plan construction and
  returns sanitized failed Q1 evidence plus `visual_authoring` on malformed or
  duty-invalid candidates.

### Fix-round verification

RED before implementation: the focused collection failed in all three Task 8
modules because the new `NarrativeBeatV4` contract was not yet defined.

```text
pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py
24 passed

pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py tests/nodes/test_visual_director.py
72 passed

pytest -q tests/nodes/v4/test_semantic.py tests/schemas/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_factory.py tests/visual_ai/test_gateway.py tests/visual_ai/test_gemini_adapter.py tests/visual_ai/test_v4_worker.py
109 passed, 4 warnings

pytest -q
1529 passed, 2 skipped, 4 warnings

python -m compileall -q src main.py
exit 0

git diff --check
exit 0
```

### Fix-round self-review and concerns

- Canonical payload/hash derivation is centralized in
  `canonical_direction_payload_v4`/`canonical_direction_sha256_v4`; asset
  semantic validation is shared between draft and durable contracts.
- Q1 uses indexed ownership/count checks and one page scan for forbidden copy;
  issue ordering is append-only and deterministic. The node's durable plan
  embeds the same revalidated semantic model, narrative and page-brief set,
  with each hash compared against its nested object.
- Full offline verification is green. Remaining concerns are the same four
  pre-existing serializer/macOS pytest cleanup warnings; no authoring failure
  is associated with them.
