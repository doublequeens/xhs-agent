# 六套模板驱动的自适应内容与图文工作流设计

## 状态

日期：2026-07-16

状态：已在对话中确认方案 A；等待书面规格复核。

本设计取代以下已经不符合当前目标的生产假设：

- 大纲固定为“首屏承诺、核心结论、至少三个分点、保存卡、总结、互动收尾”。
- `content_job` 唯一决定一条固定的 frame recipe。
- `storyboard_strategy` 在 assembler 阶段重新猜测内容结构，却没有真正驱动视觉计划。
- 所有页面都必须声明一个装饰性 asset slot。
- `examples/templates-mockup/` 中的样张页数代表生产套图页数。

它延续现有现代生产路径，不恢复旧 renderer，不绕过 Carousel QA、Render QA、
Human Review 或 Final Guard。

## 1. 问题与当前证据

当前系统已经比旧的固定六卡路径更灵活，但仍然存在两层结构僵化。

第一层在写作端。`outline_architect` 要求每篇大纲依次包含六个固定部分，并且要求主体
至少三个分点、最后互动收尾。`draft_writer` 又要求正文包含场景、判断、方法、总结和
互动收尾。因此，即使选题和角度不同，最终正文也容易反复呈现相同节奏。

第二层在视觉端。`src/editorial_carousel/strategy.py` 为五种 `content_job` 各维护一条
主要 recipe，只在近期 frame signature 重复时替换一个 layout。Assembler 已经输出
`cognitive_correction`、`step_tutorial`、`checklist`、`scenario_companion`、
`comparison`、`qa`、`story_reversal` 等结构元数据，但 visual planner 没有使用它。

六套样张目前也只是独立 HTML：

- set1–3 只展示封面和少量内页，不是完整生产模板。
- set4 固化为封面、三个步骤和收尾。
- set5 固化为封面、三个好物和收尾。
- set6 固化为封面、三个语录和收尾。
- 所有样张为 `1080 × 1350`，生产合同要求 `1080 × 1440`。
- 样张中的 emoji 是可接受的视觉语言，不应被禁止。

这些样张的图片数量只说明展示了哪些视觉特征，不构成任何生产页数约束。

## 2. 目标

工作流必须实现以下结果：

1. 最终发布正文可以采用不同叙事形态，而不是重复同一大纲骨架。
2. 正文结构与 carousel 结构共享同一个已选择的叙事形态，避免两者语义脱节。
3. 每次生产都从 `examples/templates-mockup/` 对应的六套视觉家族中选择且只选择一套。
4. 六套视觉家族都不绑定固定页面数量或固定页面顺序。
5. 最终页数由当前内容的语义单元和 `recommended_frame_count` 决定，并继续遵守
   5–7 页现代生产合同。
6. Renderer 根据每页实际字数、条目数、emoji 和结构选择有限的密度与构图变体。
7. UI 强化文案层级和语义，但不得改写、删除、截断或悄悄补充可见文字。
8. emoji 可以出现在正文、storyboard 和最终图片中，并且渲染结果必须可复现、无缺字。
9. 最近使用过的叙事形态、模板家族和 frame plan 参与去重，减少连续内容的结构重复。

## 3. 非目标

- 不实现自由坐标、自由 HTML/CSS 或拖拽编辑器。
- 不允许 LLM 直接生成模板代码。
- 不为了视觉变化改变事实、结论、步骤、标题或 ContentLock 中的可见文字。
- 不取消可截图保存价值、内容合规或人工审核。
- 不把样张 HTML 作为运行时字符串模板直接读取。
- 不引入第七套隐式默认模板；成功生产必须明确选择六套之一。
- 不强制每篇使用 emoji，也不由 renderer 无依据地添加互动话术或新语义。
- 不因为页面是纯文字设计而绕过外部素材的 provenance、许可或安全审核。

## 4. 统一术语

系统使用四个彼此独立的维度，避免继续混用“内容类型”“视觉家族”和“layout”。

