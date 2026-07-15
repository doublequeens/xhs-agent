# Editorial Beauty Carousel Workflow Implementation Plan

> 当前状态：已实施；本文保留作历史实施记录，不是自动待办。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed six-card text renderer with a local-first, content-aware beauty editorial carousel pipeline that produces 5–7 publishable images, audited stock-asset fallback, human-review artifacts, `publish-copy.txt`, and a content-locked manual Codex image-regeneration prompt.

**Architecture:** Keep LLM responsibilities at the semantic seam: it produces a strict `VisualPlan` and layout-specific storyboard content, while deterministic Python modules own asset selection, provider fallback, HTML/CSS layout, Chromium rendering, QA, provenance, and export. The automatic graph never calls image generation; `codex-image-regeneration-prompt.txt` is a final, manually invoked rescue artifact whose `ContentLock` forbids topic or copy drift.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, Requests, Pillow, Playwright/Chromium, HTML/CSS, SQLite/ChromaDB, pytest.

## Global Constraints

- Work only in `/Users/qinqiang/Documents/Workspace/Projects/xhs-agent/.worktrees/editorial-carousel-workflow` on `feature/editorial-carousel-workflow`.
- Preserve beauty/skincare audience and content-policy behavior; do not expand account domains in this feature.
- Automatic output is always `1080 × 1440`; every carousel has 5–7 frames, at least three layouts, an `editorial_cover`, and at least one saveable frame.
- Use Source Han Serif SC SemiBold 600 for display, Source Han Sans SC 400/500 for body, and Bodoni Moda 400 for numerals; system-font fallback is a hard failure.
- Keep the account palette fixed at ivory `#F7F2EA`, ink `#292625`, mauve `#9A707B`, coral `#D45D4C`, and sage `#78805E`.
- Do not restore the salamander or any fixed cartoon IP; do not require a real-person face.
- Prefer approved local assets. Search both Pexels and Unsplash only when no local candidate passes hard filters; never scrape provider webpages.
- External candidates remain `pending_external` until explicit Human Review approval; Final Policy Guard must compare source hashes before publish.
- Default tests never call Pexels, Unsplash, Codex image generation, or another live remote service.
- `codex-image-regeneration-prompt.txt` is manual-only and must lock the selected keyword, topic, angle, audience, pain, title, copy, hashtags, frame order, and every visible storyboard string.
- Golden fixtures are test-only inputs and must never enter production prompts, memory, topic signals, or publish candidates.
- Follow TDD for every production change: observe the named test fail before writing the minimum implementation, then run the focused suite and commit.

---

## File Map

### New schema and domain files

- `src/schemas/visual_plan.py` — visual-family, layout, frame-plan, and asset-requirement contracts.
- `src/schemas/storyboard.py` — strict semantic carousel frame and payload contracts.
- `src/schemas/assets.py` — local/external asset, search-report, and resolved-manifest contracts.
- `src/schemas/render_manifest.py` — rendered page, font, contact-sheet, and source-hash contract.
- `src/schemas/content_lock.py` — immutable final-content lock and canonical hash.
- `src/editorial_carousel/strategy.py` — deterministic family and frame-plan selection.
- `src/editorial_carousel/legacy.py` — one compatibility adapter for old checkpoints.

### New asset-resolver files

- `src/asset_resolver/catalog.py` — load and query the approved local manifest.
- `src/asset_resolver/providers.py` — provider interface plus Pexels and Unsplash adapters.
- `src/asset_resolver/resolver.py` — local-first selection, external merge/rank, download, and fallback.
- `src/asset_resolver/lifecycle.py` — pending/approved/rejected promotion and hash verification.
- `assets/visual/beauty-editorial-v1/manifest.json` — production asset catalog.
- `assets/visual/beauty-editorial-v1/references/manifest.json` — `reference_only` quality anchors.
- `assets/fonts/beauty-editorial-v1/` — project-local font files and license texts.

### New rendering files

- `src/rendering/editorial/design_system.py` — immutable visual tokens and font declarations.
- `src/rendering/editorial/layouts.py` — eleven layout renderers behind one dispatch table.
- `src/rendering/editorial/renderer.py` — deep `render_carousel` interface, Chromium lifecycle, cleanup, and contact sheet.
- `src/rendering/editorial/probes.py` — browser-side overflow, font, geometry, and visible-text probes.

### New/changed graph and export files

- `src/nodes/node_p_visual_strategy_planner.py` — graph adapter for visual planning.
- `src/nodes/node_p_asset_resolver.py` — graph adapter for asset resolution.
- `src/nodes/node_p_editorial_carousel_renderer.py` — graph adapter for the new renderer.
- `src/publishing/artifacts.py` — publish copy, ContentLock, rescue prompt, and atomic export.
- `src/publishing/templates/codex_image_regeneration_prompt.txt` — reviewed rescue-prompt template.
- `src/prompts/base/storyboards_generator.txt` — semantic, layout-specific storyboard prompt.
- `src/graph.py`, `main.py`, Human Review, Final Guard, writer, QA, state, and export tests — integrate and retire the old path.

---

### Task 1: Introduce strict visual, storyboard, manifest, and ContentLock contracts

**Files:**
- Create: `src/schemas/visual_plan.py`
- Replace: `src/schemas/storyboard.py`
- Create: `src/schemas/assets.py`
- Create: `src/schemas/render_manifest.py`
- Create: `src/schemas/content_lock.py`
- Modify: `src/schemas/content_contract.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `src/schemas/__init__.py`
- Test: `tests/schemas/test_editorial_carousel.py`
- Modify tests: every fixture constructing `ContentContract`

**Interfaces:**
- Produces: `VisualPlan`, `FramePlanItem`, `AssetRequirement`, `CarouselPayload`, `AssetManifest`, `AssetSearchReport`, `RenderManifest`, and `ContentLock`.
- Consumes: existing `ContentContract`, `AgentState`, and Pydantic v2.

- [ ] **Step 1: Write failing schema tests**

```python
def test_content_contract_requires_editorial_strategy_fields():
    with pytest.raises(ValidationError):
        ContentContract.model_validate(BASE_CONTRACT)


def test_visual_plan_accepts_five_to_seven_frames_and_rejects_arbitrary_layout():
    plan = VisualPlan.model_validate(ZONE_PLAN)
    assert plan.primary_visual_family == "face_zone_map"
    broken = deepcopy(ZONE_PLAN)
    broken["frame_plan"][1]["layout"] = "freeform_html"
    with pytest.raises(ValidationError):
        VisualPlan.model_validate(broken)


def test_carousel_frame_rejects_network_url_and_free_css():
    frame = deepcopy(ZONE_STORYBOARD[0])
    frame["visual_slots"][0]["network_url"] = "https://example.com/a.jpg"
    with pytest.raises(ValidationError):
        CarouselFrame.model_validate(frame)


