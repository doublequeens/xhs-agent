# Local Text Card Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace AI-image prompt export with a no-network local HTML/CSS renderer that produces six polished, upload-ready Chinese Xiaohongshu text-card PNGs per approved beauty post.

**Architecture:** The storyboard LLM emits a constrained six-card `TextCardPayload`, not image prompts. A deterministic renderer turns those cards into self-contained HTML/CSS and captures them with local Playwright Chromium. A render QA node checks the generated PNGs and card contract before human review; final export preserves the JSON audit record and writes the PNGs into the publish directory.

**Tech Stack:** Python 3.12, Pydantic, Playwright sync API, local Chromium, HTML/CSS, pytest.

## Global Constraints

- Do not call gpt-image-2, another image API, a web search API, or an image/material service.
- Output exactly six `1080 × 1440` PNG text cards for every renderable publish package.
- Supported themes are exactly `warm_neutral` and `cool_sage`; every card in one payload uses the same theme.
- Supported templates are exactly `cover_statement`, `wrong_vs_right`, `step_timeline`, `saveable_checklist`, `decision_rule`, and `question_closer`, in that order.
- The cover headline must exactly equal `content_contract.first_screen_promise`.
- Do not render long narration, external images, emojis, product imagery, logos, watermarks, characters, or decorative illustration.
- Keep the current content, compliance, human-review, and publishing metadata rules intact.

---

## File Structure

```text
src/schemas/text_card.py                 # Pydantic contracts for six card templates
src/schemas/decision.py                  # Structured visible text blocks for R1/R2 review
src/rendering/text_cards.py              # CSS/HTML builder and local Playwright PNG renderer
src/nodes/node_p_text_card_renderer.py   # Graph node that writes six cards and updates the package
src/nodes/node_p_render_qa.py            # Deterministic generated-file and contract QA node
src/prompts/base/storyboards_generator.txt
src/nodes/node_o_storyboards_generator.py
src/nodes/node_p_carousel_qa.py
src/nodes/publish_patch.py
src/schemas/agent_state.py
src/schemas/__init__.py
src/nodes/__init__.py
src/graph.py
main.py
tests/schemas/test_text_card.py
tests/rendering/test_text_cards.py
tests/nodes/test_text_card_renderer.py
tests/nodes/test_render_qa.py
tests/nodes/test_carousel_qa.py
tests/nodes/test_metadata_flow.py
tests/nodes/test_final_policy_guard.py
tests/test_graph.py
tests/test_main.py
tests/integration/test_beauty_account_workflow.py
```

### Shared Interfaces

```python
TextCardTemplate = Literal[
    "cover_statement", "wrong_vs_right", "step_timeline",
    "saveable_checklist", "decision_rule", "question_closer",
]
TextCardTheme = Literal["warm_neutral", "cool_sage"]

class TextCardPayload(BaseModel):
    storyboards: list[TextCardFrame]

def render_text_cards(
    payload: TextCardPayload,
    output_dir: Path,
    *,
    playwright_factory: Callable[[], Playwright] = sync_playwright,
) -> list[Path]: ...

def text_card_renderer_node(state: AgentState) -> dict: ...
def render_qa_node(state: AgentState) -> dict: ...
def route_after_render_qa(state: AgentState) -> str: ...
```

### Task 1: Define the structured text-card contract and migrate storyboard prompting

**Files:**

- Create: `src/schemas/text_card.py`
- Modify: `src/schemas/__init__.py`
- Modify: `src/schemas/storyboard.py`
- Modify: `src/schemas/decision.py`
- Modify: `src/prompts/base/storyboards_generator.txt`
- Modify: `src/prompts/base/r1_reflector.txt`
- Modify: `src/prompts/base/decision_engine.txt`
- Modify: `src/nodes/node_o_storyboards_generator.py`
- Modify: `src/nodes/node_q_human_review.py`
- Modify: `src/nodes/node_j_decision_engine.py`
- Modify: `src/nodes/publish_patch.py`
- Modify: `src/nodes/node_p_carousel_qa.py`
- Test: `tests/schemas/test_text_card.py`
- Test: `tests/nodes/test_metadata_flow.py`
- Test: `tests/nodes/test_final_policy_guard.py`
- Test: `tests/nodes/test_carousel_qa.py`

