# 美容编辑式图文工作流设计

## 状态

已于 2026-07-14 完成书面规格审核。该设计在实现后取代
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
- 自动主流程不调用 Codex 内置图像生成；只在最终交付包中生成一个由人手动交给 Codex
  使用的可选视觉救援 prompt。

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

### ContentLock

最终交付阶段从已通过 R2、Carousel QA、Render QA 和 Human Review 的 publish package
生成不可变 `ContentLock`：

```python
class ContentLock(BaseModel):
    focus_keyword: str
    topic: str
    topic_id: str
    angle: str
    angle_id: str
    target_group: str
    core_pain: str
    title: str
    cover_copy: str
    first_screen_promise: str
    content: str
    hashtags: list[str]
    storyboards: list[dict]
    canonical_sha256: str
```

`canonical_sha256` 对上述字段按固定 key 顺序、UTF-8、无多余空白的 canonical JSON 计算。
ContentLock 只用于导出一致性和人工视觉救援，不进入选题 prompt、memory 或下一篇文章。

## 混合素材策略

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

Asset Resolver 采用“本地优先、缺口触发外部检索”的决策链。对每个 visual slot：

1. 在 `active` 中按 role、layout、语义标签、方向、分辨率、裁切安全区、近期重复限制和
   禁用场景做硬过滤，再按视觉匹配度排序。
2. 只要存在通过硬过滤且达到匹配阈值的本地素材，就从本地选择，不调用外部服务。
3. 如果没有合格本地素材，同时检索 Pexels 和 Unsplash；两个 provider 的结果归一化后
   进入同一个候选池统一过滤、去重和排序，不按 provider 预设审美优先级。
4. 如果外部检索不可用或没有合格结果，才使用 manifest 中语义适配的显式 fallback；
   fallback 也不合格则失败并返回可操作错误，不得渲染空白占位或无关图片。

“没有合格本地素材”既包括没有对应 role，也包括素材尺寸不足、无法安全裁切、与当前
语义不符、含禁用元素或因近期重复限制被排除；不能仅以文件存在作为“可用”。

外部检索只补充照片、质地、无品牌容器和手部/皮肤局部等原始视觉素材，不搜索或复刻
Canva、小红书模板，不下载带文字的成品版式，也不替代项目原创 SVG、字体、图标和布局。
检索词来自结构化 `VisualSlot` 的 role、英文语义标签、构图和色彩条件；LLM 仍不能提供
网络 URL。provider adapter 负责调用官方接口、返回真实候选 URL 和来源元数据。

Pexels 与 Unsplash adapter 是 Asset Resolver 深模块内部实现，不新增 graph node，也不
改变 VisualPlan、Storyboard 或 Renderer 的外部 interface。缺少某个 provider 的凭据、
限流或超时只禁用该 provider；另一个 provider 和本地 fallback 仍可继续。两个 provider
都不可用且无合格 fallback 时，本次运行阻止发布。

### 素材入库与持续积累

正式素材库与历史发布产物分开管理。`outputs/publish` 只保存最终成品，不能被 Asset
Resolver 当作素材目录扫描；只有通过审核并写入 manifest 的原始素材才能被生产流程
使用。

目录分为三个生命周期区：

```text
assets/visual/beauty-editorial-v1/
  incoming/
    manual/       # 人工导入的候选素材
    external/     # 按 run_id 保存的 Pexels/Unsplash 待审候选
  active/         # 已审核、可用于生产
  retired/        # 过时、重复或质量不足，不再选用
  licenses/       # 许可证文本或获取时的条款快照
  references/     # 只供人工 Codex 救援读取的质量锚点，Asset Resolver 禁止选择
  manifest.json
```

`references` 至少包含封面、图解页和保存卡三个抽象命名的 `reference_only` 质量锚点，来自
已确认的高质量美容编辑式套图。它们只约束纸张质感、配色、线稿、材质、留白、层级和
精致度；其中的标题、正文、选题和页面顺序不得被复制。reference manifest 必须标记
`usage: reference_only`，Asset Resolver 和生产 Renderer 都不得把它们当作可合成素材。

每个素材必须经过以下步骤：

