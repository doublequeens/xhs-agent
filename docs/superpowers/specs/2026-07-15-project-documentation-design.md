# 项目文档体系设计

日期：2026-07-15  
状态：已确认

## 目标

为当前 `xhs-agent` 建立一套可以独立使用、彼此不冲突的仓库级文档，使第一次接触项目的人能够完成安装、运行、恢复和查看输出，也使编码 agent 能够在不破坏核心工作流约束的情况下修改代码。

本次重构仓库入口文档并治理现有 `docs/` 目录，不改变运行时行为、工作流节点、数据契约或发布产物。现有文档必须被明确标记为当前权威文档、历史设计/执行记录、已被替代，或删除；不允许继续以无状态的散落文件存在。

## 读者与语言

- 文档以中文为主；代码、命令、字段名和文件名保持原文。
- `README.md` 面向项目使用者和后续维护者。
- `AGENTS.md` 面向所有在仓库内工作的编码 agent，是仓库级 agent 规则的权威来源。
- `CLAUDE.md` 面向 Claude Code，作为 `AGENTS.md` 的轻量适配入口，不复制整套规则。

## 产品定位

文档必须区分“账号正式定位”和“代码技术能力”：

- 美容护肤是当前正式内容主线，推荐使用 `beauty` domain。
- `wellness` 与 `healthy_lifestyle` 在代码中可选，但只描述为技术上支持的扩展 domain，不将它们写成当前账号的同等正式定位。
- 项目生成的是经过选题、写作、合规、视觉规划、素材解析、确定性排版、人工审核和最终策略检查的小红书图文发布包，而不是自动发布机器人。

## 文档职责

### README.md

README 采用“先上手，再理解”的信息顺序：

1. 一句话项目介绍和当前定位。
2. 核心能力与明确边界。
3. 从 domain routing 到 content writer 的高层工作流。
4. 系统要求、Python 环境、依赖和 Playwright Chromium 安装。
5. 模型与外部服务环境变量。
6. 常用 CLI：新建任务、指定 domain/keyword/provider、查看任务、恢复任务。
7. 人工审核阶段的交互和失败恢复方式。
8. 发布目录结构及每种产物用途，包括 `images`、`publish-copy.txt`、审计 JSON、ContentLock 和 Codex 图像救援 prompt。
9. 测试命令、live provider 测试开关和常见问题。
10. 关键目录导航和相关工程文档链接。

README 中的所有命令、参数、默认值和路径必须来自当前实现。不得把规划中的功能写成已经存在的能力。

### AGENTS.md

AGENTS 是编码 agent 的权威操作手册，包含：

1. 项目目标、正式 domain 和非目标。
2. 开始工作前应阅读的文件。
3. 高层架构与关键契约：`VisualPlan`、`CarouselPayload`、`AssetManifest`、`RenderManifest`、ContentLock、Human Review、Final Guard。
4. 常用安装、运行、测试和静态检查命令。
5. 修改约束：保持现代单一路径、legacy 只允许存在于迁移适配器、不可绕过 QA/审核/最终策略检查、不可让人工编辑破坏 ContentLock 或现代 schema。
6. checkpoint、run registry、外部素材事务和发布目录的安全要求。
7. 测试规则：默认离线、live provider 测试显式启用、修复采用回归测试、完成前运行相称的验证。
8. Git 与工作区规则：保护用户修改，不擅自 push，不提交生成的发布产物或密钥。
9. 保留并扩充现有 Issue tracker、triage labels 和 domain docs 约定。

AGENTS 应具体到足以指导修改，但不复制 README 的用户教程。

### CLAUDE.md

CLAUDE 作为 Claude Code 入口，保持简短：

- 首先要求读取根目录 `AGENTS.md`，并声明其规则优先于 CLAUDE 中的摘要。
- 给出项目的一句话定位和默认验证命令。
- 提醒 Claude Code 使用现有 Python 环境、保护 SQLite/checkpoint/output 状态、不要擅自推送或重写用户文件。
- 指向 README、设计规格和 agent 工程文档。
- 不复制 Issue tracker、架构契约和完整测试矩阵，避免三份文件发生规则漂移。

### docs/README.md

新增 `docs/README.md` 作为文档总索引和状态目录。它负责：

- 指向当前系统架构、domain、采集器、协作规则、设计规格和实施计划。
- 区分“当前权威说明”“已实施设计”“历史实施计划”和“已被替代方案”。
- 标识当前正式产品定位、已经完成的主要能力以及是否存在正在执行的计划。
- 明确历史 plan/spec 只用于理解决策背景，不是自动待办清单；除非用户明确要求，否则 agent 不得看到未勾选项就直接继续执行。

`AGENTS.md` 只链接 `docs/README.md` 及少数必须直接读取的架构文档，不枚举每个历史 plan，避免入口文件随历史增长而膨胀。

## 现有 docs 治理

### 保留并更新为当前文档

