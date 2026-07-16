# Task 7 report: secure text-only carousels

## Outcome

- `VisualPlan.required_assets=[]` now returns an explicit, auditable empty
  `AssetManifest` without provider calls.
- Runtime asset contracts use `page_archetype`; the persisted catalog key remains
  `allowed_layouts`.
- Pending asset and audit records use `page_archetype`. The lifecycle audit reader
  alone accepts and maps historical `layout` values.
- Renderer, Render QA, and Final Guard accept exact empty slot sets and reject
  missing, extra, or duplicate manifest slots.
- Declared slots retain exact role, page-archetype, local-path, byte-hash, geometry,
  provenance, approval, and catalog-eligibility checks.
- Render QA R1 recovery now carries the authoritative narrative plan and uses
  `selected_narrative_plan` only to recover an invalid package copy.
- The checked-in asset catalog keeps the `allowed_layouts` key but stores semantic
  page-archetype values.

## TDD and review findings

- Added empty-manifest and no-provider coverage in local resolution.
- Added renderer coverage for empty slot sets, missing/extra slots, role mismatch,
  and page-archetype mismatch.
- Added Render QA and Final Guard text-only acceptance plus exact slot-set coverage.
- Controller review found and fixed one important omission: renderer slot binding
  previously checked the slot ID and page archetype but not the declared role.
- External subagent re-review remained unavailable because the local Codex account
  usage limit was already exhausted; the controller reviewed the complete Task 7
  diff directly.

## Verification

- Required focused Task 7 suite:
  `357 passed in 9.86s`
- Full asset-resolver suite:
  `213 passed, 2 skipped in 4.33s`
- Renderer suite after role-binding regression:
  `26 passed in 0.74s`
- `python -m compileall -q src main.py`: passed
- `git diff --check`: passed
- Checked-in asset catalog parses as valid JSON and contains only semantic
  `allowed_layouts` values.

Legacy layout renderer/probe tests remain intentionally deferred to Tasks 8 and 9,
which replace the temporary archetype-to-v1-renderer bridge with the six production
template families.
