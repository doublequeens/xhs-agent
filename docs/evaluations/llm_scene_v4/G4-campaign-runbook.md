# G4 Shadow 盲评战役运行手册

> 状态：待执行。本手册是 G4 门的唯一操作规程；战役产物（图片、模型 payload、盲评原始记录）
> 一律不入库，只有人工复审后的脱敏聚合报告才提交到本目录。
> 预声明阈值（调用方不可放宽）：`tests/fixtures/llm_scene_v4/quality_manifest.json` 的 `campaign` 节
> —— ≥10 个互异 beauty/skincare 主题、≥75 页、v4 better-or-equal ≥0.80、
> 每候选 ≤14 次视觉模型尝试、≤2 轮审美修订、单请求 ≤60000ms、零 critical 人工回归。

## 0. 前置条件

1. **人工批准**：战役消耗真实 Gemini/Pexels 配额，开始前需项目所有者明确批准本次运行。
2. **环境**：Python 3.12 环境已 `pip install -r requirements.txt` 并 `playwright install chromium`；
   shell 已加载 `GEMINI_API_KEY`（视觉链必需）、`PEXELS_API_KEY`/`UNSPLASH_ACCESS_KEY`（如该主题需要外部素材）。
3. **基线绿**：`pytest -q` 全套离线通过（当前基线 `2172 passed, 3 skipped`）。
4. **工作目录**：在 worktree 根目录操作；准备战役工作区（不入库）：
   ```bash
   export CAMPAIGN=<日期-批次号>          # 例 2026-08-28-run1
   mkdir -p outputs/campaign/$CAMPAIGN/{blind,decisions,raw}
   ```
5. **语料完整性**：`python -c "from src.evaluation import load_quality_manifest; from pathlib import Path; load_quality_manifest(Path('tests/fixtures/llm_scene_v4/quality_manifest.json'))"` 通过。

## 1. 准备 10 个 v3 源 run

每个主题需要一个**已完成**的 v3 run 作为 shadow 源（`--shadow-v4-from` 只读其 assembler 副本）。

```bash
# 主题清单（互异、均为 beauty/skincare）预先登记到 outputs/campaign/$CAMPAIGN/topics.txt，每行：
# <topic_id>\t<focus_keyword>
# 例：t01  夏季防晒
```

对每个主题运行 v3 生产直到完成（可分多次 `--resume`）：

```bash
python main.py --new --domain beauty --subdomain skincare \
  --focus_keyword "<focus_keyword>" --provider glm
# 记录打印的 run 编号/完整 thread ID 到 topics.txt 行尾
```

已有符合条件的完成态 v3 run 可直接复用（`--runs` 查询），无需重跑。

## 2. 派生并跑完 v4 shadow run（每主题一次）

```bash
python main.py --shadow-v4-from <v3_run_id>
```

该命令创建链接的 v4 shadow run 并进入 v4 链。到达 Human Review 中断（`WAITING_HUMAN`）后：

```bash
python main.py --review-show <new_thread_id>          # 打开 file:// review/index.html 人工查看
python main.py --review-submit <new_thread_id> --review-intent intent.json   # 提交决定
python main.py --resume <new_thread_id>
```

- intent.json 由战役协议规定统一动作：**APPROVE**（Q4 通过时）或 **AESTHETIC_OVERRIDE**（仅当审核者
  接受该页审美缺陷且给出 ≥8 字实质理由）。**禁止**在本战役中使用 REQUEST_REVISION /
  REJECT_OR_REPLACE_ASSET / VISIBLE_COPY_EDIT——它们会改变可比性；若发生，该主题作废重跑。
- run 以 `SHADOW_ARTIFACT_WRITER` 终端结束；bundle 落在 `outputs/shadow/<date>-shadow-<run>-<rev>/`。
- 记录每个 shadow run 的：thread ID、bundle 路径、`--review-verify` 输出、
  revision_history 长度（`data/agent_runs.sqlite` 的 checkpoint state）。

**作废与重试**：v4 图内 `VisualExecutionInterrupted`（候选耗尽）计为该主题失败一次；允许换新候选
重跑（`--shadow-v4-from` 同一源），失败详情记入 raw/。同一主题最多 2 次重跑。

## 3. 收集预算证据（attempts / latency / 修订轮）

```bash
cp data/agent_runs.sqlite outputs/campaign/$CAMPAIGN/raw/agent_runs.sqlite.bak
```

从 attempt ledger 汇总每个 shadow run 的：总尝试数（≤14/候选）、最大单请求时长（≤60000ms）、
审美修订轮数（revision_history 中 AESTHETIC 层事件数，≤2）。把每 run 一行的
`attempts,max_request_ms,aesthetic_revisions` 记入 `raw/budget.csv`。

## 4. 组装盲评包（身份封存）

对每个主题：v3 侧 = 源 run 发布包的 `pages/*.png` + `contact-sheet.png`；v4 侧 = shadow bundle 的页面。
用评估工具组装（在仓库根目录执行）：