def test_content_lock_is_frozen():
    lock = ContentLock.model_validate(CONTENT_LOCK)
    with pytest.raises(ValidationError):
        lock.title = "另一个标题"
```

- [ ] **Step 2: Run the new schema suite and observe RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/schemas/test_editorial_carousel.py -q`

Expected: collection fails because the new schema modules do not exist.

- [ ] **Step 3: Implement the minimum strict contracts**

Use these exact public aliases and invariants:

```python
ContentJob = Literal[
    "diagnose_and_adjust", "follow_steps", "compare_and_choose",
    "save_and_check", "understand_and_notice",
]
VisualFamily = Literal[
    "beauty_editorial", "face_zone_map", "step_flow",
    "comparison_decision", "saveable_reference",
]
LayoutName = Literal[
    "editorial_cover", "texture_baseline", "front_face_zone",
    "three_quarter_face_zone", "step_timeline", "morning_evening_flow",
    "left_right_comparison", "three_state_diagnostic", "decision_tree",
    "saveable_checklist", "saveable_reference",
]


class FramePlanItem(StrictModel):
    frame_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=48)
    layout: LayoutName
    purpose: str = Field(min_length=1, max_length=160)
    asset_roles: list[str] = Field(default_factory=list, max_length=4)


class VisualPlan(StrictModel):
    design_system: Literal["beauty_editorial_v1"]
    content_job: ContentJob
    primary_visual_family: VisualFamily
    supporting_families: list[VisualFamily] = Field(max_length=4)
    frame_plan: list[FramePlanItem] = Field(min_length=5, max_length=7)
    required_assets: list[AssetRequirement]


class CarouselPayload(StrictModel):
    storyboards: list[CarouselFrame] = Field(min_length=5, max_length=7)


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
    hashtags: list[str]
    storyboards: list[dict]
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

Extend `ContentContract` with required `content_job`, `primary_visual_family`, `primary_visual_subject`, `proof_mode`, and `recommended_frame_count=Field(ge=5, le=7)`. Update all production prompt fixtures rather than adding silent defaults.

- [ ] **Step 4: Add typed state slots**

Add `visual_plan`, `asset_manifest`, and `render_manifest` as optional/not-required state values and remove no legacy slots yet.

- [ ] **Step 5: Run schema and existing contract tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/schemas tests/domain/test_profiles.py tests/nodes/test_metadata_flow.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the contracts**

```bash
git add src/schemas tests/schemas tests/domain/test_profiles.py tests/nodes/test_metadata_flow.py
git commit -m "feat: add editorial carousel contracts"
```

---

### Task 2: Build deterministic visual strategy and semantic storyboard generation

**Files:**
- Create: `src/editorial_carousel/__init__.py`
- Create: `src/editorial_carousel/strategy.py`
- Create: `src/editorial_carousel/legacy.py`
- Create: `src/nodes/node_p_visual_strategy_planner.py`
- Modify: `src/nodes/node_o_storyboards_generator.py`
- Modify: `src/prompts/base/storyboards_generator.txt`
- Modify: `src/nodes/__init__.py`
- Test: `tests/editorial_carousel/test_strategy.py`
- Test: `tests/nodes/test_visual_strategy_planner.py`
- Modify: `tests/nodes/test_metadata_flow.py`
- Modify: `tests/prompts/test_composer.py`

**Interfaces:**
- Consumes: `ContentContract`, prior published frame-plan signatures, final publish package, evidence brief.
- Produces: `build_visual_plan(contract, recent_signatures) -> VisualPlan` and `visual_strategy_planner_node(state) -> {"visual_plan": VisualPlan}`.

- [ ] **Step 1: Write failing strategy tests for all five jobs**

```python
@pytest.mark.parametrize(
    ("job", "family"),
    [
        ("diagnose_and_adjust", "face_zone_map"),
        ("follow_steps", "step_flow"),
        ("compare_and_choose", "comparison_decision"),
        ("save_and_check", "saveable_reference"),
        ("understand_and_notice", "beauty_editorial"),
    ],
)
def test_strategy_maps_content_job_to_family(job, family):
    contract = contract_for(job)
    plan = build_visual_plan(contract, recent_signatures=[])
    assert plan.primary_visual_family == family
    assert plan.frame_plan[0].layout == "editorial_cover"
    assert 5 <= len(plan.frame_plan) <= 7
    assert len({frame.layout for frame in plan.frame_plan}) >= 3
    assert any(frame.layout in {"saveable_checklist", "saveable_reference"} for frame in plan.frame_plan)
```

Add a test proving the zone fixture produces the six semantic roles from the spec, and a test proving a recent identical signature causes a deterministic alternative auxiliary layout without changing the content job.

- [ ] **Step 2: Run strategy tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel/test_strategy.py tests/nodes/test_visual_strategy_planner.py -q`

Expected: import failures for the new strategy and node.

- [ ] **Step 3: Implement versioned frame-plan recipes**

Define one immutable recipe tuple per job. The `diagnose_and_adjust` recipe is exactly:

```python
(
    ("cover", "editorial_cover", "beauty_subject"),
    ("baseline", "texture_baseline", "product_texture"),
    ("applicable_case", "front_face_zone", "face_map"),
    ("zone_adjustment", "three_quarter_face_zone", "face_map"),
    ("feedback_diagnosis", "three_state_diagnostic", "comparison"),
    ("save", "saveable_reference", "reference"),
)
```

The other recipes must satisfy the same global invariants and must not contain production copy. Derive `required_assets` from asset roles, not from topic-title substring checks.

- [ ] **Step 4: Implement the legacy adapter in one file**

```python
def hydrate_legacy_content_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    hydrated = dict(raw)
    mode = hydrated.get("visual_mode")
    hydrated.setdefault("content_job", "save_and_check")
    hydrated.setdefault("primary_visual_family", "saveable_reference")
    hydrated.setdefault("primary_visual_subject", "checklist")
    hydrated.setdefault("proof_mode", "comparison" if mode == "comparison_table" else "diagram")
    hydrated.setdefault("recommended_frame_count", 6)
    return hydrated
```

Only checkpoint hydration may call this adapter. New topic-generation output must validate without it.

- [ ] **Step 5: Replace the fixed-six storyboard prompt**

Require strict JSON matching `CarouselPayload`, require frame IDs/layouts to equal `VisualPlan.frame_plan`, require the cover headline to equal `first_screen_promise`, and forbid HTML, CSS, coordinates, URLs, image-generation prompts, topic changes, and extra frames.

- [ ] **Step 6: Update the storyboard node to validate before state write**

