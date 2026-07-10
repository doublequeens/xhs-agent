# Task 2 Report: Profile-Bound Typed Content Contracts

## Status

Completed and committed as `1eff35e` (`feat: require profile-bound content contracts`).

## Delivered

- Added `ContentContract` with non-empty fields, an 8–42 character first-screen
  promise, and the permitted visual-mode literal values.
- Made `TopicItem.content_contract` required, so candidate contracts survive
  the existing diversity filter as part of the `TopicItem` stored in
  `state["trends"]`.
- Made creative briefs require a `CreatorProfile`; their audience is the exact
  profile audience and their pain/situation comes only from that profile.
- Passed the state profile into the creative-brief builder and made Topic
  Ideator require a profile before it parses candidates.
- Validated every parsed candidate's domain/subdomain, target group, contract
  audience, and visual mode against the creator profile.
- Updated the Topic Ideator JSON prompt to require a complete contract and a
  concrete screenshot asset.
- Updated every directly affected `TopicItem` fixture, including the offline
  signal-to-diversity integration path, to supply a beauty-profile contract.

## RED / GREEN Evidence

The inherited staged changes already contained the contract schema and several
tests, so no RED result is claimed for that pre-existing work.

I added the missing behavior test for a missing creator profile before changing
production code:

```bash
python -m pytest tests/nodes/test_topic_ideator.py -v
```

RED result: `1 failed, 3 passed`; the new test expected `ValueError("creator
profile is required")`, but the node accepted the state.

After making the profile mandatory, the same command passed with `4 passed`.
Additional tests for target-group, contract-audience, and visual-mode mismatch
were then added to cover the inherited validation paths; these passed
immediately, so no RED claim is made for those pre-existing paths.

## Verification

```bash
python -m pytest tests/schemas/test_content_contract.py tests/topic_signals/test_briefs.py tests/nodes/test_topic_ideator.py -v
```

Result: `9 passed in 1.86s`.

```bash
python -m pytest tests/domain/test_topic_metadata.py tests/integration/test_domain_workflow.py tests/nodes/test_evidence_brief.py tests/nodes/test_metadata_flow.py tests/schemas/test_topic_signal.py tests/test_signal_driven_topic_generation_integration.py tests/topic_signals/test_diversity.py -v
```

Result: `53 passed, 2 warnings in 3.93s`. The warnings were pytest temporary
directory cleanup (`rm_rf`, `OSError: Directory not empty`) from the local
environment, not test failures.

```bash
git diff --cached --check
git diff --check
```

Result: both commands exited cleanly with no whitespace errors.

## Committed Files

- `src/schemas/content_contract.py`
- `src/schemas/topic.py`
- `src/topic_signals/briefs.py`
- `src/nodes/node_a_03_creative_brief_builder.py`
- `src/nodes/node_a_04_topic_ideator.py`
- `src/prompts/base/topic_ideator.txt`
- `tests/schemas/test_content_contract.py`
- `tests/topic_signals/test_briefs.py`
- `tests/nodes/test_topic_ideator.py`
- `tests/domain/test_topic_metadata.py`
- `tests/integration/test_domain_workflow.py`
- `tests/nodes/test_evidence_brief.py`
- `tests/nodes/test_metadata_flow.py`
- `tests/schemas/test_topic_signal.py`
- `tests/test_signal_driven_topic_generation_integration.py`
- `tests/topic_signals/test_diversity.py`

## Concerns

- The worktree still has an unrelated modified `.superpowers/sdd/task-1-report.md`
  and an untracked `docs/superpowers/plans/2026-07-10-beauty-account-content-workflow.md`.
  Neither was changed or committed by Task 2.
