# Project Documentation Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Chinese-first, layered documentation system for users and coding agents, index every retained document, replace stale operational descriptions with current facts, and remove superseded task documents after preserving their still-valid constraints.

**Architecture:** `README.md` is the human entry point, `AGENTS.md` is the authoritative coding-agent rule file, and `CLAUDE.md` is a thin Claude Code adapter. `docs/README.md` owns document discovery and status, while three current architecture documents absorb stable system knowledge so that long specs/plans remain historical records instead of implicit work queues.

**Tech Stack:** Markdown, Python 3.12, pytest, argparse CLI inspection, repository-local files and links.

## Global Constraints

- Documentation is Chinese-first; commands, identifiers, paths, schema names, and environment-variable names remain in their canonical spelling.
- Beauty/skincare is the formal account direction. `wellness` and `healthy_lifestyle` are technically supported extension domains, not equal product positioning.
- Do not change runtime behavior, graph topology, schema contracts, persistence, or publishing behavior.
- Do not include real API keys, cookies, credentials, private absolute paths, or user-specific machine information.
- Do not claim the project publishes automatically to Xiaohongshu. The workflow ends with persistence plus a local publish package.
- `AGENTS.md` is the authoritative agent rule file. `CLAUDE.md` must point to it rather than duplicate it.
- Historical plan/spec documents are not automatic work queues. An agent may execute one only after an explicit user request.
- Keep `docs/domain-profiles.md`, `docs/metrics-collector.md`, and `docs/trend-collector.md` at their current paths.
- Delete the two local fixed-card documents and the two Task 8 closure plans only after current architecture docs preserve their still-valid constraints.
- Default tests are offline. Live Pexels/Unsplash tests remain opt-in through `RUN_LIVE_ASSET_PROVIDER_TESTS=1`.
- Use `apply_patch` for text-file edits. Preserve unrelated user changes.

---

## File Map

### Create

- `README.md` — human-facing project introduction, setup, CLI, resume, review, output, testing, and troubleshooting.
- `docs/README.md` — canonical document index and status registry.
- `docs/architecture/workflow.md` — current production LangGraph and resume/review loops.
- `docs/architecture/editorial-contracts.md` — modern editorial schemas and quality/safety gates.
- `docs/architecture/persistence-and-assets.md` — checkpoint, registry, memory, external asset lifecycle, and publish artifact safety.
- `tests/docs/test_documentation.py` — regression checks for the documentation inventory, entry-point layering, CLI coverage, retired documents, and local links.

### Modify

- `AGENTS.md` — concise authoritative agent instructions plus documentation map.
- `CLAUDE.md` — thin Claude Code adapter that requires `AGENTS.md`.
- `docs/domain-profiles.md` — Chinese current domain guide with beauty-first positioning.
- `docs/metrics-collector.md` — current operational guide, retaining the path required by existing tests.
- `docs/trend-collector.md` — expanded current operational guide.
- `docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md` — remove wording that assumes the deleted fixed-card document remains available; keep the historical replacement decision.

### Delete

- `docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md`
- `docs/superpowers/plans/2026-07-12-local-text-card-rendering.md`
- `docs/superpowers/plans/2026-07-14-task8-final-review.md`
- `docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md`

### Authoritative implementation sources

- CLI and resume: `main.py`, `src/run_registry.py`
- Graph topology: `src/graph.py`
- Domain profiles: `src/domain/profiles.py`
- Models: `src/models/`
- Editorial contracts: `src/schemas/`, `src/editorial_carousel/`
- External assets: `src/asset_resolver/`
- Rendering: `src/rendering/editorial/`
- Publishing: `src/publishing/artifacts.py`
- Metrics collector: `metrics_collector/`
- Trend collector: `trend_collector/`
- Agent process: `docs/agents/`

---

### Task 1: Create the documentation index and inventory contract

**Files:**
- Create: `docs/README.md`
- Create: `tests/docs/test_documentation.py`

**Interfaces:**
- Consumes: the current Markdown inventory from `docs/**/*.md` and the status decisions in `docs/superpowers/specs/2026-07-15-project-documentation-design.md`.
- Produces: a stable documentation entry point and reusable `REPO_ROOT`/`DOCS_ROOT` test helpers for later tasks.

- [ ] **Step 1: Write the failing index test**

Create `tests/docs/test_documentation.py` with the initial contract:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"


def test_docs_index_lists_current_operational_and_agent_docs():
    index = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
    required = (
        "domain-profiles.md",
        "metrics-collector.md",
        "trend-collector.md",
        "agents/domain.md",
        "agents/issue-tracker.md",
        "agents/triage-labels.md",
    )
    for relative_path in required:
        assert relative_path in index


