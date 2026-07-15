# 持久化、素材与发布安全

## 本地存储

- `checkpoints.sqlite`：只保存 LangGraph checkpoint 状态。run registry 通过 LangGraph API 读取状态，不能解析该数据库的内部表结构。
- `data/agent_runs.sqlite`：面向 CLI 的运行索引，以 `thread_id` 为唯一键记录 domain、选题、标题、最近节点和错误摘要。`running`、`interrupted`、`awaiting_review` 是可恢复状态；只有终端状态经过导出验证后才记录为完成。
- `data/xhs_memory.db`：结构化内容记忆，`content_writer` 在最终审核和合规检查通过后写入。
- `data/chroma`：与结构化内容对应的向量记忆，用于后续 domain-scoped retrieval；向量写入失败时必须执行补偿删除或保留明确恢复证据。
- `outputs/publish/<date>-<domain>-<title>/`：经过验证的发布包，包含有序图片、publish copy、审计信息和救援 prompt。所有文件必须留在 publish root 内；不要手工改写 canonical JSON 或 ContentLock。
- `~/.xhs-agent/`：浏览器 profile、下载文件、诊断数据和采集器日志。它属于本机运行状态，绝不能提交到仓库。

## 发布包边界

发布层从终端 checkpoint 验证 `publish_package`、VisualPlan、AssetManifest、RenderManifest、QA 结果和 ContentLock 后才导出。图片必须是 `outputs/publish` 下单一 package 的有序 PNG，manifest 中列出的 PNG 集合必须与目录实际内容一致。导出的本地文件供人工检查和发布，不会触发小红书上传。

## 外部素材生命周期

素材解析先在受控目录中创建 pending candidate 和元数据，再进入人工安全审核。任何 provider 素材在改变 catalog 或迁移为 approved 前，都必须验证 provider identity、URL/路径要求、目录 containment、no-follow 约束、事务绑定和字节哈希。审批记录要绑定 slot、run、素材指纹和安全决定，不能只凭文件名信任。

外部素材事务必须保留主异常；清理、回滚或 durability 确认失败时，要保留 recovery journal/backup 路径和可恢复证据，不能用清理异常覆盖最初失败原因。pending、rejected、approved 状态和 catalog review lock 共同构成素材信任边界。

## 故障处理

普通超时或人工审核暂停应通过 run registry 和 `--resume` 继续，不要删除 checkpoint、run registry 或素材恢复记录。遇到发布导出异常，先读取审计与 recovery 证据，再决定是否重试；不要直接覆盖已生成的 canonical 文件或把未审核外部素材复制进最终 images 目录。