```python
payload = CarouselPayload.model_validate(storyboard_json)
expected = [(item.frame_id, item.layout) for item in visual_plan.frame_plan]
actual = [(item.frame_id, item.layout) for item in payload.storyboards]
if actual != expected:
    raise ValueError("storyboard frames must exactly match visual_plan frame order and layouts")
package["storyboards"] = payload.model_dump(mode="json")["storyboards"]
```

- [ ] **Step 7: Run focused prompt/node tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/editorial_carousel tests/nodes/test_visual_strategy_planner.py tests/nodes/test_metadata_flow.py tests/prompts/test_composer.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit visual strategy**

```bash
git add src/editorial_carousel src/nodes src/prompts/base/storyboards_generator.txt tests/editorial_carousel tests/nodes tests/prompts
git commit -m "feat: plan content-aware editorial carousels"
```

---

### Task 3: Seed the project-local design system, production asset catalog, and quality anchors

**Files:**
- Create: `assets/fonts/beauty-editorial-v1/SourceHanSerifSC-SemiBold.otf`
- Create: `assets/fonts/beauty-editorial-v1/SourceHanSansSC-Regular.otf`
- Create: `assets/fonts/beauty-editorial-v1/SourceHanSansSC-Medium.otf`
- Create: `assets/fonts/beauty-editorial-v1/BodoniModa-Regular.ttf`
- Create: `assets/fonts/beauty-editorial-v1/LICENSE-source-han.txt`
- Create: `assets/fonts/beauty-editorial-v1/OFL-bodoni-moda.txt`
- Create: `assets/visual/beauty-editorial-v1/manifest.json`
- Create: `assets/visual/beauty-editorial-v1/active/` SVG/PNG/WebP seed files
- Create: `assets/visual/beauty-editorial-v1/references/manifest.json`
- Create: `assets/visual/beauty-editorial-v1/references/editorial-cover-anchor.png`
- Create: `assets/visual/beauty-editorial-v1/references/face-diagram-anchor.png`
- Create: `assets/visual/beauty-editorial-v1/references/save-card-anchor.png`
- Create: `src/rendering/editorial/design_system.py`
- Test: `tests/assets/test_seed_catalog.py`
- Test: `tests/rendering/test_design_system.py`

**Interfaces:**
- Produces: `BEAUTY_EDITORIAL_V1`, local font paths, validated asset manifests, and three `reference_only` paths.
- Consumes: no network at runtime or test time.

- [ ] **Step 1: Write failing catalog and font tests**

```python
def test_design_system_fonts_are_repo_local_and_licensed():
    for font_path in BEAUTY_EDITORIAL_V1.font_paths.values():
        assert font_path.is_file()
        assert font_path.is_relative_to(REPOSITORY_ROOT)
    assert BEAUTY_EDITORIAL_V1.canvas == (1080, 1440)


def test_reference_assets_cannot_enter_production_catalog():
    catalog = load_catalog(ASSET_ROOT / "manifest.json")
    assert catalog.entries
    assert all(entry.usage == "production" for entry in catalog.entries)
    reference = json.loads((ASSET_ROOT / "references/manifest.json").read_text())
    assert len(reference["assets"]) == 3
    assert {item["usage"] for item in reference["assets"]} == {"reference_only"}
```

- [ ] **Step 2: Run asset/design tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/assets/test_seed_catalog.py tests/rendering/test_design_system.py -q`

Expected: missing files/modules.

- [ ] **Step 3: Add licensed local fonts and immutable tokens**

Use the official Source Han and Bodoni Moda release files, preserve their license texts, and expose this exact token object:

```python
BEAUTY_EDITORIAL_V1 = DesignSystem(
    name="beauty_editorial_v1",
    canvas=(1080, 1440),
    colors={
        "background": "#F7F2EA", "ink": "#292625", "mauve": "#9A707B",
        "coral": "#D45D4C", "sage": "#78805E",
    },
    font_paths={
        "display": FONT_ROOT / "SourceHanSerifSC-SemiBold.otf",
        "body_regular": FONT_ROOT / "SourceHanSansSC-Regular.otf",
        "body_medium": FONT_ROOT / "SourceHanSansSC-Medium.otf",
        "numeral": FONT_ROOT / "BodoniModa-Regular.ttf",
    },
)
```

- [ ] **Step 4: Add the 50–80 item seed catalog**

Create three face angles, ten face-zone masks, sixteen serum/gel/cream/liquid textures, ten pump/dropper/unbranded-container shapes, eight hand/skin-detail assets, and twelve background/line/page-number tokens. Every manifest entry must have `asset_id`, role, relative path, ownership/license, dimensions, sha256, allowed layouts, tags, disabled contexts, fallback roles, and `usage: production`.

- [ ] **Step 5: Promote three abstractly named quality anchors**

Copy the approved cover, face diagram, and save-card pages from the previously accepted editorial set into `references/`. Record their sha256 and `usage: reference_only`; the manifest description must say “style only: never copy title, copy, topic, or page sequence.” Do not mention the example title in production prompt code.

- [ ] **Step 6: Run focused asset tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/assets/test_seed_catalog.py tests/rendering/test_design_system.py -q`

Expected: all selected tests pass and no manifest path escapes its root.

- [ ] **Step 7: Commit assets and tokens**

```bash
git add assets src/rendering/editorial/design_system.py tests/assets tests/rendering/test_design_system.py
git commit -m "feat: seed beauty editorial design assets"
```

---

### Task 4: Implement local-first asset catalog matching

**Files:**
- Create: `src/asset_resolver/__init__.py`
- Create: `src/asset_resolver/catalog.py`
- Create: `src/asset_resolver/resolver.py`
- Test: `tests/asset_resolver/test_catalog.py`
- Test: `tests/asset_resolver/test_local_resolution.py`

**Interfaces:**
- Produces: `load_catalog(path) -> AssetCatalog` and `resolve_assets(visual_plan, catalog) -> AssetManifest`.
- Consumes: `VisualPlan`, production manifest entries, recent usage metadata, and explicit fallbacks.

- [ ] **Step 1: Write failing local-resolution tests**

```python
def test_local_match_prevents_provider_calls(tmp_path):
    provider = FakeProvider(results=[external_candidate()])
    catalog = catalog_with(local_face_map(), providers=[provider], root=tmp_path)
    manifest = resolve_assets(face_plan(), catalog)
    assert manifest.items[0].status == "active"
    assert provider.search_calls == []


def test_existing_but_incompatible_asset_triggers_gap_resolution(tmp_path):
    catalog = catalog_with(low_resolution_texture(), providers=[], root=tmp_path)
    with pytest.raises(AssetResolutionError, match="no eligible asset or fallback"):
        resolve_assets(texture_plan(), catalog)
```

