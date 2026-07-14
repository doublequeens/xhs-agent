# Task 8 Final Review Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the final Task 8 security and crash-consistency review with strict journal/lock/file trust boundaries, decisive workflow versions, and canonical reused-asset provenance.

**Architecture:** Keep public behavior at the existing lifecycle, graph-resume, and Final Guard seams. Move recovery records into a versioned strict schema and a write-ahead transaction protocol, anchor all filesystem access by verified descriptor chains, and validate manifest claims against the canonical catalog rather than against one another.

**Tech Stack:** Python 3.12, Pydantic v2, POSIX `openat`/`flock`/`fsync`, LangGraph checkpoints, pytest.

## Global Constraints

- Preserve catalog lock order: review lock, candidate/asset lock, manifest lock.
- Never execute a journal-derived filesystem mutation before strict schema, transaction binding, containment, no-follow, identity, and byte-hash validation.
- Preserve the primary exception and aggregate compensation failures as notes.
- Existing project-seed assets use the checked-in canonical catalog manifest; approved external assets also require their approved audit binding.
- Public test seams are `review_pending_asset_batch`/standalone lifecycle calls, `load_run_state`/compiled graph resume, and `final_policy_guard_node`.

---

### Task 1: Strict recovery-journal trust boundary

**Files:**
- Modify: `src/asset_resolver/lifecycle.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: `AssetCatalog`, canonical pending/active roots, persistent manifest.
- Produces: versioned strict journal validation before `_recover_asset_review_journals_locked` mutates state.

- [ ] Write public batch-retry tests for corrupt schema, escaped paths, external symlink directories, and tampered audit snapshot bytes; run each and record RED.
- [ ] Add strict Pydantic journal models with schema version plus transaction/catalog/run bindings, canonical root containment, no-follow regular-file checks, audit byte hash, and identity binding.
- [ ] Quarantine or fail closed on invalid records without moving or writing any journal-controlled path.
- [ ] Run the lifecycle suite and record GREEN.

### Task 2: Crash-safe write-ahead lifecycle protocol

**Files:**
- Modify: `src/asset_resolver/lifecycle.py`
- Modify: `src/asset_resolver/catalog.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: validated journal transaction and catalog review lock.
- Produces: idempotent intent/done transitions for audit, move, manifest, rollback, and recovery.

- [ ] Write crash-injection tests at every persisted transition, approved-preexisting retry rollback, and rollback-internal failure preserving the original exception; record RED.
- [ ] Persist and fsync intent before each mutation, fsync mutated files/parent directories, then persist and fsync done; precompute the manifest mutation so its expected digest is durable before the write.
- [ ] Exclude already-approved candidates from transaction rollback ownership and make recovery resume incomplete steps idempotently.
- [ ] Fsync journal rename/unlink and every move parent; run lifecycle tests GREEN.

### Task 3: Harden the global catalog-review lock

**Files:**
- Modify: `src/asset_resolver/catalog.py`
- Test: `tests/asset_resolver/test_lifecycle.py`

**Interfaces:**
- Consumes: catalog root.
- Produces: verified, non-symlink, single-link lock inode held across every writer.

- [ ] Write lock symlink, hardlink-alias, replacement-race, and existing concurrency tests; record RED.
- [ ] Open with `O_NOFOLLOW`, compare lstat/fstat before and after flock, require regular file, stable device/inode, and `st_nlink == 1`.
- [ ] Run lifecycle tests GREEN.

### Task 4: Make modern workflow version decisive

**Files:**
- Modify: `src/editorial_carousel/legacy.py`
- Modify: `main.py`
- Test: `tests/test_main.py`
- Test: `tests/integration/test_legacy_editorial_resume.py`

**Interfaces:**
- Consumes: persisted version, legacy marker, exact checkpoint successor, package shape.
- Produces: modern state that cannot be downgraded and legacy inference only for absent version plus strict old shape.

- [ ] Write modern-v2 old-shape, marker-spoof, partial-modern, and conflicting-version tests; record RED.
- [ ] Return modern marker-clearing updates before any legacy heuristic; require absent version plus exact successor and strict shape for heuristic hydration.
- [ ] Verify partial modern checkpoints remain modern and surface normal missing-artifact policy issues; run resume tests GREEN.

### Task 5: Anchor guard paths and canonical asset provenance

**Files:**
- Modify: `src/nodes/node_q_01_final_policy_guard.py`
- Modify: `src/asset_resolver/catalog.py`
- Test: `tests/nodes/test_final_policy_guard.py`

**Interfaces:**
- Consumes: trusted active/render roots and canonical active catalog/audits.
- Produces: descriptor-anchored byte snapshots and canonical provenance decisions.

- [ ] Write trusted-root parent symlink/swap and consistent-forged-provenance tests; retain real catalog reuse pass; record RED.
- [ ] Open absolute trusted roots component-by-component from `/` with `O_DIRECTORY | O_NOFOLLOW` and hold the verified root descriptor through traversal.
- [ ] Load canonical project catalog entries and approved audit records; compare IDs, provider/license/run/review/safety/timestamps/hash fields to every reused manifest claim.
- [ ] Run Final Guard tests GREEN.

### Task 6: Regression verification, report, and commit

**Files:**
- Modify: `.superpowers/sdd/task-8-report.md`

**Interfaces:**
- Consumes: all completed slices.
- Produces: review evidence and one clean commit.

- [ ] Run targeted lifecycle, guard, and legacy suites.
- [ ] Run the combined focused suite, full `pytest -q`, bytecode compilation, and `git diff --check`.
- [ ] Update the report with the strict journal/crash protocol and exact RED/GREEN/final counts.
- [ ] Commit and verify `git status --short` is empty.

