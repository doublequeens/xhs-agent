# 当前生产工作流

## 定位和终点

项目的正式内容主线是美容护肤（`beauty` domain）。`wellness` 与 `healthy_lifestyle` 是代码支持的扩展 domain，不代表当前账号的同等定位。工作流生成经过审核的图文发布包并写入本地记忆；它不会自动发布到小红书。

## LangGraph 顺序

生产图由 `src/graph.py` 构建，采用 `llm_scene_v3` 动态视觉生产架构。主路径为：

```text
domain_router -> domain_confirmation -> memory_retriever
-> topic_signal_collector -> creative_brief_builder -> topic_ideator
-> topic_diversity_filter -> angle_strategist -> novelty_guard
-> virality_score -> evidence_brief -> outline_architect -> draft_writer
-> title_lab -> title_ranker -> decision_engine -> hashtag -> assembler
-> content_atomizer -> visual_director -> asset_resolver -> page_designer
-> design_plan_qa -> generic_scene_renderer -> render_qa -> visual_critic
-> human_review -> final_policy_guard -> content_writer
```

其中 `decision_engine` 根据决策结果进入 R1 reflector 或 R2 compliance，检查通过后才到 hashtag，R1/R2 结果回到 decision engine。Assembler 之后进入动态视觉链：内容原子化、视觉导演、素材解析、页面设计、Design Plan QA、通用 scene 渲染、Render QA、Visual Critic，然后进入 Human Review、Final Guard 与 `content_writer`。

## 动态视觉修订回路

视觉阶段有三条确定性修订回路和一条审美回路，全部由 `src/graph.py` 的条件边驱动：

- **Content Atomizer → R2**：`content_atomizer` 检测到禁止的系统文案（免责声明/AI 标注混入可见文字）时路由到 `r2_compliance` 移除；正常路径进入 `visual_director`。
- **Design Plan QA 失败 → Design Reviser**：`design_plan_qa` 在启动浏览器前确定性校验 scene graph。失败回 `design_reviser` 修订；连续 6 次失败（`MAX_QA_FAILURES`，reviser 每轮通常只能解决少量问题，多问题失败集需要更多轮次）抛 `VisualProductionInterrupted(stage="design_plan_qa")` 并 checkpoint，不进入 renderer。
- **Render QA 失败 → Design Reviser**：`render_qa` 基于实际 DOM/PNG 校验。失败回 `design_reviser`；连续 6 次失败（`MAX_RENDER_QA_FAILURES`）抛 `VisualProductionInterrupted(stage="render_qa")`，不进入 Visual Critic 或 Human Review。
- **Visual Critic 失败 → Design Reviser（最多两轮）**：`visual_critic` 是多模态审美复核。失败且修订轮 < 2 回 `design_reviser`；第 2 轮仍失败时带 `visual_needs_attention` 进入 Human Review，并保留问题和评分。
- **Design Reviser 路由**：family 或页面序列需要重排时，`design_reviser` 通过专用 `visual_route_override` 通道回 `visual_director` 重新规划；否则回 `design_plan_qa` 重新校验修订后的计划。

`design_plan_qa` 和 `render_qa` 是硬 QA，失败永远不能强制放行，也不能回退旧 renderer。瞬时 Chromium/截图错误可以对同一 plan 原样重试一次；确定性设计错误必须回到 `design_reviser`。

## 运行和恢复

`main.py` 使用 `data/agent_runs.sqlite` 展示可恢复任务，并以 `thread_id` 读取 `checkpoints.sqlite` 中的 LangGraph 状态。运行中断、等待审核或进程异常后，可以通过 `python main.py --resume` 选择任务，也可以用 run ID 或 thread ID 指定恢复。每个动态视觉合同（`ContentAtomSet`、`VisualDirectionPlan`、`AssetManifest`、`CarouselDesignPlan`、`DesignPlanQAResult`、`RenderManifest`、`RenderQAResult`、`VisualCritique`、Human Review 决定）成功生成后立即 checkpoint；恢复时从最后一个完整且哈希一致的合同继续，不重复已完成的下载或图片生成事务。

`content_writer` 是图的终端节点。它在最终审核、合规、`RenderManifest` 和 publish package 均满足要求后写入结构化记忆和向量记忆；导出发布包由主程序在终端 checkpoint 验证后完成。

## 输出边界

终端导出会在 `outputs/publish/<date>-<domain>-<title>/` 下创建本地发布包：10 个合同 JSON（content atoms、visual direction、asset manifest、design plan、design plan QA、render manifest、render QA、visual critique、content lock、final policy attestation）、`pages/*.png`、`contact-sheet.png` 和 `publish-attestation.json`。导出采用 staging + 原子提升，不覆盖已存在的 canonical 包。输出供人工发布和复核，不包含对小红书平台的自动登录、上传或发布动作。