- [ ] **Step 2: Run resolver tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/asset_resolver/test_catalog.py tests/asset_resolver/test_local_resolution.py -q`

Expected: missing resolver modules.

- [ ] **Step 3: Implement hard filters and deterministic ranking**

Hard filters are role/layout compatibility, minimum dimensions, crop compatibility, disabled contexts, provenance completeness, reference-only exclusion, and recent-repeat exclusion. Rank survivors by exact role, tag overlap, orientation, palette compatibility, and least-recently-used; break ties by `asset_id` so checkpoint replay is stable.

```python
def eligible(entry: AssetEntry, requirement: AssetRequirement) -> bool:
    return (
        entry.usage == "production"
        and entry.role == requirement.role
        and requirement.layout in entry.allowed_layouts
        and entry.width >= requirement.min_width
        and entry.height >= requirement.min_height
        and not set(requirement.context_tags).intersection(entry.disabled_contexts)
    )
```

- [ ] **Step 4: Implement explicit local fallback last**

The resolver must search eligible local exact matches first, then external providers in Task 5, then only manifest-declared fallback IDs. An unrelated existing file must never count as a fallback.

- [ ] **Step 5: Run local resolver tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/asset_resolver/test_catalog.py tests/asset_resolver/test_local_resolution.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit local resolution**

```bash
git add src/asset_resolver tests/asset_resolver
git commit -m "feat: resolve approved local visual assets"
```

---

### Task 5: Add Pexels and Unsplash gap providers with audited pending lifecycle

**Files:**
- Create: `src/asset_resolver/providers.py`
- Create: `src/asset_resolver/lifecycle.py`
- Modify: `src/asset_resolver/resolver.py`
- Modify: `.env.example`
- Modify: `requirements.txt`
- Modify: `pytest.ini`
- Delete after migration: `src/tools/pexels_search.py`
- Test: `tests/asset_resolver/test_providers.py`
- Test: `tests/asset_resolver/test_external_resolution.py`
- Test: `tests/asset_resolver/test_lifecycle.py`
- Test: `tests/asset_resolver/test_live_providers.py`

**Interfaces:**
- Produces: `AssetProvider.search(requirement)`, `AssetProvider.record_download(candidate)`, `approve_external_asset(candidate: PendingAsset, catalog: AssetCatalog) -> AssetEntry`, and normalized `ExternalAssetCandidate`.
- Consumes: `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`, `requests.Session`, and a run-scoped incoming directory.

- [ ] **Step 1: Write failing fake-provider tests**

```python
def test_gap_queries_both_enabled_providers_and_merges_results(tmp_path):
    pexels = FakeProvider("pexels", [candidate("p1", score_tags=["serum"])])
    unsplash = FakeProvider("unsplash", [candidate("u1", score_tags=["serum", "ivory"])])
    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, [pexels, unsplash]))
    assert len(pexels.search_calls) == 1
    assert len(unsplash.search_calls) == 1
    assert manifest.items[0].status == "pending_external"
    assert manifest.items[0].provider_asset_id == "u1"


def test_one_provider_timeout_keeps_other_provider_result(tmp_path):
    providers = [FailingProvider("pexels", TimeoutError("timeout")), FakeProvider("unsplash", [candidate("u1")])]
    manifest = resolve_assets(texture_plan(), empty_catalog(tmp_path, providers))
    assert manifest.search_report.provider_reports[0].status == "failed"
    assert manifest.items[0].provider == "unsplash"
```

- [ ] **Step 2: Run provider tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/asset_resolver/test_providers.py tests/asset_resolver/test_external_resolution.py tests/asset_resolver/test_lifecycle.py -q`

Expected: provider/lifecycle imports fail.

- [ ] **Step 3: Implement normalized official-API adapters**

```python
class AssetProvider(Protocol):
    name: str
    def search(self, requirement: AssetRequirement) -> list[ExternalAssetCandidate]:
        raise NotImplementedError
    def record_download(self, candidate: ExternalAssetCandidate) -> None:
        raise NotImplementedError
```

Pexels uses `https://api.pexels.com/v1/search` with `Authorization: <PEXELS_API_KEY>`. Unsplash uses `https://api.unsplash.com/search/photos` with `Authorization: Client-ID <UNSPLASH_ACCESS_KEY>` and calls the result’s official `download_location` before persisting the selected file. Both adapters must set timeouts, use English structured search terms, preserve author/page/file URLs, and never fabricate URLs.

- [ ] **Step 4: Implement merged filtering, ranking, and bounded downloads**

Query both enabled providers, normalize into one pool, deduplicate by provider ID/source URL before download, apply hard filters, rank without provider-name weight, and download at most the top three candidates per slot. Add `Pillow` as a direct dependency, normalize color mode/metadata/PNG-WebP output with it, and compute a deterministic 8×8 grayscale average hash for perceptual deduplication after the byte-level sha256 check. Save selected bytes under `incoming/external/<run_id>/` with `review_status=pending`.

- [ ] **Step 5: Implement explicit approval and hash-preserving promotion**

```python
def approve_external_asset(candidate: PendingAsset, catalog: AssetCatalog) -> AssetEntry:
    actual = sha256_file(candidate.path)
    if actual != candidate.sha256:
        raise AssetLifecycleError("pending asset hash changed before approval")
    destination = catalog.active_root / candidate.production_relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate.path.replace(destination)
    return catalog.append_approved(candidate, destination)
```

Rejected candidates remain auditable with `review_status=rejected`; they never enter the production manifest.

- [ ] **Step 6: Add opt-in live smoke tests**

Register `live_asset_providers` in `pytest.ini`, mark the tests `@pytest.mark.live_asset_providers`, and skip unless `RUN_LIVE_ASSET_PROVIDER_TESTS=1`. Default CI must report them skipped, not failed.

- [ ] **Step 7: Run provider suites GREEN without network**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/asset_resolver -q`

Expected: fake-provider tests pass; live provider tests skip.

- [ ] **Step 8: Commit provider fallback**

```bash
git add src/asset_resolver .env.example tests/asset_resolver
git commit -m "feat: source audited stock assets on demand"
```

---

### Task 6: Implement the deep editorial renderer and all eleven layouts

**Files:**
- Create: `src/rendering/editorial/__init__.py`
- Create: `src/rendering/editorial/layouts.py`
- Create: `src/rendering/editorial/probes.py`
- Create: `src/rendering/editorial/renderer.py`
- Test: `tests/rendering/editorial/test_layouts.py`
- Test: `tests/rendering/editorial/test_renderer.py`
- Test: `tests/rendering/editorial/test_chromium_smoke.py`

**Interfaces:**
- Produces: `render_carousel(visual_plan, storyboard, assets, output_dir) -> RenderManifest`.
- Consumes: strict schemas, local assets/fonts, Playwright, and one output directory.

- [ ] **Step 1: Write failing dispatch and HTML-contract tests**

```python
@pytest.mark.parametrize("layout", ALL_LAYOUT_NAMES)
def test_every_layout_has_one_renderer(layout):
    assert set(LAYOUT_RENDERERS) == set(ALL_LAYOUT_NAMES)
    html = LAYOUT_RENDERERS[layout](frame_for(layout), assets_for(layout))
    assert 'class="card"' in html
    assert 'data-layout="' + layout + '"' in html
    assert 'data-card-copy' in html


