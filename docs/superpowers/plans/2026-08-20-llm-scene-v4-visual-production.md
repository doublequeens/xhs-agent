# llm_scene_v4 Visual Production Implementation Plan

> **For team:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before every Gate or completion claim.

**Goal:** Build an isolated `llm_scene_v4` visual workflow that turns exact locked copy into semantic content, page briefs, constrained composition grammars and deterministic scene layouts; hardens every visual-model request with durable bounded execution; rejects bad inner-page design with page-level evidence; and earns production cutover only after shadow replay and blind review.

**Architecture:** Keep `src/graph.py` and all v3 schema import paths available for historical checkpoint recovery. Add a version-selected `src/graph_v4.py` whose visual chain is `content_atomizer → content_lock_builder → semantic_modeling/QA → visual_authoring/QA → asset_resolver → composition_planning → layout_compiler → aggregate design QA → existing Chromium renderer → render QA → independent critic → hash-bound Human Review → Final Guard`. Internal v4 artifacts are nested into the existing ten publication contracts. Production and shadow have different terminal writers; shadow never writes memory, Chroma, or `outputs/publish/`.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, SQLite/WAL, `google-genai`, multiprocessing worker isolation, Playwright/Chromium, Pillow, HTML/CSS, pytest, existing Pexels/Unsplash providers and scene renderer.

## Canonical references

- Approved design: `docs/superpowers/specs/2026-08-20-llm-scene-v4-visual-production-design.md`
- Current workflow: `docs/architecture/workflow.md`
- Current contracts: `docs/architecture/editorial-contracts.md`
- Persistence and asset safety: `docs/architecture/persistence-and-assets.md`
- Repository rules: `AGENTS.md`

## Global constraints

- Start every task with `git status --short`; preserve unrelated user changes.
- Do not rename or delete v3 schema classes/modules, `src/graph.py:create_graph`, or `legacy.py` while v3 checkpoints remain supported.
- Do not modify, delete, rebuild or parse internal tables in `checkpoints.sqlite`.
- Do not restore retired fixed-template contracts, nodes, renderers or 5–7-page assumptions.
- Keep exactly ten canonical contract JSON files plus PNG hashes in both v3 and v4 publish attestations.
- Visible page text must be a byte-for-byte verified projection of title, cover copy and body copy. Visual nodes may group, wrap, emphasize and repaginate it but may not rewrite it.
- Never render AI provenance, “示意图”, disclaimers or system labels. Provenance remains internal.
- Preserve provider identity, license, containment, no-follow, transaction identity, recovery evidence and asset byte hashes.
- Hard QA can never be overridden. Aesthetic override must bind the exact reviewed candidate and page bytes.
- Default tests remain offline. Live provider/model checks require the existing explicit environment flags.
- Do not commit `outputs/`, databases, local profiles, credentials, API payloads or unsanitized model responses.
- Each task ends in one focused commit. Do not proceed across a Go/No-Go Gate with failing tests.

## Phase and Gate map

| Phase | Tasks | Gate |
| --- | --- | --- |
| Baseline and version isolation | 1–3 | G0: fixtures replay; v3 resume preserved; shadow isolation proven |
| Reliable execution foundation | 4–5 | G1: timeout/retry/resume/crash injection passes |
| Three-Grammar vertical slice | 6–13 | G2: real Chromium Hero/Comparison/Step pages pass Q0–Q3 |
| Review and publication proof | 14–18 | G3: known bad pages rejected; reviewed bytes are publish bytes |
| Expansion and shadow evaluation | 19–20 | G4: 10-topic blind comparison and reliability thresholds pass |
| Cutover readiness | 21 | G5: docs, rollback drill and full verification approved |

---

### Task 1: Capture the observed visual-quality baseline

**Files:**
- Create: `tests/fixtures/llm_scene_v4/quality_manifest.json`
- Create: `tests/fixtures/llm_scene_v4/beauty-20260805/pages/*.png`
- Create: `tests/fixtures/llm_scene_v4/beauty-20260806/pages/*.png`
- Create: `tests/fixtures/llm_scene_v4/beauty-20260805/source-contracts.json`
- Create: `tests/fixtures/llm_scene_v4/beauty-20260806/source-contracts.json`
- Create: `tests/llm_scene_v4/test_quality_baseline.py`
- Create: `tests/llm_scene_v4/__init__.py`

**Purpose:** Turn the two user-identified packages into immutable test evidence without making tests depend on mutable `outputs/publish/` paths.

- [ ] **Step 1: Write the failing manifest-integrity test**

```python
def test_quality_manifest_binds_every_fixture_page():
    manifest = load_quality_manifest()
    assert {case["case_id"] for case in manifest["cases"]} == {
        "beauty-20260805",
        "beauty-20260806",
    }
    for case in manifest["cases"]:
        pages = case["pages"]
        assert pages[0]["label"] == "positive"
        assert all(page["label"] == "negative" for page in pages[1:])
        for page in pages:
            path = FIXTURE_ROOT / case["case_id"] / page["path"]
            assert sha256_path(path) == page["sha256"]
```

- [ ] **Step 2: Run it and confirm failure**

Run: `pytest -q tests/llm_scene_v4/test_quality_baseline.py`

Expected: fail because the fixture manifest and copied pages do not exist.

- [ ] **Step 3: Copy only the required evidence into fixtures**

Create fixture-owned PNGs and a minimized source-contract record containing page IDs, original Critic scores, revision round, design-plan hash and render-manifest hash. Do not copy asset provenance secrets, absolute local paths or whole canonical publish directories. Record these labels:

```json
{
  "case_id": "beauty-20260805",
  "critic": {"overall": 92, "passed": true, "revision_round": 2, "issues": []},
  "pages": [
    {"page_id": "page-1", "label": "positive", "human_issues": []},
    {"page_id": "page-2", "label": "negative", "human_issues": ["weak_hierarchy", "poor_information_design"]}
  ]
}
```

Complete all 10 and 9 page entries with page-specific human issue codes. Store fixture-relative paths and byte hashes.

- [ ] **Step 4: Verify fixture integrity and isolation**

Run: `pytest -q tests/llm_scene_v4/test_quality_baseline.py`

Expected: pass without reading `outputs/publish/`.

- [ ] **Step 5: Commit the baseline**

```bash
git add tests/fixtures/llm_scene_v4 tests/llm_scene_v4
git commit -m "test: capture llm scene v4 visual baseline"
```

---

### Task 2: Add immutable workflow metadata and additive execution state

**Files:**
- Modify: `src/run_registry.py`
- Modify: `tests/test_run_registry.py`
- Create: `tests/fixtures/run_registry/legacy-v3-schema.sql`

**Interfaces:**
- `AgentRun.workflow_version: Literal["llm_scene_v3", "llm_scene_v4"]`
- `AgentRun.run_mode: Literal["production", "shadow"]`
- `AgentRun.execution_state: ExecutionState`

- [ ] **Step 1: Write failing migration and resume-filter tests**

