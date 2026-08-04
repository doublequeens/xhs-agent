# 编辑图文契约

`llm_scene_v3` 动态视觉生产路径以 Pydantic 合同连接内容原子化、视觉导演、素材、设计、渲染、QA、审核和发布阶段。生产代码中只有 `src/editorial_carousel/legacy.py` 负责旧 v1/v2 checkpoint 的迁移适配；它不能重新启用旧的固定卡片渲染路径，相关旧名称（`VisualPlan`、`CarouselPayload`、`ResolvedVariant`、`modern_v2`、`recommended_frame_count`、`visual_strategy_planner`、`storyboard_generator`、`carousel_qa`、`editorial_carousel_renderer`）只允许出现在历史 spec、checkpoint 迁移说明和断言其不存在的测试中。

## v3 合同 producer/consumer

| Contract | Producer | Consumer | Required invariant |
| --- | --- | --- | --- |
| `ContentAtomSet` | `content_atomizer` | `visual_director`、`page_designer`、Design Plan QA、publish | 不可变 atom（标题、封面、正文句子、列表项、步骤等可见文字）携带 `atom_id` 与 `sha256`，全集有 `canonical_sha256`；视觉阶段只能通过 `content_ref` 引用，不得改字。 |
| `VisualDirectionPlan` | `visual_director` | `asset_resolver`、`page_designer`、Design Plan QA、renderer、publish | 唯一 `template_family`、5–18 `page_count`、整套 art direction、`content_fragments`、`page_sequence`、`asset_directives`；绑定 `content_atom_set_sha256`。 |
| `AssetManifest` / `AssetResolutionResult` | `asset_resolver` | `page_designer`、Design Plan QA、renderer、Render QA、publish | 每个 `AssetManifestItem` 绑定 `directive_id`/`page_id`，验证 provider、许可、路径 containment、no-follow、事务绑定、字节 `sha256`；`security_status` 区分自动安全审核与人工决定；`internal_provenance` 仅内部，不进入页面可见文字。 |
| `CarouselDesignPlan` | `page_designer` | Design Plan QA、`generic_scene_renderer`、Render QA、publish | 每页是一棵 scene graph（`text`/`image`/`shape`/`line`/`icon` 原语）；Text 元素必须用 `content_ref`，Image 元素必须用 `asset_ref`；绑定 direction/design/asset 三个哈希；无自由 HTML/CSS/JavaScript。 |
| `DesignPlanQAResult` | `design_plan_qa` | `generic_scene_renderer`、publish | 确定性校验页数、单 family、atom 覆盖/顺序/无改字、scene graph 合法性、box/safe margin/对比度、asset 引用、无 AI 标签或免责声明；失败产生 page/element/atom 级 issue。 |
| `RenderManifest` | `generic_scene_renderer` | `render_qa`、`visual_critic`、publish | 有序 1080×1440 PNG、字体加载、contact sheet、源素材哈希；每页记录 PNG 路径与 `sha256`、实际元素 probe、文字证明、图片裁剪和画布尺寸。 |
| `RenderQAResult` | `render_qa` | `visual_critic`、publish | 基于实际 DOM/PNG 校验文字字符/出现次数/顺序、bounding box/overflow、safe margin/最小字号/对比度、字体/emoji/glyph、图片 crop、页面尺寸/顺序/PNG 哈希、三个 manifest 哈希绑定。 |
| `VisualCritique` | `visual_critic` | `human_review`、publish | 多模态审美评分（overall/hierarchy/family_consistency/page_rhythm/image_relevance）、是否通过、revision round、page/element 级问题；是审美反馈，不得绕过硬 QA。 |
| `ContentLock` | publishing layer（`src/publishing/artifacts.py`） | publish copy、final guard、publish | 锁定标题、正文、hashtags、首屏承诺等可见源文，绑定 `content_atom_set_sha256`；**不再含 storyboards**；`canonical_sha256` 是规范版本。 |
| `PublishAttestation` | publishing layer | （whole-bundle 绑定） | `workflow_version=llm_scene_v3`；哈希上述 9 个合同 + `final_policy_attestation` 的 canonical sha256，以及每个 PNG（`pages/*.png` + `contact-sheet.png`）的字节 sha256。 |

## 关键规则

`ContentAtomSet` 把 assembler 的规范文案拆成不可变 atom，为标题、封面文案、正文句子、列表项、步骤和其它允许进入图片的可见文字分配稳定 `atom_id` 与 `sha256`。Hashtags、审计字段和其它 publish-only metadata 不进入图片 atom。Fragment 由 Visual Director 沿句子、列表项或步骤边界创建并保存到 `VisualDirectionPlan.content_fragments`；validator 必须证明同一 atom 的所有 fragment 按原顺序拼接后与原文逐字符一致。视觉阶段只能换行、分组、强调和按语义边界拆分分页，**不得新增、删除、改写、缩写或替换文字**。