def test_renderer_uses_repo_fonts_without_system_fallback(tmp_path, fake_playwright):
    manifest = render_carousel(plan(), storyboard(), assets(), tmp_path, playwright_factory=fake_playwright)
    assert manifest.fonts.all_loaded is True
    assert set(manifest.fonts.computed_families) == {"Source Han Serif SC", "Source Han Sans SC", "Bodoni Moda"}
```

- [ ] **Step 2: Run renderer tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/rendering/editorial/test_layouts.py tests/rendering/editorial/test_renderer.py -q`

Expected: missing editorial renderer modules.

- [ ] **Step 3: Implement shared document shell and font CSS**

The shell must include local `@font-face` URLs, exact canvas dimensions, safe margins, palette variables, frame role/layout data attributes, and no remote URLs. Wait for `document.fonts.ready` before probes or screenshots.

- [ ] **Step 4: Implement eleven layout renderers behind one table**

```python
LAYOUT_RENDERERS: Mapping[LayoutName, LayoutRenderer] = MappingProxyType({
    "editorial_cover": render_editorial_cover,
    "texture_baseline": render_texture_baseline,
    "front_face_zone": render_front_face_zone,
    "three_quarter_face_zone": render_three_quarter_face_zone,
    "step_timeline": render_step_timeline,
    "morning_evening_flow": render_morning_evening_flow,
    "left_right_comparison": render_left_right_comparison,
    "three_state_diagnostic": render_three_state_diagnostic,
    "decision_tree": render_decision_tree,
    "saveable_checklist": render_saveable_checklist,
    "saveable_reference": render_saveable_reference,
})
```

Every layout must use escaped storyboard text and resolved local asset paths. No layout may read topic title or choose a family by keyword.

- [ ] **Step 5: Implement ordered filenames and contact sheet**

Generate `01-cover.png`, then `NN-<sanitized-frame-role>.png`. Build the contact sheet as a local HTML grid and capture `contact-sheet.png` with Chromium; do not add Pillow.

- [ ] **Step 6: Implement all-or-nothing cleanup**

On any font, probe, or screenshot error, delete every PNG and temporary HTML created by that invocation and raise `EditorialCarouselRenderError`. Never leave a partially valid set.

- [ ] **Step 7: Run real Chromium smoke test GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/rendering/editorial -q`

Expected: all eleven layout cases and real Chromium smoke pass; PNGs are exactly `1080 × 1440`.

- [ ] **Step 8: Commit renderer**

```bash
git add src/rendering/editorial tests/rendering/editorial
git commit -m "feat: render beauty editorial carousels"
```

---

### Task 7: Replace Carousel QA and Render QA with editorial contracts

**Files:**
- Modify: `src/nodes/node_p_carousel_qa.py`
- Modify: `src/nodes/node_p_render_qa.py`
- Modify: `src/schemas/carousel_qa.py`
- Modify: `src/schemas/render_qa.py`
- Test: `tests/nodes/test_carousel_qa.py`
- Test: `tests/nodes/test_render_qa.py`

**Interfaces:**
- Produces: atomic `CarouselQAIssue`/`RenderQAIssue` lists and existing R1 routing behavior.
- Consumes: `VisualPlan`, `CarouselPayload`, `AssetManifest`, `RenderManifest`, and `ContentContract`.

- [ ] **Step 1: Replace fixed-six tests with invariant tests**

```python
def test_carousel_qa_rejects_missing_saveable_frame():
    issues = validate_carousel(package_without_save_frame(), contract(), plan_without_save_frame())
    assert [issue.rule_id for issue in issues] == ["missing_saveable_frame"]


def test_render_qa_rejects_source_hash_mismatch():
    issues = validate_render(package(), asset_manifest(sha256="a" * 64), render_manifest(asset_sha256="b" * 64))
    assert any(issue.rule_id == "rendered_asset_hash_mismatch" for issue in issues)
```

Cover frame count, cover promise, layout-family compatibility, three-layout minimum, repeated layout, one task per frame, semantic slot match, visible-text equality, font family, dimensions, overflow, provenance, asset stretching, contact sheet, and partial output.

- [ ] **Step 2: Run QA tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py -q`

Expected: failures from removed fixed-six assumptions and missing manifests.

- [ ] **Step 3: Implement atomic editorial QA rules**

Keep one issue per actionable failure with stable `rule_id`, `frame_id`, and location. Do not attempt LLM repair inside QA nodes. Preserve current behavior that converts deterministic failures into R1 tasks.

- [ ] **Step 4: Add deterministic quality proxy metrics**

Populate `editorial_quality`, `beauty_category_fit`, `visual_hierarchy`, `saveability`, `cross_page_consistency`, and `template_stiffness` from measured layout/token/asset facts. Label them proxy metrics in the Human Review payload; never claim they replace aesthetic review.

- [ ] **Step 5: Run QA tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit QA contracts**

```bash
git add src/nodes/node_p_carousel_qa.py src/nodes/node_p_render_qa.py src/schemas/carousel_qa.py src/schemas/render_qa.py tests/nodes/test_carousel_qa.py tests/nodes/test_render_qa.py
git commit -m "feat: enforce editorial carousel quality gates"
```

---

### Task 8: Integrate planner, resolver, renderer, asset approval, and final guard into LangGraph

**Files:**
- Create: `src/nodes/node_p_asset_resolver.py`
- Create: `src/nodes/node_p_editorial_carousel_renderer.py`
- Modify: `src/nodes/node_q_human_review.py`
- Modify: `src/nodes/node_q_01_final_policy_guard.py`
- Modify: `src/nodes/node_p_content_writer.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Modify: `main.py`
- Test: `tests/test_graph.py`
- Test: `tests/nodes/test_domain_nodes.py`
- Test: `tests/nodes/test_final_policy_guard.py`
- Test: `tests/nodes/test_content_writer.py`

**Interfaces:**
- Produces graph order: `assembler -> visual_strategy_planner -> storyboard_generator -> asset_resolver -> carousel_qa -> editorial_carousel_renderer -> render_qa -> human_review -> final_policy_guard -> content_writer`.
- Consumes existing decision/R1/R2 loops and checkpoint/resume behavior.

- [ ] **Step 1: Write failing graph-order and review-payload tests**

```python
def test_graph_places_asset_resolution_before_carousel_render(graph_edges):
    assert graph_edges["assembler"] == {"visual_strategy_planner"}
    assert graph_edges["visual_strategy_planner"] == {"storyboard_generator"}
    assert graph_edges["storyboard_generator"] == {"asset_resolver"}
    assert graph_edges["asset_resolver"] == {"carousel_qa"}
    assert graph_edges["carousel_qa"] == {"editorial_carousel_renderer", "r1_reflector"}


