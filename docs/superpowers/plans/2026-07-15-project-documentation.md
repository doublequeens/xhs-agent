# Project Documentation Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a concise human/agent documentation layer and govern every existing `docs/` file without changing runtime behavior.

**Architecture:** Keep `README.md` as the user-facing entry point, `AGENTS.md` as the authoritative agent rules plus a documentation index, and `CLAUDE.md` as a short Claude Code adapter. Add `docs/README.md` and three current architecture notes; retain operational manuals and implemented design records with explicit status; delete only superseded fixed-card documents and completed Task 8 closure plans after their durable constraints are captured.

**Tech Stack:** Markdown, Python 3.12, argparse, LangGraph, SQLite, Playwright, pytest.

## Global Constraints

- Documentation is Chinese-first; code identifiers, commands, environment variable names, and file paths remain unchanged.
- Beauty/skincare is the formal account line; `wellness` and `healthy_lifestyle` are technical extension domains, not equal account positioning.
- Do not change production Python, schemas, graph behavior, data files, checkpoint files, or publish outputs.
- Preserve the stable paths `docs/domain-profiles.md`, `docs/metrics-collector.md`, and `docs/trend-collector.md`; tests read the metrics manual by path.
- `AGENTS.md` is the authoritative agent rule file; `CLAUDE.md` must point to it instead of duplicating it.
- Plans/specs are design history, not automatic unfinished work; their status must be visible from `docs/README.md`.
- Do not document real secrets, cookies, private local paths, or automatic Xiaohongshu publishing.
- Default tests remain offline; live Pexels/Unsplash tests require `RUN_LIVE_ASSET_PROVIDER_TESTS=1`.

---

### Task 1: Add the documentation index and current architecture notes

**Files:**
- Create: `docs/README.md`
- Create: `docs/architecture/workflow.md`
- Create: `docs/architecture/editorial-contracts.md`
- Create: `docs/architecture/persistence-and-assets.md`
- Read: `src/graph.py`, `main.py`, `src/domain/profiles.py`, `src/run_registry.py`, `src/schemas/visual_plan.py`, `src/schemas/storyboard.py`, `src/schemas/assets.py`, `src/schemas/render_manifest.py`, `src/schemas/content_lock.py`, `src/publishing/artifacts.py`, `src/asset_resolver/lifecycle.py`

**Interfaces:**
- Consumes: current source contracts and the governance decisions in `docs/superpowers/specs/2026-07-15-project-documentation-design.md`.
- Produces: a single index that links every retained document and three concise current-state references used by README and AGENTS.

- [ ] **Step 1: Write `docs/README.md` with a status table**

Include these exact categories and paths:

```markdown
# 项目文档索引

## 当前入口

- `README.md`：安装、运行、恢复、输出和测试。
- `AGENTS.md`：编码 agent 必须遵守的规则。
- `CLAUDE.md`：Claude Code 入口，规则以 `AGENTS.md` 为准。

## 当前系统说明

- `docs/architecture/workflow.md`：生产 LangGraph 和恢复路径。
- `docs/architecture/editorial-contracts.md`：现代内容、视觉、审核和发布契约。
- `docs/architecture/persistence-and-assets.md`：checkpoint、run registry、记忆、素材和发布持久化。
- `docs/domain-profiles.md`：domain/profile 和安全策略。
- `docs/metrics-collector.md`：指标采集器运行手册。
- `docs/trend-collector.md`：趋势信号采集器运行手册。
- `docs/agents/`：Issue、triage 和 domain-doc 协作规则。

## 设计与实施记录

表格必须标明每个保留主题的状态为“已实施”或“历史实施记录”，并明确这些文件不是未完成任务清单：

| 主题 | Spec | Plan | 状态 |
| --- | --- | --- | --- |
| Domain profiles | `docs/superpowers/specs/2026-07-02-domain-profile-expansion-design.md` | `docs/superpowers/plans/2026-07-02-domain-profile-expansion.md` | 已实施 |
| Metrics collector | `docs/superpowers/specs/2026-07-05-xhs-metrics-collector-design.md` | `docs/superpowers/plans/2026-07-05-xhs-metrics-collector.md` | 已实施 |
| Signal-driven topics | `docs/superpowers/specs/2026-07-07-signal-driven-topic-generation-design.md` | `docs/superpowers/plans/2026-07-07-signal-driven-topic-generation.md` | 已实施 |
| Beauty account workflow | `docs/superpowers/specs/2026-07-10-beauty-account-content-workflow-design.md` | — | 已实施 |
| Run resume registry | `docs/superpowers/specs/2026-07-13-run-resume-registry-design.md` | `docs/superpowers/plans/2026-07-13-run-resume-registry.md` | 已实施 |
| Editorial carousel | `docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md` | `docs/superpowers/plans/2026-07-14-editorial-carousel-workflow.md` | 已实施 |
| Project documentation | `docs/superpowers/specs/2026-07-15-project-documentation-design.md` | `docs/superpowers/plans/2026-07-15-project-documentation.md` | 当前任务 |

## 阅读规则

历史 spec/plan 用于理解设计原因；修改某个子系统时再读取对应记录。没有“当前 active plan”时，不得从历史 plan 的未勾选项推断待办。
```