## 动态视觉生产（llm_scene_v3）

视觉阶段把设计权交给 LLM，同时保留内容锁、结构化 schema、素材安全、确定性 QA、Chromium 渲染、最终人工审核和本地发布边界。关键产品决策：

- **六个 family 是参考视觉 DNA，不是固定页面模板**：`pink_red`、`deep_teal`、`soft_pink`、`coral_impact`、`green_catalog`、`white_quote`。一套 carousel 只选一个 family；每页可在该 family 内自由改变构图、颜色比例、留白、装饰和信息密度。`FamilyStyleProfile` 只描述视觉情绪、色相/明度/饱和度范围、字体角色、装饰语言和参考图，不包含固定 DOM、坐标、archetype layout 或可执行模板代码。
- **Visual Director 主导分页**：一次性输出 `VisualDirectionPlan`，包含唯一 family、5–18 页 `page_count`、整套 art direction、每页目的/密度/视觉任务、页面节奏和每页 `AssetDirective`。页数由内容决定，**不是固定 5–7 页**；六套参考样张的页数不构成生产约束。
- **通用 scene→HTML 编译器**：`generic_scene_renderer` 把合法 scene graph（`text`/`image`/`shape`/`line`/`icon` 原语）编译成受控 HTML/CSS，再用 Chromium 生成 1080×1440 PNG 和 contact sheet。只有一个编译器，**没有 family-specific 布局分支**，也不会根据内容类型私自选择固定版式。
- **素材搜索 + 生成**：`asset_resolver` 按 `AssetDirective` 执行 `licensed_search`/`llm_generation`/`search_then_generate`/`generate_then_search`/`none` 策略；图片生成走 Gemini `gemini-3.1-flash-image`（Developer API `GEMINI_API_KEY`、`GEMINI_VISUAL_MODEL`）。
- **AI 来源仅内部**：生成模型、prompt 和 AI provenance 只写入 `AssetManifestItem.internal_provenance`，**绝不进入页面可见文字或 PNG**；用户在上传平台时统一完成 AI 内容标注。
- **图片不携带免责声明**：图片中不得自动加入“AI 生成”“示意图”“仅供参考”或任何合规/免责声明文字。
- **硬 QA 与审美复核分离**：Design Plan QA 和 Render QA 是确定性硬门；Visual Critic 是审美复核，最多自动修订两轮，之后可带 `visual_needs_attention` 进入 Human Review。审美评分可由人工显式覆盖，硬 QA 永远不能被覆盖。

## 旧 checkpoint 迁移

旧 v1（`legacy_v1`）和 v2（`modern_v2`）checkpoint 通过 `src/editorial_carousel/legacy.py` 迁移到 `llm_scene_v3`：

1. 保留内容、R1/R2、标题、hashtags 和 assembler 的 `publish_package`。
2. 丢弃旧 `visual_plan`、storyboard/`CarouselPayload`、旧 `AssetManifest`、旧 `RenderManifest`、旧视觉 QA 状态和 `content_atom_set` 等所有动态视觉槽位。
3. 记录 migration reason，标记 `editorial_workflow_version=llm_scene_v3`，清除 `legacy_editorial_checkpoint`。
4. 在 `assembler` 之后重新进入图，由 `content_atomizer → visual_director` 重新派生整套视觉计划。

迁移器不执行旧 node，也不把旧固定布局转换成 scene graph。未知版本 fail-closed。这是生产代码中唯一引用旧名称的合法位置。

## 默认离线与 live smoke

默认测试离线，不调用真实素材 provider、Gemini 或远程 Chromium 能力。需要时通过显式环境变量启用：

- `RUN_LIVE_ASSET_PROVIDER_TESTS=1`：Pexels/Unsplash 真实搜索。
- `RUN_LIVE_VISUAL_AI_TESTS=1` 配合 `GEMINI_API_KEY`：Gemini 结构化视觉与图像生成。

这些 live smoke 不进入默认离线验证门。

## 版本选择与 llm_scene_v4（预发布）

`llm_scene_v4` 已实现并通过 G0–G3 离线门（含真实 Chromium 三/八 Grammar 渲染与独立 Q3），但**尚未切换为默认**。默认仍是 `llm_scene_v3`；只有在 G4 shadow 盲评报告经人工批准后才会把新运行默认切到 v4（切换只改选择器，见回滚）。

### checkpoint 之前的版本选择

