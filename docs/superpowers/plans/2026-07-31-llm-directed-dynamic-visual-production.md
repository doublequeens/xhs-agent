# LLM-Directed Dynamic Visual Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed six-template storyboard/HTML production path with one-family-per-carousel, LLM-directed 5–18 page scene planning, automated image search/generation, deterministic geometry/content QA, multimodal visual critique, and one final Human Review.

**Architecture:** Preserve the six families only as visual DNA and reference images. Convert immutable approved copy into `ContentAtomSet`, let Visual Director choose one family and a 5–18 page sequence, resolve requested assets, let Page Designer emit a constrained scene graph, then compile that graph through one generic Chromium renderer. Deterministic Design Plan QA and Render QA remain hard gates; a multimodal critic may request at most two aesthetic revisions. Remove the old visual nodes, storyboard contracts, family-specific renderer, and production fallback instead of running old and new paths in parallel.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, `google-genai`, Playwright/Chromium, Pillow, pytest, SQLite checkpoints, existing Pexels/Unsplash asset providers.

## Global Constraints

- Follow `AGENTS.md`, preserve user-owned changes, and start every implementation session with `git status --short`.
- Treat the approved design spec at `docs/superpowers/specs/2026-07-31-llm-directed-dynamic-visual-production-design.md` as canonical.
- Visible page text must be referenced from immutable content atoms. Visual models may split, group, line-break, emphasize, and reposition it, but may not rewrite it.
- Do not render AI disclosure labels, “示意图”, disclaimers, or any equivalent visible reminder. AI provenance remains internal metadata.
- Select exactly one of the six families per carousel; allow every page to vary inside that family’s palette, composition, whitespace, ornament, and density envelope.
- Visual Director owns the final page count, constrained only to 5–18. No default five-page fallback and no empty transition pages.
- Preserve asset containment, no-follow, licensing, transaction identity, byte hashing, and recovery-journal behavior.
- Never let aesthetic feedback bypass Design Plan QA, Render QA, content hashes, asset security, R2, Human Review, or Final Guard.
- Keep default tests offline. Gate real search/generation/vision smoke tests behind `RUN_LIVE_VISUAL_AI_TESTS=1`.
- Use `gemini-3.1-flash-image` for both multimodal visual reasoning and image generation through one `GEMINI_VISUAL_MODEL` setting; do not allow the two adapters to drift to different models.
- Use `apply_patch` for source edits and deletions. Do not delete checkpoint, memory, Chroma, or output data.

---

### Task 1: Introduce Immutable Content Atoms and Remove the 5–7 Page Hint

**Files:**
- Create: `src/schemas/content_atoms.py`
- Modify: `src/schemas/content_contract.py`
- Modify: `src/schemas/__init__.py`
- Modify: `src/prompts/base/topic_ideator.txt`
- Modify: `tests/schemas/test_content_contract.py`
- Create: `tests/schemas/test_content_atoms.py`
- Modify: `tests/schemas/test_topic_signal.py`
- Modify: `tests/domain/test_topic_metadata.py`

**Interfaces:**
- Consumes: approved title, cover copy, body copy, and structured content blocks from assembler output.
- Produces: immutable `ContentAtomSet`; upstream `ContentContract.page_count_hint` is advisory and allows 5–18.

- [ ] **Step 1: Write failing atom and page-count contract tests**

```python
def test_content_atom_set_rejects_mutated_hash():
    atom = ContentAtom(
        atom_id="title",
        text="刺痛不是正常建立耐受",
        role="title",
        sha256=sha256_text("刺痛不是正常建立耐受"),
    )
    with pytest.raises(ValidationError, match="atom sha256"):
        ContentAtomSet(
            atoms=[atom.model_copy(update={"text": "刺痛很正常"})],
            canonical_sha256=canonical_sha256(
                [atom.model_dump(mode="json")]
            ),
        )


@pytest.mark.parametrize("value", [5, 12, 18])
def test_page_count_hint_accepts_full_dynamic_range(value):
    contract = ContentContract(
        audience="容易敏感的通勤人群",
        trigger_situation="护肤后皮肤持续刺痛",
        decision_problem="应该继续建立耐受还是立即停用",
        first_screen_promise="一分钟判断该继续还是停用",
        screenshot_asset="停止使用判断清单",
        proof_asset="真实风格皮肤状态示例",
        visual_mode="text_plus_real_proof",
        content_job="diagnose_and_adjust",
        primary_visual_family="face_zone_map",
        primary_visual_subject="skin_macro",
        proof_mode="real_photo",
        page_count_hint=value,
    )
    assert contract.page_count_hint == value


@pytest.mark.parametrize("value", [4, 19])
def test_page_count_hint_rejects_out_of_range(value):
    with pytest.raises(ValidationError):
        ContentContract(
            audience="容易敏感的通勤人群",
            trigger_situation="护肤后皮肤持续刺痛",
            decision_problem="应该继续建立耐受还是立即停用",
            first_screen_promise="一分钟判断该继续还是停用",
            screenshot_asset="停止使用判断清单",
            proof_asset="真实风格皮肤状态示例",
            visual_mode="text_plus_real_proof",
            content_job="diagnose_and_adjust",
            primary_visual_family="face_zone_map",
            primary_visual_subject="skin_macro",
            proof_mode="real_photo",
            page_count_hint=value,
        )
```

- [ ] **Step 2: Run the focused tests and confirm they fail for missing contracts**

Run: `pytest -q tests/schemas/test_content_atoms.py tests/schemas/test_content_contract.py tests/schemas/test_topic_signal.py tests/domain/test_topic_metadata.py`

Expected: failures because `ContentAtom`, `ContentAtomSet`, and `page_count_hint` do not exist.

- [ ] **Step 3: Implement exact immutable atom contracts**

```python
class ContentAtom(StrictModel):
    atom_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    text: str = Field(min_length=1)
    role: Literal["title", "cover", "heading", "paragraph", "list_item", "step", "quote"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_hash(self):
        if self.sha256 != sha256_text(self.text):
            raise ValueError("atom sha256 does not match text")
        return self


class ContentFragment(StrictModel):
    fragment_id: str
    source_atom_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)


class ContentAtomSet(StrictModel):
    atoms: tuple[ContentAtom, ...] = Field(min_length=1)
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def verify_canonical_hash(self):
        expected = canonical_sha256(
            [atom.model_dump(mode="json") for atom in self.atoms]
        )
        if self.canonical_sha256 != expected:
            raise ValueError("content atom set canonical sha256 does not match atoms")
        return self
```

Use one canonical JSON serializer for all visual hashes:

```python
def canonical_sha256(value: BaseModel | dict | list) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

Replace `recommended_frame_count: int = Field(ge=5, le=7)` with:

```python
page_count_hint: int | None = Field(default=None, ge=5, le=18)
```

Move `ContentJob` and the content-oriented `VisualFamily` literals into
`content_contract.py` (rename the latter to `PrimaryVisualStructure`) so this
upstream contract no longer imports the soon-to-be-deleted `visual_plan.py`.
Keep the existing serialized values for compatibility with topic signals.
Update the topic prompt to state that this is only an optional information-density hint; Visual Director decides the final count.

- [ ] **Step 4: Re-run focused tests**

Run: `pytest -q tests/schemas/test_content_atoms.py tests/schemas/test_content_contract.py tests/schemas/test_topic_signal.py tests/domain/test_topic_metadata.py`

Expected: all pass.

- [ ] **Step 5: Commit the contract slice**

```bash
git add src/schemas/content_atoms.py src/schemas/content_contract.py src/schemas/__init__.py src/prompts/base/topic_ideator.txt tests/schemas/test_content_atoms.py tests/schemas/test_content_contract.py tests/schemas/test_topic_signal.py tests/domain/test_topic_metadata.py
git commit -m "feat: define immutable visual content atoms"
```

---

### Task 2: Define Family DNA, Visual Direction, Scene Graph, and QA Contracts

**Files:**
- Create: `src/schemas/visual_style.py`
- Replace: `src/schemas/visual_director.py`
- Replace: `src/schemas/assets.py`
- Create: `src/schemas/scene_graph.py`
- Create: `src/schemas/design_qa.py`
- Create: `src/schemas/visual_critique.py`
- Replace: `src/schemas/render_manifest.py`
- Replace: `src/schemas/render_qa.py`
- Modify: `src/schemas/__init__.py`
- Create: `tests/schemas/test_visual_direction.py`
- Create: `tests/schemas/test_scene_graph.py`
- Create: `tests/schemas/test_visual_qa.py`

**Interfaces:**
- Consumes: `ContentAtomSet`, one family profile, asset bindings.
- Produces: `VisualDirectionPlan`, `CarouselDesignPlan`, `DesignPlanQAResult`, new `RenderManifest`, `RenderQAResult`, and `VisualCritique`.

- [ ] **Step 1: Write failing schema invariant tests**

Implement named tests for all of these cases:

```python
@pytest.mark.parametrize("page_count", [4, 19])
def test_direction_rejects_out_of_range_page_count(page_count):
    pages = tuple(
        PageDirection(
            page_id=f"page-{index}",
            sequence=index,
            purpose=f"purpose-{index}",
            visual_job=f"job-{index}",
            fragment_ids=(f"fragment-{index}",),
        )
        for index in range(1, page_count + 1)
    )
    with pytest.raises(ValidationError):
        make_direction_plan(page_count=page_count, page_sequence=pages)