def test_docs_index_explains_historical_plans_are_not_work_queues():
    index = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
    assert "历史实施记录" in index
    assert "不得自动继续执行" in index
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
```

Expected: FAIL because `docs/README.md` does not exist.

- [ ] **Step 3: Create the current documentation index**

Create `docs/README.md` with these exact top-level sections:

```markdown
# 项目文档索引

## 当前状态
## 使用与运维
## 当前架构
## Agent 协作规范
## 已实施设计
## 历史实施记录
## 文档维护规则
```

Required content:

- State that beauty/skincare is the formal account direction.
- State that there is no active implementation plan after the documentation-governance work completes.
- Link the three root operational docs and all three `docs/agents/` files.
- Add a status table for every retained spec and plan with one of: `当前设计`, `已实施设计`, `历史实施记录`.
- State that unchecked boxes in historical plans are not permission to execute them and agents must not automatically continue them.
- Reserve links for the three architecture docs that Task 2 will create.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
```

Expected: `2 passed`.

- [ ] **Step 5: Commit the index contract**

```bash
git add docs/README.md tests/docs/test_documentation.py
git commit -m "docs: add governed documentation index"
```

---

### Task 2: Document the current architecture and retire obsolete task docs

**Files:**
- Create: `docs/architecture/workflow.md`
- Create: `docs/architecture/editorial-contracts.md`
- Create: `docs/architecture/persistence-and-assets.md`
- Modify: `docs/README.md`
- Modify: `docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md`
- Modify: `tests/docs/test_documentation.py`
- Delete: `docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md`
- Delete: `docs/superpowers/plans/2026-07-12-local-text-card-rendering.md`
- Delete: `docs/superpowers/plans/2026-07-14-task8-final-review.md`
- Delete: `docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md`

**Interfaces:**
- Consumes: `src/graph.py`, `src/editorial_carousel/legacy.py`, `src/schemas/`, `src/asset_resolver/`, `src/publishing/artifacts.py`, and the two Task 8 plans before deletion.
- Produces: three concise current-system references that `AGENTS.md` and `docs/README.md` can safely treat as authoritative.

- [ ] **Step 1: Add RED tests for architecture files and retired documents**

Append:

```python
ARCHITECTURE_DOCS = (
    "architecture/workflow.md",
    "architecture/editorial-contracts.md",
    "architecture/persistence-and-assets.md",
)

RETIRED_DOCS = (
    "superpowers/specs/2026-07-12-local-text-card-rendering-design.md",
    "superpowers/plans/2026-07-12-local-text-card-rendering.md",
    "superpowers/plans/2026-07-14-task8-final-review.md",
    "superpowers/plans/2026-07-14-task8-transaction-final-closure.md",
)


def test_current_architecture_docs_exist_and_are_indexed():
    index = (DOCS_ROOT / "README.md").read_text(encoding="utf-8")
    for relative_path in ARCHITECTURE_DOCS:
        assert (DOCS_ROOT / relative_path).is_file()
        assert relative_path in index


def test_superseded_and_temporary_task_docs_are_removed():
    for relative_path in RETIRED_DOCS:
        assert not (DOCS_ROOT / relative_path).exists()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Expected: architecture files are missing and all four retired files still exist.

- [ ] **Step 3: Write `docs/architecture/workflow.md`**

Use these sections and facts:

```markdown
# 当前工作流架构

## 入口与终点
## 生产工作流
## 反思、合规与质量循环
## 人工审核
## 中断与恢复
## 修改边界
```

The production path must match `src/graph.py` exactly:

```text
domain routing and confirmation
-> memory and topic signals
-> creative brief and topic candidates
-> angle, novelty, virality, evidence, outline, draft, title
-> decision / R1 / R2 loop
-> hashtag and assembler
-> visual strategy and semantic storyboards
-> asset resolver and carousel QA
-> editorial renderer and render QA
-> human review and final policy guard
-> content writer and local publish package
```

Document the four Human Review return routes and explain that old checkpoints are migrated through `src/editorial_carousel/legacy.py` into the modern storyboard seam; the adapter cannot invoke deleted renderers.

- [ ] **Step 4: Write `docs/architecture/editorial-contracts.md`**

Required sections:

```markdown
# 编辑式图文契约