```python
def test_existing_registry_rows_backfill_to_v3_production(tmp_path):
    path = create_legacy_registry(tmp_path)
    registry = RunRegistry(path)
    try:
        run = registry.get_by_thread_id("legacy-thread")
        assert run.workflow_version == "llm_scene_v3"
        assert run.run_mode == "production"
    finally:
        registry.close()


def test_v4_fatal_and_exhausted_are_not_ordinary_resumable(registry):
    registry.create_run(
        "fatal", workflow_version="llm_scene_v4", execution_state="FAILED_FATAL"
    )
    registry.create_run(
        "retry", workflow_version="llm_scene_v4", execution_state="INTERRUPTED_RETRYABLE"
    )
    assert [run.thread_id for run in registry.list_resumable()] == ["retry"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/test_run_registry.py`

Expected: fail because the new columns and v4 resume semantics do not exist.

- [ ] **Step 3: Implement additive migration**

Add nullable columns through `PRAGMA table_info` + `ALTER TABLE` without changing the existing `status` CHECK:

```python
ExecutionState = Literal[
    "RUNNING", "WAITING_HUMAN", "INTERRUPTED_RETRYABLE",
    "INTERRUPTED_EXHAUSTED", "FAILED_FATAL", "COMPLETED",
]

EXECUTION_TO_LEGACY_STATUS = {
    "RUNNING": "running",
    "WAITING_HUMAN": "awaiting_review",
    "INTERRUPTED_RETRYABLE": "interrupted",
    "INTERRUPTED_EXHAUSTED": "interrupted",
    "FAILED_FATAL": "interrupted",
    "COMPLETED": "completed",
}
```

Backfill null version/mode to `llm_scene_v3`/`production`. Make version and mode immutable in update methods. `list_resumable()` must use `execution_state` for v4 and legacy status for v3.

- [ ] **Step 4: Re-run registry tests**

Run: `pytest -q tests/test_run_registry.py tests/memory/test_migrations.py`

Expected: pass; legacy rows remain readable.

- [ ] **Step 5: Commit**

```bash
git add src/run_registry.py tests/test_run_registry.py tests/fixtures/run_registry
git commit -m "feat: persist visual workflow execution identity"
```

---

### Task 3: Select the graph before checkpoint loading

**Files:**
- Create: `src/editorial_carousel/workflow_selection.py`
- Modify: `main.py`
- Modify: `tests/test_main.py`
- Modify: `tests/integration/test_legacy_editorial_resume.py`
- Create: `tests/integration/test_workflow_version_selection.py`

**Interface:** `select_workflow_context(registry, thread_id, requested_version, run_mode) -> WorkflowContext`

- [ ] **Step 1: Write failing selection-order tests**

```python
def test_resume_selects_graph_before_get_state(monkeypatch, registry):
    registry.create_run("v4-thread", workflow_version="llm_scene_v4")
    calls = []
    factories = {
        "llm_scene_v3": lambda: calls.append("build-v3") or FakeGraph("v3"),
        "llm_scene_v4": lambda: calls.append("build-v4") or FakeGraph("v4"),
    }
    graph = build_graph_for_run(registry.get_by_thread_id("v4-thread"), factories)
    graph.get_state({"configurable": {"thread_id": "v4-thread"}})
    assert calls == ["build-v4"]


def test_v4_checkpoint_never_enters_legacy_hydration(monkeypatch):
    monkeypatch.setattr(main, "hydrate_legacy_editorial_state", fail_if_called)
    load_versioned_run(FakeGraph("v4"), workflow_version="llm_scene_v4")
```

- [ ] **Step 2: Run and confirm current unconditional `create_graph()` fails**

Run: `pytest -q tests/test_main.py tests/integration/test_workflow_version_selection.py tests/integration/test_legacy_editorial_resume.py`

- [ ] **Step 3: Implement a versioned factory without changing v3 symbols**

```python
@dataclass(frozen=True)
class WorkflowContext:
    workflow_version: Literal["llm_scene_v3", "llm_scene_v4"]
    run_mode: Literal["production", "shadow"]


def build_graph_for_context(context, *, v3_factory, v4_factory):
    return v3_factory() if context.workflow_version == "llm_scene_v3" else v4_factory()
```

Make `main.py` read run metadata before building the graph. Keep `src.graph.create_graph` unchanged and lazily import `src.graph_v4.create_graph_v4` only for a v4 context. Do not expose a v4 CLI choice until Task 18 supplies a complete v4 graph.

- [ ] **Step 4: Prove v3 recovery is unchanged**

Run: `pytest -q tests/test_main.py tests/test_graph.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_workflow_version_selection.py`

- [ ] **Step 5: Commit — G0 version-isolation slice**

```bash
git add src/editorial_carousel/workflow_selection.py main.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_workflow_version_selection.py
git commit -m "feat: select visual graph before checkpoint resume"
```

---

### Task 4: Implement append-only visual Attempt Ledger

**Files:**
- Create: `src/visual_runtime/__init__.py`
- Create: `src/visual_runtime/attempt_ledger.py`
- Create: `src/schemas/v4/__init__.py`
- Create: `src/schemas/v4/runtime.py`
- Create: `tests/visual_runtime/test_attempt_ledger.py`

- [ ] **Step 1: Write failing event and crash-reconciliation tests**

```python
def test_attempt_events_are_append_only(tmp_path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    started = ledger.start(make_attempt())
    ledger.finish(started.attempt_id, status="SUCCESS", result_sha256="a" * 64)
    assert [type(event).__name__ for event in ledger.events(started.attempt_id)] == [
        "AttemptStarted", "AttemptFinished"
    ]


def test_open_attempt_is_reconciled_and_consumes_budget(tmp_path):
    ledger = AttemptLedger(tmp_path / "agent_runs.sqlite")
    started = ledger.start(make_attempt())
    ledger.reconcile_open_attempts(run_id="run-1")
    assert ledger.projection(started.attempt_id).status == "UNKNOWN_AFTER_CRASH"
    assert ledger.consumed_attempts("run-1", "candidate-1") == 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_runtime/test_attempt_ledger.py`

- [ ] **Step 3: Implement schema and SQLite events**

Use three event kinds (`AttemptStarted`, `AttemptFinished`, `AttemptReconciled`) with canonical JSON payload and monotonic sequence. Store sanitized result references under a caller-provided contained result root; reuse only after path containment and sha256 verification.

- [ ] **Step 4: Test replay, budget projection and concurrent WAL writers**

Run: `pytest -q tests/visual_runtime/test_attempt_ledger.py tests/test_run_registry.py`

- [ ] **Step 5: Commit**

```bash
git add src/visual_runtime src/schemas/v4 tests/visual_runtime
git commit -m "feat: record append only visual attempts"
```

---

### Task 5: Add a cancellable single-retry-layer LLM Gateway