**Interfaces:**

- Consumes: `content_contract.first_screen_promise`, `content_contract.screenshot_asset`, and the assembled `publish_package`.
- Produces: `TextCardPayload` stored at `publish_package["storyboards"]`; structured visible-text blocks that let R1/R2 inspect and patch every displayed text atom.

- [ ] **Step 1: Write failing schema tests for valid six-card payloads and invalid copy**

Create `tests/schemas/test_text_card.py` with a factory that returns the six required templates in fixed order. Assert a valid payload parses, then assert the following inputs raise `ValidationError`:

```python
def test_text_card_payload_requires_six_cards_in_the_fixed_template_order():
    payload = TextCardPayload.model_validate({"storyboards": valid_frames()})
    assert [frame.template for frame in payload.storyboards] == [
        "cover_statement", "wrong_vs_right", "step_timeline",
        "saveable_checklist", "decision_rule", "question_closer",
    ]

@pytest.mark.parametrize("field,value", [
    ("headline", "这是一条超过二十八个汉字限制的标题文案需要被拒绝"),
    ("kicker", "超过十个汉字的标签需要被拒绝"),
    ("footer", "超过十八个汉字的页脚内容必须被拒绝"),
])
def test_text_card_copy_limits_are_enforced(field, value):
    frame = valid_frames()[0]
    frame[field] = value
    with pytest.raises(ValidationError):
        TextCardPayload.model_validate({"storyboards": [frame, *valid_frames()[1:]]})
```

- [ ] **Step 2: Run schema tests to verify they fail**

Run: `python -m pytest tests/schemas/test_text_card.py -v`  
Expected: FAIL because `src.schemas.text_card` does not exist.

- [ ] **Step 3: Implement discriminated template models and payload-level order validation**

Create `src/schemas/text_card.py`. Use Pydantic models with `extra="forbid"`, shared `frame_id`, `template`, `theme`, `kicker`, `headline`, and `footer` fields, and six concrete subclasses. Define short child models for list entries:

```python
class TimelineStep(BaseModel):
    name: str = Field(min_length=1, max_length=12)
    hint: str = Field(min_length=1, max_length=16)

class WrongVsRightFrame(TextCardFrame):
    template: Literal["wrong_vs_right"]
    wrong_items: list[str] = Field(min_length=2, max_length=3)
    right_items: list[str] = Field(min_length=2, max_length=4)

class TextCardPayload(BaseModel):
    storyboards: list[TextCardFrame] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_template_order(self):
        expected = ["cover_statement", "wrong_vs_right", "step_timeline",
                    "saveable_checklist", "decision_rule", "question_closer"]
        if [frame.template for frame in self.storyboards] != expected:
            raise ValueError("storyboards must use the six required templates in order")
        if len({frame.theme for frame in self.storyboards}) != 1:
            raise ValueError("all storyboards must use one theme")
        return self
```

Use a discriminated union keyed by `template`. Set text limits on every template-owned string: wrong/right/checklist strings max 16, decision condition and recommendation max 16, and question max 22.

Replace the old image-prompt fields in `src/schemas/storyboard.py` by re-exporting `TextCardFrame` and `TextCardPayload` for compatibility with imports. Export the new models from `src/schemas/__init__.py`.

Migrate review-visible storyboard text at the same boundary. In `src/schemas/decision.py`, replace the fixed three-field representation with `StoryboardVisibleText(frame_id, template, text_blocks: dict[str, str])`; each key is a precise editable location such as `headline`, `wrong_items[0]`, `steps[1].hint`, or `footer`. Update `src/nodes/publish_patch.py` so `extract_storyboard_visible_text` emits every displayed atom, while `storyboard_patch_without_visible_text` removes those atom keys before metadata-only storyboard patches are reapplied. Add `apply_storyboard_visible_text_patch` to map R1/R2 `text_blocks` changes back to the matching nested card field and reject an unknown non-empty `frame_id`; it must never fall back to list position. Before R2 scans or regenerated cards consume a patch, merge its blocks into the complete prior visible-text snapshot by matching `frame_id`, so no displayed atom can disappear. Update the storyboard generator, human review, decision engine, R1 prompt, and decision prompt to use this representation. This prevents compliance edits from being lost and makes final-policy scans cover checklist and decision-rule text.

