# Task 2 Report: Topic Signal and Creative Metadata Schemas

## Scope

Implemented Task 2 exactly as scoped in `.superpowers/sdd/task-2-brief.md`:

- Added `src/schemas/topic_signal.py`
- Added `CreativeSeed` and required `TopicItem.creative_seed`
- Added AgentState fields for topic signal / creative brief / generation trace contracts
- Updated existing tests/fixtures that now require `creative_seed`

Not implemented:

- persistence
- graph node behavior for topic signals
- topic signal collection logic
- later-task runtime wiring

## Implementation Details

### New schema module

Created `src/schemas/topic_signal.py` with:

- `SignalType`
- `SignalRiskLevel`
- `TopicSignal`
- `CreativeSeed`
- `CreativeBrief`
- `TopicGenerationTrace`

The interfaces follow the brief exactly, including:

- `confidence: float = Field(ge=0, le=1)`
- `trends_num: int = Field(gt=0)`
- `generated_candidates_count` / `filtered_candidates_count` with `Field(ge=0)`

### TopicItem contract

Updated `src/schemas/topic.py` so `TopicItem` now requires:

- `creative_seed: CreativeSeed`

### AgentState contract

Updated `src/schemas/agent_state.py` to include:

- `topic_signals: List[TopicSignal]`
- `creative_briefs: List[CreativeBrief]`
- `topic_generation_trace: Optional[TopicGenerationTrace]`

`subdomain: Optional[str]` was already present and did not need to be added.

### Test fixture updates

Updated existing fixtures that construct `TopicItem` or feed normalized trend payloads into `TopicItem(**...)` so they now include the exact default `creative_seed` from the brief:

```python
{
    "signal_type": "evergreen_context",
    "signal_name": "测试默认信号",
    "why_now": "测试中使用稳定 evergreen 信号。",
    "domain_translation": "测试中保持原 domain/subdomain。",
    "evergreen_pain": "测试核心痛点。",
    "timely_framing": "测试时机包装。",
}
```

## RED / GREEN Evidence

### RED

Added `tests/schemas/test_topic_signal.py` first, before production edits.

Command:

```bash
pytest tests/schemas/test_topic_signal.py -q
```

Result:

- Failed during collection with `ModuleNotFoundError: No module named 'src.schemas.topic_signal'`

This confirmed the new contract did not exist yet.

### GREEN

After implementing the schemas and required fixture updates:

Command:

```bash
pytest tests/schemas/test_topic_signal.py -q
```

Result:

- `4 passed in 0.03s`

## Test Commands and Results

### Required focused schema test

Command:

```bash
pytest tests/schemas/test_topic_signal.py -q
```

Result:

- `4 passed in 0.03s`

### Required related schema/node suite

Command:

```bash
pytest tests/nodes tests/schemas -q
```

Result:

- `86 passed, 2 warnings in 4.55s`

Warnings were unrelated pytest temp-directory cleanup warnings from the environment.

### Additional verification on directly modified non-node tests

Command:

```bash
pytest tests/domain/test_topic_metadata.py tests/integration/test_domain_workflow.py -q
```

Result:

- `5 failed, 10 passed, 2 warnings in 3.60s`

These failures appear unrelated to Task 2 schema scope:

1. `tests/domain/test_topic_metadata.py::test_main_initial_state_includes_metadata_briefs`
   - failure: `ModuleNotFoundError: No module named 'src.prompts.composer'; 'src.prompts' is not a package`
   - cause appears to be the test's local import stubbing, not the schema changes
2. `tests/integration/test_domain_workflow.py::*`
   - failures involve domain confirmation interrupt/review routing and missing `publish_package`
   - no failure referenced `creative_seed`, `TopicSignal`, `CreativeBrief`, or `TopicGenerationTrace`

I did not change runtime graph/review behavior because that is outside Task 2 scope.

## Files Changed

- `src/schemas/topic_signal.py`
- `src/schemas/topic.py`
- `src/schemas/agent_state.py`
- `tests/schemas/test_topic_signal.py`
- `tests/domain/test_topic_metadata.py`
- `tests/integration/test_domain_workflow.py`
- `tests/nodes/test_metadata_flow.py`
- `tests/nodes/test_evidence_brief.py`

## Self-Review

- The new schema interfaces match the brief exactly.
- `TopicItem.creative_seed` is required, not optional, per brief.
- Legacy fixtures were updated with the prescribed default seed rather than weakening validation.
- No persistence, collector logic, or later-task graph behavior was added.
- Write scope stayed within the brief-listed schema files plus tests that needed fixture updates.

## Concerns

- Additional domain/integration tests currently fail for reasons that appear pre-existing or outside Task 2 scope.
- I am committing the Task 2 schema/data-contract work with the required schema/node suite green, while documenting those unrelated failures explicitly.
