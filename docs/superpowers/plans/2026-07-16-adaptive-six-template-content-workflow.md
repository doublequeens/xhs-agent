# Adaptive Six-Template Content Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the production workflow generate structurally varied copy, derive a 5–7-page semantic carousel from the same narrative plan, select exactly one of the six approved template families, and render adaptive 1080×1440 pages without changing locked visible text.

**Architecture:** Introduce a strict `NarrativePlan` that travels with the selected angle through outline, draft, editorial revision, assembly, and storyboard generation. Replace fixed visual recipes with a deterministic blueprint planner followed by a deterministic six-family selector; then render `template_family + page_archetype + density + composition_variant` through one deep renderer. Keep legacy compatibility in `src/editorial_carousel/legacy.py`, keep external-asset trust checks for declared slots, and preserve Carousel QA, Render QA, Human Review, Final Guard, ContentLock, and publish export.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, Playwright Chromium, HTML/CSS, Pillow, SQLite, pytest, `regex` for Unicode grapheme segmentation, repository-pinned Noto Color Emoji v2.051.

## Global Constraints

- Production output remains `1080 × 1440` PNG, 5–7 pages, plus an ordered contact sheet.
- Template mockup page counts are references only; every template family must support 5, 6, and 7 pages.
- Emoji remain allowed in copy and rendered pages; never silently remove or rewrite an emoji grapheme.
- A successful modern VisualPlan selects exactly one of `pink_red`, `deep_teal`, `soft_pink`, `coral_impact`, `green_catalog`, or `white_quote`.
- The planner determines semantic page count and order before template selection; template selection cannot add or remove pages.
- LLM output never contains HTML, CSS, arbitrary coordinates, font paths, local paths, remote URLs, or free-form rendering instructions.
- Renderer adaptation is limited to approved density and composition variants; no truncation, ellipsis, hidden text, whole-page scaling, or below-minimum font sizes.
- `VisualPlan`, `CarouselPayload`, `AssetManifest`, `RenderManifest`, and `ContentLock` producer/consumer order and hashes remain authoritative.
- Pure-text pages may have no asset slot. Any declared external asset still requires provider identity, license, containment, no-follow, transaction binding, human approval, and byte-hash checks.
- Do not bypass Carousel QA, Render QA, Human Review, or Final Guard.
- Do not change ContentLock facts, title, steps, judgments, or visible strings as a visual rescue.
- Legacy checkpoint adaptation remains isolated in `src/editorial_carousel/legacy.py`.
- Tests remain offline by default. Do not set `RUN_LIVE_ASSET_PROVIDER_TESTS=1` during routine verification.
- Protect existing user changes; do not reset, clean, delete databases, or overwrite canonical publish artifacts.

## File and Interface Map

### New semantic modules

- `src/schemas/narrative.py` — `NarrativeForm`, `NarrativeBeatKind`, `NarrativeBeat`, `NarrativePlan`, and `ClosingMode`.
- `src/schemas/editorial_templates.py` — `TemplateFamily`, `PageArchetype`, `Density`, `TemplateSelection`, `CopyMetrics`, and resolved variant types.
- `src/editorial_carousel/blueprints.py` — finite narrative blueprint catalog and exact 5–7-page materialization.
- `src/editorial_carousel/selector.py` — deterministic six-family scoring and stable tie-break.
- `src/editorial_carousel/planner.py` — public
  `build_visual_plan(contract, narrative_plan, publish_package, recent_signatures) -> VisualPlan`
  interface replacing fixed recipes.

### New renderer modules

- `src/rendering/editorial/template_registry.py` — six family tokens, font capabilities, archetype capabilities, density minima, and composition variant allowlists.
- `src/rendering/editorial/copy_metrics.py` — grapheme, CJK, Latin word, emoji, block, item, and line estimation.
- `src/rendering/editorial/variant_resolver.py` — deterministic
  `resolve_variant(family, archetype, hint, metrics) -> ResolvedVariant`.
- `src/rendering/editorial/primitives.py` — escaped visible-copy atoms and shared HTML primitives.
- `src/rendering/editorial/templates/pink_red.py`
- `src/rendering/editorial/templates/deep_teal.py`
- `src/rendering/editorial/templates/soft_pink.py`
- `src/rendering/editorial/templates/coral_impact.py`
- `src/rendering/editorial/templates/green_catalog.py`
- `src/rendering/editorial/templates/white_quote.py`

### Existing modules to replace or modify

- Semantic flow: `src/schemas/angle.py`, `src/schemas/novelty_guard.py`, `src/schemas/virality_score.py`, `src/schemas/outline.py`, `src/schemas/draft.py`, `src/schemas/title_ranker.py`, `src/schemas/decision.py`, `src/schemas/agent_state.py`.
- Nodes/prompts: angle, novelty, scoring, outline, draft, title ranking, decision, R1, R2, assembler, visual planner, storyboard generator.
- Editorial contracts: `src/schemas/visual_plan.py`, `src/schemas/storyboard.py`, `src/schemas/assets.py`, `src/schemas/render_manifest.py`.
- QA/rendering: `src/nodes/node_p_carousel_qa.py`, `src/nodes/node_p_render_qa.py`, `src/rendering/editorial/renderer.py`, `src/rendering/editorial/probes.py`.
- Persistence/migration: `memory/models.py`, `memory/schema.sql`, `memory/migrations.py`, `memory/memory_manager.py`, `memory/memory_context.py`, `src/nodes/node_p_content_writer.py`, `src/editorial_carousel/legacy.py`.
- Mockups/docs: `examples/templates-mockup/**`, `examples/templates-mockup/README.md`, `README.md`, `docs/architecture/editorial-contracts.md`.

---

### Task 1: Add the strict narrative contract and propagate it through schemas

**Files:**
- Create: `src/schemas/narrative.py`
- Modify: `src/schemas/__init__.py`
- Modify: `src/schemas/angle.py`
- Modify: `src/schemas/novelty_guard.py`
- Modify: `src/schemas/virality_score.py`
- Modify: `src/schemas/outline.py`
- Modify: `src/schemas/draft.py`
- Modify: `src/schemas/title_ranker.py`
- Modify: `src/schemas/decision.py`
- Modify: `src/schemas/agent_state.py`
- Test: `tests/schemas/test_narrative.py`
- Test: `tests/nodes/test_metadata_flow.py`

**Interfaces:**
- Produces: `NarrativePlan`, attached as `narrative_plan` to every selected-content schema.
- Consumes: Existing topic/angle identity fields.
- Required invariant: `saveable_beat` must exactly equal one member of `beats`; beat IDs must be unique.

- [ ] **Step 1: Write failing narrative-schema tests**

