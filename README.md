# xhs-agent

`xhs-agent` 是一个面向小红书图文帖的内容生产工作流。它围绕美容护肤人群完成选题、证据整理、写作、合规检查、视觉规划、素材解析、确定性排版、人工审核和最终策略检查，最后生成一个可供人工发布的本地 editorial carousel 发布包。

当前账号正式定位是 `beauty/skincare`。代码也支持 `wellness` 和 `healthy_lifestyle`，但它们只是技术上的扩展 domain，不是当前账号的同等内容主线。项目不会自动登录、上传或发布到小红书。

## 能力与边界

- 根据 domain、subdomain 和 focus keyword 生成面向明确人群的内容选题。
- 通过记忆和可选证据检索减少重复，执行内容与合规策略检查。
- 生成结构化 `VisualPlan`、`CarouselPayload`，解析素材并绑定来源、许可和哈希。
- 用现代 editorial renderer 输出 5–7 张 1080×1440 PNG 和 contact sheet。
- 自适应选择 6 个生产 template family 之一：根据 8 种 narrative form、density、content job 和 proof mode 评分，页面数量由 `ContentContract.recommended_frame_count` 驱动，与手工 mockup 数量无关。
- 在 Human Review 暂停，允许人工审核或按现代 schema 编辑可见文字。
- 运行 Final Guard，导出 `publish-copy.txt`、审计 JSON 和 Codex 图像救援 prompt。
- 通过 checkpoint 与 run registry 支持超时或进程中断后的恢复。

图像救援 prompt 是交付给人工使用的本地文本；它不会在 agent 运行时调用图像模型 API，也不会改变 ContentLock 中的题目、事实、步骤或可见文字。

## 安装

在 macOS 或兼容的 Python 3.12 环境中执行：

```bash
git clone <repository-url>
cd xhs-agent
/opt/anaconda3/envs/xhs-agent/bin/python -m pip install -r requirements.txt
/opt/anaconda3/envs/xhs-agent/bin/python -m playwright install chromium
cp .env.example .env
set -a
source .env
set +a
```

上面的 Python 可执行文件路径是示例环境路径；也可以先激活自己的 Python 3.12 环境，再将命令中的解释器替换为该环境的 `python`。项目运行时读取 shell 环境变量，不会自动加载 `.env`，因此每个新 shell 都要重新执行 `set -a; source .env; set +a`，或逐项 `export`。不要把 `.env` 提交到 Git。

### 环境变量

根据所选模型和功能，在 `.env` 后通过上面的 `source` 步骤加载，或直接在 shell 中设置相应变量。文档只列变量名，不包含任何值：

| 变量 | 用途 |
| --- | --- |
| `ZHIPUAI_API_KEY` | `glm` 默认模型 provider |
| `GEMINI_API_KEY` | `gemini` provider |
| `DEEPSEEK_API_KEY` | `deepseek` provider |
| `TAVILY_API_KEY` | 需要证据检索的主题 |
| `PEXELS_API_KEY` | 外部素材解析的 Pexels provider |
| `UNSPLASH_ACCESS_KEY` | 外部素材解析的 Unsplash provider |
| `RUN_LIVE_ASSET_PROVIDER_TESTS` | 设为 `1` 才启用真实素材 API 测试；默认关闭 |

## 运行 Agent

先查看完整参数：

```bash
python main.py --help
```

创建一个新的美容护肤任务：

```bash
python main.py --new --domain beauty --subdomain skincare --focus_keyword "夏季防晒" --provider glm
```

查看最近任务。默认显示最新 20 条，可恢复任务会显示业务摘要、断点节点和短 ID；需要复制完整 thread ID 时使用 `--verbose`：

```bash
python main.py --runs
python main.py --runs --verbose
```

恢复任务可以传 run ID 或完整 thread ID：

```bash
python main.py --resume <run_id-or-thread_id>
python main.py --thread-id <thread_id>
```

如果不传 `--new`、`--resume` 或 `--thread-id`，CLI 会在有可恢复任务时显示列表并要求选择；没有可恢复任务时会创建新任务。`--resume` 不带值也会进入同一选择流程。`--topic_num` 控制主题信号数量，默认值为 `10`；`--provider` 支持 `glm`、`gemini`、`deepseek`。

## 工作流与人工审核

生产路径从 domain routing、记忆和趋势信号开始，经过选题、角度、写作、标题、R1/R2 检查、视觉计划、storyboard、素材解析、Carousel QA、确定性渲染和 Render QA，然后进入 Human Review、Final Guard 和 `content_writer`。详细节点和回路见：

- [当前工作流](docs/architecture/workflow.md)
- [编辑图文契约](docs/architecture/editorial-contracts.md)
- [持久化、素材与发布安全](docs/architecture/persistence-and-assets.md)

Human Review 是显式中断。终端会打印发布包、风险上下文和待审核素材；输入 `yes` 才能继续，输入 `edit` 可粘贴完整 JSON 修改，输入 `no` 会记录反馈并保持审核流程。可见文字编辑会重新经过现代 schema、R2 和必要的重新渲染/Render QA。Final Guard 仍会在人工审核之后再次检查。

