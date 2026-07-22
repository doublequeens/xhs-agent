# Modern Editorial Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the two deleted-`strategy.py` pytest collection errors by migrating the beauty-account and domain integration tests to the current v2 editorial contracts.

**Architecture:** Keep production code unchanged. Each integration file owns deterministic modern `NarrativePlan` fixture data and builds storyboard payloads from the production `VisualPlan`; asset slots bind by canonical `slot_id`, and modern render/asset doubles emit `page_archetype` metadata.

**Tech Stack:** Python 3.12, pytest, Pydantic v2, LangGraph, current `src.editorial_carousel.planner` and schema models.

## Global Constraints

- Do not recreate `src/editorial_carousel/strategy.py` or `ASSET_ADAPTER`.
- Do not modify production workflow, schemas, planner, renderer, asset resolver, or legacy migration code.
- Keep `src/editorial_carousel/legacy.py` as the only v1 checkpoint migration boundary.
- Preserve the existing negative-test intent and Human Review / Final Guard coverage.
- Do not call live providers or browsers.
- Preserve user-owned changes in the main checkout.

---

### Task 1: Migrate the beauty-account integration fixture

**Files:**
- Modify: `tests/integration/test_beauty_account_workflow.py`
- Test: `tests/integration/test_beauty_account_workflow.py`

**Interfaces:**
- Consumes: `build_visual_plan(contract, narrative_plan, publish_package, recent_signatures) -> VisualPlan`, `NarrativePlan`, `CarouselPayload`.
- Produces: schema-valid v2 storyboard dictionaries for the existing beauty workflow tests.

- [ ] **Step 1: Capture the existing RED signal**

Run:

```bash
pytest -q --collect-only tests/integration/test_beauty_account_workflow.py
```

Expected: collection exits `2` at the top-level import with `ModuleNotFoundError: No module named 'src.editorial_carousel.strategy'`.

- [ ] **Step 2: Replace the deleted import and add a canonical narrative fixture**

Replace the old strategy import with:

```python
from src.editorial_carousel import build_visual_plan
from src.schemas.narrative import NarrativeBeat, NarrativePlan
```

Add a deterministic fixture helper whose saveable beat is an exact member:

```python
def _beauty_narrative_plan() -> NarrativePlan:
    beats = [
        NarrativeBeat(beat_id="hook", kind="hook", purpose="指出通勤底妆搓泥问题"),
        NarrativeBeat(beat_id="diagnose", kind="diagnostic", purpose="判断搓泥发生环节"),
        NarrativeBeat(beat_id="explain", kind="explanation", purpose="解释成膜等待逻辑"),
        NarrativeBeat(beat_id="steps", kind="steps", purpose="给出通勤前调整步骤"),
        NarrativeBeat(beat_id="save", kind="checklist", purpose="整理可保存检查清单"),
        NarrativeBeat(beat_id="close", kind="action", purpose="按当天肤感微调"),
    ]
    return NarrativePlan(
        narrative_form="diagnostic_qa",
        beats=beats,
        saveable_beat=beats[4],
        closing_mode="action_prompt",
    )
```

Set the beauty contract to `proof_mode="none"`, matching the production assembler guard, and pass this plan into `HashTagInput.narrative_plan`.

- [ ] **Step 3: Rewrite the storyboard helper against v2 fields**

Use the complete planner call and bind optional slots by canonical ID:

```python
plan = build_visual_plan(
    contract,
    narrative_plan,
    publish_package,
    recent_signatures=[],
)
requirements = {item.slot_id: item for item in plan.required_assets}
for planned in plan.frame_plan:
    visual_slots = []
    for role in planned.asset_roles:
        slot_id = f"{planned.frame_id}-{role}"
        if slot_id in requirements:
            visual_slots.append(
                {
                    "slot_id": slot_id,
                    "role": role,
                    "semantic_tags": ["skincare"],
                }
            )
    frame = {
        "frame_id": planned.frame_id,
        "role": planned.role,
        "page_archetype": planned.page_archetype,
        "headline": (
            contract.first_screen_promise
            if planned.page_archetype == "cover"
            else planned.purpose
        ),
        "kicker": "通勤护肤",
        "content_blocks": [{"block_type": "text", "body": planned.purpose}],
        "emphasis": ["按需微调"],
        "visual_slots": visual_slots,
        "footer": "按肤感微调",
    }
```

Derive the helper's `publish_package` fields (`topic_id`, `angle_id`, `title`, `content`, `narrative_plan`, and `content_contract`) from the beauty fixture. Update every helper call to pass the same contract/narrative/package combination.

- [ ] **Step 4: Preserve the invalid-carousel test using a modern slot mismatch**

Text-only beauty frames legitimately have no slots. Replace the old indexed slot mutation with:

```python
storyboards[0]["visual_slots"].append(
    {
        "slot_id": "undeclared-product-texture",
        "role": "product_texture",
        "semantic_tags": ["skincare"],
    }
)
```

Expected: schema parsing succeeds, Carousel QA reports `asset_slot_binding_mismatch`, and the compiled graph routes to R1.

- [ ] **Step 5: Run the beauty file to GREEN**

Run `pytest -q tests/integration/test_beauty_account_workflow.py`.

Expected: all five tests pass, including the slot-binding and extra-field negative cases.

- [ ] **Step 6: Commit the beauty migration**

```bash
git add tests/integration/test_beauty_account_workflow.py
git commit -m "test: migrate beauty workflow to editorial v2"
```

---

### Task 2: Migrate the multi-domain integration fixture