| 维度 | 回答的问题 | 示例 |
| --- | --- | --- |
| `content_intent` | 为什么写 | `experience`、`how_to`、`basic_science` |
| `narrative_form` | 正文如何展开 | `scenario_story`、`comparison`、`diagnostic_qa` |
| `content_job` | 读者读完要完成什么 | 判断、执行、选择、保存、理解 |
| `template_family` | 整套图采用什么视觉语言 | `pink_red`、`deep_teal`、`white_quote` |

每页还有一个 `page_archetype`，描述该页承担的语义 UI：

```text
cover
thesis
scene
story_beat
explanation
steps
checklist
comparison
diagnostic
qa
item_collection
quote
boundary
save
closing
```

`page_archetype` 不包含颜色或字体。相同的 `comparison` 页面在六套模板中会有六种
不同视觉实现。

## 5. 内容叙事形态

新增严格枚举 `NarrativeForm`：

| Narrative form | 主要节奏 | 不要求 |
| --- | --- | --- |
| `cognitive_correction` | 常见认知 → 反转 → 原因 → 可执行替代 | 固定三个错误 |
| `step_tutorial` | 场景目标 → 顺序 → 关键节点 → 完成标准 | 固定三个步骤 |
| `checklist_collection` | 使用场景 → 条目集合 → 选择或使用规则 | 固定三个物品 |
| `comparison` | 两种或多种状态 → 差异 → 判断规则 | 固定左右两栏正文 |
| `diagnostic_qa` | 症状/疑问 → 分支判断 → 对应处理 → 边界 | 固定问答数量 |
| `scenario_story` | 场景 → 冲突 → 发现 → 方法或结论 | 伪造个人经历 |
| `story_reversal` | 预期 → 失败/误区 → 转折 → 新做法 | 互动式固定收尾 |
| `reflective_editorial` | 观点/语录 → 解释 → 生活化落点 → 边界 | 每页都是一句语录 |

### 5.1 Narrative beat

Angle Strategist 不再只输出自由字符串 `suggested_structure`。每个 angle 还必须输出：

```python
class NarrativePlan(BaseModel):
    narrative_form: NarrativeForm
    beats: list[NarrativeBeat]  # 4..8
    saveable_beat: NarrativeBeat
    closing_mode: Literal[
        "none",
        "boundary",
        "reflection",
        "focused_question",
        "action_prompt",
    ]
```

`NarrativeBeat` 是受控枚举，包括：

```text
hook
scene
tension
misconception
reveal
principle
explanation
example
steps
checklist
comparison
diagnostic
qa
quote
boundary
summary
action
```

同一 topic 的三个 angle 必须至少使用两种不同 `narrative_form`，除非内容合同只允许
一种安全表达方式。Novelty Guard 和 Virality Scorer 保留并传播所选 narrative plan。

### 5.2 Outline 和 Draft

Outline Architect 按选中 angle 的 beats 组织大纲，不再执行统一六段顺序。它仍必须：

- 兑现 `first_screen_promise`。
- 提供一个可独立保存的语义单元。
- 保留必要的适用范围、风险边界或证据限定。
- 不新增输入没有支持的事实。

以下要求删除：

- 主体必须至少三个逻辑分点。
- 每篇必须有“一屏总结”。
- 每篇必须以互动问题收尾。
- 步骤、清单、判断和对比必须同时出现在正文中。

Draft Writer 使用 narrative plan 保持不同节奏。`closing_mode=none` 时允许正文自然结束；
`focused_question` 只在内容确实适合讨论时使用。正文可以使用 emoji，但不能用 emoji
替代事实、风险说明或关键操作文字。

### 5.3 Assembler

Assembler 不再让 LLM 根据已完成正文重新猜测 `storyboard_strategy`。它只传播经过
选择和审核的：

```text
narrative_form
narrative_beats
closing_mode
```

旧 `storyboard_strategy` 在新生产合同中删除。Legacy adapter 可以将旧值映射到最接近
的 `narrative_form`，但现代业务节点不得继续读取旧字段。

## 6. 六套视觉模板家族

六套模板变为生产级 `TemplateFamily`：

