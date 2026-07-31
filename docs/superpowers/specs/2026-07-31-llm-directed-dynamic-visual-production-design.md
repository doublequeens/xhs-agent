# LLM 主导的动态视觉生产工作流设计

## 状态

日期：2026-07-31

状态：对话设计已确认；等待书面规格复核。

本设计完整取代当前六模板固定 HTML/CSS 生产架构，以及
`docs/superpowers/specs/2026-07-16-adaptive-six-template-content-workflow-design.md`
中关于 5–7 页、固定 template renderer、page archetype renderer 和有限
composition variant 的视觉生产设计。

## 1. 背景与问题

当前实现虽然会在六个 `template_family` 中选择一个家族，也会根据字数和条目数量选择
density 与 composition variant，但最终仍然由六组 Python/HTML/CSS 分支决定页面结构。
LLM 只产生文案和有限的 storyboard 字段，不能真正决定：

- 每页的信息层级与视觉焦点；
- 元素位置、尺寸、对齐和分组；
- 页内留白、颜色比例和装饰关系；
- 图片与文字的构图；
- 整套 carousel 的视觉节奏；
- 根据内容量决定 5–18 页的实际分页。

当前所谓“动态”主要是从写死的布局集合中选择一个分支，再把文字填入固定 slot。
近期修复也集中在单个 family、archetype 和 density 组合的 CSS 溢出与 probe 顺序，
说明生产质量仍受固定模板结构约束。

本设计把视觉设计权交给 LLM，同时保留严格的内容锁、结构化 schema、素材安全、
确定性 QA、Chromium 渲染、最终人工审核和本地发布边界。

## 2. 已确认的产品决策

1. HTML/Chromium 可以继续作为底层渲染技术，但不能继续承载固定页面模板逻辑。
2. LLM 不直接生成 HTML、CSS 或 JavaScript；它生成结构化 scene graph。
3. 六个 family 继续存在，但只作为 Visual DNA，不再定义页面结构。
4. 一套 carousel 只选择一个 family；每页可以在该 family 内自由改变构图、颜色比例、
   留白、装饰和信息密度。
5. 视觉 LLM 不得增删、改写、缩写或替换任何可见文字。
6. 视觉 LLM 可以在不改变字符的前提下换行、分组、强调，并按句子、列表项或步骤边界
   拆分内容、重新分页。
7. 最终页数由视觉导演根据文案决定，最少 5 页，最多 18 页。
8. 六套参考样张的页数不构成生产页数或页面顺序约束。
9. 视觉导演可以要求搜索许可图片，或调用图片模型生成真实风格的视觉示例。
10. 图片只是视觉示例，不能替代 `EvidenceBrief` 对事实和健康内容的支持。
11. 图片中不得自动加入“AI 生成”“示意图”“仅供参考”或任何免责声明。
12. AI 来源和生成信息只写入内部 manifest；用户在上传平台时统一完成 AI 内容标注。
13. 素材自动搜索/生成、安全检查、排版和视觉复核完成后，只进行一次整套 Human Review。
14. 技术 QA 不允许强制放行；审美复核最多自动修改两轮，之后可带问题进入 Human Review。
15. 不符合新架构的旧视觉 node、合同和 renderer 必须从生产 workflow 中删除，不能保留
    双轨、fallback、feature flag 或兼容调用。

## 3. 目标

新工作流必须实现：

- LLM 根据整篇文案主动决定 art direction、页数、分页、素材需求和每页构图。
- 相同 family 的不同内容可以生成明显不同但品牌一致的 carousel。
- 页面不依赖固定 `cover/steps/comparison/save` HTML 结构。
- 所有可见文字都有唯一来源和哈希证明，视觉阶段无法静默改文案。
- 图片搜索和生成是正式视觉能力，并遵守 provider、许可、路径、哈希和事务边界。
- HTML renderer 成为通用 scene graph 执行器，而不是 family 模板选择器。
- 确定性 QA 负责技术正确性，多模态视觉模型负责审美复核。
- 运行可以 checkpoint、恢复和审计，每轮设计修改都可追踪。
- 最终输出仍是本地发布包，不自动登录、上传或发布到小红书。

## 4. 非目标