- [ ] **Step 2: Write `workflow.md` from the compiled graph**

Document this exact production path and loop points:

```text
domain_router -> domain_confirmation -> memory_retriever
-> topic_signal_collector -> creative_brief_builder -> topic_ideator
-> topic_diversity_filter -> angle_strategist -> novelty_guard
-> virality_score -> evidence_brief -> outline_architect -> draft_writer
-> title_lab -> title_ranker -> decision_engine -> hashtag -> assembler
-> visual_strategy_planner -> storyboard_generator -> asset_resolver
-> carousel_qa -> editorial_carousel_renderer -> render_qa
-> human_review -> final_policy_guard -> content_writer
```

Explain that decision/R1/R2, carousel QA, render QA, Human Review, and Final Guard can route back; `main.py --resume` resumes LangGraph checkpoint state through the run registry; `content_writer` is the terminal persistence node. State that the workflow creates a publish package and does not publish to Xiaohongshu.

- [ ] **Step 3: Write `editorial-contracts.md` from the Pydantic models**

For each contract, list producer, consumer, and invariant:

| Contract | Producer | Consumer | Required invariant |
| --- | --- | --- | --- |
| `VisualPlan` | visual strategy planner | storyboard generator/QA | layout family and visual requirements are structured, not free-form HTML/CSS |
| `CarouselPayload` | storyboard generator | resolver, QA, renderer, review | frame count/order/role/layout and visible strings remain validated |
| `AssetManifest` | asset resolver | carousel QA, renderer | every asset is approved, attributable, and bound to a slot |
| `RenderManifest` | editorial renderer | render QA, publishing | ordered 1080×1440 PNGs, fonts, contact sheet, and source hashes are recorded |
| `ContentLock` | publishing layer | publish copy/rescue prompt/final guard | locked content is canonical and hashed; visual rescue cannot change facts or text |

Document that Human Review may edit visible text only through modern schema validation; Final Guard runs after edits; `legacy.py` is the only old-checkpoint migration seam.

- [ ] **Step 4: Write `persistence-and-assets.md`**

Cover these exact stores and safety rules:

- `checkpoints.sqlite`: LangGraph state only; never parse its internal tables from the run registry.
- `data/agent_runs.sqlite`: CLI-facing run index keyed by `thread_id`, with resumable statuses `running`, `interrupted`, and `awaiting_review`; completion is recorded only after verified export.
- `data/xhs_memory.db` and `data/chroma`: structured/vector content and domain-scoped retrieval.
- `outputs/publish/<date>-<domain>-<title>/`: verified publish package; keep files within the publish root and do not hand-edit the canonical JSON or ContentLock.
- `~/.xhs-agent/`: browser profile, downloads, diagnostics, and collector logs; never commit it.
- External asset lifecycle: validate provider identity, requirements, containment, no-follow, transaction binding, and byte hashes before mutation; preserve primary exceptions and cleanup/recovery evidence.

- [ ] **Step 5: Run documentation self-check and commit**

Run:

```bash
rg -n "TBD|TODO|占位|待定" docs/README.md docs/architecture || true
git diff --check
git add docs/README.md docs/architecture
git commit -m "docs: add current architecture and documentation index"
```

Expected: no placeholder output, clean diff check, one documentation-only commit.

### Task 2: Update the domain and collector operations manuals

**Files:**
- Modify: `docs/domain-profiles.md`
- Modify: `docs/metrics-collector.md`
- Modify: `docs/trend-collector.md`
- Read: `src/domain/profiles.py`, `main.py`, `metrics_collector/__main__.py`, `metrics_collector/config.py`, `metrics_collector/launchd.py`, `trend_collector/__main__.py`, `trend_collector/config.py`, `trend_collector/launchd.py`
- Test: `tests/metrics_collector/test_launchd.py`

**Interfaces:**
- Consumes: actual CLI help, profile definitions, LaunchAgent payloads, log paths, and database paths.
- Produces: accurate operational manuals at their existing stable paths, linked from `docs/README.md`.

- [ ] **Step 1: Rewrite `domain-profiles.md` in Chinese-first form**

Keep the three domain names and actual subdomains. State that `beauty/skincare` is the current account recommendation; describe `wellness` and `healthy_lifestyle` as supported extensions. Preserve examples for explicit domain, keyword inference, evidence requirements, prohibited topics/claims, domain-partitioned memory, and legacy migration. Do not claim that all three domains are equal account strategy.

- [ ] **Step 2: Update `metrics-collector.md` without breaking tested phrases**

Keep the exact strings `playwright install chromium`, `Google Chrome`, and `Asia/Shanghai`, because `tests/metrics_collector/test_launchd.py` reads this document and asserts them. Document the commands from `python -m metrics_collector --help`: `auth`, `collect`, and `install-launchagent`; the 22:00 schedule; Chrome channel; manual login; `~/.xhs-agent/browser-profile`; workbook diagnostics; separate logs; no live access in automated tests; and `launchctl bootstrap/print/bootout` lifecycle.

- [ ] **Step 3: Expand `trend-collector.md`**

Document `collect` and `install-launchagent`, 22:30 `Asia/Shanghai` schedule, `~/.xhs-agent/browser-profile`, `data/xhs_memory.db`, namespaced logs, manual bootstrap/bootout, and the restriction to creator-center trend surfaces without opening notes, publishing, engagement, search, or aggressive pagination.