| ID | 样张来源 | 保留的视觉识别 | 适配倾向 |
| --- | --- | --- | --- |
| `pink_red` | set1 | 粉底、红色高冲击块、粗体数字/标签 | 纠偏、教程、列表 |
| `deep_teal` | set2 | 深青满版、白字、极简编辑感 | 科普、清单、步骤 |
| `soft_pink` | set3 | 浅粉、白色浮层卡片、柔和珊瑚强调 | 场景、问答、诊断 |
| `coral_impact` | set4 | 珊瑚满版、超大粗体、强节奏 | 转折、教程、重点提示 |
| `green_catalog` | set5 | 墨绿、文件夹/档案卡、米色内容面 | 合集、清单、对比、速查 |
| `white_quote` | set6 | 大留白、蓝色文楷、克制语录感 | 观点、故事、反思、轻科普 |

“适配倾向”只影响选择分数，不是硬限制。每套家族都必须实现公共 page archetype，
因此 `white_quote` 可以承载 checklist，`green_catalog` 也可以承载 scenario story，
但会以各自的视觉语言呈现。

### 6.1 页面数量

模板家族不声明 `page_count`，也不提供类似“固定三个步骤”的数组槽位。Exact frame
count 由以下信息共同决定：

1. `ContentContract.recommended_frame_count`，范围 5–7。
2. Narrative beats 中不可合并的语义任务数量。
3. 可截图保存单元是否需要独立一页。
4. 单页容量估算是否需要把一个语义任务拆为两页。
5. 最近 frame plan 去重。

Planner 必须先根据 narrative beats、保存单元和容量估算得到 exact semantic frame
plan，再为该 plan 选择 template family。模板只能改变视觉实现和允许的密度 variant，
不能反向增加或减少页面。任何模板都不得因为样张只有 2、3 或 5 张而改变页数。

### 6.2 模板样张修复

`examples/templates-mockup/` 继续作为视觉参考和人工对照，不作为生产 renderer。
需要完成以下修复：

- 将所有页面改为 `1080 × 1440`。
- set1–3 补充足以展示多种 page archetype 的样张。
- set4 删除“三个 step slot”的结构假设。
- set5 删除“三个 favorite item slot”的结构假设。
- set6 删除“三个 quote slot”的结构假设。
- 保留当前允许的 emoji；不把 emoji 全部替换成几何图标。
- 删除依赖样张序号、固定结束语或固定 item 总数的硬编码。
- 每套至少展示两种内容密度和三种非封面 page archetype。
- Gallery 明确注明“样张页数不等于生产页数”。

## 7. Template selector

Visual Strategy Planner 在正文、标题和 narrative plan 已完成后运行。它不再只读取
`ContentContract`，而是读取：

```text
publish_package.title
publish_package.content
content_contract
narrative_form
narrative_beats
content_intent
domain/profile
recent_visual_signatures
```

每个模板家族按以下确定性维度评分：

- narrative form compatibility
- content job compatibility
- tone compatibility
- estimated text density
- item/cardinality compatibility
- proof asset compatibility
- recent-template repetition penalty
- recent-combination repetition penalty

选择结果必须可解释：

```python
class TemplateSelection(BaseModel):
    template_family: TemplateFamily
    score: int
    reasons: list[str]
    rejected_families: dict[TemplateFamily, list[str]]
```

所有候选都来自六套模板。相同输入和相同近期历史必须得到相同结果；平分时使用稳定
hash tie-break，不能依赖进程随机数。

近期去重签名扩展为：

```text
narrative_form
template_family
ordered page_archetypes
frame_count
density_profile
```

不能只换颜色却复用完全相同的页面语义顺序来规避重复。

## 8. VisualPlan 与 Storyboard

### 8.1 VisualPlan

`VisualPlan` 升级为：

```python
class VisualPlan(BaseModel):
    design_system: Literal["beauty_editorial_v2"]
    template_family: TemplateFamily
    template_selection: TemplateSelection
    narrative_form: NarrativeForm
    content_job: ContentJob
    frame_plan: list[FramePlanItem]  # 5..7
    required_assets: list[AssetRequirement]
```

`FramePlanItem` 使用 `page_archetype`，并声明允许的布局密度：

```python
class FramePlanItem(BaseModel):
    frame_id: str
    role: str
    page_archetype: PageArchetype
    purpose: str
    allowed_density: list[Literal["sparse", "standard", "dense"]]
    asset_roles: list[str]
```