def test_text_element_rejects_embedded_visible_text():
    payload = {
        "kind": "text",
        "element_id": "headline",
        "layer": 2,
        "box": {"x": 100, "y": 100, "width": 800, "height": 180},
        "content_ref": "fragment-1",
        "text": "模型擅自增加的文字",
        "style": {
            "font_role": "display",
            "font_size": 64,
            "line_height": 1.2,
            "color": "#111111",
            "align": "left",
            "weight": 700,
        },
    }
    with pytest.raises(ValidationError, match="extra"):
        TextElement.model_validate(payload)
```

Add equally explicit tests named
`test_fragments_reconstruct_atoms_character_for_character`,
`test_page_requires_content_and_unique_visual_job`,
`test_image_element_requires_asset_ref`,
`test_scene_rejects_html_css_and_unknown_icons`,
`test_design_plan_binds_all_source_hashes`, and
`test_text_only_critique_marks_image_relevance_not_applicable`. Each test builds
one complete valid factory object, changes exactly one field, and asserts the
specific validator message.

- [ ] **Step 2: Run schema tests and confirm missing-model failures**

Run: `pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py`

Expected: import and validation failures.

- [ ] **Step 3: Implement the family and direction contracts**

```python
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


TemplateFamily = Literal[
    "pink_red", "deep_teal", "soft_pink",
    "coral_impact", "green_catalog", "white_quote",
]


class FamilyStyleProfile(StrictModel):
    family: TemplateFamily
    reference_image_paths: tuple[str, ...] = Field(min_length=1)
    palette: tuple[str, ...] = Field(min_length=3)
    font_roles: dict[Literal["display", "heading", "body", "caption"], str]
    composition_principles: tuple[str, ...] = Field(min_length=2)
    whitespace_range: tuple[float, float]
    density_range: tuple[float, float]
    allowed_motifs: tuple[str, ...]
    prohibited_patterns: tuple[str, ...]


class PageDirection(StrictModel):
    page_id: str
    sequence: int = Field(ge=1)
    purpose: str = Field(min_length=1)
    visual_job: str = Field(min_length=1)
    fragment_ids: tuple[str, ...] = Field(min_length=1)
    asset_directive_ids: tuple[str, ...] = ()


class AssetDirective(StrictModel):
    directive_id: str
    page_id: str
    role: Literal["evidence_example", "skin_example", "texture", "object", "decorative"]
    required: bool
    preferred_source: Literal["search", "generate", "either", "none"]
    fallback_source: Literal["search", "generate", "none"]
    query_or_prompt: str | None
    negative_constraints: tuple[str, ...] = ()
    orientation: Literal["portrait", "landscape", "square", "any"]
    min_width: int = Field(ge=1)
    min_height: int = Field(ge=1)


class VisualDirectionPlan(StrictModel):
    template_family: TemplateFamily
    page_count: int = Field(ge=5, le=18)
    content_atom_set_sha256: Sha256
    art_direction: str
    palette: tuple[str, ...]
    typography_direction: dict[str, str]
    motifs: tuple[str, ...]
    content_fragments: tuple[ContentFragment, ...]
    page_sequence: tuple[PageDirection, ...]
    asset_directives: tuple[AssetDirective, ...]
    recent_visual_context: tuple[str, ...] = ()
```

Validators must enforce:

- `page_count == len(page_sequence)`;
- page sequences are contiguous and page IDs are unique;
- every page owns at least one fragment and has a non-blank, non-duplicated `visual_job`;
- all fragments reference known atoms, use semantic boundaries, stay ordered, do not overlap, and concatenate to the exact atom text;
- palette and motif values are subsets of the selected family profile at the node boundary.

- [ ] **Step 4: Implement the constrained scene graph**

```python
class Box(StrictModel):
    x: float = Field(ge=0, le=1080)
    y: float = Field(ge=0, le=1440)
    width: float = Field(gt=0, le=1080)
    height: float = Field(gt=0, le=1440)


class ElementBase(StrictModel):
    element_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    layer: int = Field(ge=0, le=100)
    intentional_overlap_with: tuple[str, ...] = ()


class TextStyle(StrictModel):
    font_role: Literal["display", "heading", "body", "caption"]
    font_size: float = Field(ge=12, le=180)
    line_height: float = Field(ge=1.0, le=2.0)
    color: HexColor
    align: Literal["left", "center", "right"]
    weight: Literal[400, 500, 600, 700, 800, 900]
    emphasis_ranges: tuple[tuple[int, int], ...] = ()


class TextElement(ElementBase):
    kind: Literal["text"] = "text"
    box: Box
    content_ref: str
    style: TextStyle


class ImageElement(ElementBase):
    kind: Literal["image"] = "image"
    box: Box
    asset_ref: str
    fit: Literal["cover", "contain"]
    focal_point: tuple[float, float]
    corner_radius: float = Field(ge=0, le=240)


class ShapeElement(ElementBase):
    kind: Literal["shape"] = "shape"
    box: Box
    shape: Literal["rectangle", "rounded_rectangle", "circle", "ellipse"]
    fill: HexColor
    stroke: HexColor | None = None


class LineElement(ElementBase):
    kind: Literal["line"] = "line"
    start: tuple[float, float]
    end: tuple[float, float]
    color: HexColor
    width: float = Field(gt=0, le=24)


class IconElement(ElementBase):
    kind: Literal["icon"] = "icon"
    box: Box
    icon: Literal["arrow", "check", "cross", "sparkle", "dot", "bracket"]
    color: HexColor


SceneElement = Annotated[
    TextElement | ImageElement | ShapeElement | LineElement | IconElement,
    Field(discriminator="kind"),
]


class PageScene(StrictModel):
    page_id: str
    sequence: int
    background: HexColor
    elements: tuple[SceneElement, ...] = Field(min_length=1)


class CarouselDesignPlan(StrictModel):
    direction_plan_sha256: Sha256
    content_atom_set_sha256: Sha256
    asset_manifest_sha256: Sha256
    revision: int = Field(ge=0)
    pages: tuple[PageScene, ...] = Field(min_length=5, max_length=18)
```

There is no free-form `html`, `css`, script, URL, or visible `text` field in any scene element.

- [ ] **Step 5: Implement QA and render result contracts**

Complete `AssetManifestItem` and `AssetManifest` in `assets.py` with the fields
specified in Task 7. `DesignIssue` and `RenderIssue` must carry `rule`,
`message`, `repair_instruction`, and optional `page_id`, `element_id`, or
`atom_id`. `RenderedElementProbe` must carry actual bounds, computed font,
overflow flags, contrast ratio, `content_ref`, `asset_ref`, and rasterized text
hash. `VisualCritique` must carry page/element issues, scores, revision
instructions, `revision_round`, and `passed`.

- [ ] **Step 6: Run contract tests**

Run: `pytest -q tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py`

Expected: all pass.

- [ ] **Step 7: Commit the visual contracts**

```bash
git add src/schemas/visual_style.py src/schemas/visual_director.py src/schemas/assets.py src/schemas/scene_graph.py src/schemas/design_qa.py src/schemas/visual_critique.py src/schemas/render_manifest.py src/schemas/render_qa.py src/schemas/__init__.py tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/schemas/test_visual_qa.py
git commit -m "feat: define dynamic visual scene contracts"
```

---

### Task 3: Add the Six-Family Style Registry as Reference DNA

**Files:**
- Create: `assets/visual-families/manifest.json`
- Create: `src/visual_design/__init__.py`
- Create: `src/visual_design/style_registry.py`
- Create: `tests/visual_design/test_style_registry.py`
- Modify: `tests/examples/test_template_mockups.py`

**Interfaces:**
- Consumes: six checked-in reference contact sheets/sample images.
- Produces: one validated `FamilyStyleProfile` per family; never returns layout code.

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_has_exactly_six_families():
    assert set(load_style_registry()) == {
        "pink_red", "deep_teal", "soft_pink",
        "coral_impact", "green_catalog", "white_quote",
    }


def test_registry_references_existing_images_and_contains_no_layout_markup():
    for profile in load_style_registry().values():
        assert all(Path(path).is_file() for path in profile.reference_image_paths)
        payload = profile.model_dump_json()
        assert "<html" not in payload.lower()
        assert "display:" not in payload.lower()
        assert "grid-template" not in payload.lower()
```

- [ ] **Step 2: Run and confirm registry tests fail**

Run: `pytest -q tests/visual_design/test_style_registry.py tests/examples/test_template_mockups.py`

Expected: missing registry/manifest failures.

- [ ] **Step 3: Create the manifest and strict loader**

Each family entry must include reference paths, palette, font roles, composition principles, whitespace/density ranges, allowed motifs, and prohibited patterns. The loader resolves every path beneath the repository root and rejects missing files or traversal:

```python
def load_style_registry(path: Path = DEFAULT_STYLE_MANIFEST) -> dict[TemplateFamily, FamilyStyleProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = [FamilyStyleProfile.model_validate(item) for item in payload["families"]]
    registry = {profile.family: _resolve_reference_paths(profile) for profile in profiles}
    if set(registry) != set(get_args(TemplateFamily)):
        raise ValueError("style registry must define exactly the six approved families")
    return registry
```

- [ ] **Step 4: Re-run registry tests**

Run: `pytest -q tests/visual_design/test_style_registry.py tests/examples/test_template_mockups.py`

Expected: all pass.