- 不实现浏览器内拖拽编辑器。
- 不允许 LLM 执行任意代码或输出自由 HTML/CSS。
- 不允许视觉阶段生成新的事实、标签、免责声明或互动话术。
- 不让生成图片承担医学诊断、科学证据或因果证明。
- 不通过降低到不可读字号、截断、省略号或隐藏文字解决溢出。
- 不保留旧固定模板作为新架构失败时的救援路径。
- 不在本项目中自动完成平台级 AI 内容标注或发布。

## 5. 新生产拓扑

内容阶段保持现有 domain、选题、证据、写作、R1/R2、标题、hashtag 和 assembler
主链。Assembler 之后的视觉生产路径替换为：

```text
assembler
-> content_atomizer
-> visual_director
-> asset_resolver
-> page_designer
-> design_plan_qa
-> generic_scene_renderer
-> render_qa
-> visual_critic
-> human_review
-> final_policy_guard
-> content_writer
```

修订回路：

```text
design_plan_qa failed
-> design_reviser
-> design_plan_qa
```

```text
render_qa failed
-> design_reviser
-> design_plan_qa
-> generic_scene_renderer
-> render_qa
```

```text
visual_critic failed and revision_round < 2
-> design_reviser
-> design_plan_qa
-> generic_scene_renderer
-> render_qa
-> visual_critic
```

Human Review 仍位于所有硬 QA 之后。Final Guard 仍位于 Human Review 之后。

## 6. 组件职责

### 6.1 Content Atomizer

Content Atomizer 把 assembler 的规范文案转换成不可变 `ContentAtomSet`。它为标题、
封面文案、正文句子、列表项、步骤和其它允许进入图片的可见文字分配稳定 `atom_id`，
并保存每个 atom 与全集的 SHA-256。Hashtags、审计字段和其它 publish-only metadata
不进入图片 atom，也不得被视觉阶段自行加入图片。

它不总结或改写文案。视觉阶段只能通过 `content_ref` 引用 atom 或经过验证的 fragment。

### 6.2 Family Style Registry

六个 family 保留以下 ID：

```text
pink_red
deep_teal
soft_pink
coral_impact
green_catalog
white_quote
```

每个 family 的 `FamilyStyleProfile` 只描述：

- 视觉情绪、品牌特征与适配倾向；
- 色相、明度、饱和度和对比度范围；
- 字体文件与 display/body/numeral 等字体角色；
- 图形、线条、圆角、阴影、纹理和装饰语言；
- 留白、密度、摄影和图片处理倾向；
- 允许与禁止的设计模式；
- 一组经过批准的参考图片。

Style Profile 不得包含固定 DOM、固定坐标、固定页面数量、固定 archetype layout 或
可直接执行的模板代码。参考样张只用于帮助多模态 LLM 理解视觉 DNA。

### 6.3 Visual Director

Visual Director 是整套 carousel 的视觉决策者。它读取：

- `ContentAtomSet`；
- `NarrativePlan`、内容合同、domain/profile 和证据摘要；
- 六个 `FamilyStyleProfile` 与参考图；
- 最近内容的视觉签名；
- 1080×1440 画布、字体和安全边界；
- 图片搜索、生成和素材安全能力。

它一次性输出 `VisualDirectionPlan`：

- 唯一 `template_family`；
- 5–18 页 `page_count`；
- 整套 art direction；
- 本篇使用的颜色与字体角色；
- 每页目的、密度、内容 fragment 和视觉任务；
- 整套页面节奏；
- 每页的 `AssetDirective`。

Visual Director 不输出 HTML，也不决定浏览器实现细节。

### 6.4 Asset Resolver

Asset Resolver 读取每个 `AssetDirective`，自动执行允许的来源策略：

```text
licensed_search
llm_generation
search_then_generate
generate_then_search
none
```

每个 directive 必须声明 `required` 或 `optional`。Resolver 负责：

- 搜索 provider 或图片生成 provider；
- provider identity、许可、路径 containment 和 no-follow；
- 下载/生成事务、字节哈希和 recovery evidence；
- 图片尺寸、主体焦点、建议裁剪区域；
- 内部 provenance、模型和 prompt 记录；
- pending/rejected/approved 状态。

