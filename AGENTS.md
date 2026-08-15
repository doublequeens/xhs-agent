# Repository Agent Instructions

## Project scope and product line

`xhs-agent` 生成美容护肤方向的小红书图文 carousel 和本地发布包。`beauty/skincare` 是当前账号正式主线；`wellness` 与 `healthy_lifestyle` 只是代码支持的扩展 domain。系统不会自动登录、上传或发布到小红书。

## Before changing code

先阅读与任务相关的当前文档和源代码：

- [文档总索引](docs/README.md)
- [当前工作流](docs/architecture/workflow.md)
- [编辑图文契约](docs/architecture/editorial-contracts.md)
- [持久化、素材与发布安全](docs/architecture/persistence-and-assets.md)
- `README.md`（使用、CLI 和输出）

涉及 domain、采集器或仓库协作时，继续阅读 `docs/domain-profiles.md`、对应 collector 手册和 `docs/agents/` 规则。先检查 `git status`，保护已有用户修改。

## Current architecture

生产图由 `src/graph.py` 构建，采用 `llm_scene_v3` 动态视觉生产路径。内容主链从 domain routing、选题、写作经过 R1/R2、标题、hashtag 到 assembler；assembler 之后进入动态视觉链：`content_atomizer → visual_director → asset_resolver → page_designer → design_plan_qa → generic_scene_renderer → render_qa → visual_critic → human_review → final_policy_guard → content_writer`。修订回路：`design_plan_qa`/`render_qa` 失败回 `design_reviser`；`visual_critic` 失败且修订轮 < 2 回 `design_reviser`，第 2 轮仍失败带 `visual_needs_attention` 进 Human Review；`design_reviser` 在 family/页序重排时经 `visual_route_override` 回 `visual_director`，否则回 `design_plan_qa`。`design_plan_qa` 和 `render_qa` 各有连续失败中断（`MAX_QA_FAILURES`/`MAX_RENDER_QA_FAILURES`，当前为 6 次，抛 `VisualProductionInterrupted`）。运行时只有这一条现代生产路径；`src/editorial_carousel/legacy.py` 是旧 v1/v2 checkpoint 到 v3 合同的唯一兼容迁移边界（丢弃旧视觉状态、标记 `llm_scene_v3`、在 assembler 后重新进入）。

视觉阶段的关键约束：一套 carousel 只用一个 `template_family`（六个 family 是参考视觉 DNA，不是固定页面模板）；页数 5–18 由 Visual Director 根据文案决定；图片内可见文字只能来自 `ContentAtomSet`，视觉阶段不得增删改写；图片不得自动加入 AI 标识、示意图标签或免责声明；AI 来源仅写入内部 manifest。Human Review 统一在所有硬 QA 之后进行一次；Final Guard 在其后执行，硬 QA 永远不允许强制放行，审美覆盖可由人工显式记录。

## Non-negotiable contracts

- 保持 v3 合同的 producer/consumer 和哈希绑定：`ContentAtomSet`（atomizer → director/designer/QA/publish）、`VisualDirectionPlan`（director → asset/page-designer/QA/render）、`AssetManifest`/`AssetResolutionResult`（resolver → designer/QA/render/publish）、`CarouselDesignPlan`（designer → QA/compiler/render/publish）、`DesignPlanQAResult`（design_plan_qa → render/publish）、`RenderManifest`（renderer → render_qa/critic/publish）、`RenderQAResult`（render_qa → critic/publish）、`VisualCritique`（critic → human_review/publish）、`ContentLock`（assembler → human_review/final_guard/publish；不再含 storyboards，绑定 `content_atom_set_sha256`）、`PublishAttestation`（publish：`workflow_version=llm_scene_v3`，哈希 10 个合同 + 每个 PNG）。
- 不恢复已删除的旧视觉 node/合同/renderer（`visual_strategy_planner`、`storyboard_generator`、`carousel_qa`、`editorial_carousel_renderer`、`VisualPlan`、`CarouselPayload`、`ResolvedVariant`、`modern_v2`、`recommended_frame_count`、固定六模板 HTML/CSS）；不让业务节点绕过 `legacy.py` 直接处理旧状态。旧名称只允许出现在历史 spec、checkpoint 迁移说明和断言其不存在的测试中。
- 不绕过 Design Plan QA、Render QA、Visual Critic、Human Review 或 Final Guard；硬 QA 失败必须走修订回路或中断，永远不允许强制放行。人工可见文字编辑必须清除全部 8 个视觉合同与 atoms，回 R2/assembler/content_atomizer 重新进入。
- 不修改 ContentLock 已锁定的事实、标题、步骤或可见文字来实现“视觉救援”；视觉阶段只能换行、分组、强调和按语义边界拆分分页。
- 外部素材必须通过 provider、许可、containment、no-follow、事务绑定和字节哈希检查后才能进入已批准 manifest；AI provenance 仅写入内部数据，绝不进入页面可见文字或 PNG。

## Commands and verification

从仓库根目录使用当前 Python 3.12 环境：

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python main.py --help
pytest -q
python -m compileall -q src main.py
git diff --check
```

默认测试离线，不调用真实素材 provider、Gemini 或 Chromium 远程能力。只有明确需要时才设置 `RUN_LIVE_ASSET_PROVIDER_TESTS=1`（Pexels/Unsplash）、`RUN_LIVE_VISUAL_AI_TESTS=1` 配合 `GEMINI_API_KEY`（结构化视觉与图像生成）运行 live smoke tests。修复行为时先添加能复现问题的回归测试；完成前必须重新运行与风险相称的聚焦测试和全套验证。

## State, assets, and outputs

- 不删除或重建 `checkpoints.sqlite`、`data/agent_runs.sqlite`、`data/xhs_memory.db`、`data/chroma` 来解决普通故障；中断任务用 `main.py --runs` 和 `--resume` 恢复。
- `outputs/publish/` 是验证后的本地发布包。不要手工覆盖 canonical JSON、ContentLock、manifest 或已生成图片，也不要把运行产物提交到 Git。
- `~/.xhs-agent/` 下的浏览器 profile、下载、诊断和日志属于本机状态，不提交。
- 外部素材事务失败时保留主异常、recovery journal 和清理证据；不得用清理异常掩盖原始失败。

## Git and safety rules

保护用户已有改动；不要使用破坏性 reset/checkout/clean 或删除状态文件，除非用户明确授权。不要提交密钥、cookie、私有路径、本机 profile、数据库或 outputs。未经用户明确授权不得 push、创建外部消息或合并分支。完成前以新鲜命令输出为证据，不要仅凭历史测试或计划声称通过。

## Documentation index

从 [docs/README.md](docs/README.md) 查找当前架构、domain/collector 手册、agents 协作规范和 spec/plan 状态。spec/plan 是设计和实施记录，不是自动待办；只有当前用户请求、issue 或明确 active plan 才定义工作范围。

## Issue tracker, triage, and domain docs

- GitHub Issues 使用 `doublequeens/xhs-agent`；外部 PR 不是 triage surface。操作见 [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)。
- canonical labels 为 `needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`，见 [docs/agents/triage-labels.md](docs/agents/triage-labels.md)。
- 单一 context 的 domain 文档规则见 [docs/agents/domain.md](docs/agents/domain.md)；按规则读取根目录 `CONTEXT.md`（若存在）和相关 `docs/adr/`。
