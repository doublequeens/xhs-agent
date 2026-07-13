# 美容编辑式图文工作流设计

## 状态

待书面规格审核。该设计在实现后取代
`2026-07-12-local-text-card-rendering-design.md` 中固定六张纯文字卡、固定模板顺序和
仅两套纯色主题的视觉方案。账号定位、内容合规、首屏承诺和可截图保存资产等既有
业务约束继续有效。

## 目标

让 Agent 在不调用图像生成 API 的情况下，为美容护肤内容稳定生成可直接发布的
`1080 × 1440` 小红书图文。不同内容必须根据读者要完成的任务选择不同视觉家族和
页面布局；同一账号则通过字体、颜色、线稿、材质和间距保持可识别的一致性。

验收重点不是“成功生成 PNG”，而是同时满足：

- 第一屏说清谁遇到什么问题、能得到什么。
- 每一页只完成一个信息任务。
- 图解、质地或实物素材与文字有语义对应，不做纯装饰。
- 每篇至少包含一张可以独立截图使用的判断卡、流程卡或清单。
- 全套保持美容编辑感，但不让不同文章套用同一页面顺序。
- 中文文字准确、字体确定、没有溢出、缺字或系统 fallback。

## 非目标

- 不调用 GPT Image、其他图像生成 API 或远程生成服务。
- 不实现自由拖拽编辑器。
- 不允许 LLM 输出任意 HTML、CSS、坐标或字体文件路径。
- 不要求真人出镜，也不恢复小蝾螈或其他固定卡通 IP。
- 不在本次变更中调整美容账号受众、内容安全策略或发布指标采集。
- 不自动抓取授权不明的社交平台图片。

## 核心原则

LLM 决定“表达什么、属于哪类视觉任务、每页使用什么语义布局”；确定性代码决定
“字体、位置、尺寸、颜色、素材裁切、输出文件和质量门禁”。

视觉变化分为三个层次：

```text
内容任务 content_job
  -> 主视觉家族 primary_visual_family
  -> 每页具体布局 layout
```

一个帖子只选择一个主视觉家族，但可以使用多个辅助家族。账号级 Design System
始终一致。这样可以达到“同一本美容杂志、不同文章不同编排”，而不是“每篇都长得
一样”。

## 内容任务与视觉家族

### 五个首发视觉家族

| 视觉家族 | 适用内容任务 | 典型问题 |
| --- | --- | --- |
| `beauty_editorial` | 建立主题和美容氛围 | 季节趋势、护肤理念、质地观察 |
| `face_zone_map` | 判断脸部区域、用量或状态 | T 区与两颊、用量、局部干燥 |
| `step_flow` | 按顺序执行操作 | 早晚流程、叠涂顺序、等待时间 |
| `comparison_decision` | 在多个方案或状态中选择 | A/B 选择、适合/不适合、过量/不足 |
| `saveable_reference` | 保存规则并随时查阅 | 清单、对照表、速查卡、避坑表 |

`beauty_editorial` 通常承担封面或过渡页，不单独承担整篇干货。每篇必须包含
`saveable_reference` 页面角色，但它不一定是主视觉家族。

### 选择规则

Visual Strategy Planner 按以下优先顺序确定 `content_job`：

1. 内容是否要求判断脸部区域、状态或用量；是则选 `diagnose_and_adjust`，主视觉为
   `face_zone_map`。
2. 内容是否存在不可交换的先后顺序；是则选 `follow_steps`，主视觉为 `step_flow`。
3. 内容是否要求在两个以上选项中做决定；是则选 `compare_and_choose`，主视觉为
   `comparison_decision`。
4. 内容是否主要提供清单或查表规则；是则选 `save_and_check`，主视觉为
   `saveable_reference`。
5. 其余美容观点或趋势内容使用 `understand_and_notice`，主视觉为
   `beauty_editorial`，但必须补充一个可执行的辅助家族。

若同时命中多项，`ContentContract.decision_problem` 决定主任务，其余作为辅助家族。
Planner 不根据关键词随机选择，也不能为了变化硬塞脸图或流程图。

## 页面布局目录

首版 renderer 支持以下确定性布局：