```python
# tests/schemas/test_narrative.py
import pytest
from pydantic import ValidationError

from src.schemas.narrative import NarrativePlan


PLAN = {
    "narrative_form": "cognitive_correction",
    "beats": [
        {"beat_id": "hook", "kind": "hook", "purpose": "提出常见误区"},
        {"beat_id": "mistake", "kind": "misconception", "purpose": "展示误区"},
        {"beat_id": "reveal", "kind": "reveal", "purpose": "给出反转"},
        {"beat_id": "action", "kind": "action", "purpose": "给出替代动作"},
    ],
    "saveable_beat": {
        "beat_id": "action",
        "kind": "action",
        "purpose": "给出替代动作",
    },
    "closing_mode": "none",
}


def test_narrative_plan_accepts_supported_form_and_embedded_saveable_beat():
    plan = NarrativePlan.model_validate(PLAN)
    assert plan.narrative_form == "cognitive_correction"
    assert plan.saveable_beat == plan.beats[-1]


def test_narrative_plan_rejects_saveable_beat_not_in_beats():
    broken = {
        **PLAN,
        "saveable_beat": {
            "beat_id": "missing",
            "kind": "summary",
            "purpose": "不存在",
        },
    }
    with pytest.raises(ValidationError, match="saveable_beat"):
        NarrativePlan.model_validate(broken)


def test_narrative_plan_rejects_duplicate_beat_ids():
    broken = {
        **PLAN,
        "beats": [PLAN["beats"][0], PLAN["beats"][0], *PLAN["beats"][2:]],
    }
    with pytest.raises(ValidationError, match="beat IDs"):
        NarrativePlan.model_validate(broken)
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```bash
pytest -q tests/schemas/test_narrative.py
```

Expected: collection fails with `ModuleNotFoundError: No module named 'src.schemas.narrative'`.

- [ ] **Step 3: Implement `NarrativePlan`**

```python
# src/schemas/narrative.py
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NarrativeForm = Literal[
    "cognitive_correction",
    "step_tutorial",
    "checklist_collection",
    "comparison",
    "diagnostic_qa",
    "scenario_story",
    "story_reversal",
    "reflective_editorial",
]
NarrativeBeatKind = Literal[
    "hook",
    "scene",
    "tension",
    "misconception",
    "reveal",
    "principle",
    "explanation",
    "example",
    "steps",
    "checklist",
    "comparison",
    "diagnostic",
    "qa",
    "quote",
    "boundary",
    "summary",
    "action",
]
ClosingMode = Literal[
    "none",
    "boundary",
    "reflection",
    "focused_question",
    "action_prompt",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NarrativeBeat(StrictModel):
    beat_id: str = Field(min_length=1, max_length=48)
    kind: NarrativeBeatKind
    purpose: str = Field(min_length=1, max_length=160)


class NarrativePlan(StrictModel):
    narrative_form: NarrativeForm
    beats: list[NarrativeBeat] = Field(min_length=4, max_length=8)
    saveable_beat: NarrativeBeat
    closing_mode: ClosingMode

    @model_validator(mode="after")
    def validate_beats(self):
        beat_ids = [beat.beat_id for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("narrative beat IDs must be unique")
        if self.saveable_beat not in self.beats:
            raise ValueError("saveable_beat must exactly match one narrative beat")
        return self
```

Export all five public names from `src/schemas/__init__.py`.

- [ ] **Step 4: Add `narrative_plan` to every selected-content schema**

Use this exact field on `ContentAngle`, `NoveltyCheckResult`, `ScoreResult`, `OutlineItem`,
`DraftItem`, `TitleWinner`, `ContentCandidate`, `R2ContentSnapShoot`, and `HashTagInput`:

```python
from .narrative import NarrativePlan

narrative_plan: NarrativePlan
```

Add `selected_narrative_plan: NotRequired[Optional[NarrativePlan]]` to `AgentState`.

- [ ] **Step 5: Add a propagation regression test**

In `tests/nodes/test_metadata_flow.py`, extend the existing title-ranker → decision → hashtag fixture with:

```python
assert result["final_content"].narrative_plan.narrative_form == "scenario_story"
assert (
    result["final_content"].narrative_plan.saveable_beat.beat_id
    == "lesson"
)
```

Use one fixture `NarrativePlan` whose four beats are `hook`, `scene`, `reveal`, and
`lesson`, with `closing_mode="reflection"`.

- [ ] **Step 6: Run focused schema and metadata tests**

Run:

```bash
pytest -q tests/schemas/test_narrative.py tests/nodes/test_metadata_flow.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/schemas tests/schemas/test_narrative.py tests/nodes/test_metadata_flow.py
git commit -m "feat: add narrative plan contract"
```

---

### Task 2: Make writing structure follow narrative beats instead of one fixed outline

**Files:**
- Modify: `src/prompts/base/angle_strategist.txt`
- Modify: `src/prompts/base/novelty_guard.txt`
- Modify: `src/prompts/base/virality_scorer.txt`
- Modify: `src/prompts/base/outline_architect.txt`
- Modify: `src/prompts/base/draft_writer.txt`
- Modify: `src/prompts/base/title_ranker.txt`
- Modify: `src/prompts/base/decision_engine.txt`
- Modify: `src/prompts/base/r1_reflector.txt`
- Modify: `src/prompts/base/r2_compliance.txt`
- Modify: `src/nodes/node_b_angle_strategist.py`
- Modify: `src/nodes/node_b_novelty_guard.py`
- Modify: `src/nodes/node_c_virality_scorer.py`
- Modify: `src/nodes/node_d_outline_architect.py`
- Modify: `src/nodes/node_e_draft_writer.py`
- Modify: `src/nodes/node_j_decision_engine.py`
- Modify: `src/nodes/node_h_r1_reflector.py`
- Modify: `src/nodes/node_i_r2_compliance.py`
- Test: `tests/prompts/test_composer.py`
- Test: `tests/nodes/test_metadata_flow.py`
- Test: `tests/nodes/test_domain_nodes.py`

**Interfaces:**
- Consumes: `NarrativePlan` from Task 1.
- Produces: Copy whose shape follows `NarrativePlan.beats`.
- Invariant: Emoji are permitted but never mandatory; `closing_mode="none"` must not force a question.

- [ ] **Step 1: Write failing prompt-contract tests**

Add to `tests/prompts/test_composer.py`:

```python
def test_outline_prompt_follows_narrative_beats_without_fixed_six_part_order():
    prompt = compose_prompt("outline_architect", get_domain_profile("beauty"))
    assert "narrative_plan.beats" in prompt
    assert "主体展开（至少 3 个逻辑分点）" not in prompt
    assert "必须依次包含" not in prompt
    assert "每篇必须以互动问题收尾" not in prompt


def test_draft_prompt_allows_emoji_and_respects_none_closing_mode():
    prompt = compose_prompt("draft_writer", get_domain_profile("beauty"))
    assert "emoji" in prompt
    assert "不得使用 emoji" not in prompt
    assert "closing_mode=none" in prompt
    assert "必须互动收尾" not in prompt


def test_angle_prompt_requires_narrative_plan_and_cross_angle_form_variety():
    prompt = compose_prompt("angle_strategist", get_domain_profile("beauty"))
    assert '"narrative_plan"' in prompt
    assert "至少使用两种不同 narrative_form" in prompt
```

- [ ] **Step 2: Run prompt tests and verify RED**

Run:

```bash
pytest -q tests/prompts/test_composer.py
```

Expected: FAIL because the current prompts contain the fixed six-part outline and omit
`narrative_plan`.

- [ ] **Step 3: Replace the angle output contract**

In `src/prompts/base/angle_strategist.txt`, require each angle object to contain:

```json
{
  "angle_id": "ag_001",
  "angle": "string",
  "opening_hook": "string",
  "value_promise": "string",
  "suggested_structure": "one-sentence human-readable summary",
  "narrative_plan": {
    "narrative_form": "cognitive_correction | step_tutorial | checklist_collection | comparison | diagnostic_qa | scenario_story | story_reversal | reflective_editorial",
    "beats": [
      {
        "beat_id": "stable_short_id",
        "kind": "hook | scene | tension | misconception | reveal | principle | explanation | example | steps | checklist | comparison | diagnostic | qa | quote | boundary | summary | action",
        "purpose": "one semantic writing task"
      }
    ],
    "saveable_beat": {
      "beat_id": "must match a beat above",
      "kind": "must match the same beat above",
      "purpose": "must match the same beat above"
    },
    "closing_mode": "none | boundary | reflection | focused_question | action_prompt"
  }
}
```

Add hard rules:

- Three angles for one topic use at least two different narrative forms unless the
  content policy makes alternatives unsafe.
- Beat count is 4–8.
- Emoji may appear naturally in eventual copy, but narrative purposes remain plain semantic
  descriptions.

- [ ] **Step 4: Replace fixed outline and draft instructions**

Make `outline_architect` say:

```text
- 严格按照 score_result.narrative_plan.beats 的顺序组织大纲。
- 每个 beat 只完成它声明的 purpose；不得自动补“至少三个分点”。
- saveable_beat 必须成为可独立保存的内容单元，但不固定在倒数第二段。
- closing_mode=none 时自然结束；不得补互动问题。
- closing_mode=focused_question 时只提出一个与正文决策直接相关的问题。
- emoji 允许但不强制；不得用 emoji 代替风险边界或事实。
```

Make `draft_writer` say:

```text
- 保留 outline.narrative_plan，不改变 narrative_form、beats 或 closing_mode。
- 不输出结构提示词或 beat ID。
- closing_mode=none 时正文可以自然结束。
- emoji 可以用于语气、条目标记和扫读层级，但不得堆叠或替代信息。
```

Remove the fixed six-part outline and mandatory interactive ending from both prompt variants
under `src/prompts/base/`; do not edit retired prompt files outside the active composer route.

- [ ] **Step 5: Preserve narrative metadata through novelty, scoring, title selection, R1, R2, and decision**

Update each output prompt contract to copy `narrative_plan` byte-for-byte from its selected
input. In node code, add a deterministic post-model check:

```python
def _require_same_narrative_plan(actual, expected, *, stage: str) -> None:
    actual_plan = NarrativePlan.model_validate(actual)
    expected_plan = NarrativePlan.model_validate(expected)
    if actual_plan != expected_plan:
        raise ValueError(f"{stage} must preserve the selected narrative_plan")
```

Call it after model parsing in novelty, scoring, outline, draft, title ranker, R1, and R2.
For decision-engine output, inject the selected plan from `state["scores"]` by matching
`topic_id` and `angle_id`; do not trust the model to recreate it.

- [ ] **Step 6: Add closing-mode and preservation node tests**

In `tests/nodes/test_domain_nodes.py`, construct schema-valid fake outline and draft model
responses with the same `NarrativePlan`, invoke the existing outline and draft node entry
points using the file's monkeypatch style, and add:

```python
def test_outline_and_draft_preserve_none_closing_mode(monkeypatch):
    narrative = narrative_plan("scenario_story", closing_mode="none")
    outline = invoke_outline_node(monkeypatch, narrative=narrative)
    draft = invoke_draft_node(
        monkeypatch,
        outline=outline,
        draft_md="她停下来观察变化，然后按边界结束。",
    )
    assert outline.narrative_plan == narrative
    assert draft.narrative_plan == narrative
    assert "你呢" not in draft.draft_md
    assert "评论区" not in draft.draft_md
```

Add the small test-only `narrative_plan`, `invoke_outline_node`, and `invoke_draft_node`
helpers beside the new tests. They must call the real node functions and replace only the
model invocation boundary; they must not duplicate production preservation logic.

Add a negative test where the fake novelty or scorer model changes `narrative_form`; expect
`ValueError` containing `must preserve the selected narrative_plan`.

- [ ] **Step 7: Run focused writing-flow tests**

Run:

```bash
pytest -q tests/prompts/test_composer.py tests/nodes/test_domain_nodes.py tests/nodes/test_metadata_flow.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/prompts/base src/nodes tests/prompts/test_composer.py tests/nodes/test_domain_nodes.py tests/nodes/test_metadata_flow.py
git commit -m "feat: vary copy structure by narrative plan"
```

---

### Task 3: Remove assembler reclassification and make narrative metadata authoritative

**Files:**
- Modify: `src/prompts/base/assembler.txt`
- Modify: `src/nodes/node_o_assembler.py`
- Modify: `src/nodes/publish_patch.py`
- Modify: `src/schemas/decision.py`
- Test: `tests/nodes/test_metadata_flow.py`
- Test: `tests/nodes/test_publish_metadata.py`
- Test: `tests/prompts/test_composer.py`

**Interfaces:**
- Consumes: `HashTagInput.narrative_plan`.
- Produces: `publish_package["narrative_plan"]`, `narrative_form`, and `closing_mode`.
- Removes: modern `storyboard_strategy`.

- [ ] **Step 1: Write failing assembler tests**

```python
def test_assembler_injects_authoritative_narrative_metadata_and_ignores_model_strategy():
    result = assembler_node(state_with_narrative_plan())
    package = result["publish_package"]
    assert package["narrative_plan"] == state["final_content"].narrative_plan.model_dump(mode="json")
    assert package["narrative_form"] == "comparison"
    assert package["closing_mode"] == "boundary"
    assert "storyboard_strategy" not in package
```

Add a prompt test:

```python
def test_assembler_prompt_does_not_reclassify_storyboard_strategy():
    prompt = compose_prompt("assembler", get_domain_profile("beauty"))
    assert "storyboard_strategy" not in prompt
    assert "narrative_plan" in prompt
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/nodes/test_metadata_flow.py tests/nodes/test_publish_metadata.py tests/prompts/test_composer.py
```

Expected: FAIL because `storyboard_strategy` is still emitted and narrative metadata is absent.

- [ ] **Step 3: Replace assembler output shape**

Make the assembler model responsible only for:

```json
{
  "images": [],
  "hashtags": ["#夏日护肤"],
  "notes": []
}
```

Then inject:

```python
narrative_plan = final_content.narrative_plan.model_dump(mode="json")
publish_package_json.update(
    {
        "narrative_plan": narrative_plan,
        "narrative_form": narrative_plan["narrative_form"],
        "closing_mode": narrative_plan["closing_mode"],
    }
)
publish_package_json.pop("storyboard_strategy", None)
```

Add `narrative_plan`, `narrative_form`, and `closing_mode` to
`ASSEMBLER_AUTHORITATIVE_FIELDS`; remove `storyboard_strategy` from active tests and active
prompt output.

- [ ] **Step 4: Run focused assembler tests**

Run:

```bash
pytest -q tests/nodes/test_metadata_flow.py tests/nodes/test_publish_metadata.py tests/prompts/test_composer.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/prompts/base/assembler.txt src/nodes/node_o_assembler.py src/nodes/publish_patch.py src/schemas/decision.py tests/nodes/test_metadata_flow.py tests/nodes/test_publish_metadata.py tests/prompts/test_composer.py
git commit -m "refactor: make narrative metadata authoritative"
```

---

### Task 4: Introduce template, archetype, density, and v2 visual contracts

**Files:**
- Create: `src/schemas/editorial_templates.py`
- Modify: `src/schemas/visual_plan.py`
- Modify: `src/schemas/storyboard.py`
- Modify: `src/schemas/assets.py`
- Modify: `src/schemas/render_manifest.py`
- Modify: `src/schemas/decision.py`
- Modify: `src/schemas/__init__.py`
- Test: `tests/schemas/test_editorial_templates.py`
- Modify: `tests/schemas/test_editorial_carousel.py`

**Interfaces:**
- Produces: v2 `VisualPlan`, `CarouselPayload`, `AssetRequirement`, `AssetManifestItem`,
  `RenderManifest`.
- Replaces: public `layout` with semantic `page_archetype`.
- Invariant: all rendered pages in one manifest use one template family.

- [ ] **Step 1: Write failing template-contract tests**

```python
# tests/schemas/test_editorial_templates.py
import pytest
from pydantic import ValidationError

from src.schemas.editorial_templates import CopyMetrics, TemplateSelection


def test_template_selection_accepts_exactly_one_of_six_families():
    selection = TemplateSelection(
        template_family="green_catalog",
        score=82,
        reasons=["checklist affinity"],
        rejected_families={
            "pink_red": ["recent repetition"],
            "deep_teal": ["lower item-cardinality fit"],
            "soft_pink": ["lower density fit"],
            "coral_impact": ["lower tone fit"],
            "white_quote": ["dense list"],
        },
    )
    assert selection.template_family == "green_catalog"


def test_copy_metrics_rejects_negative_counts():
    with pytest.raises(ValidationError):
        CopyMetrics(
            grapheme_count=-1,
            cjk_count=0,
            latin_word_count=0,
            emoji_count=0,
            block_count=0,
            item_count=0,
            max_item_graphemes=0,
            estimated_lines=0,
        )
```

Extend `tests/schemas/test_editorial_carousel.py` with a v2 plan asserting:

```python
assert plan.design_system == "beauty_editorial_v2"
assert plan.template_family == "deep_teal"
assert [frame.page_archetype for frame in plan.frame_plan][0] == "cover"
assert 5 <= len(plan.frame_plan) <= 7
assert plan.required_assets == []
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/schemas/test_editorial_templates.py tests/schemas/test_editorial_carousel.py
```

Expected: FAIL because the v2 contracts do not exist.

- [ ] **Step 3: Implement `editorial_templates.py`**

```python
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator


TemplateFamily = Literal[
    "pink_red",
    "deep_teal",
    "soft_pink",
    "coral_impact",
    "green_catalog",
    "white_quote",
]
PageArchetype = Literal[
    "cover",
    "thesis",
    "scene",
    "story_beat",
    "explanation",
    "steps",
    "checklist",
    "comparison",
    "diagnostic",
    "qa",
    "item_collection",
    "quote",
    "boundary",
    "save",
    "closing",
]
Density = Literal["sparse", "standard", "dense"]
DensityHint = Literal["auto", "sparse", "standard", "dense"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateSelection(StrictModel):
    template_family: TemplateFamily
    score: int
    reasons: list[str] = Field(min_length=1)
    rejected_families: dict[TemplateFamily, list[str]]

    @model_validator(mode="after")
    def require_all_other_families(self):
        expected = set(get_args(TemplateFamily)) - {self.template_family}
        if set(self.rejected_families) != expected:
            raise ValueError(
                "rejected_families must contain every unselected family"
            )
        return self


class CopyMetrics(StrictModel):
    grapheme_count: int = Field(ge=0)
    cjk_count: int = Field(ge=0)
    latin_word_count: int = Field(ge=0)
    emoji_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    max_item_graphemes: int = Field(ge=0)
    estimated_lines: int = Field(ge=0)


class ResolvedVariant(StrictModel):
    density: Density
    composition_variant: str = Field(min_length=1, max_length=64)
    metrics: CopyMetrics
```

- [ ] **Step 4: Replace the v1 visual and storyboard fields**

Use these exact shapes:

```python
class FramePlanItem(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    page_archetype: PageArchetype
    purpose: str = Field(min_length=1, max_length=160)
    allowed_density: list[Density] = Field(min_length=1, max_length=3)
    asset_roles: list[str] = Field(default_factory=list, max_length=4)


class VisualPlan(StrictModel):
    design_system: Literal["beauty_editorial_v2"]
    template_family: TemplateFamily
    template_selection: TemplateSelection
    narrative_form: NarrativeForm
    content_job: ContentJob
    frame_plan: list[FramePlanItem] = Field(min_length=5, max_length=7)
    required_assets: list[AssetRequirement]
```

`CarouselFrame` replaces `layout` with `page_archetype` and adds
`content_density_hint: DensityHint = "auto"`.

`AssetRequirement` and `AssetManifestItem` replace `layout` with
`page_archetype: PageArchetype`.

`RenderedPage` adds `page_archetype`, `template_family`, `density`, and
`composition_variant`; remove its old `layout`.

`StoryboardVisibleText` replaces `layout` with `page_archetype`.

Keep `allowed_layouts` only as the persisted key inside the existing asset catalog manifest.
Modern schemas and graph nodes use `page_archetype`; catalog eligibility compares
`requirement.page_archetype` with the entry's persisted `allowed_layouts`.

Keep `ContentContract.primary_visual_family` during the v2 migration because older topics,
memory rows, and checkpoints contain it. Treat it only as a backward-compatible semantic
hint: neither `build_visual_plan` nor `select_template` may map it directly to a template
family, and new template-selection tests must prove that changing only this field does not
change frame count.

- [ ] **Step 5: Add v2 validators**

In `VisualPlan` and `CarouselPayload`, validate:

```python
if frames[0].page_archetype != "cover":
    raise ValueError("first frame page_archetype must be cover")
if not any(frame.page_archetype in {"save", "checklist", "comparison"} for frame in frames):
    raise ValueError("frame plan must include a standalone saveable archetype")
```

In `RenderManifest`, validate that every page has one template family:

```python
families = {page.template_family for page in self.pages}
if len(families) != 1:
    raise ValueError("all rendered pages must use one template family")
```

- [ ] **Step 6: Run schema tests**

Run:

```bash
pytest -q tests/schemas/test_editorial_templates.py tests/schemas/test_editorial_carousel.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/schemas tests/schemas/test_editorial_templates.py tests/schemas/test_editorial_carousel.py
git commit -m "feat: add six-template visual contracts"
```

---

### Task 5: Replace fixed recipes with narrative blueprints and deterministic template selection

**Files:**
- Create: `src/editorial_carousel/blueprints.py`
- Create: `src/editorial_carousel/selector.py`
- Create: `src/editorial_carousel/planner.py`
- Modify: `src/editorial_carousel/__init__.py`
- Delete: `src/editorial_carousel/strategy.py`
- Modify: `src/nodes/node_p_visual_strategy_planner.py`
- Test: `tests/editorial_carousel/test_blueprints.py`
- Test: `tests/editorial_carousel/test_selector.py`
- Replace: `tests/editorial_carousel/test_strategy.py`
- Modify: `tests/nodes/test_visual_strategy_planner.py`

**Interfaces:**
- Public: `build_visual_plan(contract, narrative_plan, publish_package, recent_signatures) -> VisualPlan`.
- Ordering: materialize frame plan first, select family second.
- Invariant: every narrative form has three finite blueprints, and every materialized plan is 5–7 pages.

- [ ] **Step 1: Write failing blueprint tests**

```python
from src.editorial_carousel.blueprints import BLUEPRINTS, materialize_blueprint


def test_every_narrative_form_has_three_blueprints_supporting_five_six_and_seven_pages():
    assert len(BLUEPRINTS) == 8
    for blueprints in BLUEPRINTS.values():
        assert len(blueprints) == 3
        for blueprint in blueprints:
            assert [len(materialize_blueprint(blueprint, count)) for count in (5, 6, 7)] == [5, 6, 7]


def test_materialized_blueprint_always_starts_with_cover_and_contains_saveable_page():
    for blueprints in BLUEPRINTS.values():
        for blueprint in blueprints:
            pages = materialize_blueprint(blueprint, 7)
            assert pages[0] == "cover"
            assert set(pages) & {"save", "checklist", "comparison"}
```

- [ ] **Step 2: Write failing selector tests**

```python
from src.editorial_carousel.selector import select_template


def test_selector_returns_only_approved_family_and_is_deterministic():
    first = select_template(selector_input(), recent_signatures=[])
    second = select_template(selector_input(), recent_signatures=[])
    assert first == second
    assert first.template_family in {
        "pink_red",
        "deep_teal",
        "soft_pink",
        "coral_impact",
        "green_catalog",
        "white_quote",
    }


def test_recent_family_penalty_changes_equal_fit_tie_without_changing_page_count():
    selector_value = equal_fit_input()
    original_pages = selector_value.page_archetypes
    baseline = select_template(selector_value, recent_signatures=[])
    repeated = select_template(
        selector_value,
        recent_signatures=[{"template_family": baseline.template_family}],
    )
    assert repeated.template_family != baseline.template_family
    assert selector_value.page_archetypes == original_pages
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
pytest -q tests/editorial_carousel/test_blueprints.py tests/editorial_carousel/test_selector.py
```

Expected: collection fails because the modules do not exist.

- [ ] **Step 4: Implement finite blueprint objects**

Use:

```python
from dataclasses import dataclass

from src.schemas.editorial_templates import PageArchetype
from src.schemas.narrative import NarrativeForm


@dataclass(frozen=True)
class FrameBlueprint:
    blueprint_id: str
    narrative_form: NarrativeForm
    required: tuple[PageArchetype, ...]
    optional: tuple[PageArchetype, PageArchetype]


def materialize_blueprint(
    blueprint: FrameBlueprint,
    frame_count: int,
) -> tuple[PageArchetype, ...]:
    if frame_count not in {5, 6, 7}:
        raise ValueError("frame_count must be 5, 6, or 7")
    return blueprint.required + blueprint.optional[: frame_count - 5]
```

Define exactly three blueprints per form. Each `required` tuple has five archetypes and each
`optional` tuple has two:

```python
BLUEPRINTS = {
    "cognitive_correction": (
        FrameBlueprint("correction-reveal", "cognitive_correction", ("cover", "scene", "diagnostic", "explanation", "save"), ("comparison", "boundary")),
        FrameBlueprint("correction-contrast", "cognitive_correction", ("cover", "comparison", "explanation", "steps", "save"), ("scene", "boundary")),
        FrameBlueprint("correction-qa", "cognitive_correction", ("cover", "qa", "diagnostic", "explanation", "checklist"), ("story_beat", "boundary")),
    ),
    "step_tutorial": (
        FrameBlueprint("tutorial-linear", "step_tutorial", ("cover", "scene", "steps", "diagnostic", "save"), ("explanation", "boundary")),
        FrameBlueprint("tutorial-checkpoint", "step_tutorial", ("cover", "explanation", "steps", "qa", "checklist"), ("comparison", "boundary")),
        FrameBlueprint("tutorial-example", "step_tutorial", ("cover", "story_beat", "steps", "comparison", "save"), ("diagnostic", "boundary")),
    ),
    "checklist_collection": (
        FrameBlueprint("collection-catalog", "checklist_collection", ("cover", "scene", "item_collection", "checklist", "save"), ("comparison", "boundary")),
        FrameBlueprint("collection-filter", "checklist_collection", ("cover", "thesis", "item_collection", "diagnostic", "checklist"), ("qa", "boundary")),
        FrameBlueprint("collection-use", "checklist_collection", ("cover", "item_collection", "explanation", "steps", "save"), ("comparison", "boundary")),
    ),
    "comparison": (
        FrameBlueprint("comparison-rule", "comparison", ("cover", "scene", "comparison", "diagnostic", "save"), ("explanation", "boundary")),
        FrameBlueprint("comparison-options", "comparison", ("cover", "thesis", "comparison", "qa", "checklist"), ("story_beat", "boundary")),
        FrameBlueprint("comparison-story", "comparison", ("cover", "story_beat", "comparison", "explanation", "save"), ("diagnostic", "boundary")),
    ),
    "diagnostic_qa": (
        FrameBlueprint("diagnostic-branches", "diagnostic_qa", ("cover", "scene", "diagnostic", "qa", "save"), ("explanation", "boundary")),
        FrameBlueprint("diagnostic-checklist", "diagnostic_qa", ("cover", "qa", "diagnostic", "checklist", "boundary"), ("comparison", "save")),
        FrameBlueprint("diagnostic-story", "diagnostic_qa", ("cover", "story_beat", "diagnostic", "explanation", "save"), ("qa", "boundary")),
    ),
    "scenario_story": (
        FrameBlueprint("story-discovery", "scenario_story", ("cover", "scene", "story_beat", "explanation", "save"), ("steps", "boundary")),
        FrameBlueprint("story-tension", "scenario_story", ("cover", "scene", "story_beat", "comparison", "checklist"), ("explanation", "boundary")),
        FrameBlueprint("story-reflection", "scenario_story", ("cover", "story_beat", "explanation", "quote", "save"), ("scene", "boundary")),
    ),
    "story_reversal": (
        FrameBlueprint("reversal-reveal", "story_reversal", ("cover", "scene", "story_beat", "explanation", "save"), ("comparison", "boundary")),
        FrameBlueprint("reversal-diagnostic", "story_reversal", ("cover", "story_beat", "diagnostic", "steps", "checklist"), ("explanation", "boundary")),
        FrameBlueprint("reversal-contrast", "story_reversal", ("cover", "comparison", "story_beat", "explanation", "save"), ("qa", "boundary")),
    ),
    "reflective_editorial": (
        FrameBlueprint("editorial-thesis", "reflective_editorial", ("cover", "quote", "explanation", "scene", "save"), ("story_beat", "boundary")),
        FrameBlueprint("editorial-story", "reflective_editorial", ("cover", "scene", "story_beat", "quote", "save"), ("explanation", "boundary")),
        FrameBlueprint("editorial-principle", "reflective_editorial", ("cover", "thesis", "explanation", "quote", "checklist"), ("scene", "boundary")),
    ),
}
```

- [ ] **Step 5: Implement exact frame-count and recent-blueprint selection**

Compute target count:

```python
target_count = max(
    5,
    min(
        7,
        max(contract.recommended_frame_count, len(narrative_plan.beats)),
    ),
)
```

Implement these exact helper signatures in `planner.py`:

```text
plan_frames(
    contract: ContentContract,
    narrative_plan: NarrativePlan,
    publish_package: Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> list[FramePlanItem]

required_assets_for(
    frame_plan: Sequence[FramePlanItem],
    contract: ContentContract,
) -> list[AssetRequirement]
```

`plan_frames` computes the target count above, chooses one blueprint, materializes it, and
returns stable `FramePlanItem` values in order. `required_assets_for` returns `[]` when
`proof_mode == "none"`; otherwise it emits requirements only for frames whose archetype
declares the matching proof role. The public signatures and return types are fixed.

Rank blueprints by:

1. Required archetypes matching beat kinds.
2. Saveable beat compatibility.
3. Exact recent blueprint-signature penalty.
4. Stable SHA-256 tie-break over `topic_id|angle_id|blueprint_id`.

Create one `FramePlanItem` per materialized archetype. Use stable IDs such as
`frame-01-cover`; set `allowed_density=["sparse", "standard", "dense"]` for prose archetypes
and `["standard", "dense"]` for collection archetypes.

- [ ] **Step 6: Implement deterministic template scoring**

Define the selector input before the scoring tables:

```python
@dataclass(frozen=True)
class SelectorInput:
    topic_id: str
    angle_id: str
    narrative_form: NarrativeForm
    content_job: ContentJob
    page_archetypes: tuple[PageArchetype, ...]
    estimated_density: Density
    proof_mode: str

    @property
    def frame_count(self) -> int:
        return len(self.page_archetypes)

    @classmethod
    def from_content(
        cls,
        contract: ContentContract,
        narrative_plan: NarrativePlan,
        publish_package: Mapping[str, Any],
        frame_plan: Sequence[FramePlanItem],
    ) -> "SelectorInput":
        copy_size = len(
            str(publish_package.get("title") or "")
            + str(publish_package.get("content") or "")
        )
        estimated_density: Density = (
            "sparse"
            if copy_size <= 350
            else "standard"
            if copy_size <= 900
            else "dense"
        )
        return cls(
            topic_id=str(publish_package.get("topic_id") or ""),
            angle_id=str(publish_package.get("angle_id") or ""),
            narrative_form=narrative_plan.narrative_form,
            content_job=contract.content_job,
            page_archetypes=tuple(
                frame.page_archetype for frame in frame_plan
            ),
            estimated_density=estimated_density,
            proof_mode=contract.proof_mode,
        )
```

Use integer score tables:

```python
FORM_AFFINITY = {
    "pink_red": {"cognitive_correction": 28, "step_tutorial": 24, "checklist_collection": 18},
    "deep_teal": {"step_tutorial": 24, "checklist_collection": 24, "diagnostic_qa": 20, "reflective_editorial": 18},
    "soft_pink": {"scenario_story": 26, "diagnostic_qa": 24, "reflective_editorial": 20},
    "coral_impact": {"story_reversal": 28, "cognitive_correction": 26, "step_tutorial": 22},
    "green_catalog": {"checklist_collection": 30, "comparison": 26, "diagnostic_qa": 20},
    "white_quote": {"reflective_editorial": 30, "scenario_story": 26, "story_reversal": 18},
}
DENSITY_AFFINITY = {
    "pink_red": {"sparse": 12, "standard": 18, "dense": 12},
    "deep_teal": {"sparse": 18, "standard": 20, "dense": 18},
    "soft_pink": {"sparse": 18, "standard": 18, "dense": 12},
    "coral_impact": {"sparse": 20, "standard": 18, "dense": 8},
    "green_catalog": {"sparse": 10, "standard": 20, "dense": 24},
    "white_quote": {"sparse": 26, "standard": 16, "dense": 4},
}
```

Add `content_job` affinity up to 20, proof-asset compatibility up to 10, `-18` for each
recent use of the same family in the last three signatures, and `-28` for exact
`narrative_form + family + ordered archetypes + frame_count` repetition.

Expose this exact selector interface:

```text
select_template(
    input_value: SelectorInput,
    recent_signatures: Sequence[Any],
) -> TemplateSelection
```

Return all rejected families and their lower-score reasons. Stable tie-break:

```python
hashlib.sha256(
    f"{topic_id}|{angle_id}|{family}".encode("utf-8")
).hexdigest()
```

- [ ] **Step 7: Implement the public planner and node adapter**

```python
def build_visual_plan(
    contract: ContentContract | Mapping[str, Any],
    narrative_plan: NarrativePlan | Mapping[str, Any],
    publish_package: Mapping[str, Any],
    recent_signatures: Sequence[Any],
) -> VisualPlan:
    validated_contract = ContentContract.model_validate(contract)
    validated_narrative = NarrativePlan.model_validate(narrative_plan)
    frame_plan = plan_frames(
        validated_contract,
        validated_narrative,
        publish_package,
        recent_signatures,
    )
    selection = select_template(
        SelectorInput.from_content(
            validated_contract,
            validated_narrative,
            publish_package,
            frame_plan,
        ),
        recent_signatures,
    )
    return VisualPlan(
        design_system="beauty_editorial_v2",
        template_family=selection.template_family,
        template_selection=selection,
        narrative_form=validated_narrative.narrative_form,
        content_job=validated_contract.content_job,
        frame_plan=frame_plan,
        required_assets=required_assets_for(frame_plan, validated_contract),
    )
```

`required_assets_for` returns an empty list for `proof_mode="none"` and creates requirements
only for archetypes that need the declared proof asset.

- [ ] **Step 8: Run planner tests**

Run:

```bash
pytest -q tests/editorial_carousel/test_blueprints.py tests/editorial_carousel/test_selector.py tests/editorial_carousel/test_strategy.py tests/nodes/test_visual_strategy_planner.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/editorial_carousel src/nodes/node_p_visual_strategy_planner.py tests/editorial_carousel tests/nodes/test_visual_strategy_planner.py
git commit -m "feat: plan carousels from narrative blueprints"
```

---

### Task 6: Update storyboard generation, visible-text editing, and Carousel QA

**Files:**
- Modify: `src/prompts/base/storyboards_generator.txt`
- Modify: `src/nodes/node_o_storyboards_generator.py`
- Modify: `src/nodes/publish_patch.py`
- Modify: `src/nodes/node_p_carousel_qa.py`
- Modify: `src/nodes/node_q_human_review.py`
- Modify: `src/nodes/node_q_01_final_policy_guard.py`
- Modify: `src/publishing/artifacts.py`
- Modify: `src/publishing/templates/codex_image_regeneration_prompt.txt`
- Test: `tests/nodes/test_carousel_qa.py`
- Test: `tests/nodes/test_metadata_flow.py`
- Test: `tests/nodes/test_final_policy_guard.py`
- Test: `tests/publishing/test_artifacts.py`
- Test: `tests/prompts/test_composer.py`

**Interfaces:**
- Consumes: v2 `VisualPlan`.
- Produces: v2 `CarouselPayload`.
- Invariant: `(frame_id, role, page_archetype)` matches plan exactly; emoji remains visible text.

- [ ] **Step 1: Write failing storyboard and QA tests**

```python
def test_storyboard_payload_matches_page_archetypes_and_allows_empty_visual_slots():
    payload = semantic_payload_for(plan_without_assets())
    assert [
        (frame.frame_id, frame.page_archetype)
        for frame in payload.storyboards
    ] == [
        (frame.frame_id, frame.page_archetype)
        for frame in plan.frame_plan
    ]
    assert all(frame.visual_slots == [] for frame in payload.storyboards)


def test_carousel_qa_rejects_missing_narrative_form_and_fixed_three_item_filler():
    package = package_with_three_identical_step_frames()
    issues = validate_carousel(package, contract, visual_plan)
    assert "narrative_plan_missing" in {issue.rule_id for issue in issues}
    assert "fixed_cardinality_filler" in {issue.rule_id for issue in issues}
```

Add an emoji visible-text edit test:

```python
assert extract_storyboard_visible_text(frames)[0]["text_blocks"]["headline"] == "防晒别急着叠✨"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/nodes/test_carousel_qa.py tests/nodes/test_metadata_flow.py tests/prompts/test_composer.py
```

Expected: FAIL on old `layout` fields and mandatory slot behavior.

- [ ] **Step 3: Replace storyboard prompt contract**

Require:

```json
{
  "frame_id": "copy from VisualPlan",
  "role": "copy from VisualPlan",
  "page_archetype": "copy from VisualPlan",
  "content_density_hint": "auto | sparse | standard | dense",
  "headline": "visible copy",
  "kicker": "visible copy or null",
  "content_blocks": [],
  "emphasis": [],
  "visual_slots": [],
  "footer": "visible copy or null"
}
```

Hard rules:

- Use `publish_package.narrative_plan` and the frame purpose.
- Do not insert an empty closing page.
- Do not force exactly three steps/items/quotes.
- Do not add default “收藏 + 关注”.
- Emoji are allowed and remain ordinary visible strings.
- Empty `visual_slots` is valid when the frame has no planned asset role.

- [ ] **Step 4: Update semantic matching and visible-text patch fields**

Replace every `(frame_id, layout)` comparison with:

```python
(frame.frame_id, frame.role, frame.page_archetype)
```

Update `StoryboardVisibleText` extraction and human-review structural signatures to preserve
`page_archetype` and `content_density_hint`. Visible fields remain kicker, headline, footer,
emphasis, and content-block strings; Unicode strings require no special conversion.

- [ ] **Step 5: Replace Carousel QA family/layout checks**

Validate:

- Narrative plan exists and `visual_plan.narrative_form` matches it.
- Page count equals plan and is 5–7.
- First archetype is `cover`.
- Required narrative beat purposes are covered by frame purposes.
- One frame covers the exact saveable beat purpose.
- Template family is one of six.
- Recent combination signature is not exact.
- A no-asset frame may have zero slots.
- A frame with asset roles has exact slot/requirement bindings.
- Three adjacent pages with the same archetype and item cardinality `3` produce
  `fixed_cardinality_filler`.

Use this precise filler detector:

```python
signatures = [
    (
        frame.page_archetype,
        tuple(len(block.items) for block in frame.content_blocks),
    )
    for frame in frames
]
for index in range(2, len(signatures)):
    window = signatures[index - 2:index + 1]
    if len(set(window)) == 1 and window[0][1] == (3,):
        issues.append(
            _issue(
                "fixed_cardinality_filler",
                "Three adjacent frames repeat the same three-item structure.",
                _location(index, "content_blocks"),
                frame=frames[index],
                before=str(window),
                after_hint="Vary the semantic page task or item cardinality.",
            )
        )
```

The detector must not reject one legitimate three-item page.

- [ ] **Step 6: Update Final Guard and Human Review**

Replace old layout references with `page_archetype`; show template family, density hint,
page archetype, and narrative form in the review payload. Preserve current edit → R2 →
rerender routing.

Update publish artifact summaries and rescue prompt generation to emit `template_family`,
`page_archetype`, `density`, and visible text instead of `layout`. Keep ContentLock canonical
fields unchanged; its locked storyboard dictionaries naturally contain the new v2 fields.

- [ ] **Step 7: Run focused storyboard and guard tests**

Run:

```bash
pytest -q tests/nodes/test_carousel_qa.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/publishing/test_artifacts.py tests/prompts/test_composer.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/prompts/base/storyboards_generator.txt src/nodes/node_o_storyboards_generator.py src/nodes/publish_patch.py src/nodes/node_p_carousel_qa.py src/nodes/node_q_human_review.py src/nodes/node_q_01_final_policy_guard.py src/publishing/artifacts.py src/publishing/templates/codex_image_regeneration_prompt.txt tests/nodes/test_carousel_qa.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/publishing/test_artifacts.py tests/prompts/test_composer.py
git commit -m "feat: generate archetype-based storyboards"
```

---

### Task 7: Support zero-asset carousels without weakening asset security

**Files:**
- Modify: `src/asset_resolver/resolver.py`
- Modify: `src/asset_resolver/eligibility.py`
- Modify: `src/asset_resolver/catalog.py`
- Modify: `src/asset_resolver/lifecycle.py`
- Modify: `src/nodes/node_p_asset_resolver.py`
- Modify: `src/rendering/editorial/renderer.py`
- Modify: `src/nodes/node_p_render_qa.py`
- Modify: `src/nodes/node_q_01_final_policy_guard.py`
- Test: `tests/asset_resolver/test_local_resolution.py`
- Test: `tests/rendering/editorial/test_renderer.py`
- Test: `tests/nodes/test_render_qa.py`
- Test: `tests/nodes/test_final_policy_guard.py`

**Interfaces:**
- Consumes: `VisualPlan.required_assets`, possibly empty.
- Produces: valid empty `AssetManifest`.
- Invariant: declared slots still require exact binding and sha256 verification.

- [ ] **Step 1: Write failing empty-manifest tests**

```python
def test_resolve_assets_returns_auditable_empty_manifest_without_calling_providers():
    provider = RecordingProvider()
    catalog = catalog_with_providers(provider)
    manifest = resolve_assets(plan_with_no_requirements(), catalog)
    assert manifest.items == []
    assert manifest.search_report.search_triggered is False
    assert manifest.search_report.queries == []
    assert provider.search_calls == []


def test_renderer_accepts_no_slots_but_rejects_missing_declared_slot(tmp_path):
    render_carousel(plan_without_assets(), storyboard_without_slots(), empty_manifest(), tmp_path)
    with pytest.raises(EditorialCarouselRenderError, match="asset slot"):
        render_carousel(plan_with_asset(), storyboard_with_slot(), empty_manifest(), tmp_path)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/asset_resolver/test_local_resolution.py tests/rendering/editorial/test_renderer.py
```

Expected: at least one test fails because downstream checks assume every page has an asset.

- [ ] **Step 3: Make empty resolution explicit**

At the top of `resolve_assets`:

```python
if not visual_plan.required_assets:
    return AssetManifest(
        items=[],
        search_report=AssetSearchReport(
            search_triggered=False,
            queries=[],
            provider_reports=[],
            selection_reasons={},
        ),
    )
```

Do not alter external provider, lifecycle, containment, approval, or hash code.

Replace internal requirement/pending field reads:

```python
requirement.page_archetype
pending.page_archetype
item.page_archetype
```

The persisted asset-catalog JSON key remains `allowed_layouts`; eligibility checks
`requirement.page_archetype in entry.allowed_layouts`. Rename the pending dataclass field to
`page_archetype` and migrate its audit JSON reader to accept old `layout` only inside
`src/asset_resolver/lifecycle.py`.

- [ ] **Step 4: Make renderer and guards compare declared slots, not page count**

The expected slot set is:

```python
expected_slots = {
    slot.slot_id
    for frame in storyboard.storyboards
    for slot in frame.visual_slots
}
manifest_slots = {item.slot_id for item in assets.items}
if manifest_slots != expected_slots:
    raise EditorialCarouselRenderError("asset manifest slots do not match storyboard")
```

Render QA and Final Guard must use the same set equality. No placeholder image is emitted for
an empty frame.

- [ ] **Step 5: Run focused asset and guard tests**

Run:

```bash
pytest -q tests/asset_resolver/test_local_resolution.py tests/asset_resolver/test_external_resolution.py tests/asset_resolver/test_lifecycle.py tests/rendering/editorial/test_renderer.py tests/nodes/test_render_qa.py tests/nodes/test_final_policy_guard.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asset_resolver src/nodes/node_p_asset_resolver.py src/rendering/editorial/renderer.py src/nodes/node_p_render_qa.py src/nodes/node_q_01_final_policy_guard.py tests/asset_resolver tests/rendering/editorial/test_renderer.py tests/nodes/test_render_qa.py tests/nodes/test_final_policy_guard.py
git commit -m "feat: support secure text-only carousels"
```

---

### Task 8: Add copy metrics, deterministic emoji font, template registry, and variant resolution

**Files:**
- Modify: `requirements.txt`
- Add binary: `assets/fonts/beauty-editorial-v2/NotoColorEmoji.ttf`
- Add license: `assets/fonts/beauty-editorial-v2/LICENSE-Noto-Emoji.txt`
- Create: `src/rendering/editorial/copy_metrics.py`
- Create: `src/rendering/editorial/template_registry.py`
- Create: `src/rendering/editorial/variant_resolver.py`
- Test: `tests/rendering/editorial/test_copy_metrics.py`
- Test: `tests/rendering/editorial/test_template_registry.py`
- Test: `tests/rendering/editorial/test_variant_resolver.py`

**Interfaces:**
- `measure_frame_copy(frame: CarouselFrame) -> CopyMetrics`
- `resolve_variant(family, archetype, hint, metrics) -> ResolvedVariant`
- Pinned font: Noto Color Emoji v2.051, repository commit
  `8998f5dd683424a73e2314a8c1f1e359c19e8742`.

- [ ] **Step 1: Write failing copy-metric tests**

```python
def test_copy_metrics_count_emoji_as_graphemes_not_codepoints():
    frame = frame_with_copy("防晒要等一等👩‍🔬✨")
    metrics = measure_frame_copy(frame)
    assert metrics.emoji_count == 2
    assert metrics.grapheme_count == 8


def test_copy_metrics_capture_item_cardinality_and_longest_item():
    frame = frame_with_items(["短项", "这是一条明显更长的判断标准"])
    metrics = measure_frame_copy(frame)
    assert metrics.item_count == 2
    assert metrics.max_item_graphemes == 13
```

- [ ] **Step 2: Write failing variant tests**

```python
@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
@pytest.mark.parametrize("archetype", ALL_PAGE_ARCHETYPES)
def test_registry_has_at_least_one_variant_for_every_family_archetype(family, archetype):
    capability = TEMPLATE_REGISTRY[family].archetypes[archetype]
    assert capability.composition_variants


def test_dense_collection_uses_grid_but_sparse_quote_uses_focus():
    dense = resolve_variant("green_catalog", "item_collection", "auto", dense_metrics())
    sparse = resolve_variant("white_quote", "quote", "auto", sparse_metrics())
    assert dense.density == "dense"
    assert dense.composition_variant == "catalog-grid"
    assert sparse.density == "sparse"
    assert sparse.composition_variant == "centered-focus"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
pytest -q tests/rendering/editorial/test_copy_metrics.py tests/rendering/editorial/test_template_registry.py tests/rendering/editorial/test_variant_resolver.py
```

Expected: collection fails because the modules do not exist.

- [ ] **Step 4: Add the grapheme dependency and pinned emoji resources**

Append:

```text
regex
```

Download and verify:

```bash
mkdir -p assets/fonts/beauty-editorial-v2
curl -fsSL \
  https://raw.githubusercontent.com/googlefonts/noto-emoji/8998f5dd683424a73e2314a8c1f1e359c19e8742/fonts/NotoColorEmoji.ttf \
  -o assets/fonts/beauty-editorial-v2/NotoColorEmoji.ttf
echo "72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b  assets/fonts/beauty-editorial-v2/NotoColorEmoji.ttf" \
  | shasum -a 256 -c -
curl -fsSL \
  https://raw.githubusercontent.com/googlefonts/noto-emoji/8998f5dd683424a73e2314a8c1f1e359c19e8742/LICENSE \
  -o assets/fonts/beauty-editorial-v2/LICENSE-Noto-Emoji.txt
echo "500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b  assets/fonts/beauty-editorial-v2/LICENSE-Noto-Emoji.txt" \
  | shasum -a 256 -c -
```

- [ ] **Step 5: Implement copy metrics**

Use `regex.findall(r"\X", text)` for graphemes. Classify emoji with Unicode properties:

```python
GRAPHEME_RE = regex.compile(r"\X")
EMOJI_RE = regex.compile(r"\p{Extended_Pictographic}")
CJK_RE = regex.compile(r"\p{Script=Han}")
LATIN_WORD_RE = regex.compile(r"\b[\p{Latin}\d][\p{Latin}\d'-]*\b")
```

Aggregate every visible field from `_expected_copy(frame)`. `estimated_lines` uses:

```python
estimated_lines = sum(
    max(1, math.ceil(len(graphemes) / 18))
    for text in visible_strings
)
```

- [ ] **Step 6: Implement the registry**

Create immutable dataclasses:

```python
@dataclass(frozen=True)
class ArchetypeCapability:
    composition_variants: tuple[str, ...]
    sparse_max_graphemes: int
    standard_max_graphemes: int
    dense_max_graphemes: int
    min_font_px: int


@dataclass(frozen=True)
class TemplateDefinition:
    family: TemplateFamily
    colors: Mapping[str, str]
    fonts: Mapping[str, Path]
    archetypes: Mapping[PageArchetype, ArchetypeCapability]
```

All six families must contain all 15 archetypes. Use family-specific composition names:

```text
pink_red: centered-number, red-panel, white-card, split-card
deep_teal: centered-minimal, numbered-column, rule-grid
soft_pink: offset-cover, floating-card, soft-grid
coral_impact: impact-cover, stacked-impact, contrast-impact
green_catalog: folder-cover, catalog-card, catalog-grid
white_quote: centered-focus, editorial-column, quiet-grid
```

Use existing repository font files:

- Pink/coral display: `assets/fonts/templates/Alibaba-PuHuiTi-Heavy.ttf`
- Teal/soft/green sans: HarmonyOS files under `assets/fonts/templates/`
- White quote: LXGW WenKai under `assets/fonts/beauty-editorial-v1/`
- Emoji: pinned `NotoColorEmoji.ttf`

- [ ] **Step 7: Implement variant resolution**

Density thresholds:

```python
if metrics.grapheme_count <= capability.sparse_max_graphemes and metrics.item_count <= 2:
    density = "sparse"
elif metrics.grapheme_count <= capability.standard_max_graphemes and metrics.item_count <= 4:
    density = "standard"
else:
    density = "dense"
```

If hint is not `auto`, accept it only if the measured copy fits that density's maximum;
otherwise raise `VariantResolutionError`.

Composition rules:

- `item_collection`/`checklist`: one column for 1–3 items, 2×2 for 4 items, two-column or
  family grid for 5–6 items.
- `comparison`: split panels for 2/4 items; stacked comparison for 3/5/6.
- `steps`: vertical timeline for 1–4, two-column sequence for 5–6.
- `quote`: centered focus when sparse, editorial column otherwise.
- Other archetypes choose the first registered composition compatible with density.

- [ ] **Step 8: Run focused metric/registry/variant tests**

Run:

```bash
pytest -q tests/rendering/editorial/test_copy_metrics.py tests/rendering/editorial/test_template_registry.py tests/rendering/editorial/test_variant_resolver.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt assets/fonts/beauty-editorial-v2 src/rendering/editorial/copy_metrics.py src/rendering/editorial/template_registry.py src/rendering/editorial/variant_resolver.py tests/rendering/editorial/test_copy_metrics.py tests/rendering/editorial/test_template_registry.py tests/rendering/editorial/test_variant_resolver.py
git commit -m "feat: add adaptive template variant resolution"
```

---

### Task 9: Implement shared primitives and all six production template families

**Files:**
- Create: `src/rendering/editorial/primitives.py`
- Create: `src/rendering/editorial/templates/__init__.py`
- Create: `src/rendering/editorial/templates/pink_red.py`
- Create: `src/rendering/editorial/templates/deep_teal.py`
- Create: `src/rendering/editorial/templates/soft_pink.py`
- Create: `src/rendering/editorial/templates/coral_impact.py`
- Create: `src/rendering/editorial/templates/green_catalog.py`
- Create: `src/rendering/editorial/templates/white_quote.py`
- Replace: `src/rendering/editorial/layouts.py`
- Modify: `src/rendering/editorial/__init__.py`
- Test: `tests/rendering/editorial/test_templates.py`
- Replace: `tests/rendering/editorial/test_layouts.py`
- Modify: `tests/rendering/editorial/conftest.py`

**Interfaces:**
- `render_frame(frame, assets, variant) -> str` per family.
- Dispatch key: `template_family`; internal key: `page_archetype`.
- Invariant: every visible string is emitted once with `data-card-copy`.

- [ ] **Step 1: Write failing family-render tests**

```python
@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
@pytest.mark.parametrize("archetype", ALL_PAGE_ARCHETYPES)
def test_every_family_renders_every_archetype(family, archetype):
    frame = make_frame(archetype)
    variant = resolve_variant(family, archetype, "auto", measure_frame_copy(frame))
    html = TEMPLATE_RENDERERS[family](frame, [], variant)
    assert f'data-template-family="{family}"' in html
    assert f'data-page-archetype="{archetype}"' in html
    assert f'data-density="{variant.density}"' in html
    assert escape(frame.headline, quote=True) in html


def test_template_renderers_escape_copy_and_do_not_emit_asset_placeholder():
    frame = make_frame("explanation", headline="<script>alert(1)</script>")
    html = render_family("soft_pink", frame, [], standard_variant())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "asset-placeholder" not in html
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/rendering/editorial/test_templates.py tests/rendering/editorial/test_layouts.py
```

Expected: collection fails because template modules do not exist.

- [ ] **Step 3: Implement escaped primitives**

Move `_copy`, content-block rendering, optional asset rendering, and footer primitives out of
old `layouts.py`. Use:

```python
def copy_atom(value: str, *, role: str, class_name: str, tag: str = "div") -> str:
    return (
        f'<{tag} class="{escape(class_name, quote=True)}" data-card-copy '
        f'data-copy-role="{escape(role, quote=True)}">'
        f"{escape(value, quote=True)}</{tag}>"
    )
```

Provide exact shared functions:

```text
render_header(frame)
render_blocks(frame, marker_style)
render_footer(frame)
render_assets(assets)
render_card_shell(family, frame, variant, body)
```

`render_assets([])` returns `""`.

- [ ] **Step 4: Implement family modules**

Each module exports:

```python
def render_frame(
    frame: CarouselFrame,
    assets: Sequence[AssetManifestItem],
    variant: ResolvedVariant,
) -> str:
    renderer = ARCHETYPE_RENDERERS[frame.page_archetype]
    return renderer(frame, assets, variant)
```

Use the following visual identity and CSS root class:

- `pink_red`: `.template-pink-red`; `#F4A7BF`, `#DC2333`, white; centered numeric cover,
  red full panel, white floating card, split card.
- `deep_teal`: `.template-deep-teal`; `#0E5A5A`, white, `#7FD6D6`; minimal centered cover,
  numbered editorial columns, white-rule grids.
- `soft_pink`: `.template-soft-pink`; `#F8DADA`, `#EE5C5C`, white; offset cover, rounded
  floating cards, soft diagnostic grid.
- `coral_impact`: `.template-coral-impact`; `#F45A5A`, white, `#FFE3E3`; oversized headline,
  stacked impact sections, strong comparison bands.
- `green_catalog`: `.template-green-catalog`; `#1E5A2E`, `#F3E9D2`, pink/red tabs;
  folder cover, catalog cards, dense item grid.
- `white_quote`: `.template-white-quote`; white, `#2A4A8C`, `#4A66A0`; centered WenKai
  focus, editorial columns, quiet bordered grids for dense pages.

For every family, implement the same semantic archetypes without fixed cardinality. List and
step rendering consumes `block.items` of length 1–6.

- [ ] **Step 5: Replace dispatch**

`src/rendering/editorial/layouts.py` becomes a compatibility-free v2 dispatch:

```python
TEMPLATE_RENDERERS: Mapping[TemplateFamily, TemplateRenderer] = MappingProxyType(
    {
        "pink_red": pink_red.render_frame,
        "deep_teal": deep_teal.render_frame,
        "soft_pink": soft_pink.render_frame,
        "coral_impact": coral_impact.render_frame,
        "green_catalog": green_catalog.render_frame,
        "white_quote": white_quote.render_frame,
    }
)
```

Do not inspect topic keywords.

- [ ] **Step 6: Run family renderer tests**

Run:

```bash
pytest -q tests/rendering/editorial/test_templates.py tests/rendering/editorial/test_layouts.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/rendering/editorial/primitives.py src/rendering/editorial/templates src/rendering/editorial/layouts.py src/rendering/editorial/__init__.py tests/rendering/editorial/test_templates.py tests/rendering/editorial/test_layouts.py tests/rendering/editorial/conftest.py
git commit -m "feat: implement six production template families"
```

---

### Task 10: Integrate adaptive variants and emoji into Chromium rendering and Render QA

**Files:**
- Modify: `src/rendering/editorial/renderer.py`
- Modify: `src/rendering/editorial/probes.py`
- Modify: `src/nodes/node_p_render_qa.py`
- Modify: `src/schemas/render_qa.py`
- Modify: `tests/rendering/editorial/conftest.py`
- Test: `tests/rendering/editorial/test_renderer.py`
- Test: `tests/rendering/editorial/test_probes.py`
- Test: `tests/rendering/editorial/test_chromium_smoke.py`
- Test: `tests/nodes/test_render_qa.py`

**Interfaces:**
- Renderer resolves variants before HTML generation and records them in `RenderedPage`.
- Probes attest visible copy, emoji, font family, dimensions, and no clipping.
- Render QA evaluates archetype/composition diversity.

- [ ] **Step 1: Write failing Chromium matrix tests**

```python
@pytest.mark.parametrize("family", ALL_TEMPLATE_FAMILIES)
@pytest.mark.parametrize("frame_count", [5, 6, 7])
def test_chromium_renders_each_family_at_each_page_count(
    family, frame_count, tmp_path
):
    plan, storyboard, assets = fixture_for(family, frame_count)
    manifest = render_carousel(plan, storyboard, assets, tmp_path)
    assert len(manifest.pages) == frame_count
    assert {page.template_family for page in manifest.pages} == {family}
    assert all((page.width, page.height) == (1080, 1440) for page in manifest.pages)
```

Add:

```python
def test_chromium_renders_emoji_without_tofu_or_text_drift(tmp_path):
    frame = frame_with_copy("防晒成膜后再上妆✨👩‍🔬")
    manifest = render_single(frame, family="deep_teal", tmp_path=tmp_path)
    probe = manifest.pages[0].probe
    assert [item.text for item in probe.text_results if item.role == "headline"] == [
        "防晒成膜后再上妆✨👩‍🔬"
    ]
    assert not any(issue.startswith("missing-glyph") for issue in probe.issues)
```

- [ ] **Step 2: Run Chromium tests and verify RED**

Run:

```bash
pytest -q tests/rendering/editorial/test_renderer.py tests/rendering/editorial/test_probes.py tests/rendering/editorial/test_chromium_smoke.py
```

Expected: FAIL because renderer still dispatches old layouts and does not load the emoji font.

- [ ] **Step 3: Replace font CSS and card CSS assembly**

Generate `@font-face` rules from the selected `TemplateDefinition`. Add:

```python
emoji_font_uri = template.fonts["emoji"].resolve().as_uri()
emoji_font_css = f"""
@font-face {{
  font-family: "Noto Color Emoji";
  src: url("{emoji_font_uri}") format("truetype");
  font-style: normal;
  font-weight: 400;
  font-display: block;
}}
"""
```

Set body fallback:

```css
font-family: var(--body-font), "Noto Color Emoji";
```

Use template-module CSS plus shared safety CSS. Remove old global v1 card palette and all old
asset placeholders.

- [ ] **Step 4: Resolve and record variants per page**

Before rendering:

```python
metrics = measure_frame_copy(frame)
variant = resolve_variant(
    visual_plan.template_family,
    frame.page_archetype,
    frame.content_density_hint,
    metrics,
)
card_html = TEMPLATE_RENDERERS[visual_plan.template_family](
    frame,
    frame_assets,
    variant,
)
```

Write `page_archetype`, `template_family`, `density`, and `composition_variant` to each
`RenderedPage`.

- [ ] **Step 5: Extend font and glyph probes**

Probe:

- Required display/body/emoji font faces loaded.
- Every visible text node's computed family includes the expected template text family.
- For strings containing `Extended_Pictographic`, canvas pixel ink exists in the emoji span
  bounding box and `document.fonts.check('32px "Noto Color Emoji"', emoji)` is true.
- No replacement glyph `\uFFFD`, empty glyph box, clipping, overflow, or ellipsis.

Add an `emoji_graphemes: list[str]` field to `TextProbeResult`; keep the original `text`
unchanged.

- [ ] **Step 6: Replace template stiffness calculation**

Use:

```python
render_signatures = [
    (
        page.page_archetype,
        page.density,
        page.composition_variant,
    )
    for page in manifest.pages
]
repeat_count = len(render_signatures) - len(set(render_signatures))
template_stiffness = min(
    100,
    20 * repeat_count
    + 30 * int(current_combination_signature in recent_visual_signatures),
)
```

Keep existing quality fields and pass/fail routing.

- [ ] **Step 7: Run renderer and Render QA tests**

Run:

```bash
pytest -q tests/rendering/editorial/test_renderer.py tests/rendering/editorial/test_probes.py tests/rendering/editorial/test_chromium_smoke.py tests/nodes/test_render_qa.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/rendering/editorial/renderer.py src/rendering/editorial/probes.py src/nodes/node_p_render_qa.py src/schemas/render_qa.py tests/rendering/editorial tests/nodes/test_render_qa.py
git commit -m "feat: render adaptive templates with emoji QA"
```

---

### Task 11: Persist narrative/template signatures and migrate old checkpoints at one boundary

**Files:**
- Modify: `memory/models.py`
- Modify: `memory/schema.sql`
- Modify: `memory/migrations.py`
- Modify: `memory/memory_manager.py`
- Modify: `memory/memory_context.py`
- Modify: `src/nodes/node_a_01_retrieve_memory.py`
- Modify: `src/nodes/node_p_content_writer.py`
- Modify: `src/editorial_carousel/legacy.py`
- Modify: `src/nodes/node_p_visual_strategy_planner.py`
- Test: `tests/memory/test_migrations.py`
- Test: `tests/memory/test_memory_manager.py`
- Test: `tests/memory/test_domain_retrieval.py`
- Test: `tests/nodes/test_content_writer.py`
- Test: `tests/integration/test_legacy_editorial_resume.py`

**Interfaces:**
- Persists: narrative, template, frame, and density signatures.
- Retrieves: `recent_visual_signatures`.
- Legacy behavior: clear old visual derivatives and re-enter v2 planning.

- [ ] **Step 1: Write failing migration and retrieval tests**

```python
def test_visual_signature_migration_adds_all_columns(manager):
    manager.init_db("memory/schema.sql")
    columns = {
        row[1]
        for row in manager.connect().execute("PRAGMA table_info(contents)")
    }
    assert {
        "narrative_form",
        "narrative_signature",
        "template_family",
        "frame_plan_signature",
        "density_profile",
    } <= columns


def test_memory_context_returns_recent_visual_signatures(manager):
    manager.save_generated_content(record_with_visual_signatures())
    context = manager.build_memory_context(domain="beauty", subdomain="skincare")
    assert context.recent_visual_signatures == [
        {
            "narrative_form": "comparison",
            "template_family": "green_catalog",
            "frame_plan_signature": ["cover", "comparison", "save"],
            "frame_count": 5,
            "density_profile": ["sparse", "standard", "dense"],
        }
    ]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/memory/test_migrations.py tests/memory/test_memory_manager.py tests/memory/test_domain_retrieval.py tests/integration/test_legacy_editorial_resume.py
```

Expected: FAIL because columns and context fields do not exist.

- [ ] **Step 3: Add idempotent columns**

Add columns to `memory/schema.sql` and `migrate_contents_domain_fields`:

```sql
narrative_form TEXT,
narrative_signature TEXT,
template_family TEXT,
frame_plan_signature TEXT,
density_profile TEXT,
```

Store JSON for the three signature/profile fields. Extend `ContentRecord` with:

```python
narrative_form: Optional[str] = None
narrative_signature: list[str] = field(default_factory=list)
template_family: Optional[str] = None
frame_plan_signature: list[str] = field(default_factory=list)
density_profile: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Persist and retrieve signatures**

`content_writer_node` derives:

```python
narrative_plan = publish_package["narrative_plan"]
narrative_signature = [
    f"{beat['kind']}:{beat['purpose']}"
    for beat in narrative_plan["beats"]
]
frame_plan_signature = [
    frame["page_archetype"]
    for frame in publish_package["storyboards"]
]
density_profile = [
    page.density
    for page in render_manifest.pages
]
```

`MemoryContext` adds `recent_visual_signatures`. The prompt payload includes the same key and
the visual planner reads only that v2 key for modern runs.

- [ ] **Step 5: Update the legacy adapter**

When a checkpoint has any of:

```text
design_system == beauty_editorial_v1
frame_plan items containing layout
storyboards containing layout
publish_package.storyboard_strategy
```

the adapter must:

- Preserve content contract, title, body, hashtags, and human-visible storyboard text snapshot.
- Map old `storyboard_strategy` to a `NarrativePlan` only when no modern plan exists:
  `cognitive_correction` → same, `step_tutorial` → same, `checklist` →
  `checklist_collection`, `scenario_companion` → `scenario_story`, `comparison` → same,
  `qa` → `diagnostic_qa`, `story_reversal` → same, `auto` → `reflective_editorial`.
- Clear `visual_plan`, `asset_manifest`, `render_manifest`, QA results, and old storyboards.
- Route to `visual_strategy_planner`.

No modern business node accepts old `layout`.

- [ ] **Step 6: Run persistence and resume tests**

Run:

```bash
pytest -q tests/memory/test_migrations.py tests/memory/test_memory_manager.py tests/memory/test_domain_retrieval.py tests/nodes/test_content_writer.py tests/integration/test_legacy_editorial_resume.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add memory src/nodes/node_a_01_retrieve_memory.py src/nodes/node_p_content_writer.py src/nodes/node_p_visual_strategy_planner.py src/editorial_carousel/legacy.py tests/memory tests/nodes/test_content_writer.py tests/integration/test_legacy_editorial_resume.py
git commit -m "feat: persist narrative and template signatures"
```

---

### Task 12: Modernize the six mockup reference sets without encoding production page counts

**Files:**
- Create: `examples/templates-mockup/render_mockups.py`
- Modify: `examples/templates-mockup/README.md`
- Modify: `examples/templates-mockup/set1-pink-red/template.html`
- Modify: `examples/templates-mockup/set2-teal/template.html`
- Modify: `examples/templates-mockup/set3-soft-pink/template.html`
- Modify: `examples/templates-mockup/set4-coral-promo/template.html`
- Modify: `examples/templates-mockup/set5-green-favorites/template.html`
- Modify: `examples/templates-mockup/set6-white-quote/template.html`
- Regenerate: all PNGs under `examples/templates-mockup/set*/`
- Regenerate: `examples/templates-mockup/gallery-all-6.png`
- Test: `tests/examples/test_template_mockups.py`

**Interfaces:**
- Mockups are human visual references only.
- Renderer script reads explicit page selectors; it does not export a production page count.

- [ ] **Step 1: Write failing mockup contract tests**

```python
@pytest.mark.parametrize("template_path", TEMPLATE_HTML_PATHS)
def test_mockup_templates_use_production_canvas_and_no_fixed_count_copy(template_path):
    html = template_path.read_text(encoding="utf-8")
    assert "width:1080px" in html
    assert "height:1440px" in html
    assert "1080×1350" not in html
    assert "03 / 03" not in html


def test_mockup_readme_states_reference_count_is_not_production_count():
    readme = Path("examples/templates-mockup/README.md").read_text(encoding="utf-8")
    assert "样张图片数量不等于生产套图页数" in readme
    assert "5–7" in readme
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
pytest -q tests/examples/test_template_mockups.py
```

Expected: FAIL on 1350px height and fixed-count sample wording.

- [ ] **Step 3: Create deterministic mockup rendering script**

The script defines:

```python
SETS = {
    "set1-pink-red": ["cover", "steps-standard", "comparison-dense", "save"],
    "set2-teal": ["cover", "explanation-standard", "checklist-dense", "qa"],
    "set3-soft-pink": ["cover", "scene-sparse", "diagnostic-standard", "save"],
    "set4-coral-promo": ["cover", "story-beat", "steps-dense", "boundary"],
    "set5-green-favorites": ["cover", "collection-standard", "collection-dense", "comparison", "save"],
    "set6-white-quote": ["cover", "quote-sparse", "explanation-standard", "checklist-dense", "boundary"],
}
```

For each selector, take a 1080×1440 screenshot. Build each contact sheet with Pillow and then
build `gallery-all-6.png` from the six cover screenshots. The script refuses unknown selectors
and waits for `document.fonts.ready`.

- [ ] **Step 4: Rewrite the six sample HTML files**

For each family:

- Change canvas to 1080×1440.
- Add at least three non-cover archetypes.
- Add sparse and dense examples.
- Keep natural emoji where present.
- Remove fixed `STEP 01/02/03`, `01/03`, `N°01/02/03`, fixed three-quote assumptions, and
  fixed “follow for more” closing.
- Use `data-page` selectors matching `SETS`.

Sample text can remain beauty/skincare content, but no sample string enters production prompts
or Python planner code.

- [ ] **Step 5: Regenerate and visually inspect**

Run:

```bash
python examples/templates-mockup/render_mockups.py
```

Then inspect:

```text
examples/templates-mockup/gallery-all-6.png
examples/templates-mockup/set1-pink-red/contact-sheet.png
examples/templates-mockup/set2-teal/contact-sheet.png
examples/templates-mockup/set3-soft-pink/contact-sheet.png
examples/templates-mockup/set4-coral-promo/contact-sheet.png
examples/templates-mockup/set5-green-favorites/contact-sheet.png
examples/templates-mockup/set6-white-quote/contact-sheet.png
```

Acceptance: no clipping, all canvases 1080×1440, emoji visible, and no family visually implies
that production always has the sample's number of pages.

- [ ] **Step 6: Run mockup tests**

Run:

```bash
pytest -q tests/examples/test_template_mockups.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add examples/templates-mockup tests/examples/test_template_mockups.py
git commit -m "fix: modernize six template mockups"
```

---

### Task 13: Add full narrative/template golden coverage and update public documentation

**Files:**
- Create: `tests/fixtures/adaptive_editorial/cognitive_correction.json`
- Create: `tests/fixtures/adaptive_editorial/step_tutorial.json`
- Create: `tests/fixtures/adaptive_editorial/checklist_collection.json`
- Create: `tests/fixtures/adaptive_editorial/comparison.json`
- Create: `tests/fixtures/adaptive_editorial/diagnostic_qa.json`
- Create: `tests/fixtures/adaptive_editorial/scenario_story.json`
- Create: `tests/fixtures/adaptive_editorial/story_reversal.json`
- Create: `tests/fixtures/adaptive_editorial/reflective_editorial.json`
- Create: `tests/integration/test_adaptive_six_template_workflow.py`
- Create: `tests/integration/render_adaptive_review.py`
- Modify: `tests/integration/test_editorial_carousel_workflow.py`
- Modify: `tests/test_graph.py`
- Modify: `tests/test_main.py`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `docs/architecture/workflow.md`
- Modify: `docs/architecture/editorial-contracts.md`
- Modify: `docs/README.md`

**Interfaces:**
- Golden fixtures prove all eight narrative forms and all six template families.
- At least one template fixture renders 6 pages and one renders 7 pages.

- [ ] **Step 1: Write failing end-to-end tests**

```python
@pytest.mark.parametrize("fixture_name", ALL_NARRATIVE_FIXTURES)
def test_narrative_fixture_keeps_one_form_from_copy_to_storyboard(fixture_name, tmp_path):
    fixture = load_fixture(fixture_name)
    state = run_offline_editorial_pipeline(fixture, tmp_path)
    assert state["publish_package"]["narrative_form"] == fixture["narrative_form"]
    assert state["visual_plan"].narrative_form == fixture["narrative_form"]
    assert 5 <= len(state["publish_package"]["storyboards"]) <= 7


def test_fixture_matrix_selects_all_six_template_families(tmp_path):
    selected = {
        run_offline_editorial_pipeline(load_fixture(name), tmp_path / name)["visual_plan"].template_family
        for name in ALL_NARRATIVE_FIXTURES
    }
    assert selected == {
        "pink_red",
        "deep_teal",
        "soft_pink",
        "coral_impact",
        "green_catalog",
        "white_quote",
    }


def test_template_page_count_is_content_driven(tmp_path):
    five = render_fixture("green-catalog-5", tmp_path / "five")
    six = render_fixture("green-catalog-6", tmp_path / "six")
    seven = render_fixture("green-catalog-7", tmp_path / "seven")
    assert [len(value.pages) for value in (five, six, seven)] == [5, 6, 7]
```

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```bash
pytest -q tests/integration/test_adaptive_six_template_workflow.py tests/integration/test_editorial_carousel_workflow.py tests/test_graph.py
```

Expected: FAIL until fixtures and full v2 integration are complete.

- [ ] **Step 3: Add eight synthetic fixtures**

Use this exact fixture matrix:

| Fixture | Count | Closing | Expected family | Beat kinds |
| --- | ---: | --- | --- | --- |
| `cognitive_correction` | 5 | `boundary` | `pink_red` | hook, misconception, reveal, explanation, action |
| `step_tutorial` | 6 | `action_prompt` | `deep_teal` | hook, scene, steps, diagnostic, explanation, action |
| `checklist_collection` | 7 | `none` | `green_catalog` | hook, scene, checklist, comparison, explanation, action, boundary |
| `comparison` | 5 | `boundary` | `green_catalog` | hook, scene, comparison, diagnostic, action |
| `diagnostic_qa` | 6 | `focused_question` | `soft_pink` | hook, scene, diagnostic, qa, action, boundary |
| `scenario_story` | 7 | `reflection` | `soft_pink` | hook, scene, tension, reveal, explanation, action, boundary |
| `story_reversal` | 6 | `none` | `coral_impact` | hook, scene, misconception, reveal, steps, action |
| `reflective_editorial` | 5 | `reflection` | `white_quote` | hook, quote, explanation, scene, boundary |

Each JSON file uses this exact top-level envelope:

```text
test_only
intended_use
fixture_id
synthetic_title
narrative_form
narrative_plan
content_contract
package
expected_template_family
expected_archetypes
visible_copy
```

Set `test_only=true` and keep `intended_use` prefixed with
`synthetic regression input only`. The `package` object uses the current golden-fixture
keys `focus_keyword`, `focus_keyword_cli_present`, `topic_id`, `topic`, `angle_id`, `angle`,
`target_group`, `core_pain`, `title`, `cover_copy`, `content`, `hashtags`, `domain`,
`subdomain`, `profile_version`, `content_intent`, `risk_level`, `risk_flags`,
`content_format`, and `visual_style`.

Use this complete `step_tutorial` example:

```json
{
  "test_only": true,
  "intended_use": "synthetic regression input only; never a production topic, prompt example, memory seed, signal, or publish candidate",
  "fixture_id": "step_tutorial",
  "synthetic_title": "合成回归步骤教程",
  "narrative_form": "step_tutorial",
  "narrative_plan": {
    "narrative_form": "step_tutorial",
    "beats": [
      {"beat_id": "hook", "kind": "hook", "purpose": "说明早高峰妆前等待目标"},
      {"beat_id": "scene", "kind": "scene", "purpose": "呈现赶时间的真实场景"},
      {"beat_id": "steps", "kind": "steps", "purpose": "给出有顺序的等待流程"},
      {"beat_id": "diagnostic", "kind": "diagnostic", "purpose": "说明每步完成标准"},
      {"beat_id": "explain", "kind": "explanation", "purpose": "解释为什么不能立刻叠加"},
      {"beat_id": "action", "kind": "action", "purpose": "提供可保存执行卡"}
    ],
    "saveable_beat": {
      "beat_id": "action",
      "kind": "action",
      "purpose": "提供可保存执行卡"
    },
    "closing_mode": "action_prompt"
  },
  "content_contract": {
    "audience": "合成测试通勤人群",
    "trigger_situation": "早高峰需要快速完成妆前护理时",
    "decision_problem": "如何判断每一层何时可以继续",
    "first_screen_promise": "六页完成合成妆前等待顺序验证",
    "screenshot_asset": "合成妆前顺序卡",
    "proof_asset": "合成吸收状态示意",
    "visual_mode": "text_card",
    "content_job": "follow_steps",
    "primary_visual_family": "step_flow",
    "primary_visual_subject": "process",
    "proof_mode": "none",
    "recommended_frame_count": 6
  },
  "package": {
    "focus_keyword": "合成妆前等待验证",
    "focus_keyword_cli_present": true,
    "topic_id": "synthetic-step-topic",
    "topic": "合成妆前等待顺序",
    "angle_id": "synthetic-step-angle",
    "angle": "按状态推进而不是按秒数推进",
    "target_group": "合成测试通勤人群",
    "core_pain": "赶时间时连续叠加导致搓泥",
    "title": "合成回归步骤教程",
    "cover_copy": "赶时间也别连着叠✨",
    "content": "仅用于验证六页步骤教程、emoji 和纯文字素材路径。",
    "hashtags": ["#合成回归", "#步骤验证"],
    "domain": "beauty",
    "subdomain": "skincare",
    "profile_version": "beauty-v1",
    "content_intent": "how_to",
    "risk_level": "low",
    "risk_flags": [],
    "content_format": "educational_cards",
    "visual_style": "beauty_editorial_v2"
  },
  "expected_template_family": "deep_teal",
  "expected_archetypes": [
    "cover",
    "scene",
    "steps",
    "diagnostic",
    "save",
    "boundary"
  ],
  "visible_copy": {
    "cover": "赶时间也别连着叠✨",
    "save": "妆前等待顺序卡"
  }
}
```

The other seven files use the same exact envelope and complete `content_contract`/`package`
key sets, with the form, count, closing mode, expected family, and beat kinds from the
matrix. Their `narrative_plan.beats` length equals the matrix count, their first archetype is
`cover`, and each contains at least one of `save`, `checklist`, or `comparison`. The
checklist fixture contains six `visible_copy.items` values. No fixture text may be imported
by production Python or prompt code.

- [ ] **Step 4: Update graph and historical integration tests**

Keep graph node order unchanged:

```text
assembler -> visual_strategy_planner -> storyboard_generator -> asset_resolver
-> carousel_qa -> editorial_carousel_renderer -> render_qa -> human_review
-> final_policy_guard -> content_writer
```

Replace old v1 fields in existing integration fixtures; do not weaken route assertions,
ContentLock checks, manifest hashes, or publish artifact checks.

- [ ] **Step 5: Update public documentation**

Document:

- Eight narrative forms.
- Six production template families.
- Content-driven 5–7 page count independent of mockup count.
- Adaptive density/composition boundaries.
- Emoji support and repository-pinned font.
- Optional pure-text asset manifests.
- Legacy v1 checkpoint re-planning.

Update `docs/README.md` status for the adaptive workflow to `已实施` only after all full
verification in Task 14 passes.

- [ ] **Step 6: Add the offline visual-review renderer**

`tests/integration/render_adaptive_review.py` must:

- parse `--output` as a required `Path`;
- load six fixture IDs mapped one-to-one to six families;
- call the production `render_carousel` interface;
- assert the actual selected family equals the requested review family;
- copy no output into `outputs/publish/`;
- write each family under `<output>/<family>/`;
- exit nonzero on any mismatch.

Add this exact ignore entry:

```gitignore
.artifacts/
```

- [ ] **Step 7: Run integration and documentation checks**

Run:

```bash
pytest -q tests/integration/test_adaptive_six_template_workflow.py tests/integration/test_editorial_carousel_workflow.py tests/test_graph.py
git diff --check
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add .gitignore tests/fixtures/adaptive_editorial tests/integration/test_adaptive_six_template_workflow.py tests/integration/render_adaptive_review.py tests/integration/test_editorial_carousel_workflow.py tests/test_graph.py tests/test_main.py README.md docs
git commit -m "test: cover adaptive six-template workflow"
```

---

### Task 14: Produce six production contact sheets and run completion verification

**Files:**
- Generate under ignored test output: `.artifacts/adaptive-six-template-review/<family>/`
- Modify if defects are found: only the task-relevant files from Tasks 1–13
- Final status update: `docs/README.md`

**Interfaces:**
- Evidence: six production renderer contact sheets, all required commands, clean diff check.
- Completion condition: every requirement in the approved design has authoritative evidence.

- [ ] **Step 1: Generate one production contact sheet per family**

Run the offline fixture renderer:

```bash
python -m tests.integration.render_adaptive_review \
  --output .artifacts/adaptive-six-template-review
```

The command must create:

```text
.artifacts/adaptive-six-template-review/pink_red/contact-sheet.png
.artifacts/adaptive-six-template-review/deep_teal/contact-sheet.png
.artifacts/adaptive-six-template-review/soft_pink/contact-sheet.png
.artifacts/adaptive-six-template-review/coral_impact/contact-sheet.png
.artifacts/adaptive-six-template-review/green_catalog/contact-sheet.png
.artifacts/adaptive-six-template-review/white_quote/contact-sheet.png
```

At least one sheet has 6 pages and one has 7 pages. Each uses a different narrative fixture.

- [ ] **Step 2: Visually inspect all six sheets**

Inspect each full-resolution image. Reject and fix:

- clipping, tofu, missing emoji, invisible text, unexpected system font;
- excessive empty space on dense pages;
- unreadable density or weak hierarchy;
- accidental fixed three-card rhythm;
- template-family identity drift;
- repeated composition on every page;
- content text not matching the fixture.

After each fix, rerun the focused family Chromium test and regenerate the affected sheet.

- [ ] **Step 3: Run focused production-path verification**

```bash
pytest -q \
  tests/schemas/test_narrative.py \
  tests/schemas/test_editorial_templates.py \
  tests/schemas/test_editorial_carousel.py \
  tests/editorial_carousel \
  tests/rendering/editorial \
  tests/nodes/test_carousel_qa.py \
  tests/nodes/test_render_qa.py \
  tests/nodes/test_final_policy_guard.py \
  tests/integration/test_adaptive_six_template_workflow.py \
  tests/integration/test_editorial_carousel_workflow.py \
  tests/integration/test_legacy_editorial_resume.py
```

Expected: PASS.

- [ ] **Step 4: Run the repository-required full verification**

```bash
pytest -q
python -m compileall -q src main.py
git diff --check
```

Expected: all commands exit 0. Do not run live provider tests.

- [ ] **Step 5: Audit the approved requirements against current evidence**

Confirm, with file/test/render evidence:

1. Eight narrative forms reach copy and carousel.
2. Fixed six-part outline and mandatory interactive closing are absent from active prompts.
3. Every v2 plan selects one of six families.
4. Each family renders 5, 6, and 7 pages.
5. Semantic page plan is created before family selection.
6. Copy metrics select finite variants without visible-text mutation.
7. Emoji is preserved in ContentLock input, rendered, and probed.
8. Mockups are 1080×1440 and state sample count is non-binding.
9. Empty asset manifests pass only when no slots are declared.
10. Declared external assets retain all trust checks.
11. Recent narrative/template/frame/density signatures are persisted and retrieved.
12. Legacy v1 checkpoints re-plan through the single adapter.
13. Carousel QA, Render QA, Human Review, and Final Guard remain in graph order.
14. Six visually reviewed production contact sheets exist.

- [ ] **Step 6: Mark documentation implemented and commit**

Change the adaptive workflow row in `docs/README.md` from:

```text
设计已确认，待实施
```

to:

```text
已实施
```

Then:

```bash
git add docs/README.md
git commit -m "docs: mark adaptive template workflow implemented"
```

- [ ] **Step 7: Record final evidence**

Run:

```bash
git status --short --branch
git log --oneline --decorate -15
```

Expected: no uncommitted task changes; generated `.artifacts/` remains ignored. Report exact
test commands, test counts, and contact-sheet paths in the final handoff.
