# Task 5 implementation report

## Outcome

Implemented local-gap stock sourcing through official Pexels and Unsplash APIs,
with deterministic merged selection, bounded normalized downloads, cross-run hash
deduplication, and an audited pending/approval/rejection lifecycle.

The legacy `src/tools/pexels_search.py` remains in place because
`src/nodes/node_m_image_sourcing.py` still imports it. Removing it in Task 5 would
break the legacy graph; the implementation plan explicitly removes both in Task 11.

## Delivered behavior

- Official Pexels and Unsplash search adapters use documented HTTPS endpoints,
  authentication headers, bounded timeouts, supported orientation values, and real
  provider URLs. Unsplash records `download_location` before image persistence.
- Local approved matches make zero provider calls. Gaps search enabled providers
  concurrently, retain deterministic provider-report order, merge candidates without
  provider weighting, apply provenance/safety/dimension/orientation filters, and
  download no more than three candidates per run, slot, and requirement fingerprint,
  including across reruns and rejections.
- Pillow strips image metadata and normalizes opaque input to lossless WebP and alpha
  input to PNG. The design-system loader now validates WebP pixel dimensions.
- Deduplication runs before download by provider ID/source URL and after normalization
  by SHA-256 and 8x8 grayscale average-hash Hamming distance, including prior runs.
- Pending files and atomic JSON audits live under
  `incoming/external/<run_id>/`. Strict Pydantic audits preserve provenance,
  attribution, acquisition time, requirement fingerprints, attempt numbers, hashes,
  review status, explicit safety decisions, and provider/download failures.
- Approval validates run scope, audit state, and unchanged bytes, stages the approval
  audit, moves bytes into `active`, validates the complete candidate manifest through
  the production catalog loader, and atomically replaces the manifest. Failures restore
  both the incoming image and pending audit. Rejection is explicit and cannot later be
  promoted using a stale `PendingAsset` object.
- Live provider smoke tests are marked `live_asset_providers` and skip unless
  `RUN_LIVE_ASSET_PROVIDER_TESTS=1`; API keys are documented in `.env.example`.

## TDD evidence

Initial RED:

```text
python -m pytest tests/asset_resolver/test_providers.py \
  tests/asset_resolver/test_external_resolution.py \
  tests/asset_resolver/test_lifecycle.py -q
10 failed: providers.py and lifecycle.py did not exist
```

Additional focused RED cycles proved unsupported orientation parameters, post-download
orientation validation, perceptual near-duplicate handling, rejected-to-approved state
leakage, real provider concurrency, response timing, run-scope enforcement, grounded
candidate ranking, and download-error auditing before each corresponding implementation.

Final focused GREEN:

```text
python -m pytest tests/asset_resolver tests/rendering/test_design_system.py -q
117 passed, 2 skipped
```

Final full-suite GREEN after all review corrections:

```text
python -m pytest -q
915 passed, 2 skipped, 3 warnings
```

The warnings are existing LangGraph/legacy-checkpoint warnings. Pytest also intermittently
reports a macOS temporary-directory cleanup warning after successful runs.

## Review and remaining risks

The two-axis review found no repository-standard violations. The first review pass fixed
concurrent provider calls, grounded result tags instead of query-inflated ranking, response
timing/download failures, run-scope enforcement, and audit-first approval rollback.

A second adversarial review produced additional RED/GREEN cycles and the following
hardening corrections:

- Run IDs are restricted to one safe path component and all incoming paths are checked
  against their resolved run root.
- Provider requests use exact official-host allowlists, reject redirects, validate response
  URLs, bind candidates to the adapter instance that returned them, stream downloads under
  byte limits, and reject oversized decoded images before loading pixels.
- Pending audit files are the canonical source of truth. The public list/load/reject/approve
  contract supports deterministic resume, rejects forged caller state, preserves unresolved
  safety checks, and carries stable pending/run/rank identity into manifests.
- Approval now locks and version-guards manifest replacement, while rollback covers staged
  audit changes, file movement, and manifest failure. A forced concurrent-approval test first
  reproduced a lost update and then passed with the lock in place.
- Cross-run provider-ID/source-URL deduplication occurs before the top-three attempt cap, and
  provider license records now contain a versioned local terms summary with a verified hash
  plus the official terms URL instead of treating a URL as a snapshot.
- Terminal resolution failures expose the complete structured search report to callers.