```bash
python - <<'PY'
from pathlib import Path
from src.evaluation import VariantBundle, VariantPage, build_blind_report, compose_contact_sheets

campaign = Path("outputs/campaign") / __import__("os").environ["CAMPAIGN"]
index = []
# 逐主题填入：v3_pages/v4_pages 为 VariantPage 元组（hard_qa_passed 用各自 Q3/Q4 结论）
# report = build_blind_report(v3_bundle, v4_bundle, seed="<topic_id>")
# compose_contact_sheets(report, campaign / "blind" / "<topic_id>" / "sheets")
# 写 blind-payload.json（公开）与 identity.private.json（封存， scoring 前不得打开）
PY
```

规则：
- `seed` 固定为主题 ID（可复现、可审计）。
- `identity.private.json` 统一放 `raw/identity/`（评审者无权限目录）；`blind/` 下只放 payload 与 sheets。
- payload 不得含版本号、主题、路径——工具已保证，组装后再抽查一次：
  `grep -l "llm_scene" outputs/campaign/$CAMPAIGN/blind/ -r` 必须无输出。

## 5. 盲评会话（人工）

1. 评审者只获得 `blind/<topic>/sheets/*.png` 与 `blind-payload.json`。
2. 每张 sheet 记录一个判定：`A` 更好 / `B` 更好 / `equal`，以及（可选）一句理由；
   同时标注任何一侧是否存在"不可发布"缺陷页。
3. 判定写入 `decisions/<topic>.json`：`{"sheet-01": "A", "sheet-02": "equal", ...}`；
   不可发布缺陷记 `{"sheet-NN": {"side": "A|B", "issue": "..."}}`。
4. **全部判定提交后才解锁** `raw/identity/`，据此计算每主题的 v4-better-or-equal 计数。

通过线：全部 sheet 的 better-or-equal 比例 ≥ 0.80（equal 计入分子）；
**零 critical 回归** = 不存在任何"v3 侧可发布、v4 侧被评为不可发布"的页面。

## 6. Critic 校准（质量语料）

对冻结语料（`tests/fixtures/llm_scene_v4/`）运行两次 v4 critic 判定（两次独立调用，体现重复稳定性），
把每页 pass/fail 组装为 runs，然后：

```bash
python - <<'PY'
import json
from pathlib import Path
from src.evaluation import evaluate_calibration, load_quality_manifest
manifest = load_quality_manifest(Path("tests/fixtures/llm_scene_v4/quality_manifest.json"))
runs = [json.loads(p.read_text()) for p in sorted(Path("outputs/campaign").glob("*/raw/critic_runs/*.json"))]
print(evaluate_calibration(manifest, runs))
PY
```

要求：`gate_passed=True`（正面封面全过、负面不全过、零 critical、决策稳定）。

## 7. 聚合发布门

```bash
python - <<'PY'
from pathlib import Path
from src.evaluation import evaluate_release_gate, load_quality_manifest
# 汇总实际观测值：
#   topics=盲评主题数, pages=全部 v4 页数, better_or_equal_ratio=第5步比例
#   max_attempts_per_candidate / max_request_ms / max_aesthetic_revisions = budget.csv 最大值
result = evaluate_release_gate(
    load_quality_manifest(Path("tests/fixtures/llm_scene_v4/quality_manifest.json")),
    runs,  # 第6步的 critic runs
    better_or_equal_ratio=..., topics=..., pages=...,
    max_attempts_per_candidate=..., max_request_ms=..., max_aesthetic_revisions=...,
)
print(result.gate_passed, result.reasons)
PY
```

`gate_passed=False` 时**不得**进入第 8 步；失败原因与补救（修复代码 / 扩大语料重跑）记入 raw/。

## 8. 脱敏聚合报告与人工批准

写 `docs/evaluations/llm_scene_v4/<YYYY-MM-DD>-shadow-evaluation.md`，内容只含：

- 战役元数据（批次、日期、主题数、页数、评审者角色，不含主题明文清单——用 topic ID）
- 预声明阈值 vs 观测值表（第 5/6/7 步数字）
- 校准与发布门的 `gate_passed` 及 reasons
- 每 gate（G0–G4）的证据链接（progress.md 相应行 / 测试命令）
- 结论建议（是否建议 cutover）

**删除** `outputs/campaign/` 与 `outputs/shadow/` 战役产物前先确认报告数字已固化；
原始数据如需留存，移到仓库外的归档位置。报告经人工复审后才 `git add` 提交。

## 9. G5 cutover（报告批准后的独立动作）

1. 人工批准报告 → 修改默认选择器（`workflow_selection.select_workflow_context` 的
   `requested_version or "llm_scene_v3"` 默认值 → `llm_scene_v4`）+ 同步五份 canonical 文档的默认声明。
2. 回滚 = 同一处改回；已存在的 v4 checkpoint 永远用 v4 图恢复，无需迁移。

## 附：常见故障

| 症状 | 处置 |
| --- | --- |
| review-submit 报 "decision already exists" | 该 revision 已有终局决定；换新候选（`--shadow-v4-from` 重派生） |
| resume 后 critic 立即 `VisualExecutionInterrupted` | 修订预算已在 checkpoint 持久——这是预期行为，非 bug；按第 2 步作废重跑 |
| `--shadow-v4-from` 报源缺 assembler 副本 | 源 run 未完成；先跑完 v3 |
| 盲评包 grep 出现 `llm_scene` | 组装错误，立即销毁该包重组装；不得手工删除字段了事 |