1. **收集**：人工候选放入 `incoming/manual`；外部检索命中的原图或官方允许的交付尺寸
   下载到 `incoming/external/<run_id>`。同时记录 provider、素材页 URL、原始文件 URL、
   作者、获取日期、provider asset ID 和来源类型，不能只记录缩略图 URL。
2. **权利审核**：确认是项目原创、用户自有、明确许可的字体/图库素材或允许使用的衍生
   素材；不确定则拒绝。
3. **技术规范化**：检查分辨率、透明通道、色彩空间、文件体积、重复哈希和恶意元数据；
   转为 SVG、PNG 或 WebP 的标准规格。
4. **视觉审核**：检查美容类别感、构图可裁切性、颜色、清晰度、品牌/水印/可识别人脸
   风险，以及是否能承担明确的 asset role。
5. **语义标注**：填写 asset role、适用 layout、朝向、区域、质地、主色、fallback 和
   禁用场景。
6. **预览与人工晋级**：外部候选可以按待审状态参与本次预览渲染，但 Human Review 必须
   展示来源、作者、许可说明和实际裁切结果。人明确批准后，系统才可把相同 sha256 的
   文件移动到 `active` 并写入 manifest；代码不得在无人批准时自动晋级。
7. **使用反馈**：记录使用次数、最近使用时间、人工评分和失败原因，用于避免连续重复。
8. **退役**：重复、低质量、授权变化或风格过时的素材移动到 `retired`，保留审计记录。

Manifest 至少包含：

```json
{
  "asset_id": "serum_drop_001",
  "role": "serum_drop",
  "path": "active/skincare-textures/serum-drop-001.webp",
  "source_type": "project_original",
  "provider_asset_id": null,
  "source_url": null,
  "source_file_url": null,
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

外部候选还必须记录 `review_status`（`pending`、`approved` 或 `rejected`）、`run_id`、
provider 返回的原始许可证/归属字段和条款快照。正式渲染引用的字节哈希必须与 Human
Review 批准并晋级到 `active` 的哈希一致；Final Policy Guard 对不上时阻止发布。

### 外部检索、采用与回收

外部候选按以下顺序处理：

1. Pexels 与 Unsplash provider 根据同一个结构化需求并发检索，并各自保存查询、响应时间、
   结果 ID 和失败原因；不得抓取网页或搜索引擎缩略图作为 API 失败后的替代方案。
2. 将候选归一化为 `ExternalAssetCandidate`，至少包含 provider、asset ID、作者、素材页
   URL、可交付文件 URL、尺寸、方向、主色、许可字段和下载/归属要求。
3. 先做硬过滤：最小分辨率、目标比例可裁切性、无水印/Logo/二维码/内嵌文字、无可识别
   真人正脸、role 兼容、来源字段完整，以及 provider 使用要求可被当前发布流程满足。
4. 再按语义匹配、构图留白、品牌色兼容、清晰度和近期使用重复度排序。provider 名称不
   参与加分，防止长期偏向单一图库风格。
5. 按 provider 要求记录下载事件，下载入 `incoming/external/<run_id>`；使用 source URL、
   provider asset ID、sha256 和感知哈希做跨 provider、跨运行去重。
6. 每个 slot 最多下载统一候选池排名前三的候选，避免无界扩张；其余候选只保留检索审计
   记录，不落盘原图。
7. Human Review 批准某个候选后才晋级 `active`。拒绝时尝试同一 slot 的下一个合格候选；
   候选耗尽则使用显式 fallback，否则阻止发布。

外部搜索是素材缺口修复机制，不是每次运行的默认步骤。已批准素材进入 `active` 后，后续
相同需求优先复用本地版本；使用频率、最近使用时间和人工评分继续参与选择，避免连续帖子
出现同一张图。

### 素材来源优先级

按风险从低到高使用：

1. 项目原创的 SVG/CSS：脸部线稿、区域 mask、液滴、泵头、箭头、页码和背景纹理。
2. 用户自行拍摄且拥有权利的皮肤局部、手部、质地和无品牌容器照片。
3. 官方以开源字体许可证发布的字体文件，并随仓库保存许可证。
4. 缺少合格本地素材时，通过官方 Pexels/Unsplash provider 检索、下载、记录条款并经
   Human Review 批准的图库素材；只用于最终图文组合，不把素材库包装成图库产品。
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
- 旧 Pexels-only `image_sourcing` 替换为本地优先、Pexels/Unsplash 缺口检索的
  `asset_resolver`。
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

外部只暴露这一个深模块 interface。模块内部包含本地 catalog、Pexels adapter、Unsplash
adapter、候选归一化、硬过滤、排序、下载、去重和待审入库；graph 不直接了解 provider。
`AssetManifest` 对每个 slot 标记 `active`、`pending_external` 或 `fallback`，并附带一份
`AssetSearchReport`，说明是否触发检索、查询条件、各 provider 结果/错误和最终选择理由。

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

## 最终交付包与人工 Codex 视觉救援

完整成功运行指 Human Review 已批准、Final Policy Guard 无问题、内容已写入结构化与向量
数据库，并完成安全导出。每篇最终目录固定为：

```text
outputs/publish/<YYYYMMDD>-<domain>-<subdomain>-<title>/
  images/
    01-cover.png
    02-<frame-role>.png
    ...
    05~07-<frame-role>.png
  publish-copy.txt
  codex-image-regeneration-prompt.txt
  <title>.json
