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

以下文件记录已经实施的设计或执行过程。它们不是未完成任务清单；是否有待办事项以当前明确的 issue、用户请求或 active plan 为准。

| 主题 | Spec | Plan | 状态 |
| --- | --- | --- | --- |
| Domain profiles | `docs/superpowers/specs/2026-07-02-domain-profile-expansion-design.md` | `docs/superpowers/plans/2026-07-02-domain-profile-expansion.md` | 已实施 |
| Metrics collector | `docs/superpowers/specs/2026-07-05-xhs-metrics-collector-design.md` | `docs/superpowers/plans/2026-07-05-xhs-metrics-collector.md` | 已实施 |
| Signal-driven topics | `docs/superpowers/specs/2026-07-07-signal-driven-topic-generation-design.md` | `docs/superpowers/plans/2026-07-07-signal-driven-topic-generation.md` | 已实施 |
| Beauty account workflow | `docs/superpowers/specs/2026-07-10-beauty-account-content-workflow-design.md` | — | 已实施 |
| Run resume registry | `docs/superpowers/specs/2026-07-13-run-resume-registry-design.md` | `docs/superpowers/plans/2026-07-13-run-resume-registry.md` | 已实施 |
| Editorial carousel | `docs/superpowers/specs/2026-07-13-editorial-carousel-workflow-design.md` | `docs/superpowers/plans/2026-07-14-editorial-carousel-workflow.md` | 已实施 |
| Project documentation | `docs/superpowers/specs/2026-07-15-project-documentation-design.md` | `docs/superpowers/plans/2026-07-15-project-documentation.md` | 当前任务 |
| Project documentation governance | — | `docs/superpowers/plans/2026-07-15-project-documentation-governance.md` | 历史实施记录 |

历史 spec/plan 用于理解设计原因；修改某个子系统时再读取对应记录。没有“当前 active plan”时，不得从历史 plan 的未勾选项推断待办。

## 协作规则

- Issue tracker、triage 标签和 domain 文档规则见 `docs/agents/issue-tracker.md`、`docs/agents/triage-labels.md`、`docs/agents/domain.md`。
- 当前工作流和数据契约以 `docs/architecture/` 下三份文档及源代码为准。