def test_human_review_exposes_images_contact_sheet_qa_and_pending_assets(interrupt_payload):
    assert interrupt_payload["render_manifest"]["contact_sheet_path"]
    assert interrupt_payload["asset_manifest"]["items"]
    assert interrupt_payload["carousel_qa_result"]["passed"] is True
    assert interrupt_payload["render_qa_result"]["passed"] is True
```

- [ ] **Step 2: Run graph/node tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/test_graph.py tests/nodes/test_domain_nodes.py tests/nodes/test_final_policy_guard.py tests/nodes/test_content_writer.py -q`

Expected: missing new nodes and old graph edges.

- [ ] **Step 3: Add thin graph adapters**

Each adapter validates required state, calls one deep-module interface, and stores the returned manifest. It must not duplicate ranking, rendering, or hash logic.

- [ ] **Step 4: Add explicit pending-asset decisions to Human Review**

The resume payload must accept `asset_decisions: {asset_id: "approved" | "rejected"}`. Approval calls lifecycle promotion and updates the manifest; rejection selects the next downloaded eligible candidate or explicit fallback and reruns renderer/Render QA. No pending asset may reach Final Guard.

- [ ] **Step 5: Strengthen Final Guard and writer persistence**

Final Guard requires passed QA, no pending assets, matching AssetManifest/RenderManifest/active-file hashes, and complete image paths. Update `ContentRecord.image_paths` to persist final rendered PNG paths rather than obsolete image-source URLs.

- [ ] **Step 6: Update initial state and checkpoint hydration**

Initialize the three new state slots to `None`; hydrate old checkpoints through `editorial_carousel.legacy` only. Resume must continue from the checkpointed node without repeating completed external downloads.

- [ ] **Step 7: Run graph/node tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/test_graph.py tests/nodes/test_domain_nodes.py tests/nodes/test_final_policy_guard.py tests/nodes/test_content_writer.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit graph integration**

```bash
git add src/nodes src/graph.py main.py tests/test_graph.py tests/nodes
git commit -m "feat: integrate editorial carousel graph"
```

---

### Task 9: Export publish copy, ContentLock, and manual Codex visual-rescue prompt

**Files:**
- Create: `src/publishing/__init__.py`
- Create: `src/publishing/artifacts.py`
- Create: `src/publishing/templates/codex_image_regeneration_prompt.txt`
- Modify: `src/nodes/node_o_assembler.py`
- Modify: `main.py`
- Test: `tests/publishing/test_artifacts.py`
- Modify: `tests/test_main.py`
- Modify: `tests/integration/test_beauty_account_workflow.py`

**Interfaces:**
- Produces: `build_content_lock(package) -> ContentLock`, `build_publish_copy(package) -> str`, `build_codex_rescue_prompt(package, lock, reference_paths) -> str`, and `export_publish_package(package) -> PublishArtifacts`.
- Consumes: final policy-clean publish package, final images, three reference-only anchors, and package directory.

- [ ] **Step 1: Write failing copy and ContentLock tests**

```python
def test_publish_copy_is_directly_pasteable():
    assert build_publish_copy(PACKAGE) == "精华用量判断\n\n正文第一段\n\n#护肤 #精华\n"


def test_content_lock_hash_changes_for_any_locked_content():
    first = build_content_lock(PACKAGE)
    changed = deepcopy(PACKAGE)
    changed["storyboards"][1]["headline"] = "被改写"
    second = build_content_lock(changed)
    assert first.canonical_sha256 != second.canonical_sha256


def test_content_lock_hash_is_independent_of_dict_insertion_order():
    assert build_content_lock(PACKAGE).canonical_sha256 == build_content_lock(dict(reversed(list(PACKAGE.items())))).canonical_sha256
```

- [ ] **Step 2: Write failing rescue-prompt tests**

```python
def test_rescue_prompt_locks_current_content_and_forbids_rewriting():
    lock = build_content_lock(PACKAGE)
    prompt = build_codex_rescue_prompt(PACKAGE, lock, REFERENCE_PATHS)
    assert PACKAGE["focus_keyword"] in prompt
    assert PACKAGE["topic"] in prompt
    assert lock.canonical_sha256 in prompt
    assert "这是一次视觉重制，不是内容创作" in prompt
    assert "禁止重新选题" in prompt
    assert "每张图片的所有可见文字必须逐字来自对应 storyboard" in prompt
    assert "images-codex-vN" in prompt


def test_rescue_prompt_contains_no_unrelated_golden_or_example_title():
    prompt = build_codex_rescue_prompt(PACKAGE, build_content_lock(PACKAGE), REFERENCE_PATHS)
    assert "zone_diagnosis_fixture" not in prompt
    assert "精华按1泵还是2泵" not in prompt
```

- [ ] **Step 3: Run publishing tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/publishing/test_artifacts.py tests/test_main.py -q`

Expected: publishing module does not exist and current exporter writes only JSON.

- [ ] **Step 4: Propagate `focus_keyword` into the final package**

In assembler’s deterministic metadata overwrite, set `"focus_keyword": str(state.get("focus_keyword") or "")`. A missing/empty keyword is allowed only when the run had no CLI focus keyword; the ContentLock still locks the empty value and the topic remains mandatory.

- [ ] **Step 5: Implement canonical ContentLock serialization**

```python
LOCK_FIELDS = (
    "focus_keyword", "topic", "topic_id", "angle", "angle_id", "target_group",
    "core_pain", "title", "cover_copy", "first_screen_promise", "content",
    "hashtags", "storyboards",
)


def canonical_content_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
```

Build `first_screen_promise` from the validated `content_contract`; reject missing locked fields instead of inventing them.

- [ ] **Step 6: Add the reviewed rescue-prompt template**

Create `src/publishing/templates/codex_image_regeneration_prompt.txt` with this complete template; brace names are renderer substitutions, not freeform instructions:

```text
你正在对一篇已经完成选题、写作、合规和人工审核的小红书美容护肤图文做视觉救援。
这是一次 visual-only regeneration，不是内容创作。

## 不可更改的 Content Lock

下面的 canonical JSON 是唯一内容事实来源：
{content_lock_json}

ContentLock SHA-256：{content_lock_sha256}

逐页可见文字与归属：
{frame_text_table}