Asset Resolver 不向图片或页面注入 AI 来源说明、示意图标签或免责声明。

新 manifest 区分自动素材安全状态与最终人工决定。只有通过 provider、许可、路径、
no-follow、哈希和事务检查的素材才能得到 `security_status=approved` 并进入 renderer；
`human_decision` 在整套 Human Review 前保持 pending。最终 Human Review 一次性检查页面
与素材并记录人工决定，不在素材获取过程中插入额外人工中断。

### 6.5 Page Designer

Page Designer 必须看到整套 carousel，而不是孤立设计单页。它读取：

- `VisualDirectionPlan`；
- `ContentAtomSet`；
- 已批准 `AssetManifest`；
- family Visual DNA 与参考图；
- 前后页面的视觉任务和设计摘要；
- scene graph schema 与硬约束。

它输出 `CarouselDesignPlan`。每页是一棵 scene graph，初版允许以下通用原语：

```text
text
image
shape
line
icon
group
stack
grid
```

每个元素声明唯一 ID、box、layer、alignment、style token、父子关系和必要的内容或素材
引用。Text 只能使用 `content_ref`；Image 只能使用 `asset_ref`。

Page Designer 可以决定换行、分组、视觉强调和页面内顺序，但不得改变 atom 字符。

### 6.6 Design Plan QA

Design Plan QA 在启动浏览器前确定性验证：

- 页数、页面 ID、单 family 和 direction hash；
- atom/fragment 完整覆盖、顺序、无改字、无漏字、无重复；
- 不存在未经授权的可见文字；
- scene graph 类型、父子关系和 layer 合法；
- box、safe margin、字号、颜色和预估对比度；
- asset 引用、page 绑定和 manifest hash；
- 不存在任意 HTML、CSS、JavaScript 或外部 URL；
- 不存在 AI 来源标签或系统免责声明。

失败必须产生 page/element/atom 级问题并进入 `design_reviser`。

### 6.7 Generic Scene Renderer

Generic Scene Renderer 只负责把合法 scene graph 编译成受控 HTML/CSS，使用 Chromium
生成 1080×1440 PNG 和 contact sheet。

Renderer 可以实现通用字体加载、text measurement、absolute positioning、stack、
grid、shape、crop、clip、mask 和 layer，但不得出现：

```python
if family == "pink_red" and page_archetype == "steps":
    ...
```

Family 只通过数据化 token 和已验证的设计计划影响输出。Renderer 不能根据内容类型
私自选择固定版式，也不能增加可见文字。

### 6.8 Render QA

Render QA 使用实际 DOM 与 PNG 结果验证：

- 所有 text atom 的字符、出现次数和顺序；
- 实际 bounding box、overflow、遮挡和画布边界；
- safe margin、最小字号和对比度；
- 字体加载、emoji 和 glyph；
- 图片 crop、主体区域和素材哈希；
- 页面尺寸、顺序、PNG 哈希和 contact sheet；
- `CarouselDesignPlan`、`AssetManifest` 与 `RenderManifest` 的哈希绑定。

硬 QA 未通过时不能进入视觉审美复核或 Human Review。

### 6.9 Visual Critic

Visual Critic 使用支持看图的模型读取每页 PNG、contact sheet、Visual DNA、锁定内容和
Design Plan。它检查：

- 第一视觉焦点和信息层级；
- 构图平衡、留白、颜色和字体关系；
- 相邻页面与整套节奏；
- family 一致性；
- 页面重复度；
- 图片相关性、裁剪和视觉权重；
- 明显的生成图片瑕疵；
- 内容情绪与视觉表达是否匹配。

Visual Critic 输出结构化 `VisualCritique`，只能提出设计修改，不能要求改写文字。

初始通过阈值：

```text
overall >= 80
hierarchy >= 70
family_consistency >= 75
page_rhythm >= 70
image_relevance >= 70
```

`image_relevance` 只对实际包含图片的页面和套图计算；纯文字 carousel 记为 not_applicable，
不能因为没有图片被计为零分。

最多自动修改两轮。两轮后仍不通过时，以 `visual_needs_attention` 进入 Human Review，
并展示未解决问题；只有审美评分可以由人工覆盖。

### 6.10 Design Reviser

