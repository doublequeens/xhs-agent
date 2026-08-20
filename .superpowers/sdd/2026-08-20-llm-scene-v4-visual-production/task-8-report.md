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
