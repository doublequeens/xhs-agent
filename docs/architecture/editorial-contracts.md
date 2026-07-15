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

`AssetManifest` 对每个 requirement 提供路径、来源、许可、尺寸、字节哈希和审核状态。外部素材若尚未通过安全审核，只能保持 pending，不能被当作已批准素材渲染发布。

`RenderManifest` 是渲染结果的唯一页面顺序和文件证明；渲染器输出的每页必须是 1080×1440 PNG，contact sheet 也必须列在清单中。Render QA 读取该清单，而不是猜测目录内容。

`ContentLock` 由发布层从规范化 publish package 生成，锁定标题、正文、hashtags、首屏承诺和 storyboards，并计算 `canonical_sha256`。publish copy、Codex 图像救援 prompt 和 final guard 都以锁定内容为准；救援 prompt 只能重做视觉表现，不得改题目、关键词、步骤、判断标准或可见文字。

Human Review 可以修改可见文字，但修改必须通过现代 `CarouselPayload`、内容合同和发布包校验；修改后会重新执行必要的 Render QA/R2。Final Guard 总是在 Human Review 之后运行，发现策略问题就回到人工审核，只有无问题才允许 content writer。

旧运行的迁移边界只有 `src/editorial_carousel/legacy.py`。迁移器把可识别的旧状态补齐到现代 VisualPlan、CarouselPayload 等合同，再进入现代 storyboard、resolver、QA、renderer 和 review 路径；业务节点不得直接依赖删除的旧 text-card 合同或旧 prompt。