**Files:**
- Modify: `tests/integration/test_domain_workflow.py`
- Test: `tests/integration/test_domain_workflow.py`

**Interfaces:**
- Consumes: `NarrativePlan`, v2 `VisualPlan`, `AssetRequirement.page_archetype`, `AssetManifestItem.page_archetype`, and `RenderedPage.page_archetype`.
- Produces: an offline domain graph harness whose doubles satisfy current editorial schemas while preserving routing/write-safety assertions.

- [ ] **Step 1: Verify the domain file remains RED independently**

Run `pytest -q --collect-only tests/integration/test_domain_workflow.py`.

Expected: collection exits `2` because the file still imports the deleted strategy adapter.

- [ ] **Step 2: Add one deterministic domain narrative plan and thread it through schemas**

Remove the strategy import, import `NarrativeBeat` and `NarrativePlan`, and add:

```python
def _domain_narrative_plan() -> NarrativePlan:
    beats = [
        NarrativeBeat(beat_id="hook", kind="hook", purpose="提出日常习惯问题"),
        NarrativeBeat(beat_id="scene", kind="scene", purpose="定位通勤前场景"),
        NarrativeBeat(beat_id="steps", kind="steps", purpose="拆解可执行步骤"),
        NarrativeBeat(beat_id="check", kind="checklist", purpose="整理保存清单"),
        NarrativeBeat(beat_id="boundary", kind="boundary", purpose="说明适用边界"),
        NarrativeBeat(beat_id="close", kind="action", purpose="选择一个动作开始"),
    ]
    return NarrativePlan(
        narrative_form="checklist_collection",
        beats=beats,
        saveable_beat=beats[3],
        closing_mode="action_prompt",
    )
```

Pass this plan into every `R2ContentSnapShoot` and `HashTagInput`. Add its JSON form to the assembler double under `narrative_plan`, `narrative_form`, and `closing_mode`.

- [ ] **Step 3: Rewrite `_structured_storyboards`**

Use the Task 1 slot-binding algorithm, retain the domain-specific copy, and emit `planned.page_archetype`. Never index `planned.asset_roles[0]`; zero-asset pages are valid.

- [ ] **Step 4: Update asset and render doubles to modern field names**

Replace every `requirement.layout` with `requirement.page_archetype`. Asset-manifest items must contain:

```python
{
    "slot_id": requirement.slot_id,
    "role": requirement.role,
    "page_archetype": requirement.page_archetype,
}
```

Catalog JSON retains the key `allowed_layouts`, with value `[requirement.page_archetype]`. Rendered-page doubles replace `layout` with `page_archetype` and include the selected `template_family`, `density="standard"`, `composition_variant="integration"`, `width=1080`, `height=1440`, plus the current probe metadata when schema validation reaches `RenderManifest`.

- [ ] **Step 5: Run the domain file to GREEN**

Run `pytest -q tests/integration/test_domain_workflow.py`.

Expected: all routing, evidence, R2, Human Review, rejection, and write-safety tests pass offline.

- [ ] **Step 6: Run both migrated files together**

```bash
pytest -q \
  tests/integration/test_beauty_account_workflow.py \
  tests/integration/test_domain_workflow.py
```

Expected: collection and execution pass without fixture-order coupling.

- [ ] **Step 7: Commit the domain migration**

```bash
git add tests/integration/test_domain_workflow.py
git commit -m "test: migrate domain workflow to editorial v2"
```

---

### Task 3: Verify the collection fix and repository differential

**Files:**
- Modify: `docs/README.md`
- Test: the two migrated integration files and existing planner/node tests.

**Interfaces:**
- Consumes: the two migrated integration files.
- Produces: fresh evidence that the deleted module is no longer imported and no new branch-only failure exists.

- [ ] **Step 1: Prove no stale import remains**

Run `rg -n "src\.editorial_carousel\.strategy|ASSET_ADAPTER" src tests`.

Expected: no match and exit code `1`.

- [ ] **Step 2: Run focused modern coverage**

```bash
pytest -q \
  tests/integration/test_beauty_account_workflow.py \
  tests/integration/test_domain_workflow.py \
  tests/editorial_carousel/test_strategy.py \
  tests/nodes/test_visual_strategy_planner.py
```

Expected: all selected tests pass.

- [ ] **Step 3: Confirm plain collection advances beyond the deleted module**

Run `pytest -q --collect-only`.

Expected: no `ModuleNotFoundError` for `src.editorial_carousel.strategy`; report any different collection issue separately.

- [ ] **Step 4: Run the offline broad suite and compare exact node IDs**

Run `pytest -q`.

Expected: the two former collection errors are absent. If unrelated failures remain, compare exact node IDs with the pre-change baseline; this task must add zero new failure IDs.

- [ ] **Step 5: Run static verification**

```bash
python -m compileall -q src main.py
git diff --check
git status --short --branch
```

Expected: compile and diff checks exit `0`; status has no uncommitted implementation files.

- [ ] **Step 6: Mark documentation implemented and commit**

Update the `Modern editorial integration tests` row in `docs/README.md` to point at this plan with status `已实施`, run `git diff --check`, and commit:

```bash
git add docs/README.md
git commit -m "docs: record editorial integration test migration"
```

## Plan self-review

- Spec coverage: both stale files, planner inputs, narrative schema, storyboard fields, asset/render metadata, negative-test intent, and verification are covered.
- Scope: production files remain untouched; no compatibility layer or unrelated baseline repair is included.
- Type consistency: planner calls use four inputs; frame/asset/render references use `page_archetype`; slots bind by canonical `slot_id`.
- Placeholder scan: no deferred implementation markers are present.