| Layout | 作用 | 所属家族 |
| --- | --- | --- |
| `editorial_cover` | 首屏问题、收益与美容主视觉 | `beauty_editorial` |
| `texture_baseline` | 液体、凝胶、泵头等基准说明 | `beauty_editorial` |
| `front_face_zone` | 正面脸部区域与落点 | `face_zone_map` |
| `three_quarter_face_zone` | 侧脸、干区与动作路径 | `face_zone_map` |
| `step_timeline` | 单向编号步骤 | `step_flow` |
| `morning_evening_flow` | 早晚双轨流程 | `step_flow` |
| `left_right_comparison` | A/B 或错误/正确对比 | `comparison_decision` |
| `three_state_diagnostic` | 刚好、过量、不足等三状态 | `comparison_decision` |
| `decision_tree` | 条件到建议的判断路径 | `comparison_decision` |
| `saveable_checklist` | 勾选式操作清单 | `saveable_reference` |
| `saveable_reference` | 一屏结论、分区或用量速查 | `saveable_reference` |

版式目录是可扩展集合，不是每篇必须遍历的固定顺序。首版要求一套 carousel：

- 5–7 页。
- 至少使用 3 种 layout。
- 同一 layout 最多连续出现两页。
- 必须以 `editorial_cover` 开始；封面内部根据主视觉家族选择对应的素材 slot。
- 必须以 `saveable_checklist` 或 `saveable_reference` 中至少一种提供独立保存资产。
- 除封面和保存页外，不得与上一篇拥有完全相同的 frame plan。

## 测试专用验收样例

下面的分区用量样例只用于验证已经确认的视觉决策链路。它不是生产选题、推荐主题、
模板默认文案或运行时 few-shot 示例，也不得进入 topic prompt、memory、选题历史或发布
候选。运行时必须根据当前 `ContentContract` 重新完成分类和版式选择，不得识别特定
标题后走硬编码分支。

该测试样例分类为：

```json
{
  "content_job": "diagnose_and_adjust",
  "primary_visual_family": "face_zone_map",
  "supporting_families": [
    "beauty_editorial",
    "comparison_decision",
    "saveable_reference"
  ]
}
```

期望 frame plan：

```text
cover              -> editorial_cover
baseline           -> texture_baseline
applicable_case    -> front_face_zone
zone_adjustment    -> three_quarter_face_zone
feedback_diagnosis -> three_state_diagnostic
save               -> saveable_reference
```

Golden test 只固定语义角色、layout、Design System 和测试输入中的关键可见文字，
不固定生产标题，也不对纹理的每个像素做快照，以免合理的素材版本升级造成脆弱测试。

## 数据模型

### ContentContract 扩展

保留现有字段，并增加：

```python
content_job: Literal[
    "diagnose_and_adjust",
    "follow_steps",
    "compare_and_choose",
    "save_and_check",
    "understand_and_notice",
]
primary_visual_family: Literal[
    "beauty_editorial",
    "face_zone_map",
    "step_flow",
    "comparison_decision",
    "saveable_reference",
]
primary_visual_subject: Literal[
    "face_map",
    "serum_texture",
    "product_cutout",
    "skin_macro",
    "checklist",
    "process",
]
proof_mode: Literal["diagram", "real_photo", "product_texture", "comparison", "none"]
recommended_frame_count: int  # 5..7
```

旧 checkpoint 缺少新字段时，在一个明确的兼容 adapter 中根据原合同推导默认值；
新生成的 TopicItem 必须显式包含全部字段。

### VisualPlan

Visual Strategy Planner 输出严格的 `VisualPlan`：

```python
class VisualPlan(BaseModel):
    design_system: Literal["beauty_editorial_v1"]
    content_job: ContentJob
    primary_visual_family: VisualFamily
    supporting_families: list[VisualFamily]
    frame_plan: list[FramePlanItem]  # 5..7
    required_assets: list[AssetRequirement]
```

`FramePlanItem` 只包含 `frame_id`、`role`、`layout`、`purpose` 和需要的 asset roles。
它不包含自由 CSS 或坐标。

### Semantic Storyboard

Storyboard Generator 根据 `VisualPlan` 填写每页可见内容：

```python
class CarouselFrame(BaseModel):
    frame_id: str
    role: FrameRole
    layout: LayoutName
    headline: str
    kicker: str | None
    content_blocks: list[ContentBlock]
    emphasis: list[str]
    visual_slots: list[VisualSlot]
    footer: str | None
```

每种 layout 使用 discriminated schema 限制专属字段。LLM 不能提供 HTML、CSS、任意
坐标、字体文件或网络 URL。第一张 headline 必须逐字等于 `first_screen_promise`。

### AssetManifest 与 RenderManifest

Asset Resolver 返回每个 slot 的本地路径、素材角色、来源、许可证/所有权说明和尺寸。
Renderer 返回有序 PNG、每页使用的 layout、字体加载结果和 contact sheet 路径。