Migrate `validate_carousel` in this same task so a schema-valid `TextCardPayload` can reach human review. It must validate the new payload and produce actionable failures for invalid schema, non-six-card count, template-order mismatch, mixed theme, a cover headline that differs from `first_screen_promise`, and a missing `saveable_checklist` card. Remove retired checks for `card_role`, `visual_mode`, image-prompt, and decorative-illustration fields.

- [ ] **Step 4: Make the storyboard prompt emit card data only**

Replace `src/prompts/base/storyboards_generator.txt` with a JSON-only contract that lists the six templates in order, their required fields, their character limits, and these hard rules:

```text
- 不得输出 image_prompt_cn、image_prompt_en、narration、composition、scene_background、visual_description、text_area 或 negative_prompt。
- 第一张 template 必须为 cover_statement，headline 必须逐字等于 content_contract.first_screen_promise。
- 第四张必须为 saveable_checklist，清单内容必须把 screenshot_asset 改写为 3–5 条可执行短项。
- 每个 headline 最多 28 个汉字；禁止把免责声明、正文段落或互动引导拼入 headline。
```

In `storyboards_generator_node`, leave model output unvalidated so deterministic carousel QA retains responsibility for LLM schema failures. Preserve `content_contract` and all existing package metadata exactly as today.

- [ ] **Step 5: Update metadata and visible-text tests and run the focused suite**

Replace assertions for old image-prompt fields in `tests/nodes/test_metadata_flow.py` with assertions for the six required templates, fixed theme, cover headline, and checklist field. Update `tests/nodes/test_final_policy_guard.py` to assert that a prohibited phrase in `checklist_items[1]` produces the precise location `storyboard_visible_text[3].text_blocks.checklist_items[1]`, and that an approved R1 patch at that location updates the original card item. Update `tests/nodes/test_carousel_qa.py` with a schema-valid six-card payload that passes and individual failures for the new contract. Run:

```bash
python -m pytest tests/schemas/test_text_card.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/nodes/test_carousel_qa.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the contract migration**

```bash
git add src/schemas/text_card.py src/schemas/storyboard.py src/schemas/decision.py src/schemas/__init__.py src/prompts/base/storyboards_generator.txt src/prompts/base/r1_reflector.txt src/prompts/base/decision_engine.txt src/nodes/publish_patch.py src/nodes/node_o_storyboards_generator.py src/nodes/node_q_human_review.py src/nodes/node_j_decision_engine.py src/nodes/node_p_carousel_qa.py tests/schemas/test_text_card.py tests/nodes/test_metadata_flow.py tests/nodes/test_final_policy_guard.py tests/nodes/test_carousel_qa.py
git commit -m "feat: define structured text card payloads"
```

### Task 2: Build deterministic HTML/CSS templates and local PNG rendering

**Files:**

- Create: `src/rendering/__init__.py`
- Create: `src/rendering/text_cards.py`
- Test: `tests/rendering/test_text_cards.py`

**Interfaces:**

- Consumes: a schema-valid `TextCardPayload` from Task 1 and a writable output directory.
- Produces: six ordered image paths named `01-cover.png`, `02-wrong-vs-right.png`, `03-timeline.png`, `04-checklist.png`, `05-decision.png`, and `06-question.png`.

- [ ] **Step 1: Write failing unit tests for template HTML and deterministic filenames**

Create `tests/rendering/test_text_cards.py` with a valid payload fixture. Test pure functions before browser integration:

```python
def test_render_card_html_uses_theme_tokens_and_only_template_content():
    html = render_card_html(valid_payload().storyboards[1])
    assert "#F7F2EB" in html
    assert "错误顺序" in html
    assert "wrong-vs-right" in html
    assert "image_prompt_cn" not in html