**Files:**
- Create: `src/visual_ai/gateway.py`
- Create: `src/visual_ai/v4_worker.py`
- Create: `src/visual_ai/v4_gemini.py`
- Modify: `src/visual_ai/protocols.py`
- Modify: `src/visual_ai/factory.py`
- Create: `tests/visual_ai/test_gateway.py`
- Create: `tests/visual_ai/test_v4_worker.py`
- Modify: `tests/visual_ai/test_factory.py`

- [ ] **Step 1: Write failing timeout, retry and schema-budget tests**

```python
def test_gateway_terminates_blocked_worker(fake_worker, ledger):
    fake_worker.block_forever()
    with pytest.raises(VisualInvocationError, match="HARD_TIMEOUT"):
        gateway(deadline_seconds=0.05, max_attempts=1).invoke(make_request())
    assert fake_worker.terminated is True
    assert ledger.latest().status == "HARD_TIMEOUT"


def test_schema_repair_consumes_a_visible_attempt(gateway, ledger):
    gateway.worker.queue(invalid_schema_response(), valid_response())
    result = gateway.invoke_structured(make_request(), ResponseModel)
    assert result.value == "ok"
    assert ledger.consumed_attempts("run-1", "candidate-1") == 2
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py`

- [ ] **Step 3: Implement the Gateway**

```python
@dataclass(frozen=True)
class InvocationPolicy:
    deadline_seconds: float
    max_attempts: int = 3
    max_schema_repairs: int = 1


class VisualLLMGateway:
    def invoke_structured(self, request, response_model, policy): ...
    def generate_image(self, request, policy): ...
    def evaluate_images(self, request, response_model, policy): ...
```

The v4 worker accepts only serializable provider configuration and request content, constructs its own client inside the child process, performs exactly one provider call and returns a sanitized envelope. The parent owns all retry/backoff and kills/joins the worker at deadline. Do not alter v3 `GeminiStructuredVisualModel` behavior in this task.

- [ ] **Step 4: Run failure injection and v3 regression tests**

Run: `pytest -q tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_ai/test_gemini_adapter.py tests/models/test_guard.py`

Expected: v4 has one retry layer; existing v3 tests remain green.

- [ ] **Step 5: Commit — G1 reliable invocation slice**

```bash
git add src/visual_ai src/visual_runtime src/schemas/v4 tests/visual_ai
git commit -m "feat: bound visual model execution"
```

---

### Task 6: Project Markdown into immutable visible-copy atoms and build ContentLock

**Files:**
- Create: `src/schemas/v4/content.py`
- Create: `src/nodes/v4/__init__.py`
- Create: `src/nodes/v4/content.py`
- Create: `tests/schemas/v4/test_content.py`
- Create: `tests/nodes/v4/test_content.py`

- [ ] **Step 1: Write failing projection tests including Markdown tables**

```python
def test_table_projection_excludes_structure_before_atom_hashing():
    projection = project_visible_copy("| 时刻 | 做法 |\n|---|---|\n| 午后 | 补涂 |")
    assert [unit.text for unit in projection.units] == ["时刻", "做法", "午后", "补涂"]
    assert all("|" not in unit.text for unit in projection.units)
    assert projection.table_groups[0].rows == (("时刻", "做法"), ("午后", "补涂"))


def test_content_lock_binds_the_persisted_v4_atom_set():
    result = content_lock_builder_node(atomized_state())
    assert result["content_lock"].content_atom_set_sha256 == (
        result["content_atom_set"].canonical_sha256
    )
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py`

- [ ] **Step 3: Implement `VisibleCopyProjectionV4` and nodes**

Each unit stores raw source start/end, visible text, structural role and sha256. Build `ContentAtomSetV4` from units only after stripping structural Markdown. Reuse the current ContentLock payload fields, persist the lock immediately after atomization, and expose an invalidation helper that clears ContentLock plus every downstream v4 artifact after visible-copy edits.

- [ ] **Step 4: Run v4 and v3 atomizer tests**

Run: `pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py tests/nodes/test_content_atomizer.py tests/schemas/test_content_atoms.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/content.py src/nodes/v4 tests/schemas/v4 tests/nodes/v4
git commit -m "feat: project and lock v4 visible copy"
```

---

### Task 7: Build the Semantic Content Model and Q0 hard gate

**Files:**
- Create: `src/schemas/v4/semantic.py`
- Create: `src/nodes/v4/semantic.py`
- Create: `src/visual_design/v4/__init__.py`
- Create: `src/visual_design/v4/semantic_qa.py`
- Create: `src/prompts/base/v4_semantic_modeling.txt`
- Create: `tests/schemas/v4/test_semantic.py`
- Create: `tests/nodes/v4/test_semantic.py`
- Create: `tests/visual_design/v4/test_semantic_qa.py`

- [ ] **Step 1: Write failing exact-slice and group tests**

```python
def test_semantic_fragments_exactly_reconstruct_each_atom():
    model = semantic_model_with_split_step()
    assert evaluate_semantic_model(atom_set(), model).passed is True


def test_semantic_qa_rejects_rewritten_fragment():
    model = semantic_model_with_text("午后重新涂防晒")
    result = evaluate_semantic_model(atom_set(text="午后补涂防晒"), model)
    assert result.passed is False
    assert result.issues[0].code == "VISIBLE_TEXT_MUTATED"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py`

- [ ] **Step 3: Implement semantic contracts and Gateway-backed node**

The model may assign roles and parent/group relationships but must echo source atom IDs and integer slice bounds. The node reconstructs fragment text locally from the source slice instead of trusting returned text. Q0 produces `SemanticQAResult` with stable issue codes and source hashes.

- [ ] **Step 4: Re-run focused tests**

Run: `pytest -q tests/schemas/v4/test_semantic.py tests/nodes/v4/test_semantic.py tests/visual_design/v4/test_semantic_qa.py tests/visual_ai/test_gateway.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4 src/nodes/v4/semantic.py src/visual_design/v4 src/prompts/base/v4_semantic_modeling.txt tests/schemas/v4 tests/nodes/v4 tests/visual_design/v4
git commit -m "feat: model semantic visual content"
```

---

### Task 8: Produce Carousel Narrative, Page Briefs and Q1 hard gate

**Files:**
- Create: `src/schemas/v4/direction.py`
- Create: `src/nodes/v4/authoring.py`
- Create: `src/visual_design/v4/authoring_qa.py`
- Create: `src/prompts/base/v4_visual_authoring.txt`
- Create: `tests/schemas/v4/test_direction.py`
- Create: `tests/nodes/v4/test_authoring.py`
- Create: `tests/visual_design/v4/test_authoring_qa.py`

- [ ] **Step 1: Write failing page-ownership and rhythm tests**

```python
def test_authoring_qa_requires_exact_fragment_ownership():
    result = evaluate_authoring(briefs_with_duplicate_fragment(), semantic_model())
    assert result.passed is False
    assert {issue.code for issue in result.issues} == {"FRAGMENT_OWNERSHIP_DUPLICATED"}


def test_authoring_qa_rejects_three_consecutive_high_density_pages():
    result = evaluate_authoring(briefs(densities=["high", "high", "high", "low", "low"]), semantic_model())
    assert "DENSITY_CURVE_UNBALANCED" in {issue.code for issue in result.issues}
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py`

