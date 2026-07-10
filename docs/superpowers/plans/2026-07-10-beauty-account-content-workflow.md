# Beauty Account Content Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Constrain the publishing workflow to a commuting-women beauty account, require a concrete first-screen and screenshot-value contract, and replace axolotl-based illustration carousels with text-led beauty information cards.

**Architecture:** Add a `CreatorProfile` as an account-level policy distinct from the existing domain safety profile. Every generated `TopicItem` carries a `ContentContract`; the topic node validates it against the creator profile, downstream prompts receive it through the retained trend objects, and deterministic carousel QA enforces it before human review. The existing editorial, compliance, review, and persistence loops remain intact.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, LangChain prompt composition, pytest.

## Global Constraints

- Account audience is exactly `23–35 岁、通勤、有基础护肤和底妆需求的女性`.
- The account only accepts `beauty/skincare` and `beauty/makeup_basics` topics.
- When no domain is supplied, the creator profile defaults the run to `beauty/skincare`; the generic `healthy_lifestyle` default must not run for this account.
- The account excludes wellness, exercise, sleep, stress, nutrition, supplements, and generic healthy-lifestyle topics.
- Every candidate needs a first-screen promise and a standalone screenshot asset.
- The default carousel has 6–8 cards, no cartoon character/IP, and no decorative AI scene used as evidence.
- Keep existing safety, evidence, novelty, human-review, final-policy, and persistence protections.
- Do not activate `visual_director`, `image_sourcing`, or `image_qa` in this change.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/creator_profile.py` | Immutable account positioning, allowed scope, visual modes, and candidate validation. |
| `src/schemas/content_contract.py` | Contract required before a topic can enter ranking. |
| `src/schemas/topic.py` | Adds the contract to `TopicItem`. |
| `src/schemas/storyboard.py` | Removes character-only fields, adds card-role metadata, and changes carousel cardinality to 6–8. |
| `src/schemas/carousel_qa.py` | Typed deterministic QA result and atomic QA issue. |
| `src/schemas/agent_state.py` | Carries `creator_profile` and `carousel_qa_result`. |
| `src/topic_signals/briefs.py` | Builds profile-bound briefs rather than choosing random audiences. |
| `src/nodes/node_a_00_domain_router.py` | Enforces account domain/subdomain scope when a creator profile is supplied. |
| `src/nodes/node_a_00_domain_confirmation.py` | Limits interactive choices to the profile scope. |
| `src/nodes/node_a_03_creative_brief_builder.py` | Supplies the profile to brief generation. |
| `src/nodes/node_a_04_topic_ideator.py` | Validates candidate scope and contract after model output. |
| `src/nodes/node_c_virality_scorer.py` | Provides the content contract to ranking. |
| `src/nodes/node_o_storyboards_generator.py` | Provides the contract to card generation. |
| `src/nodes/node_o_assembler.py` | Copies the selected topic's contract into the final publish package. |
| `src/nodes/node_p_content_writer.py` | Persists the contract in content metadata for later analysis. |
| `src/nodes/node_p_carousel_qa.py` | Deterministically checks generated carousel packages and creates R1 tasks on failure. |
| `src/nodes/__init__.py` | Lazily exports the new QA node. |
| `src/graph.py` | Inserts carousel QA between storyboard generation and human review. |
| `main.py` | Seeds the account profile in every new run and exports profile-aware image instructions. |
| `src/prompts/composer.py` | Appends a shared creator-profile fragment for stateful prompts. |
| `src/prompts/fragments/creator_profile.txt` | Shared account positioning rules. |
| `src/prompts/base/*.txt` | Task-specific topic, scoring, editorial, title, review, and visual requirements. |
| `tests/...` | Regression coverage for scope, contract propagation, prompts, QA routing, and card rules. |

## Task 1: Add the Account-Level Creator Profile and Enforce Scope

**Files:**
- Create: `src/creator_profile.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `src/nodes/node_a_00_domain_router.py`
- Modify: `src/nodes/node_a_00_domain_confirmation.py`
- Modify: `main.py`
- Test: `tests/test_creator_profile.py`
- Test: `tests/nodes/test_domain_nodes.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: existing `DomainContext` and `ContentPolicy`.
- Produces: `CreatorProfile`, `COMMUTING_BEAUTY_WOMEN_V1`, and `CreatorProfile.assert_domain_scope(domain, subdomain)`.
- Downstream contract: all new production initial states contain `creator_profile: COMMUTING_BEAUTY_WOMEN_V1`.

- [ ] **Step 1: Write failing profile and routing tests**

```python
def test_commuting_beauty_profile_allows_only_two_beauty_subdomains():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("beauty", "skincare")
    COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("beauty", "makeup_basics")
    with pytest.raises(ValueError, match="outside creator profile scope"):
        COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("wellness", "sleep")


def test_domain_router_rejects_out_of_scope_explicit_domain():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    with pytest.raises(ValueError, match="outside creator profile scope"):
        domain_router_node({
            "creator_profile": COMMUTING_BEAUTY_WOMEN_V1,
            "domain": "healthy_lifestyle",
            "subdomain": "daily_habits",
            "focus_keyword": "久坐",
        })
```

Add a `main.py` test asserting a fresh initial state includes the profile rather
than relying on an implicit generic-domain default.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/test_creator_profile.py tests/nodes/test_domain_nodes.py tests/test_main.py -v`

Expected: FAIL because `src.creator_profile` and the `creator_profile` state field do not exist.

- [ ] **Step 3: Implement the smallest profile boundary**

Create a frozen Pydantic model with the following public shape:

```python
class CreatorProfile(BaseModel):
    profile_id: str
    audience: str
    default_domain: Literal["beauty"]
    default_subdomain: Literal["skincare"]
    allowed_domains: tuple[str, ...]
    allowed_subdomains: tuple[str, ...]
    primary_situations: tuple[str, ...]
    excluded_themes: tuple[str, ...]
    visual_modes: tuple[Literal["text_card", "text_plus_real_proof", "comparison_table"], ...]

    def assert_domain_scope(self, domain: str, subdomain: str) -> None: ...


COMMUTING_BEAUTY_WOMEN_V1 = CreatorProfile(...)
```

Use the exact profile values in the global constraints. Add optional
`creator_profile` and `carousel_qa_result` fields to `AgentState`. When a
profile is present and the caller omitted a domain/subdomain, the router must
call `resolve_domain(profile.default_domain, ..., profile.default_subdomain)`.
For an explicit domain or subdomain, call `assert_domain_scope`. Retain generic
multi-domain behavior for tests and future accounts that omit a profile. Seed
the profile in `main.py` initial state.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_creator_profile.py tests/nodes/test_domain_nodes.py tests/test_main.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the profile boundary**

```bash
git add src/creator_profile.py src/schemas/agent_state.py \
  src/nodes/node_a_00_domain_router.py src/nodes/node_a_00_domain_confirmation.py \
  main.py tests/test_creator_profile.py tests/nodes/test_domain_nodes.py tests/test_main.py
git commit -m "feat: constrain workflow to commuting beauty audience"
```

## Task 2: Make Candidate Contracts Typed and Profile-Bound

**Files:**
- Create: `src/schemas/content_contract.py`
- Modify: `src/schemas/topic.py`
- Modify: `src/topic_signals/briefs.py`
- Modify: `src/nodes/node_a_03_creative_brief_builder.py`
- Modify: `src/nodes/node_a_04_topic_ideator.py`
- Modify: `src/prompts/base/topic_ideator.txt`
- Test: `tests/schemas/test_content_contract.py`
- Test: `tests/topic_signals/test_briefs.py`
- Test: `tests/nodes/test_topic_ideator.py`

**Interfaces:**
- Consumes: `CreatorProfile`, `CreativeBrief`, and `TopicSignal`.
- Produces: `ContentContract` embedded in every `TopicItem`.
- Downstream contract: `state["trends"]` retains the contract after diversity filtering and is the canonical QA lookup source.

- [ ] **Step 1: Write failing contract and ideator tests**

```python
def test_content_contract_requires_first_screen_and_screenshot_asset():
    with pytest.raises(ValidationError):
        ContentContract(
            audience=COMMUTING_BEAUTY_WOMEN_V1.audience,
            trigger_situation="早八通勤前",
            decision_problem="防晒后是否能立刻上底妆",
            first_screen_promise="",
            screenshot_asset="",
            proof_asset="质地对比图",
            visual_mode="text_plus_real_proof",
        )


def test_topic_ideator_rejects_candidate_outside_creator_profile(monkeypatch):
    # Fake model returns domain=wellness and a structurally valid contract.
    with pytest.raises(ValueError, match="outside creator profile scope"):
        topic_ideator_node(profile_bound_state())
```

Also assert profile-bound briefs all use the fixed audience and never emit the
old `健身新手` / `久坐人群` audience values.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/schemas/test_content_contract.py tests/topic_signals/test_briefs.py tests/nodes/test_topic_ideator.py -v`

Expected: FAIL because a contract is not required or validated.

- [ ] **Step 3: Implement contract propagation**

Define:

```python
class ContentContract(BaseModel):
    audience: str = Field(min_length=1)
    trigger_situation: str = Field(min_length=1)
    decision_problem: str = Field(min_length=1)
    first_screen_promise: str = Field(min_length=8, max_length=42)
    screenshot_asset: str = Field(min_length=1)
    proof_asset: str = Field(min_length=1)
    visual_mode: Literal["text_card", "text_plus_real_proof", "comparison_table"]
```

Add `content_contract: ContentContract` to `TopicItem`. Replace the module
constants `AUDIENCES` and `PAINS` in `briefs.py` with a required
`creator_profile` parameter; each brief uses its exact audience and selects
only an allowed beauty scenario. In `topic_ideator_node`, validate each parsed
candidate with:

```python
profile.assert_domain_scope(candidate.domain, candidate.subdomain)
if candidate.target_group != profile.audience:
    raise ValueError("candidate target_group must equal creator profile audience")
if candidate.content_contract.audience != profile.audience:
    raise ValueError("content contract audience must equal creator profile audience")
if candidate.content_contract.visual_mode not in profile.visual_modes:
    raise ValueError("content contract visual mode is not allowed by creator profile")
```

Amend the Topic Ideator prompt so every candidate emits the exact JSON object
and excludes a topic when it cannot produce a concrete screenshot asset.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/schemas/test_content_contract.py tests/topic_signals/test_briefs.py tests/nodes/test_topic_ideator.py -v`

Expected: PASS.

- [ ] **Step 5: Commit typed content contracts**

```bash
git add src/schemas/content_contract.py src/schemas/topic.py \
  src/topic_signals/briefs.py src/nodes/node_a_03_creative_brief_builder.py \
  src/nodes/node_a_04_topic_ideator.py src/prompts/base/topic_ideator.txt \
  tests/schemas/test_content_contract.py tests/topic_signals/test_briefs.py \
  tests/nodes/test_topic_ideator.py
git commit -m "feat: require profile-bound content contracts"
```

## Task 3: Give Prompts and Ranking the Same Account Contract

**Files:**
- Create: `src/prompts/fragments/creator_profile.txt`
- Modify: `src/prompts/composer.py`
- Modify: `src/nodes/node_c_virality_scorer.py`
- Modify: `src/prompts/base/angle_strategist.txt`
- Modify: `src/prompts/base/virality_scorer.txt`
- Modify: `src/prompts/base/outline_architect.txt`
- Modify: `src/prompts/base/draft_writer.txt`
- Modify: `src/prompts/base/title_lab.txt`
- Modify: `src/prompts/base/title_ranker.txt`
- Modify: `src/prompts/base/r1_reflector.txt`
- Modify: `src/prompts/base/r2_compliance.txt`
- Test: `tests/prompts/test_composer.py`
- Test: `tests/nodes/test_virality_scorer.py`

**Interfaces:**
- Consumes: `state.creator_profile` and `TopicItem.content_contract`.
- Produces: prompt payloads that preserve first-screen, screenshot, proof, and audience constraints.
- Downstream contract: R1 and R2 receive explicit instructions to treat missing contract execution as an edit/block condition.

- [ ] **Step 1: Write failing prompt and scorer tests**

```python
def test_stateful_prompt_includes_creator_profile_fragment():
    prompt = compose_prompt_for_state("draft_writer", profile_bound_state())
    assert "23–35 岁、通勤、有基础护肤和底妆需求的女性" in prompt
    assert "不使用卡通角色、IP 或纯装饰性 AI 插图" in prompt


def test_virality_scorer_receives_content_contract(monkeypatch):
    result = virality_scorer_node(profile_bound_state_with_novelty_result())
    sent = fake_model.last_messages[-1].content
    assert '"first_screen_promise"' in sent
    assert '"screenshot_asset"' in sent
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/prompts/test_composer.py tests/nodes/test_virality_scorer.py -v`

Expected: FAIL because profile text and contract fields are absent from the relevant prompts.

- [ ] **Step 3: Implement shared and task-specific prompt rules**

Append the fragment only in `compose_prompt_for_state` when the state has a
creator profile, preserving generic `compose_prompt` behavior. The fragment
must include the fixed audience, allowed subdomains, excluded themes, three
visual modes, and these hard requirements:

```text
- 第一张必须说清谁、什么问题、得到什么。
- 必须交付一页可截图保存的步骤、清单、判断标准或对比表。
- 不用虚构第一人称经历；不使用卡通角色、IP 或纯装饰性 AI 插图。
```

Pass `trends` alongside novelty results to `virality_scorer_node` so the prompt
has each candidate's contract. Add hard rejection language to the scorer for
missing screenshot asset, vague first-screen promise, out-of-profile audience,
or decorative-only proof. Update the editorial prompts with the exact
requirements from the approved design: no fabricated anecdotes, no inflated
terms (`神技`, `急救`, `亲测有效`, `救命`, `无缝`, `隐形`), and a default
outline sequence that reserves the screenshot card.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/prompts/test_composer.py tests/nodes/test_virality_scorer.py -v`

Expected: PASS.

- [ ] **Step 5: Commit prompt and scoring policy**

```bash
git add src/prompts/fragments/creator_profile.txt src/prompts/composer.py \
  src/nodes/node_c_virality_scorer.py src/prompts/base/angle_strategist.txt \
  src/prompts/base/virality_scorer.txt src/prompts/base/outline_architect.txt \
  src/prompts/base/draft_writer.txt src/prompts/base/title_lab.txt \
  src/prompts/base/title_ranker.txt src/prompts/base/r1_reflector.txt \
  src/prompts/base/r2_compliance.txt tests/prompts/test_composer.py \
  tests/nodes/test_virality_scorer.py
git commit -m "feat: enforce beauty account contract in editorial prompts"
```

## Task 4: Replace Cartoon Storyboards with Text-Led Card Layouts

**Files:**
- Modify: `src/schemas/storyboard.py`
- Modify: `src/nodes/node_o_storyboards_generator.py`
- Modify: `src/nodes/node_o_assembler.py`
- Modify: `src/nodes/node_p_content_writer.py`
- Modify: `src/prompts/base/storyboards_generator.txt`
- Modify: `src/prompts/base/storyboards_images_generator.txt`
- Modify: `src/prompts/node_o_storyboards_generator.txt`
- Modify: `main.py`
- Test: `tests/nodes/test_metadata_flow.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `publish_package`, matching `TopicItem.content_contract`, and creator profile.
- Produces: six to eight `StoryboardFrame`s with a typed `card_role`,
  `is_screenshot_asset`, `visual_mode`, and proof usage.
- Downstream contract: the first frame copies `content_contract.first_screen_promise`; at least one frame is marked screenshot-ready.

- [ ] **Step 1: Write failing storyboard schema and generation tests**

```python
def test_storyboard_payload_requires_six_to_eight_cards():
    with pytest.raises(ValidationError):
        StoryboardPayload.model_validate({"storyboards": [frame()] * 5})


def test_storyboard_first_card_and_screenshot_asset_follow_contract(monkeypatch):
    package = generated_package_with_contract()
    result = storyboards_generator_node(package)
    frames = result["publish_package"]["storyboards"]
    assert frames[0]["on_image_copy"] == package["content_contract"]["first_screen_promise"]
    assert any(frame["is_screenshot_asset"] for frame in frames)
    assert all("小蝾螈" not in frame["image_prompt_cn"] for frame in frames)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/nodes/test_metadata_flow.py tests/test_main.py -v`

Expected: FAIL because the schema requires 8–10 cards and the prompt is axolotl-specific.

- [ ] **Step 3: Implement text-card storyboard contracts**

Delete the character-only `character_action` and `continuity_note` fields from
`StoryboardFrame` and update every fixture that constructs a frame. Extend the
remaining frame model with:

```python
card_role: Literal["cover", "decision_rule", "step", "comparison", "screenshot_asset", "boundary", "discussion"]
is_screenshot_asset: bool = False
visual_mode: Literal["text_card", "text_plus_real_proof", "comparison_table"]
proof_asset_usage: str = "none"
```

Set `StoryboardPayload.storyboards` to `Field(min_length=6, max_length=8)`. In
the generator node, find the selected topic by `publish_package["topic_id"]`
in `state["trends"]`, serialize its contract into the model prompt, and reject
a generated payload whose first cover copy is not exactly the contract promise
or whose screenshot marker is absent.

In `assembler_node`, locate the selected topic in `state["trends"]` and inject
`content_contract=topic.content_contract.model_dump(mode="json")` into the
publish package. In `content_writer_node`, add that dictionary under
`record.metadata["content_contract"]`, so exports and future analytics have the
same contract as Carousel QA.

Replace all axolotl, character-action, character-reference, cute-cartoon, and
fixed top/middle/bottom layout instructions in both active prompt files. The
new prompt must require high-contrast text cards, optional real proof visuals,
and a six-to-eight-card sequence. Update `main.export_publish_package` to pass
the content contract and creator profile to the image instruction export.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/nodes/test_metadata_flow.py tests/test_main.py -v`

Expected: PASS.

- [ ] **Step 5: Commit text-card storyboard generation**

```bash
git add src/schemas/storyboard.py src/nodes/node_o_storyboards_generator.py \
  src/nodes/node_o_assembler.py src/nodes/node_p_content_writer.py \
  src/prompts/base/storyboards_generator.txt \
  src/prompts/base/storyboards_images_generator.txt \
  src/prompts/node_o_storyboards_generator.txt main.py \
  tests/nodes/test_metadata_flow.py tests/test_main.py
git commit -m "feat: generate text-led beauty card carousels"
```

## Task 5: Add Deterministic Carousel QA and Graph Routing

**Files:**
- Create: `src/schemas/carousel_qa.py`
- Create: `src/nodes/node_p_carousel_qa.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Modify: `src/schemas/agent_state.py`
- Test: `tests/nodes/test_carousel_qa.py`
- Test: `tests/nodes/test_domain_nodes.py`
- Test: `tests/test_graph.py`

**Interfaces:**
- Consumes: final `publish_package`, `state.trends`, and the active creator profile.
- Produces: `CarouselQAResult(passed, issues)` and, if failed, a populated `DecisionOutput` with `next_node="R1_REFLECTOR"`.
- Routing: pass → `human_review`; fail → `r1_reflector` → existing decision loop.

- [ ] **Step 1: Write failing QA and graph tests**

```python
def test_carousel_qa_rejects_missing_screenshot_asset():
    result = carousel_qa_node(package_without_screenshot_asset_state())
    assert result["carousel_qa_result"].passed is False
    assert result["decision_output"].next_node == "R1_REFLECTOR"
    assert result["carousel_qa_result"].issues[0].rule_id == "missing_screenshot_asset"


def test_carousel_qa_accepts_contract_compliant_cards():
    result = carousel_qa_node(contract_compliant_package_state())
    assert result["carousel_qa_result"].passed is True
    assert route_after_carousel_qa(result) == "human_review"
```

Extend the graph assertion to require `("storyboard_generator", "carousel_qa")`
and conditional QA routing, rather than the old direct edge to `human_review`.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tests/nodes/test_carousel_qa.py tests/nodes/test_domain_nodes.py tests/test_graph.py -v`

Expected: FAIL because the QA node and graph edge do not exist.

- [ ] **Step 3: Implement deterministic QA and reusable R1 task construction**

Implement these checks without an extra model call:

```python
def validate_carousel(package: dict, contract: ContentContract) -> list[CarouselQAIssue]:
    # card count must be 6..8
    # frame 1 must have card_role == "cover" and exact first_screen_promise
    # at least one screenshot marker must exist
    # each frame visual_mode must equal the contract visual mode
    # reject banned decorative terms in visible descriptions and image prompts
    # reject duplicate non-empty on_image_copy values
```

For a failed result, convert each issue into a `SingleTask` with
`source="carousel_qa"`, `severity="high"`, and a frame-level `location_hint`.
Build `R1Input` from the package's visible text using the same normalized
fields the existing decision engine expects; do not bypass R1 or R2. Add
`route_after_carousel_qa` and wire the graph:

```python
builder.add_edge("storyboard_generator", "carousel_qa")
builder.add_conditional_edges(
    "carousel_qa",
    route_after_carousel_qa,
    {"r1_reflector": "r1_reflector", "human_review": "human_review"},
)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m pytest tests/nodes/test_carousel_qa.py tests/nodes/test_domain_nodes.py tests/test_graph.py -v`

Expected: PASS.

- [ ] **Step 5: Commit carousel QA**

```bash
git add src/schemas/carousel_qa.py src/nodes/node_p_carousel_qa.py \
  src/nodes/__init__.py src/graph.py src/schemas/agent_state.py \
  tests/nodes/test_carousel_qa.py tests/nodes/test_domain_nodes.py tests/test_graph.py
git commit -m "feat: block carousels that miss first-screen contract"
```

## Task 6: Validate the Complete Workflow and Update the Design Record

**Files:**
- Modify: `docs/superpowers/specs/2026-07-10-beauty-account-content-workflow-design.md`
- Test: full suite under `tests/`

**Interfaces:**
- Consumes: all prior commits.
- Produces: documented implementation status and a verified feature branch.

- [ ] **Step 1: Add failing end-to-end fixture coverage**

Add one integration fixture that starts with `COMMUTING_BEAUTY_WOMEN_V1`, a
`beauty/skincare` signal, and a complete `ContentContract`; assert the final
package has only allowed scope, six to eight cards, an exact first-screen
promise, and one screenshot card. Add an adjacent case that routes an invalid
carousel back to R1.

- [ ] **Step 2: Run the new integration test and verify it fails before fixture wiring**

Run: `python -m pytest tests/integration/test_beauty_account_workflow.py -v`

Expected: FAIL until the fixture and graph routing are wired.

- [ ] **Step 3: Implement only the fixture and design-status update**

Mark the design document's Status section as implemented, add the feature
branch name, and document the deterministic QA rules. Do not add a second
generation path or activate inactive image nodes.

- [ ] **Step 4: Run all verification commands**

Run:

```bash
python -m pytest tests/integration/test_beauty_account_workflow.py -v
python -m pytest
git diff --check
```

Expected: the integration test passes, the full suite passes, and `git diff --check` emits no output.

- [ ] **Step 5: Commit final validation and documentation**

```bash
git add docs/superpowers/specs/2026-07-10-beauty-account-content-workflow-design.md \
  tests/integration/test_beauty_account_workflow.py
git commit -m "test: verify beauty account workflow contract"
```

## Plan Self-Review

- **Spec coverage:** Task 1 implements account positioning; Task 2 implements
  typed contracts; Task 3 covers prompt and editorial policy; Task 4 removes
  cartoon visual generation; Task 5 adds first-screen/screenshot QA; Task 6
  covers integration verification and rollout documentation. No approved
  requirement is left without a task.
- **Scope check:** inactive image nodes and unused trend scout cleanup are
  intentionally deferred; neither is necessary to enforce the new account
  contract.
- **Type consistency:** `CreatorProfile`, `ContentContract`,
  `CarouselQAResult`, `TopicItem.content_contract`, and
  `AgentState.carousel_qa_result` are introduced before consumers use them.
- **Placeholder scan:** no unresolved placeholders, implicit test steps, or
  unnamed implementation interfaces remain.