## ContentContract 与首屏承诺
## VisualPlan
## CarouselPayload
## AssetManifest
## Carousel QA
## RenderManifest 与 Render QA
## Human Review
## Final Guard 与 ContentLock
## Codex 视觉救援边界
```

State that LLMs select semantic layout/content but cannot emit arbitrary HTML/CSS; rendered text remains locked; Codex rescue is manual, visual-only, and based on the exported canonical ContentLock.

- [ ] **Step 5: Write `docs/architecture/persistence-and-assets.md` before deleting source plans**

Required sections:

```markdown
# 持久化、素材与发布安全

## LangGraph checkpoint
## Run registry
## Structured and vector memory
## Local and external assets
## External asset review transactions
## Recovery and trust boundaries
## Publish artifact transaction
## Files that must not be casually deleted
```

Preserve these current invariants from the Task 8 closure plans and code:

- journal data is untrusted until strict schema, run/catalog binding, containment, no-follow identity, and byte-hash checks pass;
- external review mutations use catalog-scoped, run-bound transactions and lock ordering;
- crash recovery must not mutate an escaped or ambiguous path;
- approval and rejection are idempotent and reconcile catalog/filesystem state;
- publish export is content-locked, attested, versioned, atomic, and fail-closed;
- do not repair normal failures by deleting `checkpoints.sqlite`, `data/agent_runs.sqlite`, `data/xhs_memory.db`, or recovery directories.

- [ ] **Step 6: Remove obsolete docs and repair references**

Delete the four named documents with `apply_patch`. Update the editorial design introduction to say the fixed-card approach is preserved only in Git history and has no production contract. Update `docs/README.md` so none of the deleted paths remains indexed.

- [ ] **Step 7: Run the architecture tests and verify GREEN**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
rg -n "local-text-card-rendering|task8-final-review|task8-transaction-final-closure" \
  README.md AGENTS.md CLAUDE.md docs/README.md docs/architecture \
  docs/domain-profiles.md docs/metrics-collector.md docs/trend-collector.md \
  docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md || true
```

Expected: documentation tests pass and active/current documentation contains no retired filename. The documentation-governance design and plan may retain those names as an auditable deletion record.

- [ ] **Step 8: Commit current architecture and retirement**

```bash
git add docs tests/docs/test_documentation.py
git commit -m "docs: document current architecture and retire stale plans"
```

---

### Task 3: Bring domain and collector operations docs under governance

**Files:**
- Modify: `docs/domain-profiles.md`
- Modify: `docs/metrics-collector.md`
- Modify: `docs/trend-collector.md`
- Modify: `docs/README.md`
- Modify: `tests/docs/test_documentation.py`

**Interfaces:**
- Consumes: `src/domain/profiles.py`, `metrics_collector/config.py`, `metrics_collector/launchd.py`, `trend_collector/config.py`, `trend_collector/launchd.py`, and both package CLIs.
- Produces: current operational guides referenced by README and agent entry points.

- [ ] **Step 1: Add RED accuracy tests for the three operational docs**

Append:

```python
def test_domain_guide_states_product_positioning_and_supported_domains():
    text = (DOCS_ROOT / "domain-profiles.md").read_text(encoding="utf-8")
    assert "美容护肤是当前正式主线" in text
    assert all(name in text for name in ("beauty", "wellness", "healthy_lifestyle"))
    assert "beauty-v1" in text


def test_metrics_collector_guide_matches_schedule_and_commands():
    text = (DOCS_ROOT / "metrics-collector.md").read_text(encoding="utf-8")
    for command in ("python -m metrics_collector auth", "python -m metrics_collector collect", "python -m metrics_collector install-launchagent"):
        assert command in text
    assert "22:00" in text
    assert "Asia/Shanghai" in text


def test_trend_collector_guide_matches_schedule_and_safety_boundary():
    text = (DOCS_ROOT / "trend-collector.md").read_text(encoding="utf-8")
    for command in ("python -m trend_collector collect", "python -m trend_collector install-launchagent"):
        assert command in text
    assert "22:30" in text
    assert "不打开笔记详情" in text
```

- [ ] **Step 2: Run tests and verify RED**

Expected: at least the Chinese positioning and expanded trend operations assertions fail.

- [ ] **Step 3: Rewrite `docs/domain-profiles.md`**

Required content:

- Beauty formal positioning and recommended `--domain beauty` usage.
- Exact domain/version/default subdomain/allowed subdomain table from `src/domain/profiles.py`.
- Explicit domain precedence, subdomain validation, inference, and confirmation behavior.
- Evidence allowlist and safety policy boundary.
- Legacy record/checkpoint compatibility notes, clearly separated from new-run behavior.

- [ ] **Step 4: Normalize `docs/metrics-collector.md`**

Keep all currently correct commands and add:

- prerequisites and shared `~/.xhs-agent/browser-profile` ownership;
- exact DB path `data/xhs_memory.db` and run-ledger purpose;
- 22:00 schedule, `RunAtLoad=True`, system-timezone verification;
- authentication recovery and logs;
- safe diagnosis order: inspect `metrics_collection_runs`, then matching/write-back state;
- no automatic network access in tests.

Do not remove phrases asserted by `tests/metrics_collector/test_launchd.py`.

- [ ] **Step 5: Expand `docs/trend-collector.md`**

Include manual collection, LaunchAgent installation/bootstrap/print/bootout commands, 22:30 schedule with `RunAtLoad=False`, shared profile/log/DB paths, normalized signals, same-day idempotence, and safety boundaries. Explain that a same-day later `skipped` run can be expected after an earlier `success`.

- [ ] **Step 6: Run focused collector and docs tests**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q \
  tests/docs/test_documentation.py \
  tests/metrics_collector/test_launchd.py \
  tests/trend_collector/test_launchd.py
```

Expected: all pass without a live Xiaohongshu request.

- [ ] **Step 7: Commit operational documentation**

```bash
git add docs/domain-profiles.md docs/metrics-collector.md docs/trend-collector.md docs/README.md tests/docs/test_documentation.py
git commit -m "docs: govern domain and collector operations"
```

---

### Task 4: Write the human-facing README

**Files:**
- Create: `README.md`
- Modify: `tests/docs/test_documentation.py`

**Interfaces:**
- Consumes: `main.py --help`, `.env.example`, `src/models/`, `docs/README.md`, and the current publishing implementation.
- Produces: a standalone quick-start and operating guide for users and maintainers.

- [ ] **Step 1: Add RED README contract tests**

Append:

```python
def test_readme_documents_current_cli_and_resume_controls():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for option in (
        "--domain", "--subdomain", "--new", "--resume", "--thread-id",
        "--runs", "--verbose", "--focus_keyword", "--topic_num", "--provider",
    ):
        assert f"`{option}`" in text


def test_readme_documents_models_outputs_and_manual_rescue():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for name in (
        "ZHIPUAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
        "outputs/publish", "publish-copy.txt", "codex-image-regeneration-prompt.txt",
        "ContentLock",
    ):
        assert name in text
    assert "不会自动发布到小红书" in text
```

- [ ] **Step 2: Run focused tests and verify RED**

Expected: FAIL because `README.md` does not exist.

- [ ] **Step 3: Write README with exact information hierarchy**

Use these top-level sections:

```markdown
# xhs-agent

## 项目定位
## 核心能力
## 能力边界
## 工作流概览
## 环境要求
## 安装
## 配置
## 使用方法
## 中断与恢复
## 人工审核
## 输出产物
## 指标与趋势采集器
## 测试
## 常见问题
## 项目结构
## 进一步阅读
```

Required examples:

```bash
python main.py --new --domain beauty --subdomain skincare --focus_keyword "夏季防晒" --provider glm
python main.py --runs
python main.py --resume 12
python main.py --resume <thread-id>
python main.py --thread-id <legacy-thread-id>
```

Configuration must explain that only one model-provider key is required for the selected provider, the default provider is `glm`, Tavily supports evidence retrieval, and Pexels/Unsplash are optional external-asset fallbacks.

Output documentation must show:

```text
outputs/publish/<date>-<domain>-<subdomain>-<title>/
├── images/
├── publish-copy.txt
├── codex-image-regeneration-prompt.txt
└── <title>.json
```

Explain that the rescue prompt is manually handed to Codex and is not automatically invoked by the runtime.

- [ ] **Step 4: Verify README commands against the live parser**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python main.py --help
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
```

Expected: help lists every documented option and docs tests pass.

- [ ] **Step 5: Commit README**

```bash
git add README.md tests/docs/test_documentation.py
git commit -m "docs: add project README"
```

---

### Task 5: Make AGENTS authoritative and CLAUDE a thin adapter

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `tests/docs/test_documentation.py`

**Interfaces:**
- Consumes: README for human usage, `docs/README.md` for discovery, and the three architecture docs for detailed invariants.
- Produces: automatically loaded, non-duplicative coding-agent instructions.

- [ ] **Step 1: Add RED entry-point layering tests**

Append:

```python
def test_agents_is_authoritative_and_indexes_current_docs():
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    required = (
        "docs/README.md",
        "docs/architecture/workflow.md",
        "docs/architecture/editorial-contracts.md",
        "docs/architecture/persistence-and-assets.md",
        "docs/agents/issue-tracker.md",
        "docs/agents/triage-labels.md",
        "docs/agents/domain.md",
    )
    for path in required:
        assert path in text
    assert "ContentLock" in text
    assert "RUN_LIVE_ASSET_PROVIDER_TESTS=1" in text


def test_claude_is_a_thin_adapter_to_agents():
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in text
    assert "权威" in text
    assert "docs/README.md" in text
    assert len(text.splitlines()) <= 60
```

- [ ] **Step 2: Run tests and verify RED**

Expected: current minimal duplicated entry files fail the new architecture/index rules.

- [ ] **Step 3: Rewrite `AGENTS.md`**

Use these sections:

```markdown
# Repository Instructions

## Project goal and scope
## Read before changing code
## Current production path
## Non-negotiable contracts
## Commands
## Testing and network rules
## Persistence and generated files
## Git and workspace safety
## Issue tracker
## Triage labels
## Domain docs
## Completion checklist
```

Keep the file concise. State hard constraints inline and link detailed explanations. Preserve all current issue tracker, triage, and domain-doc behavior.

- [ ] **Step 4: Rewrite `CLAUDE.md`**

Keep it below 60 lines. It must:

- require complete reading of `AGENTS.md` before work;
- state `AGENTS.md` is authoritative if summaries differ;
- link README and `docs/README.md`;
- remind Claude Code not to push, delete SQLite/checkpoints/recovery state, overwrite outputs, or expose secrets without explicit user authorization;
- give the focused and full pytest commands without duplicating the whole architecture.

- [ ] **Step 5: Run entry-point tests and inspect duplication**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
wc -l AGENTS.md CLAUDE.md
```

Expected: tests pass and `CLAUDE.md` remains at most 60 lines.

- [ ] **Step 6: Commit agent entry points**

```bash
git add AGENTS.md CLAUDE.md tests/docs/test_documentation.py
git commit -m "docs: define agent documentation entry points"
```

---

### Task 6: Validate links, inventory, commands, and the complete repository

**Files:**
- Modify: `tests/docs/test_documentation.py`
- Modify: any documentation file only when a validation failure identifies a concrete inconsistency.

**Interfaces:**
- Consumes: all files produced by Tasks 1–5.
- Produces: executable evidence that documentation paths and current repository behavior agree.

- [ ] **Step 1: Add local Markdown-link validation**

Append:

```python
import re


MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def test_local_markdown_links_resolve():
    markdown_files = [REPO_ROOT / "README.md", REPO_ROOT / "AGENTS.md", REPO_ROOT / "CLAUDE.md"]
    markdown_files.extend(DOCS_ROOT.rglob("*.md"))
    failures = []
    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                failures.append(f"{source.relative_to(REPO_ROOT)} -> {raw_target}")
    assert failures == []
```

- [ ] **Step 2: Run documentation tests and fix only evidenced failures**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/docs/test_documentation.py
```

Expected: all documentation contracts and local links pass.

- [ ] **Step 3: Run CLI and collector help checks**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python main.py --help
/opt/anaconda3/envs/xhs-agent/bin/python -m metrics_collector --help
/opt/anaconda3/envs/xhs-agent/bin/python -m trend_collector --help
```

Expected: exit 0 and commands match the three operating guides.

- [ ] **Step 4: Run static documentation checks**

```bash
rg -n "TBD|TODO|待定|占位符" README.md AGENTS.md CLAUDE.md docs \
  --glob '!docs/superpowers/plans/**' \
  --glob '!docs/superpowers/specs/**'
rg -n "local-text-card-rendering|task8-final-review|task8-transaction-final-closure" \
  README.md AGENTS.md CLAUDE.md docs/README.md docs/architecture \
  docs/domain-profiles.md docs/metrics-collector.md docs/trend-collector.md \
  docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md || true
git diff --check
```

Expected: no active-document placeholders, no deleted-path references, and no whitespace errors.

- [ ] **Step 5: Run the full offline test suite**

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
```

Expected: all tests pass; only the two explicit live asset-provider tests are skipped unless the environment variable is intentionally enabled.

- [ ] **Step 6: Review final repository state**

```bash
git status --short
git diff --stat HEAD~5..HEAD
```

Confirm that no production Python file, database, checkpoint, generated publish package, API key, or user-specific path was added to the commits.

- [ ] **Step 7: Commit any validation-only corrections**

If Step 2–6 required documentation/test corrections:

```bash
git add README.md AGENTS.md CLAUDE.md docs tests/docs/test_documentation.py
git commit -m "docs: validate documentation governance"
```

If no correction was required, do not create an empty commit.