- [ ] **Step 3: Implement authoring draft and durable `VisualDirectionPlanV4`**

The LLM outputs `CarouselNarrative` and `PageBriefSet`; application code supplies source hashes and converts all fragment references to validated IDs. `VisualDirectionPlanV4` embeds Semantic Model, Narrative, Page Briefs and their canonical hashes, plus one family and 5–18 pages.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/schemas/v4/test_direction.py tests/nodes/v4/test_authoring.py tests/visual_design/v4/test_authoring_qa.py tests/nodes/test_visual_director.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/direction.py src/nodes/v4/authoring.py src/visual_design/v4/authoring_qa.py src/prompts/base/v4_visual_authoring.txt tests/schemas/v4 tests/nodes/v4 tests/visual_design/v4
git commit -m "feat: author v4 carousel page briefs"
```

---

### Task 9: Add candidate/revision artifact identity and v4 asset resolution

**Files:**
- Create: `src/visual_runtime/artifact_identity.py`
- Create: `src/asset_resolver/v4.py`
- Create: `src/nodes/v4/assets.py`
- Modify: `src/asset_resolver/resolver.py`
- Create: `tests/visual_runtime/test_artifact_identity.py`
- Create: `tests/asset_resolver/test_v4_resolution.py`
- Create: `tests/asset_resolver/test_live_providers.py`
- Create: `tests/nodes/v4/test_assets.py`

- [ ] **Step 1: Write failing containment and immutable-revision tests**

```python
def test_revision_paths_include_run_candidate_and_revision(tmp_path):
    identity = ArtifactIdentity("run-1", "candidate-2", "revision-3")
    paths = resolve_artifact_paths(tmp_path, identity)
    assert paths.render_root.relative_to(tmp_path).parts[-4:] == (
        "run-1", "candidate-2", "revision-3", "render"
    )


def test_reuse_requires_matching_bytes(tmp_path):
    source = write_asset(tmp_path, b"original")
    with pytest.raises(ArtifactBindingError):
        bind_reused_artifact(source, declared_sha256="0" * 64, destination=revision_root(tmp_path))
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_runtime/test_artifact_identity.py tests/asset_resolver/test_v4_resolution.py tests/nodes/v4/test_assets.py`

- [ ] **Step 3: Implement v4 request adapter and transaction identity**

Convert `PageBrief.asset_directives` into the existing resolver’s approved provider request shape. Add an optional explicit transaction root/identity to shared resolver internals while preserving the existing v3 default. Persist assets under `data/asset_transactions/<run>/<candidate>/<revision>/`; return an immutable `AssetManifest` with automated security approval and pre-review `human_decision=pending`.

- [ ] **Step 4: Run all asset safety regressions**

Run: `pytest -q tests/asset_resolver tests/nodes/test_asset_resolver.py tests/nodes/v4/test_assets.py tests/visual_runtime/test_artifact_identity.py`

Add a separately gated live smoke in `test_live_providers.py`; without
`RUN_LIVE_ASSET_PROVIDER_TESTS=1` it must skip and never make network calls.

- [ ] **Step 5: Commit**

```bash
git add src/visual_runtime src/asset_resolver src/nodes/v4/assets.py tests/visual_runtime tests/asset_resolver tests/nodes/v4
git commit -m "feat: isolate v4 asset revisions"
```

---

### Task 10: Define family tokens and the first three Composition Grammars

**Files:**
- Create: `src/schemas/v4/layout.py`
- Create: `src/visual_design/v4/tokens.py`
- Create: `src/visual_design/v4/grammars.py`
- Create: `src/nodes/v4/composition.py`
- Create: `tests/schemas/v4/test_layout.py`
- Create: `tests/visual_design/v4/test_grammars.py`
- Create: `tests/nodes/v4/test_composition.py`

- [ ] **Step 1: Write failing grammar invariant tests**

```python
@pytest.mark.parametrize("grammar_id", ["editorial_hero", "comparison_grid", "step_flow"])
def test_initial_grammars_define_relationships_without_pixel_boxes(grammar_id):
    grammar = GRAMMARS[grammar_id]
    payload = grammar.model_dump(mode="json")
    assert "x" not in payload and "y" not in payload
    assert grammar.allowed_page_roles
    assert grammar.region_roles


def test_composition_rejects_grammar_not_allowed_by_page_brief():
    with pytest.raises(ValueError, match="preferred compositions"):
        build_layout_program(page_brief(preferred=("step_flow",)), grammar_id="comparison_grid")
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py`

- [ ] **Step 3: Implement tokens, Grammar registry and `LayoutProgram`**

Family tokens contain palette, typography roles, spacing scale, radii, motif rules and density envelopes, never fixed page coordinates. `LayoutProgram` contains regions, semantic placements, alignment axes and constraints. Composition planning selects only among the Page Brief’s allowed grammars and produces no scene boxes.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py tests/visual_design/test_style_registry.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/layout.py src/visual_design/v4 src/nodes/v4/composition.py tests/schemas/v4 tests/visual_design/v4 tests/nodes/v4
git commit -m "feat: define v4 composition grammars"
```

---

### Task 11: Build deterministic typography measurement and Layout Compiler

**Files:**
- Create: `src/visual_design/v4/typography.py`
- Create: `src/visual_design/v4/compiler.py`
- Create: `src/visual_design/v4/grammar_compilers/__init__.py`
- Create: `src/visual_design/v4/grammar_compilers/editorial_hero.py`
- Create: `src/visual_design/v4/grammar_compilers/comparison_grid.py`
- Create: `src/visual_design/v4/grammar_compilers/step_flow.py`
- Create: `src/nodes/v4/layout.py`
- Create: `tests/visual_design/v4/test_typography.py`
- Create: `tests/visual_design/v4/test_compiler.py`
- Create: `tests/nodes/v4/test_layout.py`

- [ ] **Step 1: Write failing deterministic and constraint tests**

```python
def test_compiler_is_deterministic():
    first = compile_layout(program(), inputs())
    second = compile_layout(program(), inputs())
    assert canonical_sha256(first) == canonical_sha256(second)


def test_compiler_never_shrinks_below_minimum_font():
    with pytest.raises(LayoutCompilationError) as exc:
        compile_layout(overfull_program(), inputs(min_body_font_px=24))
    assert exc.value.code == "DENSITY_EXCEEDED"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py`

- [ ] **Step 3: Implement measurement and the three compilers**

Use resolved project font files with Pillow/FreeType for deterministic line measurement. Return flat existing scene primitives with stable element IDs, exact content refs and approved asset refs. Embed `LayoutProgram` and compiler provenance in `CarouselDesignPlanV4`. Raise only the six approved structured compilation errors; never truncate or mutate text.

- [ ] **Step 4: Run geometry and scene regressions**

