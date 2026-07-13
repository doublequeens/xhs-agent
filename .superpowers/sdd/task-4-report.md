# Task 4 Report: Local-first asset catalog matching

## Implemented

- Added `src.asset_resolver.catalog` with immutable resolver-facing models.
  Loading delegates to the existing design-system integrity validator and
  preserves production provenance plus `fallback_roles` metadata.
- Added deterministic local exact matching with hard role/layout, dimensions,
  orientation/crop, disabled-context, production-use, provenance, and recent-
  repeat filters. Ranking uses tag overlap, orientation, palette compatibility,
  least-recently-used metadata, and stable `asset_id` tie-breaking.
- Resolution resolves both paths and rejects entries outside `active/` before
  reading or hashing their bytes, then checks the current file sha256. A
  manually constructed catalog or post-load file mutation cannot bypass
  integrity validation or cause an out-of-catalog read.
- Defined fallback as a dual explicit contract: the visual requirement must
  name the exact fallback asset ID, and a production entry for the required
  role must declare the fallback asset's role in `fallback_roles`. The fallback
  must still pass layout, dimensions, orientation, context, provenance, recent-
  repeat, and production-use filters. The declaration entry must independently
  pass production provenance, active-root containment, and current sha256
  integrity; its dimensions do not authorize or disqualify metadata. Unrelated
  files remain ineligible.
- Preserved the exact Task 2 semantic recipes and `FramePlanItem.asset_roles`
  vocabulary (`beauty_subject`, `product_texture`, `face_map`, `comparison`,
  `reference`, and `process`). `_required_assets` is the only adapter seam: it
  maps `(layout, semantic_role)` to a concrete catalog role, dimensions,
  orientation, and explicit fallback IDs. Base and repeated-signature
  alternative recipes for all five content jobs resolve the real 59-entry
  catalog locally without provider calls, while alternatives retain their
  original semantic role when only the layout changes.
- Kept Task 5 out of scope: providers can be attached to the catalog for the
  future lifecycle, but Task 4 never calls them or performs network I/O.

## Production requirement contract

The semantic frame plan remains unchanged from Task 2. The private requirement
adapter requests the dimensions declared by the concrete production asset
family instead of applying a canvas-sized raster rule to every asset:

- `background_token`: `1080 x 1440`, portrait.
- `line_token`: `1080 x 300`, landscape.
- `serum_texture`, `face_angle`, `face_zone_mask`, `skin_detail`,
  `container_shape`, and `pump_shape`: `512 x 512`, square.

The `512 x 512` SVG entries remain subject to strict minimum-dimension and
orientation filters; the resolver was not weakened. Only
`VisualPlan.required_assets[*].role` uses the concrete catalog vocabulary;
`RECIPES` and `FramePlanItem.asset_roles` remain semantic.

Only three current production requirement/layout pairs have technically valid
manifest-declared fallbacks, so only these receive fallback IDs:

- `serum_texture` / `texture_baseline` -> `liquid_drips`.
- `face_angle` / `front_face_zone` -> `mask_chin`.
- `face_zone_mask` / `three_quarter_face_zone` -> `face_front`.

No fallback is fabricated for background, line, skin-detail, container, or
pump requirements because their manifest-declared fallback roles do not share
the required layout and/or dimensions/orientation.

## TDD evidence

1. Initial RED: `6 failed`, all expected missing `src.asset_resolver` modules.
2. Expanded hard-filter/ranking RED: `16 failed` for the same missing modules;
   the minimal implementation then produced `16 passed`.
3. Runtime-integrity review RED: `2 failed, 12 passed`, proving outside-
   `active/` files and stale hashes were incorrectly accepted. After the fix,
   both cases pass.
4. Real-contract RED: `17 failed, 16 passed`, showing missing fallback metadata
   and zero eligible real-catalog candidates for production plans.
5. Fallback-declaration RED: `1 failed, 14 passed`, proving an explicit ID alone
   could bypass manifest role declarations.
6. Reference-declaration RED: `1 failed`, proving a reference-only entry could
   declare a production fallback before the production-use guard was added.
7. Final Task 4 plus strategy suite: `52 passed`.
8. Final-review RED: `10 failed, 33 passed`, proving the Task 2 recipes and
   alternative frame roles had been changed to catalog vocabulary, an outside-
   active path was read before rejection, and off-active, stale-hash, or
   incomplete-provenance primary declarations could authorize a fallback.
9. Final-review focused GREEN: `43 passed` after restoring the semantic recipe
   boundary and tightening resolver integrity and fallback authorization.

## Verification

- Task 4 plus strategy suite: `60 passed`.
- Task 4 plus Task 2/3 schema, strategy, seeded-catalog, and design-system
  regressions: `86 passed`.
- Full repository suite: `839 passed, 3 warnings`.
- Real-manifest integration covers every content job in both base and repeated-
  signature modes, plus all three valid production fallbacks, with zero fake-
  provider calls.
- `python -m compileall`, real-manifest loading, and `git diff --check` passed.

The three full-suite warnings are pre-existing LangGraph deprecation and
legacy-checkpoint warnings. Pytest also emitted an environment-level warning
while cleaning an old temporary directory; it did not affect the test result.
