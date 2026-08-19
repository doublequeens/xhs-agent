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

## Fix round 1: review findings after be01d0a

### TDD evidence

The review regression tests were added before the corresponding fixes. The
required red command was:

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
```

It failed as expected with:

```text
11 failed, 63 passed, 2 warnings in 2.38s
```

The failures covered hard-timeout retry, endpoint/path and request-secret
redaction, strict validated-contract reuse, direct image validation, symlink
containment, ambiguous SUCCESS finish reconciliation, and default factory key
validation.

### Changes

- HARD_TIMEOUT now uses the same bounded retry path as transient transport,
  clipped by the invocation-wide deadline.
- Structured reuse requires the exact response-schema hash and strict canonical
  JSON/model validation. Image reuse requires a stable versioned image
  validation-contract hash, exact bytes hash, MIME, and decodability checks.
- Direct image inputs require one matching supported MIME per decodable byte
  sequence before an AttemptStarted event; ambiguous path-plus-byte inputs are
  rejected.
- Fingerprints omit endpoints, recursively redact absolute local paths and
  attempt metadata, and reject secret-bearing request payload keys. Provider
  endpoint representations remove userinfo/query/fragment data.
- Result persistence now opens root/v4/kind through descriptor-relative
  O_NOFOLLOW handles, creates exclusive temporary files, writes/fsyncs,
  renames atomically, fsyncs directories, and performs bounded cleanup. A
  pre-existing symlink cannot redirect a write outside the configured root.
- Worker allocations are cleanup-owned from Pipe construction onward. Process
  start, IPC, timeout, terminate/kill fallback, join, close, and pipe cleanup
  failures are contextual fatal outcomes; no normal return occurs with a live
  child. The v4 adapter remains one SDK call per attempt.
- Result persistence is separate from terminal ledger append. Terminal append
  reconciliation inspects the durable projection and retries only an observed
  open attempt, honoring an already durable intended terminal and leaving
  unresolved state for reconciliation instead of blindly double-finishing.
- The default Gemini factory requires GEMINI_API_KEY before creating ledger
  state; explicitly injected non-Gemini configurations remain usable offline.

### GREEN verification

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
85 passed, 2 warnings in 2.42s

pytest -q
1444 passed, 2 skipped, 6 warnings in 29.33s

python -m compileall -q src main.py
git diff --check
```

The two live Gemini tests remained skipped by their documented opt-in guard.
The four additional warnings are the test-only Python 3.12 fork deprecation
warnings from the real child-process cleanup proofs. The other two are the
pre-existing pytest temporary-directory cleanup warnings emitted while
`tests/metrics_collector/test_launchd.py::test_plist_mode_is_0600_under_restrictive_umask`
is collected/cleaned.

## Fix round 2: scoped re-review after ece82f3

### TDD evidence

The round-2 regression tests were added before the corresponding fixes. The
required red command was:

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
```

It failed as expected with:

```text
4 failed, 84 passed, 2 warnings in 5.69s
```

The failures covered slash-prefixed prompt fingerprint collisions, missing
spawned-child PID proofs, SIGTERM-ignored cleanup, and the missing partial
`Process.start()` failure-injection seam.

### Changes

- Kept production worker launch on `spawn`, added a parent-side process factory
  seam, and made partial-start ownership observable through `pid`, `_popen`,
  and `is_alive()`. A child created before `start()` raises now follows the
  same bounded terminate/join then kill/join path and cannot return or retry
  while live. The tests launch real spawned blocked children, record PIDs,
  prove they disappear, cover the kill fallback, and verify normal IPC/handle
  cleanup without fork deprecation warnings.
- Restricted absolute-string fingerprint redaction to explicit path-bearing
  metadata keys while continuing to exclude `Path` values. Slash-prefixed
  prompt/content strings therefore remain semantic fingerprint input, while
  distinct local path metadata remains reusable across roots.
- Made result-store descriptor ownership explicit from open through cleanup.
  Root traversal, temporary files, and final kind directories use bounded
  close retries with `fstat`/`EBADF` state checks before any second close;
  cleanup failures remain contextual `result_store` failures and do not leak
  or redirect writes outside the contained root.
- Added a post-commit/lost-ack ledger proof: a durable SUCCESS observed after
  the first `finish` error is honored without a second append, preserving one
  terminal event.

### GREEN verification

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
91 passed, 2 warnings in 5.39s

pytest -q
1450 passed, 2 skipped, 2 warnings in 32.30s

python -m compileall -q src main.py
git diff --check
```

The two live Gemini tests remained skipped by their documented opt-in guard.
The two remaining warnings are the pre-existing pytest temporary-directory
cleanup warnings emitted by
`tests/metrics_collector/test_launchd.py::test_plist_mode_is_0600_under_restrictive_umask`;
the round-2 spawned-worker proofs no longer use `fork` and add no fork
deprecation warnings.

## Fix round 3: scoped re-review after 89bf105

### TDD evidence

The round-3 regression tests were added before the corresponding fixes. The
required red command was:

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
```

It failed as expected with:

```text
6 failed, 93 passed, 2 warnings in 5.49s
```

The failures covered relative `Path` identity, application-specific
camelCase/path metadata keys, bare `input` content semantics, numeric-fd
reuse after a post-close exception, and preservation of simultaneous primary
result-store and cleanup failures.

### Changes

- Fingerprints now redact only absolute `Path` values; relative `Path` values
  participate as stable POSIX strings. A tokenized snake/kebab/camel key
  predicate recognizes explicit path metadata such as `arbitrary_local`,
  `workspaceLocation`, `cacheDir`, and `sourceFilePath`, while bare `input`
  and `output` remain semantic content keys. The code documents that string
  classification depends on explicit key semantics rather than claiming a
  perfect distinction for unknown strings.
- Descriptor ownership is released before every single `os.close` call. A
  close exception records a sanitized cleanup marker and never performs
  `fstat` or a retry against the numeric descriptor, preventing accidental
  closure of a reused fd. Injected ordinary close failures remain fatal and
  redacted; tests close any intentionally retained injected fd themselves.
- Added structured internal result-store failures retaining primary and
  cleanup flags/codes. Root traversal, directory validation, temporary-file,
  and final directory cleanup failures remain contextual and are exposed only
  through stable redacted result-store error codes; terminal ledger status is
  still `TRANSPORT_FATAL`.

### GREEN verification

```text
pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_factory.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py
99 passed, 2 warnings in 5.47s

pytest -q
1458 passed, 2 skipped, 2 warnings in 32.44s

python -m compileall -q src main.py
git diff --check
```

The two live Gemini tests remained skipped by their documented opt-in guard.
The two remaining warnings are the pre-existing pytest temporary-directory
cleanup warnings emitted by
`tests/metrics_collector/test_launchd.py::test_plist_mode_is_0600_under_restrictive_umask`;
fork deprecation warnings remain absent.