Design Reviser 接受确定性 QA 或 Visual Critic 的原子问题，对现有
`CarouselDesignPlan` 产生结构化 revision。它可以：

- 移动、缩放、重新分组元素；
- 调整字号、行高、留白、颜色和装饰；
- 改变图片 crop、区域或视觉权重；
- 在既定分页内改变构图；
- 在 Visual Director 授权范围内重新分页。

它不能改变 `content_ref` 指向的字符、素材 provenance、family 或硬安全规则。需要改变
family 或重新规划全套页数时，必须显式返回 Visual Director，而不是局部 patch。

## 7. 数据合同

### 7.1 ContentAtomSet

```python
class ContentAtom:
    atom_id: str
    text: str
    role: str
    sha256: str

class ContentFragment:
    fragment_id: str
    source_atom_id: str
    start: int
    end: int
    text: str

class ContentAtomSet:
    atoms: list[ContentAtom]
    canonical_sha256: str
```

`ContentAtomSet` 只保存不可变 atom。Fragment 由 Visual Director 创建并保存到
`VisualDirectionPlan.content_fragments`。Fragment 只能沿句子、列表项或步骤边界创建。
Validator 必须证明同一 atom 的所有 fragment 按原顺序拼接后与原文逐字符一致。

### 7.2 VisualDirectionPlan

核心字段：

```text
template_family
page_count
content_atom_set_sha256
art_direction
palette
typography_direction
motifs
content_fragments
page_sequence
asset_directives
recent_visual_context
```

`page_count` 必须为 5–18。每一页必须有独立 `purpose`、`visual_job` 和至少一个内容
fragment，不允许为了增加页数生成空洞过渡页。

### 7.3 AssetDirective 与 AssetManifest

Directive 描述“需要什么”，Manifest 描述“实际获得什么”。Manifest 必须绑定：

```text
asset_id
page_id
source_kind
provider
license
local_path
width/height
sha256
subject_focal_point
crop_guidance
security_status
human_decision
transaction/run identity
internal provenance
```

生成模型、prompt 和 AI provenance 仅进入内部数据，不进入页面可见文字。

### 7.4 CarouselDesignPlan

核心字段：

```text
direction_plan_sha256
content_atom_set_sha256
asset_manifest_sha256
revision
pages[5..18]
pages[*].elements
```

Text 元素必须包含 `content_ref`，Image 元素必须包含 `asset_ref`。Shape、Line 和 Icon
只能使用批准的结构化字段，不允许携带自由 HTML。

### 7.5 DesignPlanQAResult

记录：

```text
passed
issues[]
design_plan_sha256
content_coverage_attestation
family_attestation
asset_binding_attestation
```

每个 issue 至少包含 rule、page_id、element_id 或 atom_id、错误信息和修复方向。

### 7.6 RenderManifest

RenderManifest 支持 5–18 页，并记录：

```text
design_plan_sha256
content_atom_set_sha256
asset_manifest_sha256
revision
pages
fonts
contact_sheet_path/hash
source_asset_sha256
```

每个 RenderedPage 记录 PNG 路径与哈希、实际元素 probe、文字证明、图片裁剪、字体和
画布尺寸。

### 7.7 VisualCritique

记录评分、是否通过、revision round、page/element 级问题和明确 revision instruction。
VisualCritique 是审美反馈，不得成为绕过硬 QA 的凭证。

## 8. 全链路不变量

1. 图片内的可见文字只能来自 `ContentAtomSet`。
2. 视觉阶段不得新增、删除、改写、缩写或替换文字。
3. 视觉阶段可以换行、分组、强调和按语义边界拆分分页。
4. 页面不得自动加入 AI 标识、示意图标签或免责声明。
5. 一套 carousel 只使用一个 family。
6. 页数必须为 5–18，由 Visual Director 根据内容决定。
7. 每页必须承担独立内容任务，不能用重复或空洞页面凑页数。
8. 六套样张只定义视觉参考，不定义页面数量、页面顺序或固定布局。
9. 所有图片必须通过 AssetManifest 的来源、安全、许可和哈希检查。
10. 图片是视觉示例，不替代 EvidenceBrief。
11. Design Plan、素材、DOM probe 和最终 PNG 必须通过哈希绑定。
12. 技术 QA 失败不得静默放行或回退旧 renderer。
13. 旧视觉 node 和合同不得重新进入生产 workflow。
14. Human Review 只在整套自动生产和视觉复核完成后进行。
15. Final Guard 仍在 Human Review 后执行。