- [ ] **Step 4: Run collector documentation checks and commit**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m metrics_collector --help
/opt/anaconda3/envs/xhs-agent/bin/python -m trend_collector --help
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q tests/metrics_collector/test_launchd.py tests/trend_collector/test_trend_launchd.py
git diff --check
git add docs/domain-profiles.md docs/metrics-collector.md docs/trend-collector.md
git commit -m "docs: align domain and collector manuals"
```

Expected: both help commands exit 0, focused tests pass, and the three stable manual paths remain present.

### Task 3: Rewrite README.md for users and maintainers

**Files:**
- Create: `README.md`
- Read: `main.py`, `.env.example`, `requirements.txt`, `pytest.ini`, `src/models/`, `src/graph.py`, `src/publishing/artifacts.py`, `docs/README.md`, `docs/architecture/workflow.md`

**Interfaces:**
- Consumes: actual CLI arguments, provider environment variable names, output filenames, and current architecture links.
- Produces: a self-contained Chinese-first quickstart and operations guide.

- [ ] **Step 1: Add project identity and scope**

State that the project generates beauty/skincare Xiaohongshu editorial carousels and local publish packages; it does not auto-publish. Mark `beauty` as the formal account line and the other two domains as technical extensions.

- [ ] **Step 2: Add installation and environment setup**

Use this exact setup sequence:

```bash
git clone <repository-url>
cd xhs-agent
/opt/anaconda3/envs/xhs-agent/bin/python -m pip install -r requirements.txt
/opt/anaconda3/envs/xhs-agent/bin/python -m playwright install chromium
cp .env.example .env
```

Explain that the Python executable path is environment-specific and can be replaced with an activated Python 3.12 environment. List `ZHIPUAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY`, `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`, and `RUN_LIVE_ASSET_PROVIDER_TESTS`; never include values.

- [ ] **Step 3: Add CLI examples from `main.py --help`**

Include these exact examples:

```bash
python main.py --help
python main.py --new --domain beauty --subdomain skincare --focus_keyword "夏季防晒" --provider glm
python main.py --runs
python main.py --runs --verbose
python main.py --resume <run_id-or-thread_id>
python main.py --thread-id <thread_id>
```

Explain that without `--new`, `--resume`, or `--thread-id`, the CLI may prompt for an existing resumable run; `--runs` lists the latest 20 runs with business summaries. Explain `--topic_num` default 10 and that `--resume` can select a numeric run ID or thread ID.

- [ ] **Step 4: Explain workflow, human review, recovery, and outputs**

Link to current architecture docs and explain the interrupt/review loop. Show this output shape without using a private absolute path:

```text
outputs/publish/<date>-<domain>-<title>/
├── images/01-*.png ...
├── publish-copy.txt
├── codex-image-regeneration-prompt.txt
├── <title>.json
└── .publish-artifacts.version
```

Explain ContentLock, publish copy, audit JSON, render manifest, and the rescue prompt; state that the original generated package should be preserved and visual rescue is a manual Codex step, not a runtime API call.

- [ ] **Step 5: Add testing, collector links, troubleshooting, and project map**

Include `pytest -q`, focused test examples, `RUN_LIVE_ASSET_PROVIDER_TESTS=1` opt-in behavior, common timeout/resume steps, model-key errors, Playwright installation, collector manual links, and links to `docs/README.md`, architecture docs, `docs/agents/`, and current specs/plans.

- [ ] **Step 6: Run README command and link checks, then commit**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python main.py --help
rg -n "TBD|TODO|占位|待定|/Users/|sk-[A-Za-z0-9]|AIza" README.md || true
git diff --check
git add README.md
git commit -m "docs: add project README"
```

Expected: help exits 0; the secret/private-path scan prints no matches; diff check passes.

### Task 4: Rewrite AGENTS.md and CLAUDE.md as thin rule/index files

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Read: `docs/README.md`, `docs/architecture/workflow.md`, `docs/architecture/editorial-contracts.md`, `docs/architecture/persistence-and-assets.md`, `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/domain.md`

**Interfaces:**
- Consumes: current documentation index and architecture notes.
- Produces: concise, non-duplicating agent instructions that preserve the existing Issue tracker/triage/domain-doc rules.

- [ ] **Step 1: Rewrite `AGENTS.md`**

Use these required sections:

```markdown
# Repository Agent Instructions
## Project scope and product line
## Before changing code
## Current architecture
## Non-negotiable contracts
## Commands and verification
## State, assets, and outputs
## Git and safety rules
## Documentation index
## Issue tracker, triage, and domain docs
```

Keep hard rules in this file: modern single production path, `legacy.py` only compatibility seam, no fixed-card references, ContentLock preservation, no QA/review bypass, offline tests by default, protect SQLite/output/user changes, no secrets/push without authorization. Link details to `docs/README.md` and architecture docs instead of copying them.

- [ ] **Step 2: Rewrite `CLAUDE.md`**

Keep it under roughly 40 lines. It must say “read `AGENTS.md` first; AGENTS is authoritative”, link `README.md` and `docs/README.md`, name the default test command, and remind Claude Code not to push, reset, delete state databases, overwrite outputs, or claim completion without fresh verification.

- [ ] **Step 3: Run agent-doc checks and commit**

Run:

```bash
rg -n "TBD|TODO|占位|待定|/Users/|sk-[A-Za-z0-9]|AIza" AGENTS.md CLAUDE.md || true
rg -n "issue-tracker|triage-labels|agents/domain|docs/README|architecture/" AGENTS.md CLAUDE.md
git diff --check
git add AGENTS.md CLAUDE.md
git commit -m "docs: make agent instructions index current docs"
```

Expected: no secret/private-path matches, required index links present, clean diff check.

### Task 5: Remove obsolete documents and mark retained history

