# Task 1 report: strict editorial carousel contracts

## Implementation summary

- Added strict Pydantic v2 contracts for visual plans, semantic storyboard frames, asset requirements/manifests/search reports, render manifests, and immutable ContentLock payloads.
- Extended `ContentContract` with required editorial strategy fields and the 5-7 recommended-frame invariant.
- Added optional typed `visual_plan`, `asset_manifest`, and `render_manifest` slots to `AgentState` without removing legacy slots.
- Exported all new public contracts through `src.schemas`.
- Kept the legacy `StoryboardFrame`/`StoryboardPayload` aliases on the old text-card contracts so Task 1 does not perform Task 2's graph migration.
- Updated every test fixture that constructs a `ContentContract`, and updated the production Topic Ideator output contract so new model output must provide the required fields explicitly.

## Files changed

Created:

- `src/schemas/visual_plan.py`
- `src/schemas/assets.py`
- `src/schemas/render_manifest.py`
- `src/schemas/content_lock.py`
- `tests/schemas/test_editorial_carousel.py`

Modified:

- `src/schemas/storyboard.py`
- `src/schemas/content_contract.py`
- `src/schemas/agent_state.py`
- `src/schemas/__init__.py`
- `src/prompts/base/topic_ideator.txt`
- `tests/domain/test_topic_metadata.py`
- `tests/integration/test_beauty_account_workflow.py`
- `tests/integration/test_domain_workflow.py`
- `tests/nodes/test_carousel_qa.py`
- `tests/nodes/test_content_writer.py`
- `tests/nodes/test_evidence_brief.py`
- `tests/nodes/test_final_policy_guard.py`
- `tests/nodes/test_metadata_flow.py`
- `tests/nodes/test_render_qa.py`
- `tests/nodes/test_text_card_renderer.py`
- `tests/nodes/test_topic_ideator.py`
- `tests/nodes/test_virality_scorer.py`
- `tests/schemas/test_content_contract.py`
- `tests/schemas/test_topic_signal.py`
- `tests/test_signal_driven_topic_generation_integration.py`
- `tests/topic_signals/test_diversity.py`

## RED evidence

Command:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/schemas/test_editorial_carousel.py -q
```

Exact output:

```text
==================================== ERRORS ====================================
__________ ERROR collecting tests/schemas/test_editorial_carousel.py ___________
ImportError while importing test module '/Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.worktrees/editorial-carousel-workflow/tests/schemas/test_editorial_carousel.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/anaconda3/envs/xhs-agent/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/schemas/test_editorial_carousel.py:6: in <module>
    from src.schemas.assets import AssetManifest, AssetSearchReport
E   ModuleNotFoundError: No module named 'src.schemas.assets'
=========================== short test summary info ============================
ERROR tests/schemas/test_editorial_carousel.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.11s
```

This was the expected RED: collection failed because the first required new schema module did not exist. The failure was caused by missing Task 1 production contracts, not by a test typo.

## GREEN evidence

New schema suite after implementation:

```text
$ /opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/schemas/test_editorial_carousel.py -q
.......                                                                  [100%]
7 passed in 0.05s
```

Required focused regression command, fresh final run:

```text
$ /opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/schemas tests/domain/test_profiles.py tests/nodes/test_metadata_flow.py -q
.......................................................                  [100%]
55 passed in 2.41s
```

Diff hygiene:

```text
$ git diff --check
```

Exit code 0 with no output.

## Full-suite result

Command:

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Exact result summary from the fresh final run:

```text
........................................................................ [  9%]
........................................................................ [ 19%]
........................................................................ [ 28%]
........................................................................ [ 38%]
........................................................................ [ 48%]
........................................................................ [ 57%]
........................................................................ [ 67%]
........................................................................ [ 77%]
........................................................................ [ 86%]
........................................................................ [ 96%]
............................                                             [100%]
=============================== warnings summary ===============================
../../../../../../../../opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5
  /opt/anaconda3/envs/xhs-agent/lib/python3.12/site-packages/langgraph/checkpoint/serde/encrypted.py:5: LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version. Pass an explicit value (e.g., allowed_objects='messages' or allowed_objects='core') to suppress this warning.
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_reapply_visible_text_patch
tests/nodes/test_final_policy_guard.py::test_regenerated_storyboards_apply_complete_r2_visible_text_without_human_patch
  /Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.worktrees/editorial-carousel-workflow/src/nodes/node_o_storyboards_generator.py:58: UserWarning: storyboards_generator is falling back to beauty-v1 for a legacy checkpoint without domain_context.
    system_prompt = compose_prompt_for_state("storyboards_generator", state)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
748 passed, 3 warnings in 20.85s
```

Pytest also emitted two post-summary temporary-directory cleanup warnings (`OSError: [Errno 66] Directory not empty`) under macOS `/private/var/folders/.../pytest-of-qinqiang/garbage-*`; the command still exited 0.

## Self-review

- Confirmed all five `ContentJob` values, five `VisualFamily` values, and eleven `LayoutName` values match the task brief exactly.
- Confirmed `VisualPlan.frame_plan` and `CarouselPayload.storyboards` enforce 5-7 items.
- Confirmed arbitrary layouts, network URL fields, free CSS fields, and other extras are rejected by strict models.
- Confirmed `ContentLock` is `extra="forbid"`, frozen, and requires a lowercase 64-character SHA-256 shape.
- Confirmed `ContentContract` has no silent defaults for the five new fields and that `recommended_frame_count` is bounded 5-7.
- Confirmed new state slots are `NotRequired[Optional[...]]` and no legacy state slots were removed.
- Confirmed the graph/checkpoint compatibility behavior was not implemented; that remains Task 2.
- Confirmed no resolver, renderer, QA, or publishing behavior from later tasks was introduced.
- Confirmed the worktree started at the requested base commit `98dd8cad4ae9f5a0e5d103a63dcc28eab8d6897a`.

## Concerns

- No Task 1 implementation concerns.
- The full suite has three pre-existing runtime warnings and two non-failing pytest temporary-directory cleanup warnings, recorded above.