Run: `pytest -q tests/visual_design/v4/test_typography.py tests/visual_design/v4/test_compiler.py tests/nodes/v4/test_layout.py tests/schemas/test_scene_graph.py tests/rendering/scene/test_compiler.py`

- [ ] **Step 5: Commit**

```bash
git add src/visual_design/v4 src/nodes/v4/layout.py tests/visual_design/v4 tests/nodes/v4
git commit -m "feat: compile v4 layouts deterministically"
```

---

### Task 12: Aggregate Q0/Q1/Q2 into the v4 Design Plan QA contract

**Files:**
- Create: `src/schemas/v4/quality.py`
- Create: `src/visual_design/v4/design_metrics.py`
- Create: `src/nodes/v4/design_qa.py`
- Create: `tests/schemas/v4/test_quality.py`
- Create: `tests/visual_design/v4/test_design_metrics.py`
- Create: `tests/nodes/v4/test_design_qa.py`

- [ ] **Step 1: Write failing aggregation and page-role metric tests**

```python
def test_aggregate_design_qa_fails_when_semantic_gate_failed():
    result = aggregate_design_qa(
        semantic=failed_semantic_qa(), authoring=passing_authoring_qa(), metrics=passing_metrics()
    )
    assert result.passed is False
    assert result.semantic_qa.passed is False


def test_whitespace_threshold_depends_on_grammar():
    hero = evaluate_page_metrics(hero_page(whitespace_ratio=.42), grammar="editorial_hero")
    checklist = evaluate_page_metrics(checklist_page(whitespace_ratio=.20), grammar="checklist")
    assert hero.passed is True
    assert checklist.passed is True
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_quality.py tests/visual_design/v4/test_design_metrics.py tests/nodes/v4/test_design_qa.py`

- [ ] **Step 3: Implement metrics and aggregate `DesignPlanQAResultV4`**

Calculate safe margins, overlap, font, contrast, whitespace, largest text block, regional density, alignment deviation, column balance, spacing consistency, hierarchy ratio, visual center, emphasis count, line length/orphans and image/text ratio. Every issue includes page, element/fragment, actual value, threshold, region and revision target. Bind all internal and public source hashes.

- [ ] **Step 4: Run v4 and v3 QA tests**

Run: `pytest -q tests/schemas/v4/test_quality.py tests/visual_design/v4/test_design_metrics.py tests/nodes/v4/test_design_qa.py tests/visual_design/test_plan_qa.py tests/nodes/test_design_plan_qa.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/quality.py src/visual_design/v4/design_metrics.py src/nodes/v4/design_qa.py tests/schemas/v4 tests/visual_design/v4 tests/nodes/v4
git commit -m "feat: hard gate v4 design quality"
```

---

### Task 13: Render v4 revisions through the existing Chromium compiler and run Q3

**Files:**
- Create: `src/schemas/v4/rendering.py`
- Create: `src/rendering/scene/v4_adapter.py`
- Create: `src/nodes/v4/render.py`
- Create: `src/visual_design/v4/render_qa.py`
- Create: `tests/rendering/scene/test_v4_adapter.py`
- Create: `tests/nodes/v4/test_render.py`
- Create: `tests/visual_design/v4/test_render_qa.py`
- Create: `tests/integration/test_v4_three_grammar_render.py`

- [ ] **Step 1: Write failing real-render and immutable-path tests**

```python
@pytest.mark.parametrize("grammar_id", ["editorial_hero", "comparison_grid", "step_flow"])
def test_v4_grammar_renders_real_1080x1440_png(grammar_id, tmp_path):
    manifest = render_compiled_fixture(grammar_id, tmp_path)
    assert manifest.pages[0].width == 1080
    assert manifest.pages[0].height == 1440
    assert Path(manifest.pages[0].path).is_relative_to(tmp_path / "candidate-1" / "revision-1")


def test_q3_rejects_rendered_box_drift():
    result = evaluate_v4_render(render_fixture(box_drift_px=12), tolerance_px=2)
    assert "RENDER_BOX_DRIFT" in {issue.code for issue in result.issues}
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/rendering/scene/test_v4_adapter.py tests/nodes/v4/test_render.py tests/visual_design/v4/test_render_qa.py tests/integration/test_v4_three_grammar_render.py`

- [ ] **Step 3: Implement the renderer Seam**

Define `RenderManifestV4`/`RenderQAResultV4` in `src/schemas/v4/rendering.py`. The adapter extracts the flat Scene Plan from `CarouselDesignPlanV4`, invokes the existing generic compiler/renderer, then constructs `RenderManifestV4` bound to the full v4 design-plan hash. Write only inside the active immutable revision root. Q3 verifies DOM text/probes, font/glyph loading, asset hashes, crop, page order, PNG bytes and actual geometry.

- [ ] **Step 4: Run focused Chromium verification**

Run: `pytest -q tests/rendering/scene tests/nodes/v4/test_render.py tests/visual_design/v4/test_render_qa.py tests/integration/test_v4_three_grammar_render.py`

Expected: all pass with real local Chromium where the existing smoke suite requires it.

- [ ] **Step 5: Commit — G2 three-Grammar vertical slice**

```bash
git add src/schemas/v4/rendering.py src/rendering/scene/v4_adapter.py src/nodes/v4/render.py src/visual_design/v4/render_qa.py tests/rendering/scene tests/nodes/v4 tests/visual_design/v4 tests/integration/test_v4_three_grammar_render.py
git commit -m "feat: render and verify v4 scene revisions"
```

---

### Task 14: Implement typed revision routing and failure fingerprints

**Files:**
- Create: `src/schemas/v4/revision.py`
- Create: `src/visual_design/v4/revisions.py`
- Create: `src/nodes/v4/revision.py`
- Create: `tests/visual_design/v4/test_revisions.py`
- Create: `tests/nodes/v4/test_revision.py`
- Create: `tests/integration/test_v4_revision_state_machine.py`

- [ ] **Step 1: Write failing loop-prevention tests**

```python
def test_second_same_fingerprint_must_change_operation():
    history = [revision_event(fingerprint="page-9:ICON_CLIPPED", operation="REFLOW")]
    request = route_revision(same_failure(), history)
    assert request.permitted_operations == ("CHANGE_GRAMMAR",)


def test_third_same_fingerprint_exhausts_candidate():
    with pytest.raises(VisualExecutionInterrupted) as exc:
        route_revision(same_failure(), history_with_two_prior_matches())
    assert exc.value.execution_state == "INTERRUPTED_EXHAUSTED"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_design/v4/test_revisions.py tests/nodes/v4/test_revision.py tests/integration/test_v4_revision_state_machine.py`

- [ ] **Step 3: Implement typed routing**

Map stable issue codes to `SEMANTIC`, `AUTHORING`, `ASSET`, `COMPOSITION`, `LAYOUT`, `RENDER` or `AESTHETIC`. First layout repair reflows within Grammar, second selects an already-approved alternative, third routes to repagination or exhausts. Only family/page-order changes invalidate the whole set; otherwise rebuild named pages and downstream contracts.

