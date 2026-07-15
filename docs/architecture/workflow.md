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