## 9. 失败处理

### 9.1 LLM schema 或内容合同失败

Visual Director 和 Page Designer 的 schema/内容错误最多自修复三次。三次仍失败时：

- 保存最后输出、精确错误和 checkpoint；
- run 状态标记为 `interrupted`；
- 允许 `--resume`；
- 不生成默认五页；
- 不回退旧节点。

### 9.2 素材失败

- 搜索失败时按 directive 执行允许的 generation fallback。
- 生成失败时按 directive 执行允许的 search fallback。
- optional 素材全部失败时返回 Design Reviser 生成无图版本。
- required 素材全部失败时中断任务并保留 recovery evidence。
- 许可、路径、no-follow、哈希或事务验证失败时阻断该素材。
- 清理失败不能覆盖原始素材错误。

### 9.3 Design Plan QA 失败

Design Plan QA 与 Design Reviser 最多循环三轮。三轮后仍失败则中断并 checkpoint，
不能进入 renderer。

### 9.4 Renderer 与 Render QA 失败

瞬时 Chromium/截图错误可以对同一 plan 原样重试一次。确定性设计错误必须返回
Design Reviser，最多三轮。Render QA 未通过时不能进入 Visual Critic 或 Human Review。

### 9.5 Visual Critic 失败

最多自动修订两轮。仍不通过时进入 `visual_needs_attention` Human Review，并保留问题
和评分。人工只能覆盖审美结果，不能覆盖内容完整性、素材安全或 Render QA。

## 10. Human Review 路由

| 人工操作 | 后续路由 |
| --- | --- |
| 直接批准 | `final_policy_guard` |
| 只提出构图、颜色、图片或排版反馈 | `design_reviser` |
| 修改任何可见文字 | 清除全部视觉产物，返回 R2、assembler 和 `content_atomizer` |
| 替换或拒绝图片 | `asset_resolver -> page_designer -> 全套 QA` |

人工替换图片后不能保留旧 RenderManifest。任何文字变化都会使 ContentAtomSet、
VisualDirectionPlan、AssetManifest、CarouselDesignPlan、RenderManifest 和
VisualCritique 失效。

人工批准 `visual_needs_attention` 时必须生成显式 aesthetic override attestation。
Final Guard 可以接受该人工审美覆盖，但仍必须拒绝任何未通过的 Design Plan QA、
Render QA、素材安全、内容哈希或合规检查。

## 11. Checkpoint、恢复与迁移

以下合同成功生成后立即 checkpoint：

```text
ContentAtomSet
VisualDirectionPlan
AssetManifest
CarouselDesignPlan
DesignPlanQAResult
RenderManifest
VisualCritique
Human Review
```

每轮记录 revision、输入/输出哈希、来源节点、修改原因、provider/model、耗时和错误。
恢复时从最后一个完整且哈希一致的合同继续，不重复已完成的下载或图片生成事务。

旧 checkpoint 迁移规则：

1. 保留内容、R1/R2、标题、hashtags 和 assembler 结果。
2. 丢弃旧 VisualPlan、Storyboard/CarouselPayload、AssetManifest、RenderManifest 和视觉
   QA 状态。
3. 记录 migration reason。
4. 从 `content_atomizer -> visual_director` 重新开始。
5. 迁移器不得执行旧 node，也不得把旧固定布局转换成新 scene graph。

## 12. 旧生产路径删除范围

最终生产图必须删除或替换：

| 旧实现 | 新处理 |
| --- | --- |
| `visual_strategy_planner` | 删除，由 `visual_director` 替代 |
| 固定 `storyboard_generator` | 删除，分页进入 Visual Director，页面设计进入 Page Designer |
| 固定 template selector/variant resolver | 删除 |
| 六套 family-specific HTML/CSS renderer | 从生产实现中删除 |
| 当前 `carousel_qa` | 删除，由 `design_plan_qa` 替代 |
| 当前 `editorial_carousel_renderer` | 删除，由 `generic_scene_renderer` 替代 |
| 当前 Render QA 的固定模板假设 | 删除，改为 scene graph 和实际几何检查 |
| Carousel QA 三次失败后强制放行 | 删除 |
| beauty 强制 `proof_mode=none` | 删除 |
| 5–7 页 schema/manifest/contact-sheet 限制 | 改为 5–18 |

