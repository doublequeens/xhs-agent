# Agent 运行恢复注册表设计

当前状态：已实施；本文保留作设计记录。

## 目标

让 CLI 在模型请求 timeout、进程异常退出或人工中断后，能够识别并恢复已有 LangGraph checkpoint，而无需用户记住随机 `thread_id` 或修改源码。多个未完成任务并存时，CLI 必须展示可识别的业务摘要并由用户选择，不能自动猜测要恢复哪一条。

## 非目标

- 不更改 LangGraph checkpoint 的数据格式或直接依赖其内部 SQLite 表结构。
- 不自动重试模型请求；本设计只保证异常后可恢复。模型级有限重试可作为后续独立工作。
- 不删除历史 checkpoint 或已完成任务。
- 不改变现有内容生成、人工审核、文字卡渲染或发布导出逻辑。

## 决策

新增独立 SQLite 注册表 `data/agent_runs.sqlite`。LangGraph 继续使用 `checkpoints.sqlite` 保存图状态；注册表只保存面向 CLI 的会话索引和摘要。两者通过 `thread_id` 关联。

选择独立数据库而不是解析 `checkpoints.sqlite`，因为 LangGraph checkpoint 表属于第三方实现细节，无法稳定提供关键词、标题、最后节点和错误摘要等用户可识别信息。

## 数据模型

注册表包含一张 `agent_runs` 表：

| 列 | 类型 | 规则 |
| --- | --- | --- |
| `run_id` | INTEGER | 自增主键，供用户在列表中选择 |
| `thread_id` | TEXT | 唯一、非空，对应 LangGraph 配置 |
| `status` | TEXT | `running`、`interrupted`、`awaiting_review`、`completed` 之一 |
| `focus_keyword` | TEXT | 新建任务时记录，可为空 |
| `domain` | TEXT | 可为空；领域确认后更新 |
| `subdomain` | TEXT | 可为空；领域确认后更新 |
| `topic_summary` | TEXT | 候选/选定主题出现后更新，可为空 |
| `title` | TEXT | 最终标题出现后更新，可为空 |
| `last_node` | TEXT | 最近完成或等待的图节点，可为空 |
| `error_summary` | TEXT | 异常类型与已截断消息；成功运行时为空 |
| `created_at` | TEXT | UTC ISO-8601，创建时写入 |
| `updated_at` | TEXT | UTC ISO-8601，每次状态或摘要变更时写入 |

`thread_id` 建唯一索引，`status, updated_at DESC` 建查询索引。数据库连接启用 `busy_timeout` 和 WAL journal mode；每次写入使用短事务。

## CLI 合同

新增以下参数：

```text
--new                 强制创建新任务
--resume [RUN]        不带值时列出可恢复任务；带 run_id 或完整 thread_id 时直接恢复
--runs                展示最近 20 条任务后退出
```

保留现有 `--thread-id` 参数，作为完整 checkpoint ID 的兼容入口。`--new`、`--resume` 与 `--thread-id` 互斥。

### 无参数启动

`python main.py` 的行为：

1. 查询 `status IN ('running', 'interrupted', 'awaiting_review')` 的任务。
2. 没有可恢复任务：创建新 `thread_id` 与 `running` 注册记录。
3. 有一个或多个可恢复任务：显示编号列表并等待输入。
4. 用户输入 `1`、`2` 等编号：恢复对应任务。
5. 用户输入 `n`：创建新任务。
6. 用户输入 `q`：不执行图，正常退出。

即使只有一条可恢复任务，也必须显示并让用户确认；不会自动恢复。

### 列表显示

每条可恢复任务至少显示：

```text
[12] 2026-07-13 14:32 ｜已中断｜断在：TITLE_RANKER
     主题词：通勤防晒
     当前选题：防晒后底妆卡粉怎么办
     原因：TimeoutError: request timed out
     ID：xhs_conversation_20260713T0632...
```

优先显示 `title`，其次 `topic_summary`，再其次 `focus_keyword`。完整 `thread_id` 只在 `--runs --verbose` 或显式恢复失败提示中显示。

## 生命周期与状态迁移

```text
new/resume -> running
running + node success -> running (更新 last_node 与摘要)
running + human-review interrupt -> awaiting_review
awaiting_review + resume -> running
running/awaiting_review + uncaught Exception -> interrupted
running + terminal final-policy-clean export -> completed
```

每个 `graph.stream()` 输出的节点都更新 `last_node`。从状态中提取可用摘要：优先 `publish_package.title` / `publish_package.topic`，其次 `trends[0].topic`，并更新领域与子领域。

当 `main()` 捕获异常时，若当前任务已登记，必须写入 `interrupted` 与 `f"{type(error).__name__}: {message[:240]}"`，然后保留原有非零退出行为。Timeout 因此不会丢失已完成节点的 LangGraph checkpoint。

当图完整结束后，仅在 `export_completed_publish_package()` 返回成功时标记为 `completed`。若最终策略守门把流程送回人工审核，状态保持 `awaiting_review`，不得导出或标记完成。

## 旧任务兼容

- `--thread-id <id>` 继续直接读取现有 checkpoint。
- 若该 `thread_id` 不在注册表，CLI 从 checkpoint 当前状态提取摘要并 upsert 一条 `running` 记录；仅当后续 `export_completed_publish_package()` 成功时才更新为 `completed`。
- 找不到 checkpoint 时保留当前“新任务”行为；不得创建一条虚假的 completed 记录。
- registry 缺失、损坏或无法打开时，CLI 失败并说明是本地运行注册表错误；不得悄悄创建随机 thread ID 继续运行。

## 模块边界

### `src/run_registry.py`

仅负责 SQLite schema 初始化、CRUD、状态枚举、可恢复任务查询与格式化所需的 `AgentRun` 数据模型。它不了解 LangGraph、CLI 输入或业务内容。

### `main.py`

仅负责解析新 CLI 参数、选择/创建 run、从图输出提取摘要、调用 registry 生命周期更新，以及在异常/终态更新状态。它仍负责构建 LangGraph config 与交互输入。

### 测试

- registry 单元测试：schema、upsert、状态过滤、排序、错误摘要截断、thread ID 唯一性。
- CLI 测试：无可恢复任务新建、有多个任务选择、`n` 新建、`q` 退出、`--resume` 按 run ID/完整 thread ID 恢复、互斥参数、`--runs` 不启动图。
- 生命周期测试：节点成功更新摘要、异常标记 interrupted、审核等待状态、最终导出成功后才完成。
- 兼容测试：未登记的旧 `--thread-id` 从 checkpoint 回填记录。

## 验收标准

用户在模型 timeout 后再次运行 `python main.py`，会看到包含主题、标题/选题、最后节点、错误摘要和更新时间的恢复列表；选择对应编号后，使用原 `thread_id` 恢复 LangGraph checkpoint。用户始终可以用 `--new` 开新任务，且没有任何任务会在最终策略守门通过前被标记为 completed 或导出为最终发布包。