- [ ] **Step 4: Verify budgets survive simulated resume**

Run: `pytest -q tests/integration/test_v4_revision_state_machine.py tests/visual_runtime/test_attempt_ledger.py tests/integration/test_visual_loop_regression.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/revision.py src/visual_design/v4/revisions.py src/nodes/v4/revision.py tests/visual_design/v4 tests/nodes/v4 tests/integration/test_v4_revision_state_machine.py
git commit -m "feat: route bounded v4 visual revisions"
```

---

### Task 15: Add the independent page-first Aesthetic Evaluator

**Files:**
- Create: `src/schemas/v4/critique.py`
- Create: `src/visual_ai/aesthetic_evaluator.py`
- Create: `src/nodes/v4/critic.py`
- Create: `src/prompts/base/v4_aesthetic_critic.txt`
- Create: `tests/schemas/v4/test_critique.py`
- Create: `tests/visual_ai/test_aesthetic_evaluator.py`
- Create: `tests/nodes/v4/test_critic.py`

- [ ] **Step 1: Write failing worst-page and blind-input tests**

```python
def test_one_critical_page_fails_the_carousel_even_with_high_average():
    critique = build_critique(page_scores=[excellent_page(), critical_page("page-4")])
    assert critique.passed is False


def test_critic_request_omits_revision_round_and_authoring_prompt():
    request = build_aesthetic_request(render_manifest(), page_briefs())
    assert "revision_round" not in request.model_dump()
    assert "authoring_prompt" not in request.model_dump()
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/schemas/v4/test_critique.py tests/visual_ai/test_aesthetic_evaluator.py tests/nodes/v4/test_critic.py`

- [ ] **Step 3: Implement two-pass evaluation**

Pass 1 scores every page on hierarchy, readability, composition, whitespace, focus and asset integration with observable issues. Pass 2 scores rhythm, repetition, family consistency and cover/body consistency. Application code derives final pass/fail from per-page rules; the model cannot set a contradictory aggregate decision. Record `critic_independence=independent|degraded` based on configured authoring/evaluator identities.

- [ ] **Step 4: Test known baseline pages with a scripted evaluator**

Run: `pytest -q tests/schemas/v4/test_critique.py tests/visual_ai/test_aesthetic_evaluator.py tests/nodes/v4/test_critic.py tests/llm_scene_v4/test_quality_baseline.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/critique.py src/visual_ai/aesthetic_evaluator.py src/nodes/v4/critic.py src/prompts/base/v4_aesthetic_critic.txt tests/schemas/v4 tests/visual_ai tests/nodes/v4
git commit -m "feat: evaluate v4 aesthetics page first"
```

---

### Task 16: Generate the Review Workspace and hash-bound HumanReviewDecision

**Files:**
- Create: `src/review/__init__.py`
- Create: `src/review/v4_workspace.py`
- Create: `src/schemas/v4/review.py`
- Create: `src/nodes/v4/human_review.py`
- Modify: `main.py`
- Create: `tests/review/test_v4_workspace.py`
- Create: `tests/schemas/v4/test_review.py`
- Create: `tests/nodes/v4/test_human_review.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing workspace and approval-binding tests**

```python
def test_review_decision_binds_every_visible_artifact(tmp_path):
    workspace = build_review_workspace(review_inputs(), tmp_path)
    decision = approve_workspace(workspace)
    assert decision.render_manifest_sha256 == canonical_sha256(render_manifest())
    assert decision.page_sha256 == rendered_page_hashes(render_manifest())
    assert all(item.decision == "approved" for item in decision.asset_decisions)


def test_final_review_rejects_changed_page_bytes(tmp_path):
    decision = approved_decision(tmp_path)
    mutate_page(decision.page_paths["pages/01-page-1.png"])
    with pytest.raises(ReviewBindingError):
        verify_human_review_decision(decision, current_contracts())
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/review/test_v4_workspace.py tests/schemas/v4/test_review.py tests/nodes/v4/test_human_review.py tests/test_main.py`

- [ ] **Step 3: Implement the local workspace**

Generate `index.html`, contact sheet, page links, metric overlays, previous revision links, quality report and decision JSON inside the immutable revision review root. Display provider/license/source/security/hash for every asset. Human actions produce `APPROVE`, `AESTHETIC_OVERRIDE`, typed revision, asset reject/replace, or visible-copy edit.

Keep the original AssetManifest immutable with `human_decision=pending`; final per-asset approval lives in `HumanReviewDecision.asset_decisions` and binds asset bytes. Visible-copy edits clear ContentLock/atoms/all downstream contracts. Asset replacement clears manifest and every downstream contract.

- [ ] **Step 4: Render-inspect the workspace**

Run: `pytest -q tests/review/test_v4_workspace.py tests/schemas/v4/test_review.py tests/nodes/v4/test_human_review.py tests/test_main.py`

Then open the generated fixture workspace with the existing local Chromium/Playwright test seam and verify contact sheet, full-size pages, overlays and asset evidence are visible without network access.

- [ ] **Step 5: Commit**

```bash
git add src/review src/schemas/v4/review.py src/nodes/v4/human_review.py main.py tests/review tests/schemas/v4 tests/nodes/v4 tests/test_main.py
git commit -m "feat: bind v4 human visual review"
```

---

### Task 17: Implement v4 Final Guard, ten-contract publisher and shadow exporter

**Files:**
- Create: `src/schemas/v4/publishing.py`
- Create: `src/nodes/v4/final_guard.py`
- Create: `src/nodes/v4/shadow_writer.py`
- Create: `src/publishing/v4_artifacts.py`
- Create: `src/publishing/shadow_artifacts.py`
- Modify: `src/publishing/__init__.py`
- Create: `tests/nodes/v4/test_final_guard.py`
- Create: `tests/publishing/test_v4_artifacts.py`
- Create: `tests/publishing/test_shadow_artifacts.py`

- [ ] **Step 1: Write failing attestation and isolation tests**

```python
def test_v4_publish_attestation_hashes_ten_contracts_and_all_pngs(tmp_path):
    artifacts = export_v4(approved_terminal_state(), tmp_path)
    assert artifacts.publish_attestation.workflow_version == "llm_scene_v4"
    assert len(artifacts.contract_paths) == 10
    assert set(artifacts.publish_attestation.page_sha256) == expected_page_paths()