**Files:**
- Delete: `docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md`
- Delete: `docs/superpowers/plans/2026-07-12-local-text-card-rendering.md`
- Delete: `docs/superpowers/plans/2026-07-14-task8-final-review.md`
- Delete: `docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md`
- Modify: retained `docs/superpowers/specs/*.md` and `docs/superpowers/plans/*.md` headers only when needed to state `已实施` or `历史实施记录`
- Modify: `docs/README.md` if any status table path changes

**Interfaces:**
- Consumes: current architecture notes from Task 1 and the retained design/plan inventory.
- Produces: no obsolete fixed-card or one-off Task 8 closure plan remains in the active docs tree; retained records are clearly non-active.

- [ ] **Step 1: Verify deletion candidates are not current runtime inputs**

Run:

```bash
rg -n "local-text-card-rendering|task8-final-review|task8-transaction-final-closure" . --glob '!docs/superpowers/specs/2026-07-15-project-documentation-design.md' --glob '!docs/superpowers/plans/2026-07-15-project-documentation.md'
```

Expected: only historical references in the documentation design/plan, not production code or tests. Do not delete any other docs from the inventory.

- [ ] **Step 2: Delete only the four approved files**

Run:

```bash
git rm docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md \
  docs/superpowers/plans/2026-07-12-local-text-card-rendering.md \
  docs/superpowers/plans/2026-07-14-task8-final-review.md \
  docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md
```

- [ ] **Step 3: Mark retained historical records and update the index**

Add a short status line to each retained completed spec/plan only when its current header does not already state status. Do not rewrite the historical task body or change checkboxes. Ensure `docs/README.md` calls these records “已实施” or “历史实施记录”, not active work.

- [ ] **Step 4: Run doc inventory and commit**

Run:

```bash
test ! -e docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md
test ! -e docs/superpowers/plans/2026-07-12-local-text-card-rendering.md
test ! -e docs/superpowers/plans/2026-07-14-task8-final-review.md
test ! -e docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md
rg -n "docs/(domain-profiles|metrics-collector|trend-collector)\.md" docs/README.md README.md AGENTS.md
git diff --check
git add docs
git commit -m "docs: retire obsolete design records"
```

Expected: all four deletion checks pass, the three operational manuals are indexed, and no unrelated docs are deleted.

### Task 6: Final documentation and repository verification

**Files:**
- Read: `README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/README.md`, all retained `docs/` files
- Test: full `tests/` suite and CLI help commands

**Interfaces:**
- Consumes: all documentation changes from Tasks 1–5.
- Produces: evidence that docs are internally consistent and runtime behavior remains unchanged.

- [ ] **Step 1: Verify all referenced paths exist**

Run this exact Python check from the repository root:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python - <<'PY'
from pathlib import Path
import re

files = [Path("README.md"), Path("AGENTS.md"), Path("CLAUDE.md"), Path("docs/README.md")]
text = "\n".join(path.read_text(encoding="utf-8") for path in files)
refs = set(re.findall(r"(?<![A-Za-z0-9_/.-])(docs/[A-Za-z0-9_./-]+\.md|README\.md|AGENTS\.md|CLAUDE\.md)", text))
missing = sorted(str(path) for raw in refs if not (path := Path(raw)).exists())
assert not missing, missing
print(f"checked {len(refs)} markdown references")
PY
```

- [ ] **Step 2: Verify CLI and collector entry points**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python main.py --help
/opt/anaconda3/envs/xhs-agent/bin/python -m metrics_collector --help
/opt/anaconda3/envs/xhs-agent/bin/python -m trend_collector --help
```

Expected: all three exit 0 and their documented subcommands appear.

- [ ] **Step 3: Run static and full test verification**

Run:

```bash
/opt/anaconda3/envs/xhs-agent/bin/python -m compileall -q src main.py metrics_collector trend_collector
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
git diff --check
git status --short
```

Expected: compileall exits 0; full suite has zero failures; only the two documented live-provider skips remain; diff check is clean; status is clean after the final documentation commit.

- [ ] **Step 4: Commit verification evidence**

Record the final test count and any known non-blocking warnings in the handoff message. Do not add generated databases, logs, browser profiles, or publish outputs to the commit.