`src/editorial_carousel/workflow_selection.py` 在读取任何 checkpoint 之前解析不可变的工作流身份：registry 行是权威来源，新 run 可通过 `--visual-workflow {llm_scene_v3,llm_scene_v4}` 显式选择；已存在的 thread 不能切换版本或 run mode（mismatch fail-closed）。`src/graph.py`（v3）与 `src/graph_v4.py` 共享 `graph_common.py` 提取的内容链（domain routing 到 assembler，含 R1/R2 回路），v3 的节点/边签名冻结在 `tests/fixtures/graph/v3-signature.json` 并被逐字节断言；视觉路由两个版本完全不共享。

### v4 视觉链

```text
assembler -> content_atomizer -> content_lock_builder
-> semantic_modeling(Q0) -> visual_authoring(Q1) -> asset_resolver
-> composition_planning -> layout_compiler -> design_plan_qa(Q2)
-> generic_scene_renderer -> render_qa(Q3) -> visual_critic(Q4)
-> review_workspace_builder -> human_review -> final_policy_guard
-> content_writer(production) | shadow_artifact_writer(shadow)
```

- **Q0–Q3 是硬门**，全部从当前合同与字节重新计算；类型化修订边界（Task 14）拥有全部修复重入：同一 fingerprint 第三次出现（非 LAYOUT 层第二次）抛 `VisualExecutionInterrupted` 候选耗尽，预算持久在 checkpoint 状态里，v4 恢复**不重置**失败预算。
- **八个 Composition Grammar**（`editorial_hero`、`comparison_grid`、`step_flow`、`diagnostic_matrix`、`checklist`、`evidence_card`、`image_annotation`、`summary_closing`）各有独立确定性 solver，全部通过真实 Chromium 渲染与独立 Q3。
- **Review Workspace**（`review_workspace_builder`）在 Human Review 中断之前构建：`build_review_workspace` 把整套 Q0–Q4 证据、页面 contact sheet 和素材证据写进 revision 目录的 `review/`，外部授权引用 `ReviewWorkspaceReferenceV4` 持久在 state——review 文件系统永远不能自我授权。
- **Human Review 五种动作**（APPROVE/AESTHETIC_OVERRIDE/REQUEST_REVISION/REJECT_OR_REPLACE_ASSET/VISIBLE_COPY_EDIT）都从不可信 intent 派生、追加 append-only 决定记录，并在路由前经 `verify_human_review_decision` 重开决定记录、workspace、Q0–Q3 与全部页面/contact/素材字节。
- **双终端**：production 走 `content_writer`（写记忆/Chroma，发布包由 CLI 在终端 checkpoint 后经 v4 exporter 导出）；shadow 走 `shadow_artifact_writer`，把非发布评估 bundle 写到 `outputs/shadow/`（`shadow-manifest.json` 标记 `run_mode=shadow`、`publishable=false`），**绝不触碰** publish root、记忆或 Chroma。

### v4 人工审核 CLI

v4 的 Human Review 中断后，主程序把 run 标记为 `WAITING_HUMAN` 并提示使用本地 review CLI（graph-free，只读 checkpoint）：

```bash
python main.py --review-show <run>      # 打印 review/index.html 的 file:// URI
python main.py --review-submit <run> --review-intent intent.json   # 追加 append-only 决定
python main.py --review-verify <run> --review-reference reference.json  # 重开全部字节验证
python main.py --resume <run>           # 决定写入 decision.json 后恢复图
```

`--shadow-v4-from <run-id>` 从一个 v3 run 的 checkpoint 提取并验证 assembler 副本，创建链接的 v4 shadow run（源 run 行与图只读不改动）。

### 发布门与回滚

- **G0** 基线 fixture replay / v3 恢复 / shadow 隔离；**G1** timeout/retry/resume/crash 注入；**G2** 三 Grammar 真实渲染过全部硬 QA；**G3** 已知坏页被拦截、已审核字节即发布字节；**G4** shadow 盲评（≥10 主题约 80 页、≥80% better-or-equal、零 critical 回归、尝试/修订/时延预算内，阈值预声明在 `tests/fixtures/llm_scene_v4/quality_manifest.json` 且调用方不可放宽）；**G5** 文档、回滚演练与全套验证。G0–G3 已离线通过；G4 等待凭证背书的手动战役与人工报告批准。
- **回滚**：因为默认选择器是唯一开关，回滚只影响未来新 run——把默认（或建议的 `--visual-workflow`）改回 `llm_scene_v3` 即可；已存在的 v4 checkpoint 继续用 v4 图恢复（版本不可中途切换），v3 checkpoint 与 schema 路径全程冻结不受影响。