```

`publish-copy.txt` 使用 UTF-8 和 LF，内容严格为“标题、空行、短正文、空行、空格连接的
hashtags、末尾换行”。它不包含 storyboard、QA、素材来源或内部说明。

`codex-image-regeneration-prompt.txt` 是供人对 `images/` 不满意时手动交给 Codex 的
自包含救援指令。生成该文本本身不调用图像模型、API 或网络。prompt 必须：

- 声明这是 `visual-only regeneration`，不是重新选题或重新写作。
- 要求先读取同目录 `<title>.json`、现有 `images/` 和项目内 `reference_only` 质量锚点。
- 内嵌 ContentLock canonical JSON、`canonical_sha256` 和每页逐字可见文字，避免只依赖
  路径或自然语言概述。
- 锁定 `focus_keyword`、topic/angle、目标人群、核心痛点、标题、封面承诺、正文、hashtags、
  frame 数量/顺序/角色以及 storyboard 所有可见文字。
- 禁止增加、删除或改写护肤结论、步骤、用量、判断标准、风险提示和新事实；缺字段时
  停止并报告，不能补写。
- 允许改变的只有布局实现、换行、字体层级、留白、素材、插画、背景、光影、裁切和
  Design System 内的色彩组合；每页的信息任务和文字归属不变。
- 指导 Codex 使用内置 image generation，而不是 CLI/API：先用 `view_image` 检查当前套图
  与三个质量锚点，再逐页生成美容视觉底图；封面作为 style anchor，后续页面同时参考
  封面和上一页，每个不同页面单独调用一次图像生成。
- 图像生成负责纸张/液体质地、面部线稿、分区图、无品牌容器和光影；中文使用项目字体
  进行确定性本地叠加，不让图像模型自由生成或改写文字。
- 每页验证 `1080 × 1440`、无 Logo/水印/二维码/真人正脸、文字逐字一致、主体与内容语义
  对应；最终通过 contact sheet 检查美容编辑感、跨页一致性、版式变化和可保存性。
- 把结果写入同目录第一个不存在的 `images-codex-vN/`，不得覆盖 `images/`、文章 JSON、
  `publish-copy.txt` 或之前的 `images-codex-vN/`。

该 prompt 不能保证随机图像模型每次达到完全相同的像素质量；它通过真实质量锚点、Style
Lock、逐页生成、确定性中文叠加和最终人工检查，把结果约束在已确认的美容编辑方向。
救援目录不是自动 Agent 的正式输出，只有用户检查并主动采用后才替代上传文件。

## 错误处理

- VisualPlan、Storyboard 或 manifest schema 无效：失败并回到 R1，不猜测补字段。
- 缺少合格本地素材：检索 Pexels 与 Unsplash；外部无合格候选或均不可用时使用显式
  fallback，没有合格 fallback 则阻止发布。
- 外部候选 provenance 不完整、下载哈希变化或 Human Review 未明确批准：阻止发布。
- 单个 provider 超时、限流或缺少凭据：记录到 `AssetSearchReport` 并继续另一个 provider；
  不进行网页抓取降级。
- 字体加载失败或发生 fallback：阻止截图进入通过状态。
- 任意页面截图失败：删除本次所有部分输出。
- QA 失败：保留审计结果，但不进入 Human Review。
- 旧 checkpoint：通过单一 legacy adapter 升级，不把兼容分支散落在各节点。
- 最终导出缺少 ContentLock 必填字段、canonical hash 不一致或交付文件写入不完整：清理
  本次新建的文本/JSON 临时文件并拒绝标记导出成功，不删除已经通过 Render QA 的图片。

## 测试策略

### Schema 与选择算法

- 每种 `content_job` 映射到正确主视觉家族。
- 多任务内容以 `decision_problem` 为主，其余成为辅助家族。
- 5–7 页限制、layout/family 兼容和保存页约束。
- 有合格本地素材时不调用任何外部 provider。
- 本地候选缺失、质量不合格或被近期重复限制排除时触发 Pexels 与 Unsplash。
- 两个 provider 候选经过统一硬过滤、排序和跨来源去重；provider 部分失败可降级。
- 外部候选未经明确人工批准不能进入 `active`，也不能通过 Final Policy Guard。

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
- Human Review payload 包含待审外部素材的作者、来源页、许可说明、裁切预览和批准动作。
- 外部素材批准后，`AssetManifest` 记录的源素材 sha256、`RenderManifest` 记录的所用源素材
  sha256 和 `active` 中实际源文件的 sha256 三者一致。
- `publish-copy.txt` 的标题、正文和 hashtags 逐字来自最终 publish package。
- ContentLock canonical 序列化稳定，任一锁定字段变化都会改变 sha256。
- 救援 prompt 包含当前选题/关键词和逐页文字，但不包含测试 fixture 标题、旧文章内容或
  重新创作指令；prompt 要求输出到不覆盖原图的 `images-codex-vN/`。

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
2. 增加本地字体、素材 manifest，以及本地 catalog、Pexels、Unsplash adapter 组成的 Asset
   Resolver；用 fake provider 完成确定性测试，真实网络只做显式 opt-in 集成测试。
3. 用 TDD 实现新 renderer 与 11 个 layout。
4. 接入新 graph 和 QA，golden fixtures 走新路径。
5. 将旧 checkpoint 测试切到 legacy adapter。
6. 在最终导出中增加 `publish-copy.txt`、ContentLock 和人工 Codex 视觉救援 prompt，保持
   自动 graph 不调用图像生成能力。
7. 全量测试与四个 golden 渲染通过后，删除旧固定模板 schema、旧 renderer、Pexels-only
   sourcing 和 URL-description-only image QA。

不允许同时长期维护两个生产 renderer；旧实现只在迁移阶段存在。

## 验收标准

- 有合格本地素材时，Agent 离线完成视觉规划、素材解析和本地渲染，不发生网络请求；缺少
  合格素材时才调用 Pexels/Unsplash 官方 provider，始终不调用图像生成 API。
- 外部检索候选只有在 provenance 完整、技术与视觉过滤通过并经 Human Review 明确批准后
  才能进入 `active` 和最终发布；后续相同需求优先复用该本地素材。
- 四类合成 golden fixture 自动选择不同主视觉家族和不同 frame plan。
- 分区用量测试 fixture 生成约定的六页语义结构，但生产代码不包含特定标题判断。
- 测试 fixture 不进入生产 prompt、memory、选题信号或发布候选。
- 所有页面使用项目内字体，无系统 fallback。
- 每套至少三种 layout、一个保存页、一个有意义的视觉主体。
- 完整测试套件通过，真实 Chromium smoke test 通过。
- Human Review 能看到 contact sheet、单页图片、布局和 QA，而不是只看到 JSON。
- 每个成功导出的发布目录包含 `images/`、`publish-copy.txt`、
  `codex-image-regeneration-prompt.txt` 和 `<title>.json`；救援 prompt 的 ContentLock 与
  JSON 一致，并明确禁止内容重写和覆盖原图。
- 旧的固定六卡顺序、提问结尾和空白文字卡不再出现在生产路径。