- [ ] **Step 5: Commit the family registry**

```bash
git add assets/visual-families/manifest.json src/visual_design/__init__.py src/visual_design/style_registry.py tests/visual_design/test_style_registry.py tests/examples/test_template_mockups.py
git commit -m "feat: encode six visual families as style dna"
```

---

### Task 4: Add Structured Multimodal and Image-Generation Provider Ports

**Files:**
- Create: `src/visual_ai/__init__.py`
- Create: `src/visual_ai/protocols.py`
- Create: `src/visual_ai/gemini.py`
- Create: `src/visual_ai/factory.py`
- Modify: `requirements.txt`
- Modify: `.env.example`
- Create: `tests/visual_ai/test_gemini_adapter.py`
- Create: `tests/visual_ai/test_factory.py`
- Create: `tests/visual_ai/test_live_gemini.py`

**Interfaces:**
- Consumes: prompts, local reference/render image bytes, target Pydantic schema, image-generation request.
- Produces: schema-validated structured output or locally persisted generated image plus internal provenance.

- [ ] **Step 1: Write failing port and adapter tests with a fake SDK client**

```python
@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    negative_constraints: tuple[str, ...]
    width: int
    height: int
    prompt_sha256: str


@dataclass(frozen=True)
class GeneratedImage:
    path: Path
    mime_type: str
    sha256: str
    provider: str
    model: str


class StructuredVisualModel(Protocol):
    generate_json: Callable[
        [str, type[T], Sequence[Path]],
        T,
    ]


class ImageGenerationProvider(Protocol):
    generate: Callable[[ImageGenerationRequest, Path], GeneratedImage]
```

Assert that:

- local image paths become byte parts with MIME types;
- JSON responses validate through the supplied Pydantic model;
- planning/critique and image generation use the exact same
  `gemini-3.1-flash-image` model setting;
- planning/critique parse a JSON object from text output instead of relying on
  unsupported native structured-output configuration;
- schema failures expose the raw response to the caller;
- generated bytes are written only beneath the supplied transaction directory;
- provenance records provider, model, prompt hash, response hash, and generation timestamp;
- no generated disclosure text is added to the prompt or image metadata.

- [ ] **Step 2: Run and confirm adapter tests fail**

Run: `pytest -q tests/visual_ai/test_gemini_adapter.py tests/visual_ai/test_factory.py`

Expected: missing provider modules.

- [ ] **Step 3: Add the official SDK and adapter**

Add `google-genai` to `requirements.txt`. Implement adapters around
`google.genai.Client`, using `types.Part.from_bytes` for local images. Use the
Gemini Developer API with the existing API-key authentication path, so no
Google Cloud Project ID or location is required. Read configuration from:

```text
GEMINI_API_KEY
GEMINI_VISUAL_MODEL=gemini-3.1-flash-image
```

Both factories must consume the same setting and accept injected clients for
offline tests:

```python
DEFAULT_VISUAL_MODEL = "gemini-3.1-flash-image"


def configured_visual_model() -> str:
    model = os.environ.get("GEMINI_VISUAL_MODEL", DEFAULT_VISUAL_MODEL)
    if model != DEFAULT_VISUAL_MODEL:
        raise ValueError("GEMINI_VISUAL_MODEL must be gemini-3.1-flash-image")
    return model


def get_structured_visual_model(*, client=None) -> StructuredVisualModel:
    return GeminiStructuredVisualModel(
        client=client or genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
        model=configured_visual_model(),
    )


def get_image_generation_provider(*, client=None) -> ImageGenerationProvider:
    return GeminiImageGenerationProvider(
        client=client or genai.Client(api_key=os.environ["GEMINI_API_KEY"]),
        model=configured_visual_model(),
    )
```

For Visual Director, Page Designer, Design Reviser, and Visual Critic calls,
request text output, extract exactly one JSON object, then validate it through
the requested Pydantic model and the existing three-attempt repair boundary.
Do not send a `response_schema` or claim native structured-output support for
this model. For image generation calls, request image output and validate the
returned MIME type and bytes before entering the asset transaction.

- [ ] **Step 4: Add opt-in live smoke tests**

The live tests skip unless both `RUN_LIVE_VISUAL_AI_TESTS=1` and `GEMINI_API_KEY` are present. They request one tiny structured response and one small generated image, validate MIME/bytes, and clean only their own temporary directory.

- [ ] **Step 5: Run offline adapter tests**

Run: `pytest -q tests/visual_ai/test_gemini_adapter.py tests/visual_ai/test_factory.py`

Expected: all pass and no network calls.

- [ ] **Step 6: Commit the provider boundary**

```bash
git add requirements.txt .env.example src/visual_ai tests/visual_ai
git commit -m "feat: add multimodal visual model adapters"
```

---

### Task 5: Build the Deterministic Content Atomizer Node

**Files:**
- Create: `src/nodes/node_p_content_atomizer.py`
- Create: `tests/nodes/test_content_atomizer.py`
- Modify: `src/nodes/node_o_assembler.py`
- Modify: `src/prompts/base/r2_compliance.txt`
- Modify: `tests/prompts/test_composer.py`
- Modify: `tests/nodes/test_metadata_flow.py`
- Modify: `tests/integration/test_beauty_account_workflow.py`

**Interfaces:**
- Consumes: assembler `publish_package` with approved title, cover copy, and body content.
- Produces: `content_atom_set`; removes the beauty-only `proof_mode="none"` override.

- [ ] **Step 1: Write failing atomizer tests**

Use real Chinese cases containing headings, paragraphs, ordered steps, emoji graphemes, punctuation, and the example sentence `出现持续刺痛、明显泛红或第二天仍然紧绷时`.

```python
def test_atomizer_preserves_visible_copy_character_for_character():
    result = content_atomizer_node(state_with_copy())
    atoms = result["content_atom_set"].atoms
    assert [atom.text for atom in atoms] == EXPECTED_VISIBLE_BLOCKS
    assert "免责声明" not in [atom.text for atom in atoms]


def test_beauty_assembler_does_not_force_proof_mode_none():
    result = assembler_node(beauty_state(proof_mode="real_photo"))
    assert result["publish_package"]["content_contract"]["proof_mode"] == "real_photo"


@pytest.mark.parametrize("forbidden", ["AI生成示意图", "仅供参考", "不构成医疗建议"])
def test_atomizer_routes_system_disclosure_or_disclaimer_copy_back_to_r2(forbidden):
    state = state_with_copy(content=f"护肤判断方法\n{forbidden}")
    result = content_atomizer_node(state)
    assert result["content_atomization_route"] == "r2_compliance"
    assert result["content_atom_set"] is None
    assert forbidden in result["content_atomization_issues"][0]
```

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/nodes/test_content_atomizer.py tests/prompts/test_composer.py tests/nodes/test_metadata_flow.py tests/integration/test_beauty_account_workflow.py`

Expected: missing node plus the current forced-`none` assertion fails.

- [ ] **Step 3: Implement deterministic parsing**

Parse only canonical publish fields. Strip Markdown structural markers without changing the text payload, preserve emoji as Unicode, assign stable role-prefixed IDs, and hash each atom plus the ordered set:

```python
def content_atomizer_node(state: AgentState) -> dict:
    package = state["publish_package"]
    issues = find_forbidden_visible_system_copy(
        title=package["title"],
        cover_copy=package["cover_copy"],
        content=package["content"],
    )
    if issues:
        return {
            "content_atom_set": None,
            "content_atomization_route": "r2_compliance",
            "content_atomization_issues": issues,
            "current_node": "CONTENT_ATOMIZER",
        }
    atoms = build_content_atoms(
        title=package["title"],
        cover_copy=package["cover_copy"],
        content=package["content"],
    )
    atom_set = ContentAtomSet(
        atoms=tuple(atoms),
        canonical_sha256=canonical_sha256([atom.model_dump(mode="json") for atom in atoms]),
    )
    return {
        "content_atom_set": atom_set,
        "content_atomization_route": "visual_director",
        "content_atomization_issues": [],
        "current_node": "CONTENT_ATOMIZER",
    }