## 本地素材策略

首版素材来自仓库中经过审核的本地素材包：

```text
assets/visual/beauty-editorial-v1/
  face-maps/
  skincare-textures/
  product-shapes/
  skin-feedback/
  decorative/
  manifest.json
```

素材类型包括：

- 正面、四分之三侧面、侧面脸部 SVG 线稿。
- T 区、两颊、眼周、下颌等可组合区域 mask。
- 精华液滴、凝胶涂抹、液体纹理和泵头轮廓。
- 经许可的皮肤触感局部图；没有合适照片时使用审核过的 diagram fallback。
- 细线、页码、圆点和材质背景等账号级装饰 token。

不自动下载未记录来源的素材。Asset Resolver 找不到满足 slot 的素材时，优先使用
manifest 中声明的 fallback；没有 fallback 时失败并返回可操作错误，不得渲染空白占位。

未来如接入图库或图像生成，只需新增 `AssetProvider` adapter，不改变 VisualPlan、
Storyboard 或 Renderer 的外部 interface。

### 素材入库与持续积累

正式素材库与历史发布产物分开管理。`outputs/publish` 只保存最终成品，不能被 Asset
Resolver 当作素材目录扫描；只有通过审核并写入 manifest 的原始素材才能被生产流程
使用。

目录分为三个生命周期区：

```text
assets/visual/beauty-editorial-v1/
  incoming/       # 候选素材，不可用于生产
  active/         # 已审核、可用于生产
  retired/        # 过时、重复或质量不足，不再选用
  licenses/       # 许可证文本或获取时的条款快照
  manifest.json
```

每个素材必须经过以下步骤：

1. **收集**：把候选文件放入 `incoming`，同时记录来源 URL、作者、获取日期和来源类型。
2. **权利审核**：确认是项目原创、用户自有、明确许可的字体/图库素材或允许使用的衍生
   素材；不确定则拒绝。
3. **技术规范化**：检查分辨率、透明通道、色彩空间、文件体积、重复哈希和恶意元数据；
   转为 SVG、PNG 或 WebP 的标准规格。
4. **视觉审核**：检查美容类别感、构图可裁切性、颜色、清晰度、品牌/水印/可识别人脸
   风险，以及是否能承担明确的 asset role。
5. **语义标注**：填写 asset role、适用 layout、朝向、区域、质地、主色、fallback 和
   禁用场景。
6. **人工晋级**：审核通过后移动到 `active` 并写入 manifest；代码不得自动晋级。
7. **使用反馈**：记录使用次数、最近使用时间、人工评分和失败原因，用于避免连续重复。
8. **退役**：重复、低质量、授权变化或风格过时的素材移动到 `retired`，保留审计记录。

Manifest 至少包含：

```json
{
  "asset_id": "serum_drop_001",
  "role": "serum_drop",
  "path": "active/skincare-textures/serum-drop-001.webp",
  "source_type": "project_original",
  "source_url": null,
  "author": "xhs-agent",
  "license": "project-owned",
  "license_snapshot": null,
  "acquired_at": "2026-07-14",
  "width": 1200,
  "height": 1200,
  "sha256": "...",
  "allowed_layouts": ["editorial_cover", "texture_baseline"],
  "tags": ["clear", "watery", "ivory"],
  "fallback_for": []
}
```

### 素材来源优先级

按风险从低到高使用：

1. 项目原创的 SVG/CSS：脸部线稿、区域 mask、液滴、泵头、箭头、页码和背景纹理。
2. 用户自行拍摄且拥有权利的皮肤局部、手部、质地和无品牌容器照片。
3. 官方以开源字体许可证发布的字体文件，并随仓库保存许可证。
4. 逐张人工下载并记录条款的图库素材，只用于最终图文组合，不把素材库包装成图库产品。
5. 在外部工具中人工制作后导入、且权利和来源清晰的视觉素材。

禁止来源：直接抓取小红书、Canva 模板、品牌广告、电商详情页、搜索引擎缩略图、授权
未知的社交截图，以及带水印、Logo、二维码或可识别人物但缺少适当许可的图片。

### 初始种子库

首版不追求数量，先建立约 50–80 个高复用素材：

- 3 个原创脸部角度和 8–12 个区域 mask。
- 12–18 个精华、凝胶、乳霜和液体质地素材。
- 8–12 个泵头、滴管、瓶型和操作图标。
- 8–12 个经审核的皮肤触感或手部局部素材。
- 10–15 个背景、纸张、细线、编号和装饰 token。
- 3 套项目内字体及其许可证。

