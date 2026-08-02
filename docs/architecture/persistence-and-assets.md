# 持久化、素材与发布安全

## 本地存储

- `checkpoints.sqlite`：只保存 LangGraph checkpoint 状态。run registry 通过 LangGraph API 读取状态，不能解析该数据库的内部表结构。
- `data/agent_runs.sqlite`：面向 CLI 的运行索引，以 `thread_id` 为唯一键记录 domain、选题、标题、最近节点和错误摘要。`running`、`interrupted`、`awaiting_review` 是可恢复状态；只有终端状态经过导出验证后才记录为完成。
- `data/xhs_memory.db`：结构化内容记忆，`content_writer` 在最终审核和合规检查通过后写入；动态视觉合同的元数据从 v3 合同派生。
- `data/chroma`：与结构化内容对应的向量记忆，用于后续 domain-scoped retrieval；向量写入失败时必须执行补偿删除或保留明确恢复证据。
- `data/asset_transactions/<run_id>/`：素材解析的事务目录，按 run 派生路径，存放 pending candidate、元数据和 recovery evidence；run ID 来自 `topic_generation_trace.run_id`（或 publish package 身份的稳定哈希）。
- `outputs/publish/<date>-<domain>-<title>/`：经过验证的本地发布包。所有文件必须留在 publish root 内；不要手工改写 canonical JSON、ContentLock、manifest 或已生成图片。
- `~/.xhs-agent/`：浏览器 profile、下载文件、诊断数据和采集器日志。它属于本机运行状态，绝不能提交到仓库。

## 发布包边界（llm_scene_v3）

发布层（`src/publishing/artifacts.py`）从终端 `StateSnapshot` 重新验证 Final Guard、读取已持久化的 v3 合同、重算每个 PNG 字节哈希后，才导出本地发布包。canonical 包内容：

```text
outputs/publish/<date>-<domain>-<title>/
├── content_atom_set.json
├── visual_direction_plan.json
├── asset_manifest.json
├── carousel_design_plan.json
├── design_plan_qa.json
├── render_manifest.json
├── render_qa.json
├── visual_critique.json
├── content_lock.json
├── final_policy_attestation.json
├── pages/<NN>-<page_id>.png ...
├── contact-sheet.png
└── publish-attestation.json
```

`publish-attestation.json` 的 `workflow_version=llm_scene_v3`，记录上述 9 个合同 + `final_policy_attestation` 的 canonical sha256，以及每个 PNG（`pages/*.png` + `contact-sheet.png`）的字节 sha256；attestation 本身作为单独文件写出，不参与它所携带的哈希（无循环依赖）。导出采用 staging + 原子提升：bundle 先写入同级 staging 目录，再原子重命名到 canonical 路径，**绝不手工覆盖已存在的 canonical 包**。包内不再含 `storyboards`/`visual_plan`/`carousel_qa` 或固定模板 variant 字段。AI provenance 只存在于 `AssetManifestItem.internal_provenance`，绝不进入页面可见文字或 PNG。导出的本地文件供人工检查和发布，不会触发小红书上传。

## 外部素材生命周期

素材解析（`src/asset_resolver/`）按 `AssetDirective` 执行允许的来源策略（`licensed_search`/`llm_generation`/`search_then_generate`/`generate_then_search`/`none`），先在受控事务目录中创建 pending candidate 和元数据，再进入安全审核。任何 provider 素材在改变 catalog 或迁移为 approved 前，都必须验证 provider identity、URL/路径要求、目录 containment、no-follow 约束、事务绑定和字节哈希。审批记录要绑定 directive/page/run/素材指纹和安全决定，不能只凭文件名信任。搜索 provider 是 Pexels/Unsplash；图片生成走 Gemini `gemini-3.1-flash-image`（Developer API `GEMINI_API_KEY`、`GEMINI_VISUAL_MODEL`）。

外部素材事务必须保留主异常；清理、回滚或 durability 确认失败时，要保留 recovery journal/backup 路径和可恢复证据，不能用清理异常覆盖最初失败原因。pending/rejected/approved 状态共同构成素材信任边界：只有 `security_status=approved` 的素材能进入 renderer，`human_decision` 在整套 Human Review 前保持 pending。required 素材全部失败时中断任务并保留 recovery evidence；optional 全部失败时回 Design Reviser 生成无图版本。

## 故障处理

普通超时或人工审核暂停应通过 run registry 和 `--resume` 继续，不要删除 checkpoint、run registry 或素材恢复记录。视觉阶段的 `VisualProductionInterrupted`（Design Plan QA 或 Render QA 3-strike）也会 checkpoint，允许 `--resume`。遇到发布导出异常，先读取审计与 recovery 证据，再决定是否重试；不要直接覆盖已生成的 canonical 文件或把未审核外部素材复制进最终 images 目录。