```

Do not atomize hashtags, audit text, provenance, or runtime warnings as
page-visible text. Do not silently drop forbidden phrases that are present in
canonical title/cover/body copy: return an actionable R2 route so approved copy
and the eventual atom set remain identical. Update the R2 prompt to prohibit
system-added AI disclosure labels, “示意图”, general disclaimers, and medical
disclaimer boilerplate in page-visible copy while preserving ordinary factual
risk conditions and stop-use guidance.

- [ ] **Step 4: Remove the assembler’s beauty proof-mode rewrite and run tests**

Run: `pytest -q tests/nodes/test_content_atomizer.py tests/prompts/test_composer.py tests/nodes/test_metadata_flow.py tests/integration/test_beauty_account_workflow.py`

Expected: all pass.

- [ ] **Step 5: Commit the atomizer**

```bash
git add src/nodes/node_p_content_atomizer.py src/nodes/node_o_assembler.py src/prompts/base/r2_compliance.txt tests/nodes/test_content_atomizer.py tests/prompts/test_composer.py tests/nodes/test_metadata_flow.py tests/integration/test_beauty_account_workflow.py
git commit -m "feat: atomize approved carousel copy"
```

---

### Task 6: Implement the Visual Director and Its Three-Attempt Self-Repair

**Files:**
- Create: `src/prompts/base/visual_director.txt`
- Create: `src/nodes/node_p_visual_director.py`
- Create: `src/visual_design/model_retry.py`
- Modify: `src/prompts/composer.py`
- Modify: `tests/prompts/test_composer.py`
- Create: `tests/nodes/test_visual_director.py`

**Interfaces:**
- Consumes: `ContentAtomSet`, six `FamilyStyleProfile` values and reference images, content contract, recent visual memory.
- Produces: one validated `VisualDirectionPlan` with 5–18 pages, content fragments, and asset directives.

- [ ] **Step 1: Write failing director tests using scripted model responses**

Cover:

- chooses one family for the entire carousel;
- may choose 5, 11, or 18 pages independent of the number of family samples;
- rejects 4 or 19 pages;
- rejects altered fragment text;
- rejects empty/duplicate page jobs;
- allows a real-photo or generated-photo directive for the persistent-pain example;
- prompt explicitly bans visible AI labels and disclaimers;
- invalid response → validation feedback → retry, with a maximum of three attempts;
- third failure raises a resumable `VisualProductionInterrupted` containing raw outputs and validation errors.

- [ ] **Step 2: Run and confirm director tests fail**

Run: `pytest -q tests/nodes/test_visual_director.py tests/prompts/test_composer.py`

Expected: missing prompt/node/retry helper.

- [ ] **Step 3: Implement the exact retry boundary**

```python
def generate_validated(
    model: StructuredVisualModel,
    *,
    prompt: str,
    response_model: type[T],
    image_paths: Sequence[Path],
    validate: Callable[[T], None],
    max_attempts: int = 3,
) -> T:
    errors: list[str] = []
    raw_outputs: list[str] = []
    for attempt in range(1, max_attempts + 1):
        candidate = model.generate_json(
            prompt=repair_prompt(prompt, errors),
            response_model=response_model,
            image_paths=image_paths,
        )
        raw_outputs.append(candidate.model_dump_json())
        try:
            validate(candidate)
            return candidate
        except (ValidationError, ValueError) as exc:
            errors.append(str(exc))
    raise VisualProductionInterrupted(
        stage="visual_director",
        errors=errors,
        raw_outputs=raw_outputs,
    )
```

- [ ] **Step 4: Implement director prompt and node**

The prompt must send all six family profiles and reference images, immutable atoms, recent family usage, and content/asset needs. It must instruct the model to:

- select one family;
- choose 5–18 meaningful pages;
- create semantic-boundary fragments without changing characters;
- request searched/licensed, generated photoreal, diagrammatic, or no asset per content need;
- never request embedded image text, disclosure labels, or disclaimer copy.

The node validates the plan against atoms and selected profile before returning it.

- [ ] **Step 5: Run director and prompt tests**

Run: `pytest -q tests/nodes/test_visual_director.py tests/prompts/test_composer.py`

Expected: all pass.

- [ ] **Step 6: Commit the Visual Director**

```bash
git add src/prompts/base/visual_director.txt src/nodes/node_p_visual_director.py src/visual_design/model_retry.py src/prompts/composer.py tests/nodes/test_visual_director.py tests/prompts/test_composer.py
git commit -m "feat: direct dynamic carousel page plans"
```

---

### Task 7: Replace Slot-Based Asset Requirements with Directive Resolution

**Files:**
- Modify: `src/schemas/assets.py`
- Modify: `src/asset_resolver/resolver.py`
- Modify: `src/asset_resolver/providers.py`
- Modify: `src/asset_resolver/lifecycle.py`
- Modify: `src/asset_resolver/catalog.py`
- Modify: `src/asset_resolver/__init__.py`
- Replace: `src/nodes/node_p_asset_resolver.py`
- Modify: `tests/asset_resolver/test_local_resolution.py`
- Modify: `tests/asset_resolver/test_external_resolution.py`
- Modify: `tests/asset_resolver/test_lifecycle.py`
- Create: `tests/asset_resolver/test_directive_resolution.py`
- Create: `tests/nodes/test_asset_resolver.py`

**Interfaces:**
- Consumes: `VisualDirectionPlan.asset_directives`, run transaction context, search providers, image-generation provider.
- Produces: hash-bound `AssetManifest`; all rendered assets are security-approved while human decision remains pending until final review.

- [ ] **Step 1: Write failing directive and fallback tests**

```python
def test_search_failure_uses_generation_only_when_directive_allows_it(tmp_path):
    directive = make_asset_directive(
        preferred_source="search",
        fallback_source="generate",
        required=True,
    )
    result = resolve_asset_directives(
        directives=(directive,),
        transaction_root=tmp_path,
        search_provider=AlwaysFailingSearchProvider("search unavailable"),
        generation_provider=FakeGenerationProvider(b"safe-image-bytes"),
        safety_checker=AlwaysSafeChecker(),
    )
    item = result.manifest.items[0]
    assert item.source_kind == "generated"
    assert item.directive_id == directive.directive_id
    assert item.security_status == "approved"
    assert item.human_decision == "pending"
```

Add concrete tests named
`test_search_result_binds_page_and_directive`,
`test_generation_records_internal_provenance`,
`test_optional_failure_returns_unresolved_optional`,
`test_required_failure_keeps_recovery_evidence`,
`test_no_follow_rejects_symlink_escape`,
`test_unlicensed_asset_is_rejected`, and
`test_unwanted_image_text_is_rejected`. Use one-purpose fake providers/checkers
and assert the exact manifest or interruption fields in each test.

- [ ] **Step 2: Run and confirm existing slot schema cannot satisfy tests**

Run: `pytest -q tests/asset_resolver/test_directive_resolution.py tests/nodes/test_asset_resolver.py tests/asset_resolver/test_lifecycle.py`

Expected: import/schema failures.

- [ ] **Step 3: Wire the new directive and manifest contracts into resolution**

```python
class AssetDirective(StrictModel):
    directive_id: str
    page_id: str
    role: Literal["evidence_example", "skin_example", "texture", "object", "decorative"]
    required: bool
    preferred_source: Literal["search", "generate", "either", "none"]
    fallback_source: Literal["search", "generate", "none"]
    query_or_prompt: str | None
    negative_constraints: tuple[str, ...] = ()
    orientation: Literal["portrait", "landscape", "square", "any"]
    min_width: int = Field(ge=1)
    min_height: int = Field(ge=1)


class AssetManifestItem(StrictModel):
    asset_id: str
    directive_id: str
    page_id: str
    source_kind: Literal["catalog", "search", "generated"]
    provider: str
    license: str
    local_path: str
    width: int
    height: int
    sha256: Sha256
    subject_focal_point: tuple[float, float]
    crop_guidance: str
    security_status: Literal["approved", "rejected"]
    human_decision: Literal["pending", "approved", "rejected"]
    run_id: str
    transaction_id: str
    internal_provenance: dict[str, str]
```

These are the contracts introduced in Task 2. Remove all remaining
`slot_id`, `page_archetype`, fixed layout name, pending-external status, and
storyboard-derived requirement logic from the resolver boundary.

- [ ] **Step 4: Adapt the resolver while preserving security primitives**

Keep provider attribution, license snapshots, transaction journals, bounded retries, no-follow file opening, containment, and byte hashes. Add generated-image acquisition through `ImageGenerationProvider`. Run deterministic dimension/hash/path/license checks plus configured image-safety and unwanted-text checks before `security_status="approved"`.

Resolution semantics:

```python
if primary_failed and directive.fallback_source != "none":
    try_fallback()
if unresolved and directive.required:
    raise VisualProductionInterrupted(
        stage="asset_resolver",
        errors=(str(primary_error), str(fallback_error)),
        raw_outputs=(),
    )
if unresolved and not directive.required:
    return UnresolvedOptionalAsset(
        directive_id=directive.directive_id,
        reason=str(primary_error),
    )
```

- [ ] **Step 5: Update the node**

Return `asset_manifest`, `unresolved_optional_assets`, transaction evidence, and `current_node`. Do not pause for asset-specific Human Review here.

- [ ] **Step 6: Run all asset tests**

Run: `pytest -q tests/asset_resolver tests/nodes/test_asset_resolver.py`

Expected: all offline tests pass; live provider tests remain skipped by default.

- [ ] **Step 7: Commit the directive resolver**

```bash
git add src/schemas/assets.py src/asset_resolver src/nodes/node_p_asset_resolver.py tests/asset_resolver tests/nodes/test_asset_resolver.py
git commit -m "feat: resolve visual asset directives"
```

---

### Task 8: Implement Page Designer and Design Reviser

**Files:**
- Create: `src/prompts/base/page_designer.txt`
- Create: `src/prompts/base/design_reviser.txt`
- Create: `src/nodes/node_p_page_designer.py`
- Create: `src/nodes/node_p_design_reviser.py`
- Modify: `src/prompts/composer.py`
- Modify: `tests/prompts/test_composer.py`
- Create: `tests/nodes/test_page_designer.py`
- Create: `tests/nodes/test_design_reviser.py`

**Interfaces:**
- Consumes: direction, family profile/reference images, atoms/fragments, approved asset manifest, optional unresolved assets, prior QA/critic feedback.
- Produces: revisioned `CarouselDesignPlan` or a new director route request when family/page count must change.

- [ ] **Step 1: Write failing designer/reviser tests**

Assert that Page Designer:

- emits only structured scene elements;
- never embeds copy, HTML, CSS, scripts, or external URLs;
- binds every text element to a fragment and every image to an approved asset;
- can freely vary composition among pages without changing family;
- creates a valid no-image composition when optional assets are unresolved;
- retries invalid model output at most three times.

Assert that Design Reviser:

- patches only named pages/elements;
- increments revision;
- preserves family and all content/asset hashes;
- cannot change `content_ref` text or point to an unapproved asset;
- returns `route="visual_director"` when feedback requires family/page-count replanning.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/nodes/test_page_designer.py tests/nodes/test_design_reviser.py tests/prompts/test_composer.py`

