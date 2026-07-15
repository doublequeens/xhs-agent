# 项目文档体系设计

日期：2026-07-15  
状态：已确认

## 目标

为当前 `xhs-agent` 建立一套可以独立使用、彼此不冲突的仓库级文档，使第一次接触项目的人能够完成安装、运行、恢复和查看输出，也使编码 agent 能够在不破坏核心工作流约束的情况下修改代码。

本次只重构仓库文档，不改变运行时行为、工作流节点、数据契约或发布产物。

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
- README 的 `main.py --help` 参数与当前 CLI 一致。
- 安装、运行、恢复、测试和输出路径可以从仓库根目录执行或定位。
- AGENTS 保留原有 GitHub Issues、triage labels、domain docs 规则，并补齐当前架构与修改约束。
- CLAUDE 明确以 AGENTS 为权威来源。
- 文档没有 `TBD`、`TODO`、占位符、密钥或不存在的链接。
- 文档变更不修改生产代码，完整测试仍通过。