def test_output_paths_follow_the_fixed_publish_sequence(tmp_path):
    assert output_paths(tmp_path) == [
        tmp_path / "01-cover.png", tmp_path / "02-wrong-vs-right.png",
        tmp_path / "03-timeline.png", tmp_path / "04-checklist.png",
        tmp_path / "05-decision.png", tmp_path / "06-question.png",
    ]
```

- [ ] **Step 2: Run renderer unit tests to verify they fail**

Run: `python -m pytest tests/rendering/test_text_cards.py -v`  
Expected: FAIL because `src.rendering.text_cards` does not exist.

- [ ] **Step 3: Implement design tokens, HTML escaping, and one template renderer per card type**

In `src/rendering/text_cards.py`, define immutable token maps matching the approved spec:

```python
THEMES = {
    "warm_neutral": {"background": "#F7F2EB", "ink": "#292622", "accent": "#B85C56"},
    "cool_sage": {"background": "#EEF2ED", "ink": "#243128", "accent": "#607A69"},
}
CANVAS = {"width": 1080, "height": 1440, "padding": 84}
```

Implement `render_card_html(frame: TextCardFrame) -> str` by dispatching on `frame.template`. Build complete standalone HTML with embedded CSS, a Chinese sans-serif stack, fixed `1080px × 1440px` body, and no external fonts/assets. Escape every content string with `html.escape`. Use CSS grid for `wrong_vs_right`, timeline steps, checklist rows, and decision rows. Do not reduce font size dynamically.

- [ ] **Step 4: Add a Playwright renderer with overflow detection**

Implement `render_text_cards`. It must start one local Chromium session, render each standalone document using `page.set_content`, check every `[data-card-copy]` element before screenshot, and close all resources in `finally`:

```python
def _assert_no_overflow(page, frame_id: str) -> None:
    overflowing = page.locator("[data-card-copy]").evaluate_all(
        "elements => elements.filter(e => e.scrollHeight > e.clientHeight || e.scrollWidth > e.clientWidth).map(e => e.dataset.copyRole)"
    )
    if overflowing:
        raise TextCardRenderError(f"{frame_id} text overflow: {', '.join(overflowing)}")

page.set_viewport_size({"width": 1080, "height": 1440})
page.set_content(render_card_html(frame), wait_until="load")
_assert_no_overflow(page, frame.frame_id)
page.locator(".card").screenshot(path=str(path))
```

The renderer creates `output_dir`, writes all six images only after each screenshot succeeds, and removes already-written images if a later frame fails. Raise `TextCardRenderError` for browser startup, overflow, screenshot, or output failures.

- [ ] **Step 5: Add a real local-browser smoke test and run the renderer suite**

Add a test guarded by the installed local Playwright browser that calls `render_text_cards(valid_payload(), tmp_path)` and uses `PIL.Image.open` only if Pillow is already available; otherwise inspect PNG IHDR width/height with `struct.unpack`. Assert six images exist and each is `1080 × 1440`.

Run:

```bash
python -m pytest tests/rendering/test_text_cards.py -v
```

Expected: PASS. If Chromium is missing, install it with `playwright install chromium`, then rerun the same command.

- [ ] **Step 6: Commit renderer implementation**

```bash
git add src/rendering/__init__.py src/rendering/text_cards.py tests/rendering/test_text_cards.py
git commit -m "feat: render text cards locally with CSS"
```

### Task 3: Add rendering and generated-file QA nodes to the graph

**Files:**

- Create: `src/schemas/render_qa.py`
- Create: `src/nodes/node_p_text_card_renderer.py`
- Create: `src/nodes/node_p_render_qa.py`
- Modify: `src/schemas/__init__.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Test: `tests/nodes/test_text_card_renderer.py`
- Test: `tests/nodes/test_render_qa.py`
- Test: `tests/test_graph.py`

**Interfaces:**

- Consumes: carousel-QA-approved `publish_package["storyboards"]`, selected content contract, and `outputs/publish` as the local root.
- Produces: `publish_package["rendered_image_paths"]`, `RenderQAResult`, and a route to human review only when every generated PNG passes.

- [ ] **Step 1: Write failing renderer-node and QA-node tests**

Create tests with a monkeypatched `render_text_cards` so they do not require Chromium:

```python
def test_renderer_node_adds_six_ordered_local_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(module, "render_text_cards", fake_renderer_writing_pngs)
    result = module.text_card_renderer_node(valid_state(tmp_path))
    assert [Path(path).name for path in result["publish_package"]["rendered_image_paths"]] == [
        "01-cover.png", "02-wrong-vs-right.png", "03-timeline.png",
        "04-checklist.png", "05-decision.png", "06-question.png",
    ]

def test_render_qa_routes_missing_or_wrong_size_pngs_to_r1(tmp_path):
    result = render_qa_node(state_with_invalid_png(tmp_path))
    assert result["render_qa_result"].passed is False
    assert result["decision_output"].next_node == "R1_REFLECTOR"
```

- [ ] **Step 2: Run node tests to verify they fail**

Run: `python -m pytest tests/nodes/test_text_card_renderer.py tests/nodes/test_render_qa.py -v`  
Expected: FAIL because the new nodes and schema do not exist.

- [ ] **Step 3: Implement `RenderQAResult` and renderer node**

In `src/schemas/render_qa.py`, define Pydantic `RenderQAIssue(rule_id, message, location_hint)` and `RenderQAResult(passed, issues)`. In `node_p_text_card_renderer.py`:

```python
def text_card_renderer_node(state: AgentState) -> dict:
    package = dict(state["publish_package"])
    payload = TextCardPayload.model_validate({"storyboards": package.get("storyboards")})
    output_dir = render_output_directory(package)
    paths = render_text_cards(payload, output_dir)
    package["rendered_image_paths"] = [str(path) for path in paths]
    return {"publish_package": package, "current_node": "TEXT_CARD_RENDERER"}
```

Put `render_output_directory` in this module. It must validate domain/profile metadata using the same profile resolver as export, create `outputs/publish/YYYYMMDD-domain-subdomain-title/images`, and return that path. It must reject output paths outside the repository `outputs/publish` root.

At this step add `render_qa_result: NotRequired[Optional[RenderQAResult]]` and `rendered_image_paths: NotRequired[list[str]]` to `AgentState`, and export `RenderQAIssue` / `RenderQAResult` from `src/schemas/__init__.py`.

- [ ] **Step 4: Implement render QA and graph routing**

`render_qa_node` validates exactly six paths, their required names/order, PNG signature, and PNG IHDR dimensions. It also revalidates the `TextCardPayload`, cover headline against the selected contract, and presence of `saveable_checklist`. Convert every issue into the same R1 decision shape as carousel QA, with source `render_qa`.

Update graph routing precisely:

```python
builder.add_node("text_card_renderer", nodes.text_card_renderer_node)
builder.add_node("render_qa", nodes.render_qa_node)
builder.add_edge("storyboard_generator", "carousel_qa")
builder.add_conditional_edges(
    "carousel_qa", route_after_carousel_qa,
    {"r1_reflector": "r1_reflector", "text_card_renderer": "text_card_renderer"},
)
builder.add_edge("text_card_renderer", "render_qa")
builder.add_conditional_edges(
    "render_qa", route_after_render_qa,
    {"r1_reflector": "r1_reflector", "human_review": "human_review"},
)
```

Change `route_after_carousel_qa` so a pass returns `text_card_renderer`, not `human_review`. Add exports in `src/nodes/__init__.py` and test the graph edge sequence.

- [ ] **Step 5: Run focused node and graph tests**

Run:

