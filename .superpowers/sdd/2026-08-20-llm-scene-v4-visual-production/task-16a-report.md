# Task 16A report: v4 offline review workspace

## RED

- Added contract and workspace tests before production modules existed.
- `pytest -q tests/review/test_v4_workspace.py tests/schemas/v4/test_review.py` initially failed during collection because `src.review` and `src.schemas.v4.review` did not exist. This was the expected missing-feature boundary.

## GREEN

- Added strict, frozen v4 review contracts: workspace manifest, untrusted intent, asset decision, and durable hash-bound decision record.
- Added transactional no-replace review workspace materialization under the exact revision `ArtifactPaths.review_root`, using verified no-follow reads of current rendered bytes and descriptor-relative staged writes.
- The published local workspace includes contact sheet, page copies, deterministic Q2 overlays, Q0-Q4 quality report, untrusted `decision.json`, and a canonical workspace manifest. It never mutates render/source contracts.
- Added local-only `file://` HTML with restrictive CSP, escaped dynamic display values, local images, visible review sections and internal asset evidence.
- Added verifier seam for current workspace contracts/bytes and optional validated previous-revision comparison copies. Task 16B owns decision acceptance, terminal routing, invalidation and the node/CLI wiring.

## Verification

| Command | Result |
| --- | --- |
| `pytest -q tests/review/test_v4_workspace.py tests/schemas/v4/test_review.py` | `8 passed in 14.29s` |
| `pytest -q tests/visual_runtime/test_artifact_identity.py tests/schemas/v4/test_quality.py tests/visual_design/v4/test_v4_render_qa.py` | `92 passed in 110.31s` |
| `python -m compileall -q src` | passed |
| `git diff --check` | passed |

The workspace test suite runs an actual local Playwright/Chromium `file://` smoke: contact sheet, all page cards, overlays, quality/asset sections, no non-file network requests, no page errors, and screenshot output restricted to pytest `tmp_path`.

## Risks / remaining boundary

- Decision intake verification, immutable accepted-decision append, replay protection, typed revision invalidation, Human Review node, and additive CLI are intentionally deferred to Task 16B. The contracts and workspace verifier are the seam for that work.
- The manifest excludes its own file-byte digest to avoid a self-hash cycle; its canonical digest binds every other materialized workspace file, while the verifier re-parses the manifest itself before trusting its entries.