删除当前 `RECIPES` 和 `ALTERNATIVE_LAYOUTS` 的单一 recipe 选择方式。新的 planner 使用
有限 blueprint 目录，每个 `narrative_form` 至少提供三种 5–7 页 blueprint，并结合
实际 beats、frame count 和近期签名选择。Blueprint 只决定语义任务，不决定模板颜色。

### 8.2 Storyboard

Storyboard Generator 必须逐项匹配 VisualPlan 的 frame ID、role 和 page archetype，
并把最终文案压缩成适合上图的可见字符串。它不能：

- 改变正文结论或新增事实。
- 为凑页数创建空洞页面。
- 把固定“收藏 + 关注”作为默认 closing。
- 输出字体、坐标、CSS 或模板名称之外的自由视觉指令。

`CarouselFrame` 增加：

```python
page_archetype: PageArchetype
content_density_hint: Literal["auto", "sparse", "standard", "dense"]
```

保留 `content_blocks`、`emphasis`、`visual_slots` 和所有可见文字字段。

## 9. 自适应排版

Renderer 不让 LLM决定字号和坐标。它先从 storyboard 计算 `CopyMetrics`：

```python
class CopyMetrics(BaseModel):
    grapheme_count: int
    cjk_count: int
    latin_word_count: int
    emoji_count: int
    block_count: int
    item_count: int
    max_item_graphemes: int
    estimated_lines: int
```

然后在所选 template family 的有限 variant 中解析：

```text
template_family
  + page_archetype
  + density variant
  + optional composition variant
```

允许的动态行为包括：

- `sparse`、`standard`、`dense` 三档字号和间距 token。
- 根据条目数量切换单列、双列、2×2、纵向时间线或卡片栅格。
- 根据标题长度切换两种经过测试的标题比例。
- 根据 emphasis 数量选择下划线、色块、标签或大字强调。
- 在模板允许时，把一个正文卡片区域切成主结论和辅助说明。
- 根据 visual slot 是否存在选择纯文字或文字 + proof asset 构图。

禁止的行为包括：

- 截断、ellipsis、隐藏、缩放整张页面。
- 把字号降到 Design System 最小值以下。
- 在 render 阶段把文字移动到另一页。
- 改写文字以解决溢出。
- 悄悄删除 emoji、标点、风险限定或 footer。

若所有允许 variant 都无法容纳内容，renderer 必须失败。工作流回到 storyboard/R1，
在不改变事实的前提下重新分配页面或精简重复表述，然后重新通过 R2、Carousel QA 和
Render QA。

Resolved variant 写入 `RenderManifest`，使最终产物可以审计：

```python
class RenderedPage(BaseModel):
    frame_id: str
    page_archetype: PageArchetype
    template_family: TemplateFamily
    density: Literal["sparse", "standard", "dense"]
    composition_variant: str
    ...
```

## 10. Emoji

emoji 是允许的内容字符和视觉元素。

规则如下：

- Outline、Draft、R1 和 Storyboard prompt 不得禁止 emoji。
- 模型可以在自然语气、条目标记或情绪强调中使用 emoji，但不能堆叠到影响扫读。
- ContentLock 保留原始 Unicode grapheme，renderer 不把它改写成文字描述。
- 仓库内版本化保存 `Noto Color Emoji` 字体及其许可快照；生产渲染不得依赖 macOS、
  Linux 或 CI 主机恰好安装的系统 emoji 字体。
- 字体 preflight 必须覆盖本次 storyboard 中实际出现的 emoji。
- Render QA 验证 emoji grapheme 可见、无 tofu、无裁切，并核对 storyboard 原始字符。
- 模板自带装饰 emoji 只能来自经过版本化的模板资源，不能携带新的事实或 CTA。
- 若某个 emoji 不在已批准字形集中，QA 返回明确问题，不能静默删除；R1 可以在保持语义
  的情况下替换为受支持 emoji 或普通标点。

## 11. 素材与安全边界

六套模板以 typography 和 UI 为主，因此不是每页都需要 asset。

调整当前合同：

