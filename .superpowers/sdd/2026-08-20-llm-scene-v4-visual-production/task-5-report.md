# Task 5 report: bound visual model execution

## Outcome

- Added frozen, serializable v4 provider/request/policy contracts. Requests carry
  the full run/candidate/revision/node/page identity and operation payload;
  payloads are recursively frozen and API keys are excluded from repr,
  fingerprints, ledger events, result bytes, and raised errors.
- Added `VisualLLMGateway` as the single parent-side owner of candidate budget,
  shared monotonic deadlines, bounded retry/backoff, strict JSON/schema parsing,
  schema-repair attempt accounting, verified result reuse, atomic contained
  result writes, image-byte validation, and deterministic status mapping.
- Added `V4Worker`, which starts a fresh spawned process for each attempt,
  constructs the provider client in the child, performs exactly one Gemini SDK
  call, emits only a strict JSON-safe success/failure envelope, and terminates,
  joins, and kills on deadline as needed.
- Added an isolated v4 Gemini adapter with no import or call to the v3 adapters
  and no nested provider retry loop. Existing v3 factories and
  `GeminiStructuredVisualModel` behavior were not changed.
- Added an explicit lazy v4 factory; calling it creates configuration, worker,
  ledger, and gateway but does not construct a Google client in the parent.

## TDD evidence

Tests were written before the v4 implementation. The initial required red
command was:

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py
```

It failed during collection with the expected missing-boundary errors:
`ModuleNotFoundError: No module named 'src.visual_ai.gateway'` and the missing
v4 factory symbol.

The first implementation pass then ran the same focused command and produced
9 behavioral failures, including result-shape, timeout classification, and
envelope-serialization regressions. Those were corrected in follow-up red/green
cycles. The final focused command is green.

## Verification

- `pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py` — `25 passed, 2 warnings`.
- `pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py` — `60 passed, 2 warnings`.
- `pytest -q` — `1419 passed, 2 skipped, 2 warnings`. The two skips are the documented opt-in Gemini live tests.
- `python -m compileall -q src main.py` — passed.
- `git diff --check` — passed.

## Remaining risks

- No live Gemini call was made; live verification remains intentionally gated by
  `RUN_LIVE_VISUAL_AI_TESTS=1` and credentials.
- Task 9 still owns approved asset-transaction binding for generated images;
  this gateway stores only diagnostic/cache results beneath the v4 result root.