多个 layout 对少量素材进行裁切、着色、mask 和组合，提供组合多样性。Asset Resolver
同时限制近期重复使用，不依赖无边界扩充素材数量来制造变化。

## Design System

`beauty_editorial_v1` 作为代码配置和本地字体资产存在：

```text
display font: Source Han Serif SC SemiBold, weight 600
body font: Source Han Sans SC Regular/Medium, weight 400/500
numeral font: Bodoni Moda Regular, weight 400
background: #F7F2EA
ink: #292625
mauve: #9A707B
coral: #D45D4C
sage: #78805E
canvas: 1080 × 1440
```

实现必须通过项目内 `@font-face` 加载字体，并在 Chromium 中等待 `document.fonts.ready`。
不允许静默 fallback 到 PingFang、Microsoft YaHei 或其他系统字体。

排版硬规则：

- 每页最多两种中文字体，全套最多三种字体。
- 正文字重最多 500，显示标题最多 600。
- 粗体/强调文字估算面积不超过可见文字面积的 25%。
- 标题最多两行，正文行高为字号的 1.4–1.5 倍。
- 页面必须有一个占画布至少 35% 的视觉主体或结构化信息主体。
- 中文正文不使用书法、手写或装饰字体。
- 红色重点词不同时叠加超大字号、最高字重和高饱和三种强调。

## 节点与 Graph

新主流程为：

```text
hashtag
  -> assembler
  -> visual_strategy_planner
  -> storyboard_generator
  -> asset_resolver
  -> carousel_qa
  -> editorial_carousel_renderer
  -> render_qa
  -> human_review
  -> final_policy_guard
  -> content_writer
```

### 保留

- 选题、证据、正文、标题、R1/R2、合规、assembler、human review、final guard 和导出。
- `storyboard_generator`、`carousel_qa`、`render_qa` 的节点位置与职责名称，但更换合同。

### 替换

- 旧 `visual_director` 替换为读取 publish package、content contract、evidence 和素材目录的
  `visual_strategy_planner`。
- 旧 Pexels-only `image_sourcing` 替换为本地 `asset_resolver`。
- 旧 `text_card_renderer` 替换为 `editorial_carousel_renderer` 深模块和薄 graph adapter。
- 旧的 URL-description-only `image_qa` 不接入新流程；素材像素和 provenance 在 Asset
  Resolver/Render QA 中验证。

### 删除的固定约束

- 固定六张。
- 固定 `cover_statement -> wrong_vs_right -> step_timeline -> saveable_checklist ->
  decision_rule -> question_closer` 顺序。
- 固定最后一张提问卡。
- 仅 `warm_neutral` / `cool_sage` 两套纯色主题。
- 所有页面共用同一个标题＋空白正文骨架。

## 深模块与 Interface

Renderer 提供一个外部 interface：

```python
render_carousel(
    visual_plan: VisualPlan,
    storyboard: CarouselPayload,
    assets: AssetManifest,
    output_dir: Path,
) -> RenderManifest
```

布局 dispatch、字体加载、SVG/mask 组合、素材裁切、HTML/CSS、Playwright、截图、contact
sheet 和清理逻辑都隐藏在该模块内部。Graph node 只负责验证 state、调用 interface、写回
manifest。测试与调用者不跨过这个 seam 操作内部 HTML。

Asset Resolver 提供：

```python
resolve_assets(visual_plan: VisualPlan, catalog: AssetCatalog) -> AssetManifest
```

当前只有本地目录 adapter；未来有第二种 provider 时才引入 provider seam。

## Carousel QA

渲染前检查：

- frame 数量为 5–7。
- cover headline 等于 first-screen promise。
- 存在可独立保存的 frame role。
- layout 属于所选视觉家族或辅助家族。
- 至少三种 layout，同一 layout 不连续重复。
- 每页只有一个主要信息任务。
- visual slot 与文案语义匹配。
- 不存在固定卡通 IP、无意义互动结尾或整段正文上图。
- 当前 frame plan 与最近已发布记录不完全相同。

确定性问题生成原子 R1 任务。LLM 输出 schema 无效时不在节点内猜测修复。

## Render QA

渲染后必须检查：

- 文件数量、顺序、PNG 签名和 `1080 × 1440` 尺寸。
- 所有 font face 成功加载且实际 computed font family 与 Design System 一致。
- 无文字溢出、裁切、缺字或不可见文字。
- 最小字号、行高、安全边距和颜色对比满足 token。
- asset 存在、尺寸足够、未拉伸，并有 provenance。
- 每页主体占比、空白率和相邻布局相似度在允许范围内。
- rendered visible text 与 storyboard 逐字一致。
- contact sheet 成功生成。