- `required_assets` 可以为空，也可以只覆盖需要真实 proof 的页面。
- `visual_slots` 可以为空；Carousel QA 不再要求每个 frame 都有一个装饰性 slot。
- 有 visual slot 时仍必须一一匹配 `AssetRequirement` 和 `AssetManifest`。
- 外部素材仍必须经过 provider、许可、containment、no-follow、事务绑定、人工审核和
  字节哈希检查。
- Renderer 不生成未声明的 asset placeholder 来冒充证明。
- 纯文字页面不应为了满足旧 adapter 而解析无意义的背景素材。

这项调整减少装饰性素材，但不削弱任何外部素材安全不变量。

## 12. 生产 renderer 结构

不为六套模板复制六个完整 renderer。保留一个深模块 interface：

```python
render_carousel(
    visual_plan: VisualPlan,
    storyboard: CarouselPayload,
    assets: AssetManifest,
    output_dir: Path,
) -> RenderManifest
```

内部按职责拆分：

```text
src/rendering/editorial/
  template_registry.py      # 六套家族声明、tokens、能力
  copy_metrics.py           # grapheme 和容量测量
  variant_resolver.py       # archetype + density + composition
  primitives.py             # 共享卡片、标签、列表、分栏、footer
  templates/
    pink_red.py
    deep_teal.py
    soft_pink.py
    coral_impact.py
    green_catalog.py
    white_quote.py
  renderer.py               # HTML、字体、Chromium、manifest
  probes.py                 # 文字、emoji、素材、边距和溢出证据
```

每个模板模块只拥有视觉 token 和 page archetype 的有限实现，不负责读取 graph state、
选择模板、改写文字或操作发布目录。

## 13. QA

### 13.1 Carousel QA

在现有检查基础上增加：

- narrative form 与 narrative beats 存在且已传播。
- frame count 等于规划结果并在 5–7 范围内。
- frame plan 覆盖 narrative plan 的必要 beats。
- 每页只有一个主要语义任务。
- template family 是六套之一。
- 当前组合签名未与近期内容完全重复。
- saveable beat 已映射到独立可保存页面。
- 没有固定三步骤、三物品、三语录或固定 closing 的填充痕迹。
- 纯文字 frame 可以没有 visual slot。
- 有 visual slot 时保持现有素材绑定不变量。

### 13.2 Render QA

增加：

- 每页为 `1080 × 1440`。
- RenderManifest 中所有页面使用同一个 template family。
- resolved density 和 composition variant 属于该 family/archetype 的允许集合。
- 所有可见字符串逐字匹配 storyboard，包括 emoji。
- 没有 tofu、缺字、溢出、裁切、隐藏或 ellipsis。
- 字号、行高、安全边距、颜色对比达到模板 token 下限。
- sparse 页面不过度空洞，dense 页面仍保持可扫读层级。
- contact sheet 顺序与 manifest 一致。
- `template_stiffness` 同时考虑 page archetype、composition variant 和近期组合，不再
  只统计 layout 重复。

## 14. 历史记录与去重

Content Writer 在现有内容记忆中增加：

```text
narrative_form
narrative_signature
template_family
template_selection_reasons
frame_plan_signature
density_profile
```

Memory Retriever 返回同 domain/subdomain 的近期组合签名。Planner 对最近连续使用同一
模板、同一 narrative form 或同一 archetype 顺序施加惩罚，但内容适配和安全优先于
形式轮换。

不采用简单六套轮播，因为轮播会在不适合的内容上强行使用模板。

## 15. 迁移与删除

实施时：

1. 新增 narrative plan schema，并贯穿 angle、score、outline、draft、decision 和
   publish package。
2. 删除现代 prompt 中固定六段大纲和固定互动收尾要求。
3. 删除 assembler 对 `storyboard_strategy` 的重新推断。
4. 新增六套 template registry 和 selector。
5. 用 narrative blueprint planner 取代 `RECIPES` / `ALTERNATIVE_LAYOUTS`。
6. 让 storyboard 和 Carousel QA 使用 page archetype。
7. 实现六套 renderer family 和自适应 variant resolver。
8. 修复 mockup 尺寸和固定数量假设。
9. 增加 emoji 字形资源、preflight 和 Render QA。
10. 扩展记忆签名和重复惩罚。