```bash
python -m pytest tests/nodes/test_carousel_qa.py tests/nodes/test_text_card_renderer.py tests/nodes/test_render_qa.py tests/test_graph.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit graph integration**

```bash
git add src/schemas/render_qa.py src/schemas/__init__.py src/schemas/agent_state.py src/nodes/node_p_text_card_renderer.py src/nodes/node_p_render_qa.py src/nodes/__init__.py src/graph.py tests/nodes/test_text_card_renderer.py tests/nodes/test_render_qa.py tests/test_graph.py
git commit -m "feat: validate locally rendered text cards"
```

### Task 4: Export rendered assets instead of image-generation prompts and verify the full beauty workflow

**Files:**

- Modify: `main.py`
- Delete: `src/prompts/base/storyboards_images_generator.txt`
- Modify: `src/prompts/composer.py`
- Modify: `tests/test_main.py`
- Modify: `tests/integration/test_beauty_account_workflow.py`
- Modify: `tests/prompts/test_composer.py`

**Interfaces:**

- Consumes: a human-approved package containing `rendered_image_paths` from Task 3.
- Produces: a final publish directory containing the audit JSON and exactly six `images/*.png`, with no `Storyboard_images_generator_prompt.txt`.

- [ ] **Step 1: Write failing export and end-to-end tests**

Replace prompt-file assertions in `tests/test_main.py` with:

```python
def test_export_publish_package_preserves_rendered_cards_without_image_prompt(monkeypatch, tmp_path):
    package = valid_publish_package_with_rendered_images(tmp_path)
    monkeypatch.chdir(tmp_path)
    main.export_publish_package(package)
    exported = next((tmp_path / "outputs" / "publish").glob("*/images/*.png"))
    assert exported.name == "01-cover.png"
    assert not list((tmp_path / "outputs" / "publish").glob("*/Storyboard_images_generator_prompt.txt"))
```

Add a beauty integration assertion that an approved workflow reaches human review only after six local images are present, then resumes to final export.

- [ ] **Step 2: Run export and integration tests to verify they fail**

Run:

```bash
python -m pytest tests/test_main.py tests/integration/test_beauty_account_workflow.py -v
```

Expected: FAIL because the exporter still writes `Storyboard_images_generator_prompt.txt`.

- [ ] **Step 3: Replace prompt export with rendered-image export**

In `main.py`, remove the `compose_prompt("storyboards_images_generator", profile)` call and all prompt-file construction. Refactor `export_publish_package` to:

1. resolve the same final directory used by the renderer;
2. require exactly six `rendered_image_paths` already inside its `images` directory;
3. write the JSON audit file with `rendered_image_paths` relative to the package directory;
4. raise `ValueError` if a path is missing, outside the publish directory, non-PNG, or not in the required sequence.

Only call `export_publish_package` after the `human_review` node emits a package and on the completed-checkpoint branch. Do not export interim storyboard output before render QA or human approval.

Remove `storyboards_images_generator` from `TASK_FILES`, delete its base prompt, and update composer tests so that requesting it raises `ValueError`.

- [ ] **Step 4: Run all relevant tests and the real local render smoke test**

Run:

```bash
python -m pytest tests/schemas/test_text_card.py tests/rendering/test_text_cards.py tests/nodes/test_text_card_renderer.py tests/nodes/test_render_qa.py tests/nodes/test_carousel_qa.py tests/nodes/test_metadata_flow.py tests/test_graph.py tests/test_main.py tests/integration/test_beauty_account_workflow.py tests/prompts/test_composer.py -v
python -m pytest
```

Expected: all tests pass. Then run one controlled beauty workflow fixture and inspect the generated contact sheet or six PNG dimensions; do not call an image API.

- [ ] **Step 5: Commit the export migration**

```bash
git add main.py src/prompts/composer.py src/prompts/base/storyboards_images_generator.txt tests/test_main.py tests/integration/test_beauty_account_workflow.py tests/prompts/test_composer.py
git commit -m "feat: export locally rendered publish cards"
```

## Plan Self-Review

- Spec coverage: Task 1 implements the six-card contract and copy limits; Task 2 implements the approved HTML/CSS design system and local renderer; Task 3 adds deterministic generated-file QA and graph gating; Task 4 removes image-generation prompt export and verifies the full publish workflow.
- Placeholder scan: this plan contains no unfinished markers; browser absence has an explicit installation and retry command.
- Type consistency: `TextCardPayload` is created in Task 1, rendered in Task 2, used by Task 3 nodes, and exported in Task 4. `rendered_image_paths` and `RenderQAResult` are added to state before Task 3 routing writes them. Structured `StoryboardVisibleText.text_blocks` is introduced before R1/R2/human-review code consumes it.
- Scope check: the work is one vertical workflow change. The only dependency is existing Playwright, already listed in `requirements.txt`; no new image API or external service is introduced.