最终代码中不得存在新旧双轨、旧 renderer fallback、feature flag 或兼容调用。素材
directive 明确声明的 search/generation 来源 fallback 不受此限制。旧名称只允许出现在
历史 spec、checkpoint migration 说明和明确断言其不存在的测试中。

## 13. 测试策略

### 13.1 合同测试

必须覆盖：

- 5/18 页合法，4/19 页拒绝；
- 单 family；
- fragment 无损还原；
- 漏字、改字、重复和额外文字拒绝；
- AI 标签和免责声明注入拒绝；
- design/asset/render hash 绑定；
- scene graph 禁止自由 HTML/CSS/JavaScript；
- Human Review 文字变更使全部视觉合同失效。

默认测试不调用真实 LLM。

### 13.2 Renderer 测试

逐一验证所有通用原语、嵌套、layer、字体、中文、数字、emoji、换行、图片 crop、
5/9/18 页、1080×1440、contact sheet、staging 与事务清理。测试不得包含
family-specific 页面结构断言。

### 13.3 Asset Pipeline 测试

使用离线 fake provider 验证双向 fallback、required/optional、许可、no-follow、
containment、哈希、provenance、checkpoint 恢复和无可见 AI/免责声明文字。真实搜索和
图片生成只作为显式 live smoke tests。

### 13.4 Plan QA 与 Render QA 测试

注入最小失败案例：越过 safe margin、元素重叠、文字溢出、错误 asset 绑定、字体
fallback、对比度不足、PNG 修改、contact sheet 错序和 hash 不一致。每个错误必须返回
准确 page/element/atom ID。

### 13.5 Visual Critic 测试

使用固定多模态模型响应验证通过、修订、两轮上限、`visual_needs_attention`、内容不可
修改和人工审美覆盖。硬 QA 不能被视觉评分或人工覆盖。

### 13.6 Visual Golden Set

建立至少 24 组固定 brief，覆盖：

- 六个 family；
- 5 页、常规页数和 18 页；
- 纯文字、搜索图片、生成图片和混合素材；
- 短/长文案、步骤、比较、诊断、故事和清单；
- 中文、数字、emoji；
- sparse、standard 和 dense；
- 同 family 不同 carousel 的构图差异。

每组保存内容合同、Visual Direction、Asset Manifest、Design Plan、PNG/contact sheet、
Render Manifest、Visual Critique 和人工结果。

Golden Set 硬 QA 必须 100% 通过。首轮上线门槛为至少 80% 的案例不需要人工进行结构性
视觉修改。

### 13.7 Workflow 集成测试

断言最终图只注册新视觉节点，旧节点不可达；覆盖旧 checkpoint 迁移、内容 checkpoint
接入、Human Review 路由、`--resume`、18 页发布包、ContentLock 和不自动上传平台。

## 14. 完成与验收标准

实现完成前必须满足：

1. `src/graph.py` 不再注册旧视觉 node。
2. family-specific renderer 和旧 variant resolver 无生产引用。
3. beauty `proof_mode=none` 强制逻辑已删除。
4. 所有 5–7 页限制已改为 5–18。
5. 六个 family 只通过 Style Profile 和参考图参与设计。
6. 真实 Chromium 可以渲染 5 页和 18 页 scene graph。
7. 每个 family 至少完成一套真实 smoke。
8. 至少完成一套真实搜索素材、一套真实生成素材和一套视觉自动修订 smoke。
9. Golden Set 硬 QA 100% 通过，至少 80% 不需要结构性人工重做。
10. 默认离线全套测试、compileall 和 diff check 通过。
11. 当前架构文档、README 和发布包说明已同步。
12. 没有旧 renderer fallback、静默 QA 放行或自动平台发布。

验证命令：

```bash
pytest -q
python -m compileall -q src main.py
git diff --check
```

真实 provider 和多模态 smoke 只能通过明确的 live 标志运行，不进入默认离线测试。
