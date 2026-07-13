# Task 7 implementation report

## Outcome

Task 7 now enforces the editorial carousel and render contracts from durable,
persisted evidence. The independent-review bypasses are closed: QA no longer trusts
optional caller diagnostics, truncated PNG headers, duplicate-ID dict overwrites,
package-selected contracts, or a broad missing-artifact legacy fallback.

## Review fixes delivered

### Durable render evidence and artifact binding

- `RenderManifest` now requires every `RenderedPage` to persist its PNG SHA-256 and
  a strict `PageProbeAttestation` containing exact visible text, visibility/overflow/
  clip flags, font metrics, measured bounds, canvas/safe-margin facts, and measured
  asset geometry.
- The renderer validates exact storyboard copy, exact project font families, canvas
  geometry, probe findings, and slot correspondence before publishing a page.
- Page and contact-sheet PNGs are fully decoded with Pillow (`verify` plus `load`),
  not accepted from a signature/IHDR prefix. The renderer stores page hashes, the
  contact-sheet hash, and an ordered page-hash binding.
- Render QA recomputes hashes from current bytes, distinguishes missing/corrupt/
  wrong-dimension/tampered artifacts, and reports corrupt contact sheets atomically.
- `publish_package.rendered_visible_text` and `render_diagnostics` are no longer QA
  inputs. Persisted per-page probe evidence is mandatory.

### Aggregate correspondence, identity, and atomicity

- Carousel QA validates exact VisualPlan/storyboard length before indexed traversal;
  no non-strict `zip` or out-of-range `continue` remains on the editorial path.
- Duplicate plan frame IDs, storyboard frame IDs, storyboard slot IDs, plan
  requirement slot IDs, and AssetManifest slot IDs are rejected before mapping.
- Schema-invalid frames do not enter dependent role/layout/slot checks.
- Frame ID, role, and layout drift have distinct rules and narrow locations.
- Missing render pages produce one missing-page issue rather than count/partial
  cascades. External provenance fields have distinct rules and locations.
- Carousel and render R1 task IDs are hashes of source/rule/frame/location, so they
  remain stable when unrelated issues are inserted or removed.
- Storyboard slot IDs are now global carousel identities, not merely per-frame
  identities. Page probe asset IDs are schema-unique and must match that page's
  storyboard slots exactly once.
- Identity audits group occurrences before constructing maps. Conflicted groups skip
  only their own dependent checks; unrelated frames/items and independently provable
  global composition rules continue to be audited.
- Duplicate AssetManifest groups no longer return early. QA reports the duplicate
  occurrence and continues auditing every unconflicted item.
- Asset requirement role and layout drift have separate rules/locations. Every
  missing semantic slot location includes its planned index and semantic role, so
  multiple missing-slot R1 tasks have unique stable IDs.

### Asset audit

- Each asset audit reads one bytes snapshot and derives both SHA-256 and decoded
  intrinsic dimensions from it, removing the prior hash/dimension TOCTOU gap.
- Current bytes are checked against the AssetManifest and the rendered source-hash
  binding.
- Actual source dimensions are checked against VisualPlan minimums.
- Persisted browser geometry is checked for natural dimensions, `object-fit`, crop,
  and aspect-ratio error; distorted/cropped output emits `asset_render_stretched`.
- QA recomputes aspect-ratio error and crop state from raw natural/rendered dimensions
  and `object_fit`, then separately checks the persisted derived fields. A caller
  cannot clear `cropped` or `aspect_ratio_error` to hide contradictory raw geometry.
- Every page rechecks exact 1080x1440 canvas, exact 84px safe margin, role-specific
  repository font family, headline line count, body line-height ratio, and text bounds.
- Local and external provenance fields are audited atomically.

### Trust boundaries and migration isolation

- Carousel QA selects the authoritative contract from the selected topic, verifies
  package-contract equality, and checks the cover against the authoritative promise.
- Legacy QA is entered only for an explicit old text-card shape (`template` fields,
  no editorial fields) when VisualPlan, AssetManifest, and RenderManifest are all
  absent.
- Missing VisualPlan or manifests on an editorial state yields deterministic
  editorial `*_missing` issues and never falls through to fixed-six QA.
- Public editorial validators retain the 5–7-frame contract and contain no fixed-six
  assumptions or model-based repair.

## Deterministic proxy metrics

All six 0–100 fields remain explicitly labelled `deterministic_proxy` and retain the
warning that they do not replace human aesthetic review. They now vary on measured
facts rather than relabelled hard-gate counts:

`RenderQAResult.metrics_available` is true only when editorial render QA has zero
issues. All six values are nullable and remain `None` for failed or legacy QA results;
the schema rejects publishing values while `metrics_available` is false.

- `editorial_quality`: composite including persisted visible-text density.
- `beauty_category_fit`: adapter role fit plus measured natural-dimension headroom
  over VisualPlan minimums.
- `visual_hierarchy`: persisted headline/body type-scale separation plus cover facts.
- `saveability`: actionable item count on measured saveable frames.
- `cross_page_consistency`: measured headline-size variance, exact fonts, identities,
  source bindings, and ordered contact-sheet binding.
- `template_stiffness`: all layout reuse, including non-adjacent reuse; higher is
  stiffer.

Direction/variation tests cover every metric, including dense versus concise copy,
dimension headroom, type-scale separation, checklist richness, cross-page type
variance, and non-adjacent layout reuse. Both baseline and variant are asserted to be
passing, internally consistent render artifacts with real decodable PNGs, exact
storyboard/probe text, and aligned plan/manifest identities.

## TDD evidence

Review-fix RED was established in five groups:

- Carousel identity/atomic/trust: `10 failed`.
- Render artifact/atomic gates: `9 failed`.
- Schema/renderer durable evidence: `2 failed`.
- Proxy direction/variation: `6 failed`.
- Asset minimums and persisted DOM geometry: `2 failed`.

After implementation, the focused Task 7 + renderer/schema/probe suite is:

```text
106 passed, 2 warnings in 6.03s
```

The warnings are non-failing macOS pytest temporary-directory cleanup warnings.

The pre-final full-suite run found one legacy integration fixture that still wrote a
truncated 24-byte IHDR prefix. The fixture was corrected to emit a real decodable PNG;
its integration file then passed `5 passed` and `compileall` completed successfully.

Fresh final full-repository verification:

```text
1023 passed, 2 skipped, 4 warnings in 30.43s
```

The two skips are opt-in live stock-provider tests. Two warnings are existing legacy
storyboard fallback warnings and two are non-failing macOS pytest cleanup warnings.

Final re-review RED was then established in five requested areas:

- schema identity/hash element constraints: `2 failed`, followed by one additional
  schema-level cross-frame storyboard slot uniqueness RED;
- global carousel identity, aggregation, and task atomicity: `5 failed`;
- render raw-evidence, conflict-group, and proxy availability selection: `12 failed`
  (`8` pre-existing direction tests in the same selection already passed).

Final re-review GREEN:

```text
90 passed, 2 warnings in 2.55s
```

Focused Task 7 plus renderer/schema/probe verification:

```text
121 passed, 2 warnings in 6.36s
```

Fresh full repository verification after the final re-review fixes:

```text
1038 passed, 2 skipped, 4 warnings in 30.08s
```

## Self-review

- Re-read the independent review and mapped every Critical, Important, and Minor
  finding to implementation plus regression tests.
- Confirmed the renderer validates and persists probe evidence before publication.
- Confirmed page/contact hashes bind current decodable bytes and ordered page output.
- Confirmed duplicate identities are rejected before dict construction.
- Confirmed no `_frame_by_slot` last-write-wins mapping remains; occurrence groups are
  built before any unique mapping.
- Confirmed duplicate/invalid roots suppress only their own dependent checks and
  multi-error tests retain unrelated failures.
- Confirmed asset hash and dimensions come from one source snapshot.
- Confirmed raw DOM geometry recomputes derived aspect/crop facts and page token facts
  are revalidated from persisted raw measurements.
- Confirmed all six proxy direction pairs pass hard gates, publish availability, and
  demonstrate within-range directional variation.
- Confirmed ordered contact-sheet page bindings enforce strict lowercase 64-hex values
  per element and `template_stiffness` documents all layout reuse.
- Confirmed no QA path calls an LLM or attempts automatic repair.
- Confirmed deterministic failures still route one atomic mandatory task per issue to
  `R1_REFLECTOR`.

## Concerns

- The explicit private fixed-card bridge remains for the pre-Task-8 graph only. Its
  discriminator is intentionally narrow and should be deleted when Task 8 removes
  the legacy checkpoint path.
- `ruff` and `black` are not installed in the active environment; syntax was checked
  with `compileall`, whitespace with `git diff --check`, and behavior with focused and
  full pytest suites.
