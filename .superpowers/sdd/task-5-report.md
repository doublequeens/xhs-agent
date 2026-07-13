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
  download no more than the top three candidates per slot.
- Pillow strips image metadata and normalizes opaque input to lossless WebP and alpha
  input to PNG. The design-system loader now validates WebP pixel dimensions.
- Deduplication runs before download by provider ID/source URL and after normalization
  by SHA-256 and 8x8 grayscale average-hash Hamming distance, including prior runs.
- Pending files and atomic JSON audits live under
  `incoming/external/<run_id>/`. Audits preserve provenance, attribution, acquisition
  time, hashes, review status, and provider/download failures.
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
64 passed, 2 skipped
```

Final full-suite GREEN after all review corrections:

```text
python -m pytest -q
862 passed, 2 skipped, 3 warnings
```

The warnings are existing LangGraph/legacy-checkpoint warnings. Pytest also intermittently
reports a macOS temporary-directory cleanup warning after successful runs.

## Review and remaining risks

The two-axis review found no repository-standard violations. Review findings fixed before
commit include concurrent provider calls, grounded result tags instead of query-inflated
ranking, response timing/download failures, run-scope enforcement, and audit-first approval
rollback.

Remaining risks:

- Live API calls were intentionally not executed without opt-in credentials; provider
  response-shape/rate-limit drift remains a live-smoke concern.
- Pexels/Unsplash metadata cannot prove the visual absence of every face, logo, embedded
  text, or watermark. Known description flags are filtered and every surviving asset
  remains pending for explicit human review before production use.
- The resolver now contains substantial external-ingestion orchestration. A later cleanup
  can extract shared atomic-file and provenance mapping utilities without changing this
  tested interface.
