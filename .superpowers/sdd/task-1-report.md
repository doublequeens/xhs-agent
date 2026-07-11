# Task 1 Report: CLI and Domain/Subdomain Routing

## What you implemented

- Extended `resolve_domain()` to accept `subdomain` and `interactive`, reject bare subdomains, validate explicit subdomains against the selected domain profile, and distinguish explicit domain defaults via `classification_source="explicit_domain_default_subdomain"`.
- Extended `DomainContext` to allow the new `classification_source` value.
- Added CLI `--subdomain` support in `main.py`, including parser validation for `--subdomain` requiring `--domain` and for subdomain/domain compatibility.
- Added `subdomain` to `AgentState` and seeded it from CLI initial state.
- Updated `domain_router_node()` to pass explicit subdomain state into routing.
- Updated `domain_confirmation_node()` so explicit-domain default-subdomain routing still interrupts for confirmation, and so confirmed selections rebuild context through `resolve_domain()`.
- Added router tests for explicit domain+subdomain behavior and CLI tests for invalid subdomain usage.
- Updated the existing router expectation for explicit domain without explicit subdomain to match Task 1 behavior.

## Tests run and results

- `pytest tests/domain/test_router.py -q`
  - RED verification: failed with 4 `TypeError` failures because `resolve_domain()` did not accept `subdomain`.
- `pytest tests/domain/test_router.py tests/test_main.py -q`
  - GREEN verification: passed, `26 passed`.
- `pytest tests/nodes/test_domain_nodes.py -q`
  - Related verification: `1 failed, 11 passed`.
  - Failure is `test_domain_confirmation_node_skips_interrupt_for_high_confidence`, which still expects the pre-Task-1 behavior where explicit domain without explicit subdomain skips confirmation. Task 1 explicitly changes that behavior.

## TDD Evidence: RED and GREEN commands/output summary

- RED
  - Command: `pytest tests/domain/test_router.py -q`
  - Result: `4 failed, 7 passed`
  - Failure summary: all four new tests failed with `TypeError: resolve_domain() got an unexpected keyword argument 'subdomain'`.
- GREEN
  - Command: `pytest tests/domain/test_router.py tests/test_main.py -q`
  - Result: `26 passed, 2 warnings`
  - Warning summary: unrelated pytest temp-directory cleanup warnings from the environment.

## Files changed

- `main.py`
- `src/domain/models.py`
- `src/domain/router.py`
- `src/nodes/node_a_00_domain_router.py`
- `src/nodes/node_a_00_domain_confirmation.py`
- `src/schemas/agent_state.py`
- `tests/domain/test_router.py`
- `tests/test_main.py`

## Self-review findings

- The implementation matches the briefed `resolve_domain()` interface and behavior, including the explicit-domain default-subdomain distinction.
- CLI validation fails early with parser errors before graph or database setup.
- Confirmation behavior now intentionally interrupts for explicit domain without explicit subdomain, even at high confidence, per Task 1.
- I kept write scope to the files listed in the brief, plus this required report file.

## Concerns if any

- `tests/nodes/test_domain_nodes.py::test_domain_confirmation_node_skips_interrupt_for_high_confidence` now conflicts with Task 1’s required behavior. I did not modify that file because it is outside the allowed write scope from the brief.

## Fix report

- Updated `tests/nodes/test_domain_nodes.py` so the skip-path coverage now matches the new confirmation rule:
  - inferred high-confidence routing still skips interrupt;
  - explicit `domain + subdomain` routing still skips interrupt;
  - explicit `domain` with default subdomain now interrupts and accepts a resumed subdomain selection.
- Verified with `pytest tests/nodes/test_domain_nodes.py tests/domain/test_router.py tests/test_main.py -q` after the test update.

## Review follow-up fix: interactive state plumbing

- Added `interactive` to `AgentState` and seeded `initial_state["interactive"] = True` in `main.py` so CLI behavior remains interactive by default.
- Updated `domain_router_node()` to pass `interactive=state.get("interactive", True)` into `resolve_domain(...)` instead of hardcoding interactive mode.
- Updated `domain_confirmation_node()` to skip the confirmation interrupt when `interactive` is explicitly `False`, allowing future non-interactive runs to keep the router-selected default subdomain.
- Added node coverage proving:
  - interactive default still interrupts for explicit domain without explicit subdomain;
  - non-interactive state routes to `classification_source="explicit_domain_default_subdomain"` and does not force confirmation.
- Added a `tests/test_main.py` assertion that fresh CLI state defaults `interactive` to `True`.

### Earlier out-of-brief test update

- Earlier in Task 1, `tests/nodes/test_domain_nodes.py` was updated even though the original brief listed different primary test files. That earlier update remains in place because the current review finding is specifically about node-level interactive vs non-interactive behavior, and this file is the narrowest place to prove it.

### Verification

- Command: `pytest tests/nodes/test_domain_nodes.py tests/domain/test_router.py tests/test_main.py -q`
- Result: `42 passed, 2 warnings`
- Warning summary: unrelated pytest temp-directory cleanup warnings from the environment.
