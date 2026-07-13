# Task 4 Report: Local-first asset catalog matching

## Implemented

- Added `src.asset_resolver.catalog` with immutable resolver-facing catalog
  models. Its loader delegates integrity validation to the existing design
  system loader, which accepts only local `active/` production assets and
  verifies provenance, file existence, hashes, dimensions, and uniqueness.
- Added `src.asset_resolver.resolver` with deterministic local exact matching,
  hard eligibility filters, recent-repeat exclusion, semantic ranking,
  least-recently-used ordering, and `asset_id` tie-breaking.
- Added explicit fallback resolution by `AssetRequirement.fallback_asset_ids`.
  Unrelated local files are never treated as fallbacks.
- Kept Task 5 out of scope: configured providers are stored on the catalog for
  the future lifecycle, but Task 4 never calls them or performs network I/O.

## TDD evidence

1. Initial RED command:

   ```text
   /opt/anaconda3/envs/xhs-agent/bin/python -m pytest \
     tests/asset_resolver/test_catalog.py \
     tests/asset_resolver/test_local_resolution.py -q
   ```

   Result: `6 failed`; every failure was the expected
   `ModuleNotFoundError: No module named 'src.asset_resolver'`.

2. The test contract was extended before production code to cover all hard
   filters and deterministic ranking. Re-running RED produced `16 failed` for
   the same missing-module reason.

3. After the minimal implementation, the focused suite produced `16 passed`.

## Verification

- Task 4 focused suite: `16 passed`.
- Task 4 plus Task 2/3 schema, strategy, seeded catalog, and design-system
  regressions: `56 passed`.
- Full repository suite: `809 passed, 3 warnings`.
- The production manifest loads through the new loader as
  `beauty_editorial_v1` with 59 entries.
- `python -m compileall -q src/asset_resolver` and `git diff --check` passed.

The three full-suite warnings are pre-existing LangGraph deprecation and
legacy-checkpoint warnings. Pytest also emitted an environment-level warning
while cleaning an old temporary directory; it did not affect the test result.

## Risks and follow-up

The resolver intentionally enforces the Task 4 minimum-dimension contract as
declared. Task 2's strategy currently requests `1080 x 1440` assets, while the
Task 3 production SVG entries declare `512 x 512`. Consequently, those SVGs
are correctly rejected by strict local resolution. This is an integration
contract decision for a later task: either vector assets need scale-aware
eligibility, or strategy requirements need asset-type-aware minimums. Task 4
does not weaken the hard filter or modify Task 2/3.

There is also a role-taxonomy seam to reconcile later: strategy requirements
use semantic roles such as `beauty_subject` and `face_map`, while the seeded
catalog uses concrete roles such as `face_angle` and `face_zone_mask`. Exact
role matching is required by Task 4, so an explicit mapping or aligned
taxonomy will be needed before end-to-end local resolution can consume the
seeded catalog.