def test_shadow_export_never_writes_publish_or_memory(tmp_path, monkeypatch):
    writes = install_write_spies(monkeypatch)
    export_shadow(approved_shadow_state(), tmp_path / "outputs" / "shadow")
    assert writes.publish == []
    assert writes.sqlite_memory == []
    assert writes.chroma == []
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/nodes/v4/test_final_guard.py tests/publishing/test_v4_artifacts.py tests/publishing/test_shadow_artifacts.py`

- [ ] **Step 3: Implement versioned guard/exporters**

Final Guard recomputes ContentLock, Q0/Q1/Q2 aggregate bindings, Q3, asset security, `HumanReviewDecision`, every reviewed PNG and any aesthetic override. Embed the complete review decision/hash in `final_policy_attestation.json`. The v4 publisher exports the same ten filenames as v3 plus `publish-attestation.json`; it accepts pre-review `AssetManifest.human_decision=pending` only when every rendered asset has a byte-bound approved decision. Shadow exporter writes a non-publish evaluation bundle under `outputs/shadow/` and never calls content writer.

- [ ] **Step 4: Run v3/v4 publishing regressions**

Run: `pytest -q tests/publishing tests/nodes/v4/test_final_guard.py tests/nodes/test_final_policy_guard.py`

- [ ] **Step 5: Commit**

```bash
git add src/schemas/v4/publishing.py src/nodes/v4/final_guard.py src/nodes/v4/shadow_writer.py src/publishing tests/nodes/v4 tests/publishing
git commit -m "feat: attest v4 reviewed publish artifacts"
```

---

### Task 18: Wire the full v4 LangGraph and expose explicit shadow execution

**Files:**
- Create: `src/graph_v4.py`
- Create: `src/editorial_carousel/graph_common.py`
- Modify: `src/graph.py`
- Create: `src/schemas/v4/agent_state.py`
- Modify: `src/editorial_carousel/workflow_selection.py`
- Modify: `main.py`
- Modify: `src/nodes/__init__.py`
- Create: `tests/fixtures/graph/v3-signature.json`
- Create: `tests/test_graph_v4.py`
- Create: `tests/integration/v4_harness.py`
- Create: `tests/integration/test_v4_workflow.py`
- Modify: `tests/integration/test_workflow_version_selection.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing topology, resume-budget and terminal-route tests**

```python
def test_v4_visual_topology_has_no_page_designer_or_design_reviser():
    graph = create_graph_v4(checkpointer=InMemorySaver())
    nodes = set(graph.get_graph().nodes)
    assert {"semantic_modeling", "visual_authoring", "composition_planning", "layout_compiler"} <= nodes
    assert {"page_designer", "design_reviser"}.isdisjoint(nodes)


def test_extracting_common_graph_keeps_v3_node_and_edge_snapshot():
    assert graph_signature(create_graph(checkpointer=InMemorySaver())) == load_v3_signature()


def test_v4_resume_does_not_reset_failure_budget(v4_harness):
    first = v4_harness.interrupt_after_same_failure(count=2)
    resumed = v4_harness.resume(first.thread_id)
    assert resumed.failure_count == 3
    assert resumed.execution_state == "INTERRUPTED_EXHAUSTED"


def test_shadow_terminal_never_reaches_content_writer(v4_harness):
    state = v4_harness.run(run_mode="shadow")
    assert state["current_node"] == "SHADOW_ARTIFACT_WRITER"
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/test_graph_v4.py tests/integration/test_v4_workflow.py tests/integration/test_workflow_version_selection.py tests/test_main.py`

- [ ] **Step 3: Build the v4 graph and CLI routes**

Extract the identical domain/topic/writing chain into `graph_common.py`; make both graph builders use it while preserving a checked-in v3 node/edge signature and every historical node name. Do not share visual routing between versions.

Add `--visual-workflow {llm_scene_v3,llm_scene_v4}` for new runs, defaulting to v3 until G5. Add `--shadow-v4-from <run-id>` to load the source run with its frozen v3 graph, extract and validate canonical assembler copy, then seed a new linked v4 shadow run. Store `source_run_id`, immutable version and run mode before creating the v4 graph. Remove the resume counter reset only for v4; leave v3 behavior frozen.

- [ ] **Step 4: Run complete graph regressions**

Run: `pytest -q tests/test_graph.py tests/test_graph_v4.py tests/test_main.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_workflow_version_selection.py tests/integration/test_v4_workflow.py tests/integration/test_dynamic_visual_workflow.py`

- [ ] **Step 5: Commit — G3 complete reviewed workflow**

```bash
git add src/graph.py src/graph_v4.py src/editorial_carousel/graph_common.py src/schemas/v4/agent_state.py src/editorial_carousel/workflow_selection.py src/nodes/__init__.py main.py tests/fixtures/graph/v3-signature.json tests/test_graph.py tests/test_graph_v4.py tests/integration/v4_harness.py tests/integration/test_v4_workflow.py tests/integration/test_workflow_version_selection.py tests/test_main.py
git commit -m "feat: wire llm scene v4 workflow"
```

---

### Task 19: Add the remaining five Composition Grammars

**Files:**
- Modify: `src/visual_design/v4/grammars.py`
- Create: `src/visual_design/v4/grammar_compilers/diagnostic_matrix.py`
- Create: `src/visual_design/v4/grammar_compilers/checklist.py`
- Create: `src/visual_design/v4/grammar_compilers/evidence_card.py`
- Create: `src/visual_design/v4/grammar_compilers/image_annotation.py`
- Create: `src/visual_design/v4/grammar_compilers/summary_closing.py`
- Modify: `tests/visual_design/v4/test_grammars.py`
- Modify: `tests/visual_design/v4/test_compiler.py`
- Create: `tests/fixtures/llm_scene_v4/grammar_cases/*.json`
- Create: `tests/integration/test_v4_all_grammars_render.py`

- [ ] **Step 1: Add one failing positive, boundary and impossible case per Grammar**

```python
@pytest.mark.parametrize("grammar_id", REMAINING_GRAMMAR_IDS)
def test_each_grammar_has_positive_boundary_and_failure_fixture(grammar_id):
    cases = load_grammar_cases(grammar_id)
    assert {case.kind for case in cases} == {"positive", "boundary", "impossible"}
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/visual_design/v4/test_grammars.py tests/visual_design/v4/test_compiler.py tests/integration/test_v4_all_grammars_render.py`

- [ ] **Step 3: Implement each compiler independently**

Do not add a generic catch-all template. Each compiler consumes the shared Layout Program/Token/Measurement Interfaces and returns the same flat Scene Plan primitives. Impossible cases must fail with an approved structured error, not a smaller font or truncated copy.

- [ ] **Step 4: Real-render all Grammar fixtures**

Run: `pytest -q tests/visual_design/v4 tests/integration/test_v4_all_grammars_render.py`

- [ ] **Step 5: Commit**

```bash
git add src/visual_design/v4 tests/visual_design/v4 tests/fixtures/llm_scene_v4/grammar_cases tests/integration/test_v4_all_grammars_render.py
git commit -m "feat: complete v4 information design grammars"
```

---

### Task 20: Build shadow comparison, Critic calibration and blind-review evidence

**Files:**
- Create: `src/evaluation/__init__.py`
- Create: `src/evaluation/v4_comparison.py`
- Create: `src/evaluation/v4_calibration.py`
- Create: `tests/evaluation/test_v4_comparison.py`
- Create: `tests/evaluation/test_v4_calibration.py`
- Create: `tests/integration/render_v4_shadow_review.py`
- Modify: `tests/fixtures/llm_scene_v4/quality_manifest.json`
- Create: `docs/evaluations/llm_scene_v4/.gitkeep`