## 恢复中断任务

LangGraph 状态保存在 `checkpoints.sqlite`，CLI 友好的任务索引保存在 `data/agent_runs.sqlite`。发生 request timeout、终端中断或人工审核暂停时，不要删除这些文件；重新运行 `main.py`，用 `--runs` 选择任务，或直接使用 `--resume <run_id-or-thread_id>`。恢复逻辑会迁移可识别的旧 checkpoint 到现代合同，再从现代路径继续。

## 发布产物

验证通过后，发布目录形状如下（目录名中的日期、domain 和标题由实际任务生成）：

```text
outputs/publish/<date>-<domain>-<title>/
├── images/01-*.png ...
├── publish-copy.txt
├── codex-image-regeneration-prompt.txt
├── <title>.json
└── .publish-artifacts.version
```

- `images/`：按 RenderManifest 顺序排列的 5–7 张 1080×1440 PNG，以及 `contact-sheet.png`。
- `publish-copy.txt`：由 ContentLock 生成的标题、正文和 hashtags，可复制到小红书编辑器。
- `<title>.json`：包含 VisualPlan、AssetManifest、RenderManifest、QA 结果、ContentLock 和发布 attestation 的审计快照。
- `.publish-artifacts.version`：发布包版本标记；同一目录的重复导出受锁和 generation 保护。
- `codex-image-regeneration-prompt.txt`：基于当前锁定选题和 storyboard 的人工视觉救援 prompt。若对 PNG 不满意，保留原始 `images/`，再将该 prompt 交给 Codex 重新生成视觉套图；这不是 workflow 自动调用的 API。

不要手工修改 canonical JSON、ContentLock、manifest 或已验证图片后声称它们仍然通过审核。需要改变内容时，应从 Human Review 或重新运行工作流开始。

## 测试与质量检查

默认测试不访问真实模型、Pexels、Unsplash 或小红书网络服务：

```bash
pytest -q
```

常用的聚焦测试：

```bash
pytest -q tests/metrics_collector/test_launchd.py tests/trend_collector/test_trend_launchd.py
pytest -q tests/integration/test_editorial_carousel_workflow.py
pytest -q tests/integration/test_adaptive_six_template_workflow.py
```

只有在明确需要验证官方素材 provider 时才启用 live 测试：

```bash
RUN_LIVE_ASSET_PROVIDER_TESTS=1 pytest -q tests/asset_resolver/test_live_providers.py
```

live 测试会消耗外部服务配额并依赖有效 API key，平时不要开启。

## 采集器

指标采集器和趋势采集器是独立的 creator-center 辅助工具，不会发布内容：

- [指标采集器操作手册](docs/metrics-collector.md)：手动认证、22:00 LaunchAgent、workbook 诊断和数据库核对。
- [趋势信号采集器操作手册](docs/trend-collector.md)：22:30 LaunchAgent、趋势 surface 边界和日志。
- [Domain 与内容策略](docs/domain-profiles.md)：domain、风险和旧数据迁移。

## 常见问题

### 请求超时后如何继续？

先确认 `checkpoints.sqlite` 和 `data/agent_runs.sqlite` 仍在原位置，然后运行 `python main.py --runs`。按选题和“断在”节点选择任务，或使用其 run ID/thread ID 执行 `--resume`。不要手动新建一个相同标题的任务来替代原 checkpoint。

### 模型 key 错误怎么办？

检查 `.env` 是否包含与 `--provider` 对应的变量名，并确认当前 shell 已加载 `.env`。`glm` 使用 `ZHIPUAI_API_KEY`，`gemini` 使用 `GEMINI_API_KEY`，`deepseek` 使用 `DEEPSEEK_API_KEY`。不要把 key 粘贴到 issue、日志或代码中。

### Playwright 无法启动？

确认已安装依赖和 Chromium：

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

采集器另要求本机安装 **Google Chrome**，并使用 `~/.xhs-agent/browser-profile` 保存手动登录状态；详细步骤见采集器手册。

## 项目导航

- [文档总索引](docs/README.md)
- [Agent 编码规则](AGENTS.md)
- [Claude Code 入口](CLAUDE.md)
- [当前 workflow](docs/architecture/workflow.md)
- [当前 editorial contracts](docs/architecture/editorial-contracts.md)
- [持久化与素材安全](docs/architecture/persistence-and-assets.md)
- `src/graph.py`：LangGraph 拓扑
- `src/schemas/`：现代内容、视觉、素材、渲染和 ContentLock 合同
- `src/rendering/editorial/`：确定性 editorial renderer
- `src/asset_resolver/`：素材解析与安全生命周期
- `src/publishing/`：发布包验证和导出
- `tests/`：离线单元、集成和安全回归测试

设计规格和执行计划集中在 `docs/superpowers/specs/` 与 `docs/superpowers/plans/`，其状态和阅读规则见 [文档总索引](docs/README.md)。历史计划用于解释设计背景，不会自动变成当前待办。