Expected: missing nodes/prompts.

- [ ] **Step 3: Implement Page Designer**

Call `generate_validated` with the selected family reference images and the `CarouselDesignPlan` schema. The prompt must explain canvas `1080x1440`, safe margin, family palette, font roles, layer ordering, density envelope, and exact allowed element fields. Resolve fragment text only for model context; do not store it in `TextElement`.

- [ ] **Step 4: Implement constrained revision**

```python
RevisionIssue = DesignIssue | RenderIssue | VisualCritiqueIssue


class RevisionRequest(StrictModel):
    source: Literal["design_plan_qa", "render_qa", "visual_critic", "human_review"]
    issues: tuple[RevisionIssue, ...]
    current_revision: int


def validate_revision(before: CarouselDesignPlan, after: CarouselDesignPlan) -> None:
    if after.content_atom_set_sha256 != before.content_atom_set_sha256:
        raise ValueError("revision changed content binding")
    if after.asset_manifest_sha256 != before.asset_manifest_sha256:
        raise ValueError("revision changed asset binding")
    if tuple(page.page_id for page in after.pages) != tuple(page.page_id for page in before.pages):
        raise ValueError("family or page-sequence changes require visual_director")
```

- [ ] **Step 5: Run designer/reviser tests**

Run: `pytest -q tests/nodes/test_page_designer.py tests/nodes/test_design_reviser.py tests/prompts/test_composer.py`

Expected: all pass.

- [ ] **Step 6: Commit page design**

```bash
git add src/prompts/base/page_designer.txt src/prompts/base/design_reviser.txt src/nodes/node_p_page_designer.py src/nodes/node_p_design_reviser.py src/prompts/composer.py tests/nodes/test_page_designer.py tests/nodes/test_design_reviser.py tests/prompts/test_composer.py
git commit -m "feat: generate and revise structured page scenes"
```

---

### Task 9: Add Deterministic Design Plan QA

**Files:**
- Create: `src/visual_design/plan_qa.py`
- Create: `src/nodes/node_p_design_plan_qa.py`
- Create: `tests/visual_design/test_plan_qa.py`
- Create: `tests/nodes/test_design_plan_qa.py`

**Interfaces:**
- Consumes: atoms, direction, assets, scene plan, selected family profile.
- Produces: hard-gate `DesignPlanQAResult` with actionable issues and route.

- [ ] **Step 1: Write failing rule tests**

Test exact failures for:

- missing, duplicated, reordered, or unknown `content_ref`;
- wrong content/direction/asset hash;
- missing or unsafe `asset_ref`;
- page count outside 5–18 or mixed family;
- bounds outside 1080×1440 or inside the 84 px safe-margin exclusion where required;
- body text below 24 px or display text below 32 px;
- contrast below 4.5:1 for normal text or 3:1 for large text;
- unintended overlaps without `intentional_overlap_with`;
- forbidden visible label/disclaimer atoms;
- raw HTML/CSS/script-like fields.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/visual_design/test_plan_qa.py tests/nodes/test_design_plan_qa.py`

Expected: missing QA implementation.

- [ ] **Step 3: Implement pure rules and attestations**

```python
MIN_BODY_FONT_PX = 24
MIN_DISPLAY_FONT_PX = 32
SAFE_MARGIN_PX = 84
NORMAL_TEXT_CONTRAST = 4.5
LARGE_TEXT_CONTRAST = 3.0


@dataclass(frozen=True)
class DesignPlanQAInputs:
    atoms: ContentAtomSet
    direction: VisualDirectionPlan
    assets: AssetManifest
    design_plan: CarouselDesignPlan
    style: FamilyStyleProfile


def evaluate_design_plan(inputs: DesignPlanQAInputs) -> DesignPlanQAResult:
    issues = (
        validate_hash_bindings(inputs)
        + validate_content_coverage(inputs)
        + validate_asset_bindings(inputs)
        + validate_geometry(inputs)
        + validate_typography(inputs)
        + validate_family_envelope(inputs)
    )
    return DesignPlanQAResult(
        passed=not issues,
        issues=tuple(issues),
        design_plan_sha256=canonical_sha256(inputs.design_plan),
        content_coverage_attestation=not any(i.rule.startswith("content.") for i in issues),
        family_attestation=not any(i.rule.startswith("family.") for i in issues),
        asset_binding_attestation=not any(i.rule.startswith("asset.") for i in issues),
    )
```

- [ ] **Step 4: Implement routing and retry budget**

```python
def route_after_design_plan_qa(state: AgentState) -> Literal["generic_scene_renderer", "design_reviser"]:
    return "generic_scene_renderer" if state["design_plan_qa_result"].passed else "design_reviser"
```

The reviser loop may run at most three times. On the third failed QA result, raise `VisualProductionInterrupted` with checkpointable issue details; never force-pass.

- [ ] **Step 5: Run QA tests**

Run: `pytest -q tests/visual_design/test_plan_qa.py tests/nodes/test_design_plan_qa.py`

Expected: all pass.

- [ ] **Step 6: Commit plan QA**

```bash
git add src/visual_design/plan_qa.py src/nodes/node_p_design_plan_qa.py tests/visual_design/test_plan_qa.py tests/nodes/test_design_plan_qa.py
git commit -m "feat: hard-gate dynamic scene plans"
```

---

### Task 10: Build the Generic Scene-to-HTML Compiler

**Files:**
- Create: `src/rendering/scene/__init__.py`
- Create: `src/rendering/scene/fonts.py`
- Create: `src/rendering/scene/compiler.py`
- Create: `tests/rendering/scene/test_compiler.py`
- Create: `tests/rendering/scene/test_fonts.py`

**Interfaces:**
- Consumes: one `PageScene`, content fragments, approved asset map, family profile.
- Produces: self-contained deterministic HTML for Chromium; no family-specific layout branch.

- [ ] **Step 1: Write failing compiler tests**

Assert:

- all six families pass through the same `compile_page_scene` function;
- the output includes `data-element-id`, `data-content-ref`, and `data-asset-ref`;
- text is looked up from immutable fragments, not supplied by element data;
- asset paths are converted to safe local file URIs after containment validation;
- output contains no remote requests, scripts, editable content, or family-specific template names;
- element order follows `(layer, source order)`;
- font fallback is deterministic and missing required fonts fail clearly.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/rendering/scene/test_compiler.py tests/rendering/scene/test_fonts.py`

Expected: missing scene compiler.

- [ ] **Step 3: Implement one compiler with generic primitives**

```python
@dataclass(frozen=True)
class CompiledPage:
    page_id: str
    html: str
    expected_element_ids: tuple[str, ...]


def compile_page_scene(
    page: PageScene,
    *,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    style: FamilyStyleProfile,
) -> CompiledPage:
    body = "\n".join(
        compile_element(element, fragments=fragments, assets=assets, style=style)
        for element in sorted(page.elements, key=lambda item: item.layer)
    )
    return CompiledPage(
        page_id=page.page_id,
        html=PAGE_DOCUMENT.format(background=page.background, body=body),
        expected_element_ids=tuple(element.element_id for element in page.elements),
    )
```

`compile_element` is a discriminator dispatch over generic `text`, `image`, `shape`, `line`, and `icon` primitives only. It may compute CSS declarations from validated numeric/enumerated fields; it must not accept free-form CSS.

- [ ] **Step 4: Run compiler tests**

Run: `pytest -q tests/rendering/scene/test_compiler.py tests/rendering/scene/test_fonts.py`

Expected: all pass.

- [ ] **Step 5: Commit the compiler**

```bash
git add src/rendering/scene/__init__.py src/rendering/scene/fonts.py src/rendering/scene/compiler.py tests/rendering/scene/test_compiler.py tests/rendering/scene/test_fonts.py
git commit -m "feat: compile generic visual scene graphs"
```

---

### Task 11: Add Chromium Rendering, DOM Probes, and Hash-Bound Manifest

**Files:**
- Create: `src/rendering/scene/probes.py`
- Create: `src/rendering/scene/renderer.py`
- Create: `src/nodes/node_p_generic_scene_renderer.py`
- Create: `tests/rendering/scene/test_probes.py`
- Create: `tests/rendering/scene/test_renderer.py`
- Create: `tests/rendering/scene/test_chromium_smoke.py`
- Create: `tests/nodes/test_generic_scene_renderer.py`

**Interfaces:**
- Consumes: QA-approved design plan, atoms/direction/assets, run output directory.
- Produces: 5–18 PNGs, contact sheet, element probes, and `RenderManifest` bound to every source hash.

- [ ] **Step 1: Write failing render/probe tests**

Cover:

- 5, 12, and 18 page outputs retain exact order;
- every PNG is 1080×1440 and has a byte hash;
- every planned element produces one probe;
- text probes report scroll/client dimensions, computed font, line boxes, contrast, and rendered text hash;
- image probes report natural/rendered dimensions, crop rectangle, and asset hash;
- contact sheet includes all pages and its own hash;
- renderer rejects a failed/missing Design Plan QA result;
- one transient Chromium failure retries the identical plan once, then raises.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/rendering/scene/test_probes.py tests/rendering/scene/test_renderer.py tests/nodes/test_generic_scene_renderer.py`

Expected: missing renderer.

- [ ] **Step 3: Implement browser probes**

Use one evaluation script that reads only generated `data-*` attributes and computed layout:

```javascript
return [...document.querySelectorAll("[data-element-id]")].map((node) => {
  const rect = node.getBoundingClientRect();
  const style = getComputedStyle(node);
  return {
    element_id: node.dataset.elementId,
    content_ref: node.dataset.contentRef || null,
    asset_ref: node.dataset.assetRef || null,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    scroll_width: node.scrollWidth,
    scroll_height: node.scrollHeight,
    client_width: node.clientWidth,
    client_height: node.clientHeight,
    font_family: style.fontFamily,
    font_size: parseFloat(style.fontSize),
    color: style.color,
    background_color: style.backgroundColor
  };
});
```

- [ ] **Step 4: Implement renderer and node**

Render to a run-scoped staging directory, write PNGs atomically, then build the contact sheet and manifest. `source_asset_sha256` is the ordered hash map of every used asset. The node accepts only `design_plan_qa_result.passed is True`.

- [ ] **Step 5: Run render tests including real Chromium**

Run: `pytest -q tests/rendering/scene`

Expected: all pass with installed Chromium.

- [ ] **Step 6: Commit the renderer**

```bash
git add src/rendering/scene/probes.py src/rendering/scene/renderer.py src/nodes/node_p_generic_scene_renderer.py tests/rendering/scene tests/nodes/test_generic_scene_renderer.py
git commit -m "feat: render and probe generic carousel scenes"
```

---

### Task 12: Replace Render QA with Scene/PNG Verification

**Files:**
- Create: `src/visual_design/render_qa.py`
- Replace: `src/nodes/node_p_render_qa.py`
- Replace: `tests/nodes/test_render_qa.py`
- Create: `tests/visual_design/test_render_qa.py`

**Interfaces:**
- Consumes: plan, Design Plan QA, render manifest, actual files and probes.
- Produces: hard-gate `RenderQAResult`, or actionable Design Reviser feedback.

- [ ] **Step 1: Write failing Render QA tests**

Test:

- manifest hashes match the plan, atoms, assets, images, and contact sheet;
- page order/count and canvas dimensions match;
- missing/extra probes fail;
- clipping, overflow, off-canvas bounds, undersized fonts, low contrast, and unintended overlap fail;
- rasterized text hashes attest every referenced fragment;
- image crop/focal point and asset hash match;
- failure routes to Design Reviser, not R1 and not Human Review;
- third deterministic failure interrupts rather than force-passes.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/visual_design/test_render_qa.py tests/nodes/test_render_qa.py`

Expected: old fixed-template assumptions fail the new cases.

- [ ] **Step 3: Implement pure verification**

```python
@dataclass(frozen=True)
class RenderQAInputs:
    atoms: ContentAtomSet
    direction: VisualDirectionPlan
    assets: AssetManifest
    design_plan: CarouselDesignPlan
    design_plan_qa: DesignPlanQAResult
    render_manifest: RenderManifest


def evaluate_render(inputs: RenderQAInputs) -> RenderQAResult:
    issues = (
        verify_manifest_bindings(inputs)
        + verify_page_files(inputs)
        + verify_element_probes(inputs)
        + verify_text_attestation(inputs)
        + verify_image_crops(inputs)
    )
    return RenderQAResult(
        passed=not issues,
        issues=tuple(issues),
        render_manifest_sha256=canonical_sha256(inputs.render_manifest),
        content_attestation=not any(i.rule.startswith("content.") for i in issues),
        geometry_attestation=not any(i.rule.startswith("geometry.") for i in issues),
        asset_attestation=not any(i.rule.startswith("asset.") for i in issues),
    )
```

- [ ] **Step 4: Implement route and retry accounting**

```python
def route_after_render_qa(state: AgentState) -> Literal["visual_critic", "design_reviser"]:
    return "visual_critic" if state["render_qa_result"].passed else "design_reviser"
```

- [ ] **Step 5: Run Render QA tests**

Run: `pytest -q tests/visual_design/test_render_qa.py tests/nodes/test_render_qa.py`

Expected: all pass.

- [ ] **Step 6: Commit Render QA**

```bash
git add src/visual_design/render_qa.py src/nodes/node_p_render_qa.py tests/visual_design/test_render_qa.py tests/nodes/test_render_qa.py
git commit -m "feat: verify rendered scene geometry and content"
```

---

### Task 13: Add the Multimodal Visual Critic and Two-Round Aesthetic Loop

**Files:**
- Create: `src/prompts/base/visual_critic.txt`
- Create: `src/nodes/node_p_visual_critic.py`
- Modify: `src/prompts/composer.py`
- Modify: `tests/prompts/test_composer.py`
- Create: `tests/nodes/test_visual_critic.py`

**Interfaces:**
- Consumes: rendered pages/contact sheet, family references/profile, direction, design plan, Render QA result.
- Produces: `VisualCritique` and route to Human Review or Design Reviser.

- [ ] **Step 1: Write failing critic tests**

Assert:

- critic receives actual rendered images and family references;
- scores hierarchy, legibility, composition, family coherence, page variation, color, spacing, and image relevance;
- image relevance is `not_applicable` for text-only pages;
- every problem names page/element and gives a concrete revision instruction;
- hard QA failure prevents critic invocation;
- passed critique routes to Human Review;
- failed rounds 0 and 1 route to Design Reviser;
- failed round 2 routes to Human Review with `review_status="visual_needs_attention"`;
- critic cannot alter content, hashes, assets, or family.

- [ ] **Step 2: Run and confirm failures**

Run: `pytest -q tests/nodes/test_visual_critic.py tests/prompts/test_composer.py`

Expected: missing critic.

- [ ] **Step 3: Implement prompt, node, and routing**

```python
def route_after_visual_critic(
    state: AgentState,
) -> Literal["design_reviser", "human_review"]:
    critique = state["visual_critique"]
    if critique.passed:
        return "human_review"
    if critique.revision_round < 2:
        return "design_reviser"
    return "human_review"
```

The third visual evaluation is round 2: it cannot trigger another automatic redesign. Preserve its scores/issues for Human Review.

- [ ] **Step 4: Run critic tests**

Run: `pytest -q tests/nodes/test_visual_critic.py tests/prompts/test_composer.py`

Expected: all pass.

- [ ] **Step 5: Commit the critic**

```bash
git add src/prompts/base/visual_critic.txt src/nodes/node_p_visual_critic.py src/prompts/composer.py tests/nodes/test_visual_critic.py tests/prompts/test_composer.py
git commit -m "feat: critique rendered carousels visually"
```

---

### Task 14: Switch Agent State, Graph, Node Exports, and Checkpoint Migration

**Files:**
- Replace: `src/schemas/agent_state.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Replace: `src/editorial_carousel/legacy.py`
- Modify: `main.py`
- Replace: `tests/test_graph.py`
- Modify: `tests/test_main.py`
- Replace: `tests/integration/test_legacy_editorial_resume.py`

**Interfaces:**
- Consumes: upstream writing state and legacy/current checkpoints.
- Produces: one `llm_scene_v3` production path; old visual state is discarded and re-enters after assembler.

- [ ] **Step 1: Write failing graph and migration tests**

Assert exact production topology:

```text
assembler
  -> content_atomizer
  -> visual_director
  -> asset_resolver
  -> page_designer
  -> design_plan_qa
  -> generic_scene_renderer
  -> render_qa
  -> visual_critic
  -> human_review
  -> final_policy_guard
  -> content_writer
```

Assert conditional loops:

- Content Atomizer forbidden-system-copy result → R2, then normal decision/assembler/atomizer re-entry;
- optional asset loss → Page Designer no-image path;
- Design Plan QA/Render QA/visual feedback → Design Reviser;
- Design Reviser may route to Visual Director only for family/page-sequence replanning;
- no graph node named `visual_strategy_planner`, `storyboard_generator`, `carousel_qa`, or `editorial_carousel_renderer`.

Migration tests must prove that legacy/current-v2 checkpoints:

- preserve content, R1/R2, title, hashtags, and assembler package;
- discard old visual plan, storyboards, asset/render manifests, and old QA;
- set version `llm_scene_v3`;
- resume with `content_atomizer` as the successor by updating checkpoint state `as_node="assembler"`;
- never import or execute an old renderer.

- [ ] **Step 2: Run and confirm old graph fails**

Run: `pytest -q tests/test_graph.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py`

Expected: old node names and `modern_v2` migration expectations fail.

- [ ] **Step 3: Replace AgentState visual fields**

Add:

```python
content_atom_set: NotRequired[ContentAtomSet | None]
content_atomization_route: NotRequired[Literal["visual_director", "r2_compliance"]]
content_atomization_issues: NotRequired[list[str]]
visual_direction_plan: NotRequired[VisualDirectionPlan | None]
asset_manifest: NotRequired[AssetManifest | None]
carousel_design_plan: NotRequired[CarouselDesignPlan | None]
design_plan_qa_result: NotRequired[DesignPlanQAResult | None]
render_manifest: NotRequired[RenderManifest | None]
render_qa_result: NotRequired[RenderQAResult | None]
visual_critique: NotRequired[VisualCritique | None]
design_revision_round: NotRequired[int]
visual_revision_round: NotRequired[int]
unresolved_optional_assets: NotRequired[list[dict]]
```

Remove production state fields `visual_plan`, `carousel_qa_result`, and pending storyboard replacement.

- [ ] **Step 4: Register only new nodes and routes**

Update lazy exports and graph edges. Represent interruptions through the existing LangGraph/run-registry resume mechanism, retaining stage/error payloads in state/checkpoint.

- [ ] **Step 5: Replace the migration seam**

```python
DYNAMIC_VISUAL_V3 = "llm_scene_v3"
DYNAMIC_REENTRY_PREDECESSOR = "assembler"