- `docs/domain-profiles.md`：保留现有路径，改为中文主文档，准确区分美容护肤正式主线与另外两个技术扩展 domain。
- `docs/metrics-collector.md`：保留为指标采集器操作手册；当前测试直接验证该路径，不移动文件。
- `docs/trend-collector.md`：保留并补充认证依赖、手动运行、LaunchAgent 管理、日志、数据库和安全边界。
- `docs/agents/domain.md`：保留为 domain 文档消费规则；它不是 domain profile 业务说明。
- `docs/agents/issue-tracker.md`：保留 GitHub Issues 操作约定。
- `docs/agents/triage-labels.md`：保留 triage 标签映射。

### 新增当前架构文档

- `docs/architecture/workflow.md`：描述当前生产 LangGraph、循环审核路径、断点恢复入口和每个阶段的职责；不复制节点实现。
- `docs/architecture/editorial-contracts.md`：描述 `VisualPlan`、`CarouselPayload`、`AssetManifest`、`RenderManifest`、ContentLock、Human Review 与 Final Guard 的边界。
- `docs/architecture/persistence-and-assets.md`：描述 checkpoint、run registry、结构化/向量记忆、外部素材事务、发布目录和失败恢复原则，并吸收已完成 Task 8 临时计划中仍然有效的安全约束。

### 保留为有状态的设计与实施记录

以下主题仍对应当前能力，应保留其 spec/plan，并通过 `docs/README.md` 标记为“已实施”或“历史实施记录”：

- domain profile expansion
- Xiaohongshu metrics collector
- signal-driven topic generation
- beauty account content workflow
- run resume registry
- editorial carousel workflow
- project documentation design

保留并不表示 agent 每次都需要加载这些长文档。只有修改对应子系统或追溯设计原因时才读取。

### 删除已被替代或已完成的临时文档

- 删除 `docs/superpowers/specs/2026-07-12-local-text-card-rendering-design.md`。
- 删除 `docs/superpowers/plans/2026-07-12-local-text-card-rendering.md`。

固定六张纯文字卡路径已经从生产代码移除，当前 editorial carousel spec 已明确取代该方案；继续保留这两个文件会诱导 agent 恢复已删除的合同。Git 历史仍保留其追溯价值。

- 删除 `docs/superpowers/plans/2026-07-14-task8-final-review.md`。
- 删除 `docs/superpowers/plans/2026-07-14-task8-transaction-final-closure.md`。

这两个文件是已完成任务的临时审查闭环计划，不应继续作为项目计划出现。仍然有效的事务、信任边界和恢复约束必须先整理到 `docs/architecture/persistence-and-assets.md`，然后再删除原文件。

### 路径稳定性

除上述明确删除项外，本轮不移动现有操作手册或长篇 plan/spec。保持路径稳定可以避免测试、历史提交信息和外部书签失效；目录分类由 `docs/README.md` 的状态索引完成。

## 信息来源

文档事实以以下当前实现为准：

- CLI 与任务恢复：`main.py`、`src/run_registry.py`
- 工作流拓扑：`src/graph.py`
- domain：`src/domain/profiles.py`
- 模型供应商：`src/models/`
- 素材解析：`src/asset_resolver/`
- 视觉渲染：`src/rendering/editorial/`
- 发布产物：`src/publishing/artifacts.py`
- 测试配置：`pytest.ini`、`tests/`
- 工程协作：`docs/agents/`
- 当前文档索引：`docs/README.md`
- 当前架构：`docs/architecture/`

历史 plan/spec 可以提供设计背景，但 README 不应要求普通使用者阅读实现计划才能运行项目。

## 安全与准确性约束

- 不在文档中写入真实 API key、账号、cookie 或本地私人路径。
- 环境变量只写变量名和用途。
- 不承诺自动发布到小红书；当前交付终点是本地发布包和持久化内容记录。
- 不把 Pexels/Unsplash 网络访问写成测试默认行为。
- 不建议删除 `checkpoints.sqlite`、`data/agent_runs.sqlite` 或外部素材恢复记录来解决普通故障。
- 不把 Codex 内置图像救援流程描述成 agent 运行时自动调用的模型 API。

## 验收标准

- 三份文档职责清晰，没有大段重复内容或互相矛盾的命令。
- `docs/README.md` 收录所有保留文档，并为 plan/spec 标记用途和状态。
- `domain-profiles.md`、`metrics-collector.md`、`trend-collector.md` 都被纳入索引并与当前代码核对。
- 已被替代的 fixed-card 文档和已完成的 Task 8 临时闭环计划，在有效约束被当前架构文档吸收后删除。
- README 的 `main.py --help` 参数与当前 CLI 一致。
- 安装、运行、恢复、测试和输出路径可以从仓库根目录执行或定位。
- AGENTS 保留原有 GitHub Issues、triage labels、domain docs 规则，并补齐当前架构与修改约束。
- CLAUDE 明确以 AGENTS 为权威来源。
- 文档没有 `TBD`、`TODO`、占位符、密钥或不存在的链接。
- 文档变更不修改生产代码，完整测试仍通过。