旧 checkpoint 只通过 `src/editorial_carousel/legacy.py` 迁移。识别到旧
`beauty_editorial_v1` VisualPlan 或旧 `storyboard_strategy` 时，adapter 保留内容合同
和人工可见文字，清除旧 visual/asset/render 派生产物，并从现代 visual planner 重新
规划。业务节点不得直接兼容旧 recipe。

删除对象包括：

- `src/editorial_carousel/strategy.py` 中的固定 `RECIPES` 和
  `ALTERNATIVE_LAYOUTS`。
- assembler prompt 中的 `storyboard_strategy` 分类规则。
- outline/draft prompt 中的固定六段结构。
- renderer 中为每页强制显示 asset placeholder 的逻辑。
- mockup HTML 中固定三个 item/step/quote 和固定 closing 的结构假设。

## 16. 测试策略

### 16.1 内容结构

- 八种 narrative form 都有 schema 和 prompt contract tests。
- 同一 topic 的不同 angle 可以产生不同 narrative form 和 beat plan。
- Outline 按 beats 生成，不自动补固定三个分点或互动结尾。
- Draft 在 `closing_mode=none` 时不被要求生成提问。
- Narrative metadata 从 angle 一直传播到 publish package 和 ContentLock 前的终端状态。

### 16.2 Template selector

- 六套模板都能被至少一个确定性 fixture 选中。
- selector 只返回六套之一。
- 相同输入和历史得到相同选择。
- 最近重复惩罚能在两个同样合适的家族之间改变选择。
- 内容适配硬约束不会被轮换惩罚覆盖。
- selection reasons 与实际评分一致。

### 16.3 Frame planning

- 每种 narrative form 至少三种 blueprint。
- 同一模板可以生成 5、6、7 页。
- 同一 5–7 页内容可以由不同模板家族渲染，证明页数不属于模板。
- 计划覆盖必要 beats、包含 saveable frame，但不固定 save 页位置。
- 近期重复时改变 archetype 顺序或 blueprint，而不是只换颜色。

### 16.4 Renderer

- 六套模板 × 5/6/7 页的 Chromium matrix smoke test。
- 每套至少覆盖 sparse、standard、dense。
- 每个公共 page archetype 在六套 family 中都有 renderer。
- 长标题、长条目、1/2/3/4/5/6 项列表、混合中英文和 emoji 的边界测试。
- 不允许截断、ellipsis、隐藏或最小字号以下降级。
- 无 visual slot 的纯文字页面通过；有 slot 的页面继续验证 provenance 和 sha256。
- 输出始终为 `1080 × 1440`，contact sheet 与 manifest 顺序一致。

### 16.5 Golden fixtures

至少维护八个按 narrative form 命名的合成 fixture。每个 fixture 固定语义输入和关键
可见文字，不固定生产标题，也不把测试文案注入 prompt 或 memory。

额外维护六个模板视觉 fixture，确保每个模板的配色、字体、核心构图和密度变体没有
意外漂移。

## 17. 验收标准

设计完成的实现必须由当前状态证据证明：

- 生产 VisualPlan 明确选择六套模板之一。
- 任意模板可以产出 5、6 或 7 页；样张文件数量不影响生产页数。
- 至少八种 narrative form 可贯穿正文和 carousel，不再存在统一六段大纲要求。
- 同一内容形态有多个 frame blueprint，近期重复会改变组合。
- 六套模板都进入生产 renderer，而不是停留在 mockup HTML。
- 排版按 CopyMetrics 选择有限 variant，且不会更改锁定文字。
- emoji 可以正常生成、锁定、渲染和通过 QA。
- set1–6 样张统一到 `1080 × 1440`，并移除固定三个内容页假设。
- 纯文字模板不再被迫绑定装饰性 asset；真实外部素材的安全合同保持不变。
- Carousel QA、Render QA、Human Review 和 Final Guard 全部保留。
- 聚焦测试、完整 `pytest -q`、`python -m compileall -q src main.py` 和
  `git diff --check` 通过。
- 至少生成六套生产级 contact sheet 进行人工视觉复核，每套使用不同 narrative fixture，
  并包含至少一个非五页样例。