- [ ] **Step 1: Write failing no-version-leak and release-threshold tests**

```python
def test_blind_report_hides_variant_identity():
    report = build_blind_report(v3_bundle(), v4_bundle(), seed="case-1")
    assert set(report.variants) == {"A", "B"}
    assert "llm_scene_v3" not in report.public_payload_json()
    assert "llm_scene_v4" not in report.public_payload_json()


def test_release_gate_rejects_known_negative_false_passes():
    result = evaluate_calibration(quality_manifest(), scripted_critic_that_passes_all())
    assert result.gate_passed is False
    assert result.false_passed_negative_pages
```

- [ ] **Step 2: Run and confirm failure**

Run: `pytest -q tests/evaluation/test_v4_comparison.py tests/evaluation/test_v4_calibration.py`

- [ ] **Step 3: Implement comparison and calibration reports**

Generate side-by-side contact sheets, randomized A/B labels, per-page decisions, hard-QA evidence, attempts, latency and revision counts. Keep private identity mapping separate from the blind reviewer payload. Calibration must require the two positive covers to pass, known negative inner pages not to all pass, zero critical human regressions and stable repeated final decisions.

- [ ] **Step 4: Execute the G4 evaluation campaign**

Run offline: `pytest -q tests/evaluation tests/llm_scene_v4 tests/integration/test_v4_workflow.py`

Run local shadow cases explicitly (credentials only when approved):

```bash
python tests/integration/render_v4_shadow_review.py --cases 10 --output outputs/review/llm_scene_v4
```

Required recorded evidence before G4 approval:

- at least 10 distinct beauty/skincare topics and approximately 80 pages;
- v4 is better or equal in at least 80% of blind comparisons;
- zero human-rated unpublishable regressions;
- no request exceeds deadline + cleanup grace;
- no candidate exceeds 14 visual-model attempts or two aesthetic revisions.

Do not commit generated local review images or model payloads. Commit only a sanitized aggregate Markdown report after explicit human review.

- [ ] **Step 5: Commit the evaluation tooling**

```bash
git add src/evaluation tests/evaluation tests/integration/render_v4_shadow_review.py tests/fixtures/llm_scene_v4/quality_manifest.json docs/evaluations/llm_scene_v4/.gitkeep
git commit -m "test: evaluate llm scene v4 shadow quality"
```

---

### Task 21: Document cutover, rehearse rollback and run full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/architecture/workflow.md`
- Modify: `docs/architecture/editorial-contracts.md`
- Modify: `docs/architecture/persistence-and-assets.md`
- Modify: `.gitignore` only if new local evaluation/review roots require it
- Create after G4 approval: `docs/evaluations/llm_scene_v4/2026-XX-XX-shadow-evaluation.md`

- [ ] **Step 1: Update canonical documentation without declaring cutover prematurely**

Document version selection before checkpoint load, frozen v3 recovery, the full v4 chain, producer/consumer/hash tables, attempt events, candidate/revision storage, Review Workspace, shadow isolation, CLI commands, release Gates and rollback. Set default workflow to v4 only after the G4 report and explicit human approval.

- [ ] **Step 2: Run stale-path and placeholder scans**

```bash
rg -n 'visual_strategy_planner|storyboard_generator|carousel_qa|editorial_carousel_renderer|CarouselPayload|ResolvedVariant|modern_v2|recommended_frame_count|5-7|5–7' src main.py README.md docs/architecture docs/README.md
rg -n 'T[B]D|T[O]DO|NotImplementedError|pass[[:space:]]*$' src tests
```

Expected: old names only in `legacy.py`, historical specs/plans and absence assertions; no new placeholders.

- [ ] **Step 3: Rehearse version and rollback behavior**

Run:

```bash
pytest -q tests/integration/test_workflow_version_selection.py tests/integration/test_legacy_editorial_resume.py tests/integration/test_v4_workflow.py tests/publishing/test_shadow_artifacts.py tests/publishing/test_v4_artifacts.py
```

Manually verify:

- an existing v3 checkpoint resumes with v3 graph and unchanged schema imports;
- a new v4 shadow failure does not touch v3 state, memory or publish root;
- a new run can explicitly select v3 before start;
- an in-progress v4 run cannot switch to v3;
- rollback changes only the selector for future runs.

- [ ] **Step 4: Run focused v4 verification**

```bash
pytest -q tests/llm_scene_v4 tests/schemas/v4 tests/visual_runtime tests/visual_ai/test_gateway.py tests/visual_ai/test_v4_worker.py tests/visual_design/v4 tests/nodes/v4 tests/review tests/evaluation tests/publishing/test_v4_artifacts.py tests/publishing/test_shadow_artifacts.py tests/integration/test_v4_workflow.py tests/integration/test_v4_three_grammar_render.py tests/integration/test_v4_all_grammars_render.py
```

- [ ] **Step 5: Run full offline verification**

```bash
pytest -q
python -m compileall -q src main.py
git diff --check
```

Expected: all tests pass, live tests skip, compilation exits 0 and diff check has no output.

- [ ] **Step 6: Run optional live smokes only with explicit credentials/approval**

```bash
RUN_LIVE_VISUAL_AI_TESTS=1 pytest -q tests/visual_ai/test_live_gemini.py
RUN_LIVE_ASSET_PROVIDER_TESTS=1 pytest -q tests/asset_resolver/test_live_providers.py
```

These are evidence supplements, not substitutes for offline Gates.

- [ ] **Step 7: Review the final diff and commit documentation**

Confirm every requirement in the approved spec has an implementation site and test; no output package, database, profile, credential or unrelated user change is staged.

```bash
git add README.md docs/README.md docs/architecture/workflow.md docs/architecture/editorial-contracts.md docs/architecture/persistence-and-assets.md docs/evaluations/llm_scene_v4 .gitignore
git commit -m "docs: document llm scene v4 operations"
```

## Completion definition

Implementation is not complete merely because the v4 graph runs. Completion requires all of the following:

- G0–G5 evidence is recorded and approved.
- Existing v3 checkpoints still resume through frozen v3 imports.
- The two known packages are present as immutable quality fixtures and their bad inner pages are not silently passed.
- Three initial and five additional Grammars real-render through the single existing Chromium path.
- Q0/Q1/Q2 aggregate into `design_plan_qa.json`; Q3 binds actual PNG/DOM evidence.
- Human Review decisions bind the exact contracts, assets and page bytes that the exporter publishes.
- Shadow runs cannot write production memory, Chroma or `outputs/publish/`.
- Timeout, retry, schema repair, crash and resume budgets are durable and bounded.
- Ten contracts plus all PNGs are present in the v4 PublishAttestation.
- Blind comparison meets the predeclared 80% better-or-equal threshold with no critical regression.
- Full offline verification passes from a fresh command run.