`VisualDirectionPlan` 的 `page_count` 必须为 5–18，由 Visual Director 根据文案决定（不再是旧的 5–7 限制）。每页必须承担独立内容任务，不能用重复或空洞页面凑页数。一套 carousel 只使用一个 family；六个 family（`pink_red`、`deep_teal`、`soft_pink`、`coral_impact`、`green_catalog`、`white_quote`）只通过 `FamilyStyleProfile`（视觉情绪、色相/明度/饱和度范围、字体角色、装饰语言、参考图）参与设计，不定义页面数量、页面顺序或固定布局。

`CarouselDesignPlan` 的 scene graph 元素声明唯一 ID、box、layer、alignment、style token、所属页面绑定和必要的内容/素材引用（扁平结构，无父子嵌套）。Text 只能用 `content_ref`，Image 只能用 `asset_ref`；Shape/Line/Icon 只能用批准的结构化字段，不允许携带自由 HTML/CSS/JavaScript。`generic_scene_renderer` 是单一通用编译器，没有 family-specific 布局分支。

`AssetManifest.items` 可以为空，对应纯文字 carousel；空 manifest 仍要经过 Design Plan QA、Render QA 和 ContentLock 校验，渲染器只产出文字版页面。需要外部素材时，每个 directive 声明 `required` 或 `optional`，resolver 执行允许的 `licensed_search`/`llm_generation`/`search_then_generate`/`generate_then_search`/`none` 策略；只有通过 provider、许可、路径、no-follow、哈希和事务检查的素材才能得到 `security_status=approved` 并进入 renderer。`human_decision` 在整套 Human Review 前保持 pending。图片生成走 Gemini `gemini-3.1-flash-image`，**生成模型、prompt 和 AI provenance 仅进入 `internal_provenance` 内部数据，绝不进入页面可见文字或 PNG**；图片中也不得自动加入“AI 生成”“示意图”“仅供参考”或任何免责声明。

## Human Review 路由

Human Review 统一在所有硬 QA 和审美复核完成后进行一次。`route_after_human_review` 读取节点写入的 `state["review_route"]`：

| 人工操作 | 后续路由 | 状态清除 |
| --- | --- | --- |
| 直接批准 | `final_policy_guard` | — |
| 构图/颜色/图片/排版反馈 | `design_reviser` | — |
| 修改任何可见文字 | `r2_compliance` | 清除全部 8 个视觉合同 + atoms，保留编辑后的 copy 作为 R2 输入 |
| 替换或拒绝图片 | `asset_resolver` | 清除 manifest/scene/render/critique，保留 atoms + direction |
| `visual_needs_attention` 批准 | `final_policy_guard`（需显式 `visual_aesthetic_override`） | — |

人工替换图片后不能保留旧 `RenderManifest`。任何文字变化都会使 `ContentAtomSet`、`VisualDirectionPlan`、`AssetManifest`、`CarouselDesignPlan`、`RenderManifest` 和 `VisualCritique` 失效。`visual_needs_attention` 必须由人工生成显式 aesthetic override attestation 才能继续。

## Final Guard

Final Guard 仍在 Human Review 之后执行，硬门每个 attestation：审美 override 允许，**硬 QA override 永远不允许**。Final Guard 可以接受人工审美覆盖，但仍必须拒绝任何未通过的 Design Plan QA、Render QA、素材安全、内容哈希或合规检查。无问题才进入 `content_writer`。

## 失败处理与中断

- LLM schema 或内容合同失败：Visual Director / Page Designer / Design Reviser 通过 `generate_validated` 最多自修复 6 次（`MAX_GENERATION_ATTEMPTS`，结构化模型产出复杂嵌套 JSON 时频繁出现缺失字段/判别器错误，3 次不足以吸收）；仍失败则 `interrupted` 并 checkpoint，不生成默认五页，不回退旧 node。
- 素材失败：按 directive 执行允许的 search/generation fallback；optional 全部失败回 Design Reviser 生成无图版本；required 全部失败中断并保留 recovery evidence。
- Design Plan QA / Render QA：与 Design Reviser 最多循环 3 轮，3 轮后抛 `VisualProductionInterrupted` 中断并 checkpoint。
- Visual Critic：最多自动修订 2 轮，仍不通过进入 `visual_needs_attention` Human Review。

## 迁移边界

旧运行的迁移边界只有 `src/editorial_carousel/legacy.py`。迁移器把可识别的旧 v1/v2 状态丢弃旧视觉槽位、标记 `llm_scene_v3`、在 `assembler` 之后重新进入图，由 `content_atomizer → visual_director` 重新派生视觉计划；业务节点不得直接依赖删除的旧 text-card 合同或旧 prompt，迁移器也不执行旧 node 或把旧固定布局转换成 scene graph。