Review-correction RED runs covered unsafe run paths, redirect/final-host attacks, oversized
downloads and images, provider identity spoofing, lost manifest updates, forged pending
objects, incomplete rollback, resume/reject advancement, pre-cap cross-run deduplication,
and dishonest license snapshot semantics before each implementation was added.

A third adversarial review drove further failing tests and corrections:

- A separate per-candidate lifecycle lock now spans canonical reload, state checks, safety
  resolution, audit staging, file movement, manifest append, and rollback. Forced
  approve/approve and approve/reject races prove exactly one operation wins while the
  audit, active file, and manifest remain consistent.
- Pending audit parsing is a strict Pydantic contract with forbidden extras and validated
  types, non-empty values, URLs, layout, hashes, paths, status transitions, tags, and
  attribution. Unknown safety facts remain previewable but approval requires an explicit
  safe human decision for every unknown and records the decision, time, and disposition.
- Every pending audit and manifest carries a deterministic requirement fingerprint. Resume
  only considers the matching contract and revalidates the pending file hash; approved
  audits validate the exact moved production path instead.
- A locked persisted attempt ledger enforces the three-download ceiling across reruns and
  rejections, independently of global candidate rank. Exhaustion proceeds to the declared
  fallback or terminal structured error and never advances to candidates four through six.
- Incoming roots are revalidated on every access so an external symlink cannot escape the
  catalog. Catalog scope is mandatory for public load and reject operations.
- Approved stock provenance is stored as a validated typed catalog mapping and survives a
  fresh catalog load, including acquisition, provider, licensing, hash, fingerprint, and
  safety-review fields. Seed project-original assets remain compatible.
- The resolver independently applies official URL allowlists before provider download or
  persistence, including for injected provider implementations.

Third-review RED evidence included stale requirement resume, persisted-budget bypass,
catalog symlink escape, permissive audit types, dropped reloaded provenance, malicious
injected URLs, and both same-candidate races. Final GREEN counts above include all of these
regressions.

A final review added five bounded corrections:

- A catalog-scoped provider-asset lock now serializes cross-run approvals that share the
  same production asset identity. It is held across the destination check, move, manifest
  append, and rollback, so the losing run cannot overwrite or move the winner's bytes.
- Attempt reservation atomically enforces provider/asset-ID and source-URL uniqueness and
  distinguishes duplicate candidates from an exhausted budget. Concurrent resolves skip
  duplicate reservations and consume the three-attempt budget with three unique candidates.
- Approved external provenance is projected back into `AssetManifestItem` when a freshly
  loaded stock entry is selected locally, including acquisition, licensing, provider,
  perceptual hash, requirement, and safety-review evidence.
- Production-catalog validation retains the original unresolved-safety context and requires
  an exact, complete decision set: risk flags must be false and publishing permission must
  be true before `approved_for_publishing` is accepted.
- Attempt ledgers now live under the dedicated `.attempt-ledgers/` directory. Candidate
  listing reads only run-root JSON audits, so legal slot IDs beginning with `attempts-`
  resume and advance normally.

The final RED run produced six failures across the cross-run approval race, concurrent
reservation race, local provenance projection, two unsafe decision variants, and the
`attempts-` slot collision. The targeted GREEN run passed all six before the focused and
full-suite runs above.

The closing re-review identified and corrected two remaining concurrency/path gaps:

- The `.attempt-ledgers` directory, ledger file, and ledger lock are resolved and checked
  beneath the run-scoped incoming root before directory creation or ledger access. An
  outside-directory symlink now fails before any download or external write.
- Requirements without an exact local match and with a complete external provider are
  serialized by a run/slot/requirement-fingerprint lock. The lock spans resume checking,
  search, reservation, download, and pending persistence, so a concurrent caller waits for
  the owner and then resumes the same canonical pending audit without another provider call.
  Catalogs without an external provider retain the previous read-only local/fallback path.

Both closing tests failed before implementation: the ledger symlink accepted an outside
write, and a peer resolver exhausted by the owner's reservations raised a terminal error.
The targeted GREEN passed both, followed by the focused and full-suite counts above.

Remaining risks:

- Live API calls were intentionally not executed without opt-in credentials; provider
  response-shape/rate-limit drift remains a live-smoke concern.
- Pexels/Unsplash metadata cannot prove the visual absence of every face, logo, embedded
  text, or watermark. Known description flags are filtered and every surviving asset
  remains pending for explicit human review before production use.
- The resolver now contains substantial external-ingestion orchestration. A later cleanup
  can extract shared atomic-file and provenance mapping utilities without changing this
  tested interface.
