# Task 8 Transaction Final Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining multi-run, quota, identity-race, registry-retention, and requirement-binding findings without expanding Task 9.

**Architecture:** Keep lifecycle behavior behind `review_pending_asset_batch`, `approve_external_asset`, and `reject_external_asset`. Make the registry catalog-scoped with run-bound entries, make every transaction resource reservation and filesystem precondition explicit before mutation, and make Final Guard reproduce the resolver's requirement filters from current state.

**Tech Stack:** Python 3.12, Pydantic v2, POSIX `openat`/`flock`/`fsync`, pytest.

## Global Constraints

- Use RED/GREEN TDD at public lifecycle and Final Guard seams.
- Same-UID/root administration is outside prevention scope, but races or corruption must never silently lose a catalog update or mutate an unbound external path.
- Do not add Task 9 behavior.
- Preserve the primary exception and annotate cleanup failures.

---

### Task 1: Catalog-scoped multi-run registry and compaction

**Files:**
- Modify: `src/asset_resolver/lifecycle.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: `AssetCatalog.catalog_id`, root, and run ID.
- Produces: catalog-scoped `TransactionRegistry` whose entries bind `run_id`, plan, state, and timestamp.

- [ ] Add RED tests for run A commit followed by run B approve/reject, run A crash followed by unaffected run B work and later run A recovery, old committed cleanup, old prepared fail-closed, and small-threshold compaction.
- [ ] Remove top-level registry `run_id`; add entry `run_id`; store journals below `.asset-review-recovery/<run_id>/` and scan only that directory.
- [ ] Validate entry run binding and apply freshness only to prepared entries; compact terminal entries with no journal before enforcing registry byte limits.
- [ ] Run the multi-run/compaction tests and lifecycle suite GREEN.

### Task 2: Pre-mutation recovery quota reservation

**Files:**
- Modify: `src/asset_resolver/lifecycle.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: manifest/audit snapshots and final serialized journal bytes.
- Produces: bounded preparation that fails before registry preparation or audit/asset mutation.

- [ ] Add RED tests for an 800 KiB audit, aggregate multi-asset snapshots, and base64-expanded serialized journal overflow; assert no registry, audit, move, or manifest side effects.
- [ ] Bounded-read the manifest and each audit, accumulate decoded snapshot bytes, serialize the complete journal, and reject over the exact recovery file limit before `_registry_prepare`.
- [ ] Run quota tests and lifecycle suite GREEN.

### Task 3: Lock/root version checkpoints and identity-bound mutations

**Files:**
- Modify: `src/asset_resolver/catalog.py`
- Modify: `src/asset_resolver/lifecycle.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: held catalog lock token, expected file identity/hash/existence.
- Produces: mutation helpers that compare expected identity at the atomic operation point and refuse destination overwrite.

- [ ] Add RED tests for lock unlink/recreate between writers, source swap, destination creation, metadata swap, and root-directory replacement.
- [ ] Yield an opaque verified lock token from `catalog_review_lock`; revalidate root/lock identity at transaction start, before each durable mutation, and before registry commit.
- [ ] Extend `_atomic_write_bytes`, `_durable_replace`, and `_durable_unlink` with expected identity/hash/existence contracts; implement `_durable_mkdir` using held parent dirfds and `mkdirat`.
- [ ] Keep manifest writes CAS-based and prove replacement causes explicit failure/rollback with no lost update.
- [ ] Run identity/lock tests and lifecycle suite GREEN.

### Task 4: Canonical current requirement enforcement in Final Guard

**Files:**
- Modify: `src/nodes/node_q_01_final_policy_guard.py`
- Test: `tests/nodes/test_final_policy_guard.py`

**Interfaces:**
- Consumes: `visual_plan.required_assets`, canonical catalog entry, manifest item, and approved audit.
- Produces: resolver-equivalent current requirement validation.

- [ ] Add RED tests for catalog assets that violate minimum dimensions/orientation/tags/disabled contexts, requirement fingerprint drift, and project-original items carrying external-only provenance.
- [ ] Recompute `requirement_fingerprint` from each current `AssetRequirement`; require item/audit equality for external assets.
- [ ] Enforce min width/height, orientation, context tags, disabled contexts, allowed layout, and role/fallback rules against the canonical entry.
- [ ] Require all external-only fields to be null/empty for project-original manifest items.
- [ ] Run Final Guard tests GREEN.

### Task 5: Verification, report, and commit

**Files:**
- Modify: `.superpowers/sdd/task-8-report.md`
- Modify: `docs/superpowers/plans/2026-07-14-task8-final-review.md`

**Interfaces:**
- Consumes: all GREEN slices.
- Produces: final evidence and one clean Task 8 commit.

- [ ] Remove the obsolete trailing blank line from the prior plan and update the report with RED/GREEN evidence.
- [ ] Run multi-run/quota/lifecycle/Guard targeted suites, broader focused suite, and full `pytest -q`.
- [ ] Run `python -m compileall -q main.py src tests` and `git diff --check`.
- [ ] Commit only Task 8 changes and verify `git status --short` is empty.