必须锁定：focus_keyword、topic、topic_id、angle、angle_id、target_group、core_pain、
title、cover_copy、first_screen_promise、content、hashtags、frame 数量、frame 顺序、
frame role、layout，以及 storyboard 内每一个可见字符串。

禁止重新选题、重新写文案、替换关键词、改变目标人群或核心痛点。禁止增加、删除或
改写护肤结论、步骤、用量、判断标准、风险提示和事实。禁止把参考图中的标题或内容
带入本篇。如果锁定字段缺失、JSON 无法读取或哈希校验失败，立即停止并报告，不得补写。

每张图片的所有可见文字必须逐字来自对应 storyboard。文字放不下时改变构图、字号层级
或换行，不能缩写、同义改写、删字或增加互动话术。

## 输入文件及角色

- 本文件所在目录：{package_directory}
- 当前文章审计 JSON：{audit_json_path}，只读内容来源。
- 当前套图：{current_images_directory}，用于诊断问题，不是必须保留的编辑目标。
- 质量锚点：
{style_reference_paths}

先用 view_image 查看当前套图中的每张图片和全部质量锚点。质量锚点只用于理解美容编辑
感、纸张质感、配色、线稿、材质、留白、层级和精致度；不得复制其文字、选题、信息结构
或固定页面顺序。

## Style Lock

- 画布：1080 × 1440，竖版小红书图文。
- 气质：当代美容杂志编辑感，克制、柔和、精致、有呼吸感；不能像 PPT、微商海报、
  电商详情页、儿童手账或廉价信息卡。
- 色彩：暖象牙白 #F7F2EA、墨色 #292625、灰粉 #9A707B、珊瑚 #D45D4C、
  鼠尾草绿 #78805E。允许改变各页占比，不增加高饱和霓虹色。
- 视觉语言：细腻纸张、柔光护肤品质地、透明液滴、纤细面部线稿、清晰分区、轻量细线
  和编号。每页必须有与本页语义对应的视觉主体，不能只做装饰。
- 中文字体：项目内 Source Han Serif SC SemiBold 只用于显示标题；Source Han Sans SC
  Regular/Medium 用于正文；Bodoni Moda Regular 用于页码或数字。禁止系统 fallback、
  书法体、手写体、卡通字体和超粗黑体。
- 同套一致性：颜色、纸张、线条、字体和光线统一；构图必须随 layout 和信息任务变化，
  不能把同一模板机械复制 5–7 次。

## 允许改变的内容

只允许改变布局的视觉实现、换行、字号层级、留白、素材选择、插画、背景、光影、裁切和
Design System 内的配色占比。不得改变 frame 数量、顺序、role、layout、信息任务或文字归属。

## 执行流程

1. 读取审计 JSON，重新计算 ContentLock canonical JSON 的 SHA-256；必须等于上面的哈希。
2. 用 view_image 查看当前 images 中每张图，列出需要修复的视觉问题；不要修改原文件。
3. 用 view_image 查看三个 reference_only 质量锚点并提炼 Style Lock；只提炼风格。
4. 找到同目录第一个不存在的 images-codex-vN，创建该目录和其 visual-bases 子目录；禁止
   覆盖 images、审计 JSON、publish-copy.txt、prompt 本身或已有 images-codex-vN。
5. 先为封面单独调用一次 Codex 内置 image generation。它只生成无中文文字的视觉底图，
   按封面 layout 为锁定文字留出安全区；不得调用 API、CLI 或要求 OPENAI_API_KEY。
6. 用 view_image 检查封面底图。未达到 Style Lock 就只调整一个问题并重新生成封面；通过后
   将它作为后续页面的 style anchor。
7. 按锁定顺序逐页处理剩余 frame。每个不同页面单独调用一次内置 image generation，参考
   质量锚点、已通过的封面和紧邻上一页；生成与本页 role/layout/visual slots 对应、无中文
   文字的视觉底图。
8. 使用项目本地字体和确定性 HTML/CSS 把对应 storyboard 的锁定文字叠加到底图。不得让
   图像模型自由生成中文；不得修改项目生产代码。临时 HTML 只放在本次版本目录的工作区。
9. 用 Playwright 截图得到 1080 × 1440 PNG，文件名保持 01-cover.png、随后
   NN-<frame-role>.png 的顺序。
10. 逐页验证尺寸、文字逐字一致、字体、溢出、安全边距、语义对应、无 Logo/水印/二维码、
    无可识别真人正脸。某页失败时只重做该页，不推翻已通过页面。
11. 生成 contact-sheet.png，检查跨页美容编辑感、风格一致性、版式变化、主视觉和保存页。
    contact sheet 失败时定位并只重做失败页面。
12. 最终再次比较所有排版输入文字与 ContentLock storyboards。全部一致后才交付；否则停止并
    明确列出未通过页面，不得声称完成。

## 最终输出

只把新套图、visual-bases、临时排版文件和 contact-sheet.png 写入选定的
images-codex-vN。保留原 images 和所有既有版本。结束时报告新目录、每页文件、采用的
内置 image generation 路径、最终 ContentLock 哈希和仍需人工判断的视觉风险。
```

- [ ] **Step 7: Implement atomic final artifacts**

Write `publish-copy.txt`, `codex-image-regeneration-prompt.txt`, and `<title>.json` to sibling temporary files, fsync/close them, then `os.replace` into the package directory. If a write fails, delete only new temporary/support files; keep Render-QA-approved images. JSON must include serialized `content_lock`, `visual_plan`, `asset_manifest`, `render_manifest`, and relative rendered-image paths.

- [ ] **Step 8: Replace fixed-six export validation in `main.py`**

Validate the dynamic ordered paths from `RenderManifest` rather than importing old `output_paths`. Require 5–7 PNGs inside one package `images/` directory and no unlisted PNGs. Delegate artifact creation to `src.publishing.artifacts.export_publish_package`.

- [ ] **Step 9: Run publishing and integration tests GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/publishing/test_artifacts.py tests/test_main.py tests/integration/test_beauty_account_workflow.py -q`

Expected: a successful package contains `images/`, `publish-copy.txt`, `codex-image-regeneration-prompt.txt`, and one title JSON; rescue prompt contains current content only and makes no image-generation call.

- [ ] **Step 10: Commit publish artifacts**

```bash
git add src/publishing src/nodes/node_o_assembler.py main.py tests/publishing tests/test_main.py tests/integration/test_beauty_account_workflow.py
git commit -m "feat: export content-locked visual rescue package"
```

---

### Task 10: Add golden fixtures, end-to-end regression, and checkpoint compatibility

