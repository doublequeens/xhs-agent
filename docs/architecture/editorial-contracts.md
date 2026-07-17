# 编辑图文契约

现代生产路径以 Pydantic 合同连接内容、视觉、素材、渲染和审核阶段。生产代码中只有 `src/editorial_carousel/legacy.py` 负责旧 checkpoint 的迁移适配；它不能重新启用旧的固定卡片渲染路径。

| Contract | Producer | Consumer | Required invariant |
| --- | --- | --- | --- |
| `VisualPlan` | visual strategy planner | storyboard generator/QA | layout family 和视觉要求是结构化字段，不是自由格式 HTML/CSS。 |
| `CarouselPayload` | storyboard generator | resolver、QA、renderer、review | frame 数量、顺序、角色、layout 和可见字符串经过 schema 验证。 |
| `AssetManifest` | asset resolver | carousel QA、renderer | 每个素材均已审核、可追溯，并绑定到一个 slot。 |
| `RenderManifest` | editorial renderer | render QA、publishing | 记录有序的 1080×1440 PNG、字体加载、contact sheet 和源素材哈希。 |
| `ContentLock` | publishing layer | publish copy、rescue prompt、final guard | 锁定内容是规范版本并带 canonical hash；视觉救援不能改变事实或文字。 |

## 关键规则

`VisualPlan` 必须指定 `beauty_editorial_v1` 设计系统、内容任务、视觉家族和 5–7 个 frame plan；首帧为 editorial cover，并且包含可保存的参考/清单布局。`CarouselPayload` 的 storyboards 与 VisualPlan 对齐，frame 和 visual slot ID 不重复，所有可见文字由现代合同承载。

## 自适应六模板工作流

`NarrativePlan.narrative_form` 是从 copy 到 storyboard 再到渲染都保留的单一形式标签，取自八种叙事形式之一：`cognitive_correction`、`step_tutorial`、`checklist_collection`、`comparison`、`diagnostic_qa`、`scenario_story`、`story_reversal`、`reflective_editorial`。VisualPlan 的 `narrative_form` 必须与 `NarrativePlan` 一致；Carousel QA 会显式拒绝不匹配。

`VisualPlan.template_family` 由 selector 根据 `narrative_form`、估算的 density（`sparse`/`standard`/`dense`）、`content_job` 和 `proof_mode` 综合评分，在六个生产家族中选择一个：`pink_red`、`deep_teal`、`soft_pink`、`coral_impact`、`green_catalog`、`white_quote`。一次 plan 只允许一个家族；近期使用过的家族会被扣分以避免连续重复。

页面数量是内容驱动的：`ContentContract.recommended_frame_count`（5–7）决定 `VisualPlan.frame_plan` 的长度，与手工 mockup 数量无关。同一 `green_catalog` 家族可以从同一合同渲染 5、6、7 页，仅靠 `recommended_frame_count` 改变。

自适应 density 和 composition 边界由 `FramePlanItem.allowed_density` 给出每页许可范围，渲染器据此选择 sparse/standard/dense 排版，不会出现截断、省略号、隐藏文字或低于最小字号的情况。Emoji 作为 grapheme 保留并和正文一起渲染；仓库固定字体为 `Source Han Serif SC`（display）、`Source Han Sans SC`（body）和 `Bodoni Moda`（numeral），emoji 走 `Noto Color Emoji` fallback。

`AssetManifest.items` 可以为空列表，对应纯文字 carousel（`proof_mode=none`、`content_job=follow_steps` 等）。空 manifest 仍然经过 Carousel QA、Render QA 和 ContentLock 校验，不会触发外部素材搜索。需要外部素材时，每个 requirement 提供路径、来源、许可、尺寸、字节哈希和审核状态；外部素材若尚未通过安全审核，只能保持 pending，不能被当作已批准素材渲染发布。

`RenderManifest` 是渲染结果的唯一页面顺序和文件证明；渲染器输出的每页必须是 1080×1440 PNG，contact sheet 也必须列在清单中。Render QA 读取该清单，而不是猜测目录内容。

`ContentLock` 由发布层从规范化 publish package 生成，锁定标题、正文、hashtags、首屏承诺和 storyboards，并计算 `canonical_sha256`。publish copy、Codex 图像救援 prompt 和 final guard 都以锁定内容为准；救援 prompt 只能重做视觉表现，不得改题目、关键词、步骤、判断标准或可见文字。

Human Review 可以修改可见文字，但修改必须通过现代 `CarouselPayload`、内容合同和发布包校验；修改后会重新执行必要的 Render QA/R2。Final Guard 总是在 Human Review 之后运行，发现策略问题就回到人工审核，只有无问题才允许 content writer。

旧运行的迁移边界只有 `src/editorial_carousel/legacy.py`。迁移器把可识别的旧状态补齐到现代 VisualPlan、CarouselPayload 等合同，再进入现代 storyboard、resolver、QA、renderer 和 review 路径；业务节点不得直接依赖删除的旧 text-card 合同或旧 prompt。