def dynamic_visual_transition_updates(values: Mapping[str, Any]) -> dict[str, Any]:
    package = dict(values.get("publish_package") or {})
    package.pop("storyboards", None)
    return {
        "editorial_workflow_version": DYNAMIC_VISUAL_V3,
        "legacy_editorial_checkpoint": False,
        "publish_package": package,
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
        "review_status": None,
        "review_route": None,
    }
```

Unknown future versions fail closed. No old layout conversion is allowed.

- [ ] **Step 6: Run graph, CLI, and migration tests**

Run: `pytest -q tests/test_graph.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py`

Expected: all pass.

- [ ] **Step 7: Commit the production switch**

```bash
git add src/schemas/agent_state.py src/nodes/__init__.py src/graph.py src/editorial_carousel/legacy.py main.py tests/test_graph.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py
git commit -m "feat: switch workflow to dynamic visual production"
```

---

### Task 15: Rebuild Unified Human Review and Final Guard

**Files:**
- Replace: `src/nodes/node_q_human_review.py`
- Replace: `src/nodes/node_q_01_final_policy_guard.py`
- Modify: `src/schemas/content_lock.py`
- Modify: `src/nodes/publish_patch.py`
- Replace: `tests/nodes/test_final_policy_guard.py`
- Create: `tests/nodes/test_dynamic_visual_human_review.py`

**Interfaces:**
- Consumes: complete rendered carousel, visual critique, asset provenance/decisions, all hard QA attestations.
- Produces: one review decision and final policy attestation; visible-copy edits invalidate every visual artifact.

- [ ] **Step 1: Write failing review-routing tests**

Assert:

- direct approval → Final Guard;
- layout/color/image/spacing feedback → Design Reviser;
- any visible-text edit → R2, with atoms and all downstream visual contracts cleared;
- image rejection/replacement → Asset Resolver, with design/render/critique cleared;
- `visual_needs_attention` requires explicit human aesthetic override;
- Human Review cannot approve a security-rejected or unresolved required asset;
- no asset-specific interrupt occurs before the final unified review;
- Final Guard rejects failed/missing Design Plan QA, Render QA, content hashes, asset security, R2, or ContentLock;
- Final Guard may accept only aesthetic override, never hard-QA override.

- [ ] **Step 2: Run and confirm old storyboard review fails**

Run: `pytest -q tests/nodes/test_dynamic_visual_human_review.py tests/nodes/test_final_policy_guard.py`

Expected: old storyboard/renderer routes fail.

- [ ] **Step 3: Replace visual invalidation and review routes**

```python
def invalidated_visual_artifacts() -> dict:
    return {
        "content_atom_set": None,
        "visual_direction_plan": None,
        "asset_manifest": None,
        "carousel_design_plan": None,
        "design_plan_qa_result": None,
        "render_manifest": None,
        "render_qa_result": None,
        "visual_critique": None,
    }


def route_after_human_review(
    state: AgentState,
) -> Literal["r2_compliance", "asset_resolver", "design_reviser", "final_policy_guard"]:
    return state["review_route"]
```

For a text edit, preserve the human-edited publish copy as R2 input and clear the complete visual chain. For image rejection, preserve atoms/direction but clear manifest, scene, render, and critique.

- [ ] **Step 4: Update ContentLock**

Remove locked storyboards. Bind immutable visible source content and new hashes:

```python
class ContentLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    focus_keyword: str
    topic: str
    topic_id: str
    angle: str
    angle_id: str
    target_group: str
    core_pain: str
    title: str
    cover_copy: str
    first_screen_promise: str
    content: str
    hashtags: tuple[str, ...]
    content_atom_set_sha256: Sha256
    canonical_sha256: Sha256