**Files:**
- Create: `tests/fixtures/editorial_carousel/zone_diagnosis.json`
- Create: `tests/fixtures/editorial_carousel/ordered_routine.json`
- Create: `tests/fixtures/editorial_carousel/multi_option_decision.json`
- Create: `tests/fixtures/editorial_carousel/reference_checklist.json`
- Create: `tests/integration/test_editorial_carousel_workflow.py`
- Modify: `tests/integration/test_beauty_account_workflow.py`
- Modify: `tests/test_main.py`
- Modify: `tests/prompts/test_composer.py`
- Modify: checkpoint/resume tests under `tests/`

**Interfaces:**
- Produces four test-only end-to-end fixtures and regression evidence for new/legacy runs.
- Consumes all modules from Tasks 1–9 with fake LLM/provider adapters and real local Chromium.

- [ ] **Step 1: Write the four fixture-isolation tests**

```python
@pytest.mark.parametrize("fixture_name", GOLDEN_FIXTURE_NAMES)
def test_golden_fixture_names_and_copy_never_enter_production_prompt(fixture_name):
    production_prompt = compose_all_production_prompts(real_state_without_fixtures())
    fixture = load_golden(fixture_name)
    assert fixture_name not in production_prompt
    assert fixture["synthetic_title"] not in production_prompt
```

- [ ] **Step 2: Write failing end-to-end assertions**

For each fixture, assert its expected primary family, distinct frame-plan signature, 5–7 ordered PNGs, three-layout minimum, one saveable page, correct font families, contact sheet, passed QA, final DB record with rendered paths, `publish-copy.txt`, content-locked rescue prompt, and title JSON. Assert no fake provider call when local seed assets satisfy the fixture.

- [ ] **Step 3: Run end-to-end tests RED**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/integration/test_editorial_carousel_workflow.py -q`

Expected: failures expose any remaining graph, fixture, export, or compatibility gaps.

- [ ] **Step 4: Add one external-gap integration case**

Use fake Pexels/Unsplash adapters, force one missing texture role, approve the selected pending asset through Human Review, and assert the final active/source/render hashes match. No real network request is permitted.

- [ ] **Step 5: Add interrupted-run resume coverage**

Interrupt after a provider download and after rendering. Resume with the same thread ID; assert no duplicate download, no duplicate output version, and one completed run-registry entry.

- [ ] **Step 6: Make all integration cases GREEN**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/integration/test_editorial_carousel_workflow.py tests/integration/test_beauty_account_workflow.py tests/test_main.py tests/test_run_registry.py -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit golden integration coverage**

```bash
git add tests/fixtures/editorial_carousel tests/integration tests/test_main.py tests/test_run_registry.py tests/prompts/test_composer.py
git commit -m "test: cover editorial carousel workflow end to end"
```

---

### Task 11: Remove the legacy production path and verify the complete branch

**Files:**
- Delete: `src/schemas/text_card.py`
- Delete: `src/rendering/text_cards.py`
- Delete: `src/nodes/node_p_text_card_renderer.py`
- Delete: `src/nodes/node_l_visual_director.py`
- Delete: `src/nodes/node_m_image_sourcing.py`
- Delete: `src/nodes/node_n_image_qa.py`
- Delete: `src/tools/pexels_search.py`
- Delete: obsolete prompts `src/prompts/node_l_visual_director.txt`, `src/prompts/node_m_image_sourcing.txt`, `src/prompts/node_n_image_qa.txt`, `src/prompts/node_o_storyboards_images_generator.txt`
- Delete/replace: old fixed-card tests under `tests/rendering/`, `tests/nodes/`, and `tests/schemas/`
- Modify: `src/nodes/__init__.py`
- Modify: `src/schemas/__init__.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `main.py`
- Modify: `requirements.txt` only if implementation introduced a verified direct dependency
- Modify: `docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md` only for implementation-discovered clarifications, never to weaken acceptance criteria

**Interfaces:**
- Produces one production renderer/resolver path with legacy checkpoint hydration isolated in `src/editorial_carousel/legacy.py`.
- Consumes passing coverage from Tasks 1–10.

- [ ] **Step 1: Prove the new path passes before deletion**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest tests/integration/test_editorial_carousel_workflow.py tests/rendering/editorial tests/asset_resolver -q`

Expected: all selected tests pass; live-provider tests skip.

- [ ] **Step 2: Delete old production modules and exports**

Remove imports, lazy exports, state fields, fixed-six filename checks, and prompt references. Keep only the single legacy content-contract/checkpoint adapter; it must hydrate into the new contracts, never invoke the old renderer.

- [ ] **Step 3: Search for forbidden legacy references**

Run:

```bash
rg -n "REQUIRED_TEXT_CARD_TEMPLATES|TextCardPayload|text_card_renderer|pexels_search|visual_director_node|image_sourcing_node|image_qa_node|question_closer|warm_neutral|cool_sage" src main.py
```

Expected: no matches except an explicitly documented legacy migration-key string in `src/editorial_carousel/legacy.py`, if required by checkpoint decoding.

- [ ] **Step 4: Run formatting/import/static sanity**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m compileall -q src main.py`

Expected: exit 0 with no output.

- [ ] **Step 5: Run the complete test suite fresh**

Run: `/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q`

Expected: all tests pass; only explicitly marked live provider tests skip; no unexpected warnings or network calls.

- [ ] **Step 6: Inspect four generated contact sheets and publish packages**

Open all four golden contact sheets and verify: distinct layout composition, one coherent account design system, readable Chinese, no system-font fallback, no salamander, no identifiable face, no meaningless decoration, and a useful saveable page. Open each `publish-copy.txt` and rescue prompt; verify the copy matches JSON and each prompt locks only its own fixture content.

- [ ] **Step 7: Commit legacy removal**

```bash
git add -A
git commit -m "refactor: retire fixed text card workflow"
```

- [ ] **Step 8: Request code review and address findings**

Use `superpowers:requesting-code-review` against merge-base `main`. Any accepted change must get a focused regression test and another full-suite run.

- [ ] **Step 9: Run final verification after review fixes**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
git status --short
```

Expected: complete suite passes and worktree is clean.

---

## Plan Self-Review Record

- Spec coverage: contracts, five visual families, eleven layouts, local fonts, 50–80 seed assets, Pexels/Unsplash fallback, pending-asset approval, renderer, QA, Human Review, ContentLock, `publish-copy.txt`, rescue prompt, golden isolation, checkpoint resume, and legacy removal each map to a task above.
- Type consistency: the public flow is `VisualPlan -> CarouselPayload -> AssetManifest -> RenderManifest -> ContentLock/PublishArtifacts`; node/state names match the graph task.
- Network isolation: all normal tests use fake providers; real provider tests are explicit opt-in; automatic Codex image generation is absent.
- Content safety: the rescue prompt embeds and hashes current final content, forbids content creation, uses abstract style anchors, and writes only to a new versioned image directory.
- Placeholder scan: the plan contains no deferred implementation markers; each task names concrete behavior, tests, commands, and commits.