质量结果记录：

```python
editorial_quality
beauty_category_fit
visual_hierarchy
saveability
cross_page_consistency
template_stiffness
```

无需视觉模型即可确定的项目采用硬门禁。首版主观分数来自基于布局、素材和 token 的
确定性代理指标，并在 Human Review 中展示；它们不能替代人工最终审美审核。

## Human Review

Human Review interrupt 展示：

- 六张或实际 5–7 张最终图片。
- contact sheet。
- 每页 role、layout 和素材来源。
- Carousel QA 与 Render QA 结果。
- 字体加载状态和 fallback 错误。

文字修改继续触发 R2。只修改非文字视觉选择时重新走 Visual Strategy/Asset Resolver/
Renderer/Render QA，不无条件重跑正文和标题节点。

## 错误处理

- VisualPlan、Storyboard 或 manifest schema 无效：失败并回到 R1，不猜测补字段。
- 缺少本地素材：使用 manifest 中显式 fallback；没有 fallback 则阻止发布。
- 字体加载失败或发生 fallback：阻止截图进入通过状态。
- 任意页面截图失败：删除本次所有部分输出。
- QA 失败：保留审计结果，但不进入 Human Review。
- 旧 checkpoint：通过单一 legacy adapter 升级，不把兼容分支散落在各节点。

## 测试策略

### Schema 与选择算法

- 每种 `content_job` 映射到正确主视觉家族。
- 多任务内容以 `decision_problem` 为主，其余成为辅助家族。
- 5–7 页限制、layout/family 兼容和保存页约束。

### Renderer

- 11 个首版 layout 的 HTML 结构、字体 token 和素材 slot。
- 真正 Chromium 渲染 smoke test。
- 字体 ready、computed font、溢出、缺素材和部分输出清理。
- 所有输出为 `1080 × 1440`。

### Graph 与 QA

- 新节点顺序和 pass/fail 路由。
- Carousel QA 对重复布局、错误家族和缺少保存页的原子问题。
- Render QA 对 fallback 字体、错误尺寸、缺失 provenance 和文字不一致的拦截。
- Human Review payload 包含 contact sheet 和质量报告。

### 测试专用 Golden 与回归

至少维护四个按“内容任务”命名的合成 golden fixtures：

1. `zone_diagnosis_fixture`：验证 `face_zone_map`。
2. `ordered_routine_fixture`：验证 `step_flow`。
3. `multi_option_decision_fixture`：验证 `comparison_decision`。
4. `reference_checklist_fixture`：验证 `saveable_reference`。

这些 fixture 是测试目录中的合成输入，不是日后的创作主题。测试必须证明它们不会被
序列化进生产 prompt、memory、选题信号或发布候选。不同 fixture 应产生不同 frame
plan，同时共享同一 Design System。现有内容、合规、checkpoint 恢复和发布导出测试
继续通过。

## 迁移与清理

1. 先新增新 schema、选择算法和兼容 adapter，不删除旧 renderer。
2. 增加本地字体、素材 manifest 和 Asset Resolver。
3. 用 TDD 实现新 renderer 与 11 个 layout。
4. 接入新 graph 和 QA，golden fixtures 走新路径。
5. 将旧 checkpoint 测试切到 legacy adapter。
6. 全量测试与四个 golden 渲染通过后，删除旧固定模板 schema、旧 renderer、Pexels-only
   sourcing 和 URL-description-only image QA。

不允许同时长期维护两个生产 renderer；旧实现只在迁移阶段存在。

## 验收标准

- Agent 离线完成视觉规划、素材解析和本地渲染，不调用图像生成 API。
- 四类合成 golden fixture 自动选择不同主视觉家族和不同 frame plan。
- 分区用量测试 fixture 生成约定的六页语义结构，但生产代码不包含特定标题判断。
- 测试 fixture 不进入生产 prompt、memory、选题信号或发布候选。
- 所有页面使用项目内字体，无系统 fallback。
- 每套至少三种 layout、一个保存页、一个有意义的视觉主体。
- 完整测试套件通过，真实 Chromium smoke test 通过。
- Human Review 能看到 contact sheet、单页图片、布局和 QA，而不是只看到 JSON。
- 旧的固定六卡顺序、提问结尾和空白文字卡不再出现在生产路径。