```

- [ ] **Step 5: Rebuild Final Guard checks and run tests**

Run: `pytest -q tests/nodes/test_dynamic_visual_human_review.py tests/nodes/test_final_policy_guard.py`

Expected: all pass.

- [ ] **Step 6: Commit unified review**

```bash
git add src/nodes/node_q_human_review.py src/nodes/node_q_01_final_policy_guard.py src/schemas/content_lock.py src/nodes/publish_patch.py tests/nodes/test_dynamic_visual_human_review.py tests/nodes/test_final_policy_guard.py
git commit -m "feat: unify dynamic visual human review"
```

---

### Task 16: Update Publish Artifacts, Content Writer, and Memory Metadata

**Files:**
- Replace: `src/publishing/artifacts.py`
- Replace: `src/nodes/node_p_content_writer.py`
- Modify: `memory/models.py`
- Modify: `memory/schema.sql`
- Modify: `memory/migrations.py`
- Modify: `memory/memory_manager.py`
- Replace: `tests/publishing/test_artifacts.py`
- Replace: `tests/nodes/test_content_writer.py`
- Modify: `tests/memory/test_migrations.py`
- Modify: `tests/memory/test_memory_manager.py`

**Interfaces:**
- Consumes: final approved dynamic visual contracts.
- Produces: verified local publish package and visual-diversity metadata; no storyboard payload.

- [ ] **Step 1: Write failing artifact and memory tests**

Assert that the canonical package contains:

```text
content_atom_set.json
visual_direction_plan.json
asset_manifest.json
carousel_design_plan.json
design_plan_qa.json
render_manifest.json
render_qa.json
visual_critique.json
content_lock.json
final_policy_attestation.json
pages/*.png
contact-sheet.png
```

Also assert:

- attestation hashes every contract and PNG;
- workflow version must equal `llm_scene_v3`;
- no `storyboards`, `visual_plan`, `carousel_qa`, or fixed-template variant fields are exported;
- AI provenance exists only in internal asset JSON, never page-visible copy;
- memory persists `page_count`, `template_family`, `direction_signature`, `design_signature`, and density/color summary;
- existing DBs migrate additively without deleting old rows or rebuilding the database.

- [ ] **Step 2: Run and confirm old artifact contract fails**

Run: `pytest -q tests/publishing/test_artifacts.py tests/nodes/test_content_writer.py tests/memory/test_migrations.py tests/memory/test_memory_manager.py`

Expected: old visual/storyboard artifact assertions fail.

- [ ] **Step 3: Implement new package attestation**

```python
class PublishAttestation(StrictModel):
    workflow_version: Literal["llm_scene_v3"]
    content_atom_set_sha256: Sha256
    visual_direction_plan_sha256: Sha256
    asset_manifest_sha256: Sha256
    carousel_design_plan_sha256: Sha256
    design_plan_qa_sha256: Sha256
    render_manifest_sha256: Sha256
    render_qa_sha256: Sha256
    visual_critique_sha256: Sha256
    content_lock_sha256: Sha256
    page_sha256: dict[str, Sha256]
```

Use staging plus atomic promotion for the publish bundle. Do not overwrite an existing canonical run package by hand.

- [ ] **Step 4: Add non-destructive memory migration**

Add nullable columns through the existing migration framework. Leave historical storyboard/template columns readable for old analytics, but stop writing or consuming them in the v3 production path.

- [ ] **Step 5: Run artifact and memory tests**

Run: `pytest -q tests/publishing/test_artifacts.py tests/nodes/test_content_writer.py tests/memory/test_migrations.py tests/memory/test_memory_manager.py`

Expected: all pass.

- [ ] **Step 6: Commit publishing and memory**

```bash
git add src/publishing/artifacts.py src/nodes/node_p_content_writer.py memory/models.py memory/schema.sql memory/migrations.py memory/memory_manager.py tests/publishing/test_artifacts.py tests/nodes/test_content_writer.py tests/memory/test_migrations.py tests/memory/test_memory_manager.py
git commit -m "feat: publish dynamic visual artifacts"
```

---

### Task 17: Delete the Obsolete Visual Production Path

**Files:**
- Delete: `src/nodes/node_p_visual_strategy_planner.py`
- Delete: `src/nodes/node_o_storyboards_generator.py`
- Delete: `src/nodes/node_p_carousel_qa.py`
- Delete: `src/nodes/node_p_editorial_carousel_renderer.py`
- Delete: `src/schemas/visual_plan.py`
- Delete: `src/schemas/storyboard.py`
- Delete: `src/schemas/carousel_qa.py`
- Delete: `src/schemas/editorial_templates.py`
- Delete: `src/rendering/editorial/`
- Delete: `src/editorial_carousel/planner.py`
- Delete: `src/editorial_carousel/selector.py`
- Delete: obsolete blueprint/strategy modules under `src/editorial_carousel/` after `rg` proves they have no non-test consumer
- Delete: `tests/nodes/test_visual_strategy_planner.py`
- Delete: `tests/nodes/test_carousel_qa.py`
- Delete: `tests/rendering/editorial/`
- Delete: obsolete `tests/editorial_carousel/` planner/selector/blueprint tests
- Delete: `tests/integration/test_adaptive_six_template_workflow.py`
- Modify: `src/rendering/__init__.py`
- Modify: `src/editorial_carousel/__init__.py`
- Modify: `tests/test_runtime_imports.py`
- Create: `tests/architecture/test_no_obsolete_visual_path.py`

**Interfaces:**
- Consumes: the now-complete v3 graph.
- Produces: one production visual architecture with no old execution path, fallback, or feature flag.

- [ ] **Step 1: Write a failing architecture guard before deletion**

```python
FORBIDDEN_GRAPH_NODES = {
    "visual_strategy_planner",
    "storyboard_generator",
    "carousel_qa",
    "editorial_carousel_renderer",
}


def scan_python_imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_production_graph_contains_no_obsolete_visual_nodes():
    graph = create_graph(checkpointer=MemorySaver()).get_graph()
    assert FORBIDDEN_GRAPH_NODES.isdisjoint(graph.nodes)


def test_source_has_no_obsolete_visual_imports():
    forbidden = (
        "src.schemas.visual_plan",
        "src.schemas.storyboard",
        "src.schemas.carousel_qa",
        "src.rendering.editorial",
        "src.editorial_carousel.planner",
        "src.editorial_carousel.selector",
    )
    assert scan_python_imports(Path("src")).isdisjoint(forbidden)
```

Also assert no production source contains `modern_v2`, `force_pass`, `CarouselPayload`, `ResolvedVariant`, or `recommended_frame_count`.

- [ ] **Step 2: Run the guard and collect exact remaining references**

Run: `pytest -q tests/architecture/test_no_obsolete_visual_path.py`

Expected: failures list every remaining obsolete import/reference.

- [ ] **Step 3: Delete obsolete modules and tests**

Delete only files proven obsolete by the guard and `rg`. Keep:

- `src/editorial_carousel/legacy.py` as the sole checkpoint migration seam;
- any publish-profile helper still consumed by v3, after renaming it out of fixed-template vocabulary if necessary;
- historical additive database columns required to read existing records.

Do not retain compatibility wrappers, imports, fallback functions, or a feature flag.

- [ ] **Step 4: Run architecture and import tests**

Run: `pytest -q tests/architecture/test_no_obsolete_visual_path.py tests/test_runtime_imports.py tests/test_graph.py`

Expected: all pass.

- [ ] **Step 5: Commit the deletion**

```bash
git add -A src tests
git commit -m "refactor: remove fixed visual production path"
```

---

### Task 18: Add the 24-Case Golden Set and End-to-End Workflow Proof

**Files:**
- Create: `tests/fixtures/dynamic_visual/manifest.json`
- Create: 24 fixture JSON files under `tests/fixtures/dynamic_visual/cases/`
- Create: `tests/dynamic_visual/golden_fixtures.py`
- Create: `tests/dynamic_visual/test_golden_set.py`
- Create: `tests/integration/test_dynamic_visual_workflow.py`
- Create: `tests/integration/render_dynamic_visual_review.py`
- Modify: `tests/integration/test_beauty_account_workflow.py`
- Modify: `tests/integration/test_domain_workflow.py`

**Interfaces:**
- Consumes: representative beauty/skincare copy shapes and fake model/provider outputs.
- Produces: deterministic offline regression proof across all families, page counts, densities, and asset modes.

- [ ] **Step 1: Define the golden matrix**

Create 24 cases covering:

- all six families at least three times;
- page counts 5, 6, 8, 10, 12, 15, and 18;
- tutorial, checklist, comparison, Q&A, diagnostic, narrative, myth correction, and saveable-reference copy;
- sparse, standard, and dense pages;
- text-only, searched photo, generated photoreal skin example, texture, and mixed optional asset loss;
- long Chinese lines, emoji, Latin ingredient names, ordered steps, and the persistent-pain/redness/tightness example.

Each fixture stores immutable input copy plus scripted direction/design/critic responses, not expected HTML.

- [ ] **Step 2: Write failing golden and integration tests**

For every case assert:

- exact atom reconstruction and coverage;
- one family only;
- page count 5–18 and no empty page;
- asset provenance/safety and hash binding;
- Design Plan QA and Render QA pass;
- PNG dimensions/order/count;
- no visible AI/disclaimer text;
- no structural Human Review edit is required for approved fixtures.

Workflow tests assert retry ceilings and every Human Review route.

- [ ] **Step 3: Run and confirm failures reveal missing fixture coverage**

Run: `pytest -q tests/dynamic_visual/test_golden_set.py tests/integration/test_dynamic_visual_workflow.py`

Expected: failures until all 24 cases and fakes are complete.

- [ ] **Step 4: Complete fixtures and preview utility**

The review script renders all cases to a temporary/output-review location excluded from Git and generates family-grouped contact sheets plus a machine-readable result summary. It must not modify canonical publish packages.

- [ ] **Step 5: Run the complete dynamic visual slice**

Run: `pytest -q tests/schemas/test_content_atoms.py tests/schemas/test_visual_direction.py tests/schemas/test_scene_graph.py tests/visual_ai tests/visual_design tests/rendering/scene tests/asset_resolver tests/nodes/test_content_atomizer.py tests/nodes/test_visual_director.py tests/nodes/test_page_designer.py tests/nodes/test_design_reviser.py tests/nodes/test_design_plan_qa.py tests/nodes/test_generic_scene_renderer.py tests/nodes/test_render_qa.py tests/nodes/test_visual_critic.py tests/nodes/test_dynamic_visual_human_review.py tests/nodes/test_final_policy_guard.py tests/dynamic_visual tests/integration/test_dynamic_visual_workflow.py`

Expected: all pass, live tests skipped.

- [ ] **Step 6: Generate and inspect review contact sheets**

Run: `python tests/integration/render_dynamic_visual_review.py`

Inspect every generated family contact sheet for hierarchy, family coherence, meaningful page variation, correct image relevance, legibility, and absence of forbidden labels. Record fixture-specific accepted baselines in `manifest.json`; do not weaken deterministic QA thresholds to accept visual defects.

- [ ] **Step 7: Commit golden coverage**

```bash
git add tests/fixtures/dynamic_visual tests/dynamic_visual tests/integration/test_dynamic_visual_workflow.py tests/integration/render_dynamic_visual_review.py tests/integration/test_beauty_account_workflow.py tests/integration/test_domain_workflow.py
git commit -m "test: cover dynamic visual production golden set"
```

---

### Task 19: Update Canonical Documentation and Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/workflow.md`
- Modify: `docs/architecture/editorial-contracts.md`
- Modify: `docs/architecture/persistence-and-assets.md`
- Modify: `.gitignore` if the review script introduces a new local preview directory

**Interfaces:**
- Consumes: completed v3 implementation and fresh command output.
- Produces: canonical architecture/operations documentation and final verification evidence.

- [ ] **Step 1: Update the workflow documentation**

Document:

- the exact v3 graph and all retry/interrupt routes;
- responsibilities and producer/consumer table for every new contract;
- six families as reference DNA, not fixed page templates;
- Visual Director’s 5–18 page autonomy;
- asset search/generation and internal-only AI provenance;
- unified Human Review routes and hard-QA override prohibition;
- old checkpoint migration to assembler → atomizer;
- local/live environment variables and offline default behavior;
- local publish package contents.

Remove all current-path wording that describes storyboard generation, family-specific renderer selection, Carousel QA, or a 5–7 page limit.

- [ ] **Step 2: Run stale-reference and placeholder scans**

Run:

```bash
rg -n 'visual_strategy_planner|storyboard_generator|carousel_qa|editorial_carousel_renderer|CarouselPayload|ResolvedVariant|modern_v2|recommended_frame_count|5-7|5–7' src main.py README.md docs/architecture docs/README.md
rg -n 'T[B]D|T[O]DO|NotImplementedError|pass[[:space:]]*$' src tests
```

Expected: the first command reports old names only inside the explicitly documented migration/history section, and the second reports no newly introduced placeholder implementation.

- [ ] **Step 3: Run focused architectural verification**

Run:

```bash
pytest -q tests/architecture/test_no_obsolete_visual_path.py tests/test_graph.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_dynamic_visual_workflow.py
```

Expected: all pass.

- [ ] **Step 4: Run the full offline suite**

Run:

```bash
pytest -q
python -m compileall -q src main.py
git diff --check
```

Expected: all tests pass, compilation exits 0, and diff check has no output.

- [ ] **Step 5: Optionally run live provider smoke tests when credentials are explicitly available**

Run: `RUN_LIVE_VISUAL_AI_TESTS=1 pytest -q tests/visual_ai/test_live_gemini.py tests/asset_resolver/test_live_providers.py`

Expected: structured vision, image generation, and configured asset-provider smokes pass. Do not make this command part of the offline completion gate.

- [ ] **Step 6: Review the final diff against the approved spec**

Verify every requirement in sections 2, 8, 9, 10, 11, 12, and 14 of the approved design document has both an implementation site and a test. Confirm no unrelated user changes or generated outputs are staged.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md docs/README.md docs/architecture/workflow.md docs/architecture/editorial-contracts.md docs/architecture/persistence-and-assets.md .gitignore
git commit -m "docs: document dynamic visual production"
```
