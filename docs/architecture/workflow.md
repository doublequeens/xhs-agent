# 当前生产工作流

## 定位和终点

项目的正式内容主线是美容护肤（`beauty` domain）。`wellness` 与 `healthy_lifestyle` 是代码支持的扩展 domain，不代表当前账号的同等定位。工作流生成经过审核的图文发布包并写入本地记忆；它不会自动发布到小红书。

## LangGraph 顺序

生产图由 `src/graph.py` 构建，主路径为：

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

其中 `decision_engine` 根据决策结果进入 R1 reflector 或 R2 compliance，检查通过后才到 hashtag。`carousel_qa` 和 `render_qa` 失败会回到 R1；R1/R2 的结果会回到 decision engine。Human Review 可以批准、编辑可见文字后要求 R2 复核，或要求重新渲染/重新做 render QA。Final Guard 发现策略风险时返回 Human Review，否则进入 `content_writer`。

## 审核回路

- R1（反思）处理选题、结构、视觉或确定性 QA 发现的问题。
- R2（合规）检查内容策略和风险；合规阻断不会绕过 R1/R2。
- Carousel QA 验证 storyboard、内容合同和视觉计划的一致性。
- Render QA 验证最终 PNG、尺寸、字体、页面和接触表。
- Human Review 是显式人工中断；只有批准或按现代 schema 验证的编辑才能继续。
- Final Guard 在人工审核之后再次执行最终策略检查，确保写入前没有未处理风险。

## 运行和恢复

`main.py` 使用 `data/agent_runs.sqlite` 展示可恢复任务，并以 `thread_id` 读取 `checkpoints.sqlite` 中的 LangGraph 状态。运行中断、等待审核或进程异常后，可以通过 `python main.py --resume` 选择任务，也可以用 run ID 或 thread ID 指定恢复。恢复时会对旧 checkpoint 做必要的 domain/editorial 合同迁移，然后从现代图路径继续。

`content_writer` 是图的终端节点。它在最终审核、合规、RenderManifest 和 publish package 均满足要求后写入结构化记忆和向量记忆；导出发布包由主程序在终端 checkpoint 验证后完成。

## 输出边界

终端导出会在 `outputs/publish/<date>-<domain>-<title>/` 下创建 PNG、publish copy、审计和救援 prompt 等发布产物。输出是供人工发布和复核的本地包，不包含对小红书平台的自动登录、上传或发布动作。

## 自适应六模板

视觉规划阶段运行自适应六模板工作流：根据 `NarrativePlan.narrative_form`（八种形式）和 `ContentContract` 在六个生产家族（`pink_red`、`deep_teal`、`soft_pink`、`coral_impact`、`green_catalog`、`white_quote`）中选择唯一家族，再按 `ContentContract.recommended_frame_count`（5–7）确定 frame plan 长度。页面数量是内容驱动，与手工 mockup 数量无关。

每个 `FramePlanItem` 携带 `allowed_density`（sparse/standard/dense）和 `page_archetype`，渲染器据此选择排版密度和组件布局；不会出现截断、省略号、隐藏文字或低于最小字号的情况。Emoji 作为 grapheme 与正文一起渲染，使用仓库固定字体（`Source Han Serif SC`、`Source Han Sans SC`、`Bodoni Moda`，emoji 走 `Noto Color Emoji`）。

当 `ContentContract.proof_mode=none` 时，`AssetManifest.items` 可以为空，对应纯文字 carousel；空 manifest 仍要经过 Carousel QA、Render QA 和 ContentLock 校验，渲染器只产出文字版页面。需要外部素材时，由 `asset_resolver` 按 `AssetRequirement` 解析并绑定来源、许可和哈希。

旧 v1 checkpoint 通过 `src/editorial_carousel/legacy.py` 迁移：迁移器把可识别的旧 storyboard strategy 翻译成现代 `narrative_form`、补齐 `NarrativePlan`、重建现代 `VisualPlan`，再从现代 storyboard seam 进入图，不会重新启用删除的固定卡片路径。
