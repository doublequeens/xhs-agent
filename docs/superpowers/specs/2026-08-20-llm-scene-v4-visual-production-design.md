# llm_scene_v4 受约束混合视觉生产架构设计

## 状态

- 日期：2026-08-20
- 状态：对话设计已确认；等待书面规格复核
- 目标 workflow version：`llm_scene_v4`
- 当前生产 workflow version：`llm_scene_v3`

本设计重构 assembler 之后的视觉生产链，解决近期真实发布包暴露出的内页排版质量、
审美误判、无界 API 等待、重试放大和恢复预算失真问题。内容生产主链、素材安全、
ContentLock、Chromium renderer、Human Review、Final Guard 和本地发布边界继续保留。

本设计在迁移期允许 `llm_scene_v3` 与 `llm_scene_v4` 隔离双轨运行，因此取代
`2026-07-31-llm-directed-dynamic-visual-production-design.md` 中“不保留双轨或 feature
flag”的迁移决策。这个例外只用于版本级 shadow/cutover，不允许一次 v4 运行在中途
回退 v3，也不恢复旧 v1/v2 固定模板生产路径。

## 1. 背景与现场证据

近期两个发布包是本次设计的首要回归样本：

- `outputs/publish/20260805-beauty-下班赴约底妆斑驳？按脱妆面积选补妆方案（`
- `outputs/publish/20260806-beauty-一天5个时刻补防晒：每个场景做法都不一样`

人工观察表明，两套 carousel 的 `01-page-1` 达到较好视觉质量，其余内页在信息组织、
层级、留白、构图节奏和整体美感上明显不足。现有自动系统未能可靠识别这些问题：

- 第一套共 10 页，`VisualCritique` 在 revision round 2 给出 `overall=92`、
  `passed=true`、`issues=[]`。
- 第二套共 9 页，`VisualCritique` 在 revision round 0 给出 `overall=91`、
  `passed=true`、`issues=[]`。

实现核对还发现：

1. `content_atomizer` 主要按非空行生成 atom。Markdown 表格只跳过 separator，普通表格行
   仍可能以管道文本整体进入 atom，步骤、比较项、标签和值之间缺少显式语义关系。
2. `VisualDirectionPlan.PageDirection` 只用 `purpose`、`visual_job` 和 fragment ID 表达页面
   任务；这些自然语言不足以稳定驱动高质量信息设计。
3. `page_designer` 一次模型调用负责整套 5–18 页的完整低层 scene graph，包括全部
   box、字号、层级和样式。巨大嵌套 JSON 同时承载审美判断和几何执行细节。
4. Design Plan QA 与 Render QA 能检查合同绑定、覆盖、边界、最小字号、对比度、
   overflow 和素材引用，但没有充分表达页面职责相关的留白、密度、对齐、平衡、
   视觉重心和整套节奏。
5. Visual Critic 与视觉创作依赖同一类模型能力，现有总分阈值允许高分页面抵消坏页面，
   也缺少可校准的负例。
6. Human Review 节点虽然携带合同和 manifest，终端审核面仍偏 JSON，不能直接提供整套
   contact sheet、单页放大、指标 overlay、前后版本对比和页面级反馈入口。
7. `generate_validated` 最多执行 6 次结构化生成，而 Gemini adapter 在每次生成内最多
   执行 5 次 API 重试，最坏情况下形成约 30 次 provider 调用；同步
   `generate_content` 没有真正的外部 hard deadline。
8. `main.py` 在 resume 时把 `design_plan_qa_failures` 和 `render_qa_failures` 重置为 0，
   同一失败可以通过多次恢复获得新的自动修订预算。
9. `VisualProductionInterrupted` 用 `len(errors)` 表示 attempts，run registry 以最近完成
   节点为主，不能准确表达实际失败节点、provider attempts、schema repairs 和重复失败。

这些问题共同说明：当前缺陷不是单一 prompt、CSS 或评分阈值问题，而是创作意图、
信息结构、低层布局、质量证据和运行控制被耦合进同一条高随机性链路。

## 2. 设计目标

`llm_scene_v4` 必须实现：

1. LLM 负责语义理解、叙事节奏、页面任务和构图策略，确定性模块负责文字测量、网格、
   间距、字号、对齐、坐标和 fit。
2. 视觉阶段仍能根据内容动态决定 5–18 页，并在一个 family 内产生明显不同的页面，
   但不能重新变成六套固定模板。
3. 每个可见字符都能追溯到 `ContentAtomSet`；视觉修复不得修改 ContentLock。
4. 技术正确性、可量化视觉质量、模型审美判断和人工审核分别承担不同责任。
5. 单页失败不能被整套平均分掩盖；已知坏内页必须进入回归集。
6. 所有视觉模型调用拥有真正可终止的 deadline、单层重试、持久化 attempt 记录和
   跨 resume 的预算约束。
7. 修订只作用于正确的抽象层和受影响页面，避免整套 scene graph 反复重生成。
8. v4 在 shadow 期与 v3 完全隔离，达到明确 Gate 后才获得正式发布权限。

## 3. 非目标

- 不重写内容主链、R1/R2、标题、hashtag 或 assembler。
- 不允许视觉阶段生成新事实、新互动话术、AI 标识或免责声明。
- 不恢复 `visual_strategy_planner`、`storyboard_generator`、`carousel_qa`、
  `editorial_carousel_renderer`、`VisualPlan`、`CarouselPayload`、`ResolvedVariant`、
  `modern_v2` 或固定六模板 HTML/CSS。
- 不让 LLM 直接生成 HTML、CSS、JavaScript 或可执行代码。
- 不实现线上发布、小红书登录或自动上传。
- 不以降低最小字号、截断文字、隐藏元素或突破安全边距解决排版问题。
- 不在本次架构设计中规定每个 Python 文件和每个 commit；这些属于设计批准后的实施计划。

## 4. 核心术语

为避免不同 Module 对同一概念使用不同语言，v4 采用以下术语：

| 术语 | 含义 |
| --- | --- |
| Content Atom | 可见文字的不可变来源单位，携带稳定 ID 和 sha256 |
| Semantic Fragment | Content Atom 的精确字符切片及其语义角色 |
| Semantic Group | 有结构关系的一组 fragment，例如步骤组、比较行或 checklist |
| Narrative Beat | carousel 叙事推进中的一个阶段，例如 hook、诊断、方法、收尾 |
| Page Brief | 某一页承担的叙事职责、内容引用、密度预算、素材需求和视觉重点 |
| Composition Grammar | 描述区域、关系、对齐和密度约束的构图语法，不是固定成品模板 |
| Layout Program | 某页选定 Grammar 后的结构化布局意图，不包含最终像素坐标 |
| Scene Plan | 可交给现有 renderer 的精确 `CarouselDesignPlan` scene graph |
| Visual Metric | 从文本测量、scene geometry、DOM probe 或 PNG 得出的确定性指标 |
| Revision Request | 指定问题证据、目标层、允许操作和受影响页面的有类型修订请求 |
| Attempt | 一次完整 provider 请求及其解析、schema 校验和持久化结果 |
| Candidate | 一次可独立经过硬 QA、Critic 和 Human Review 的视觉版本 |

## 5. 目标架构选择

v4 采用“分层混合创作架构”：

```text
ContentAtomSet
  -> ContentLock
  -> SemanticContentModel
  -> CarouselNarrative + PageBriefSet
  -> AssetManifest
  -> LayoutProgram
  -> deterministic Layout Compiler
  -> CarouselDesignPlan
  -> hard QA + Chromium render
  -> independent aesthetic review
  -> Human Review
```

没有采用两种替代方案：

- 纯确定性版式编译器虽然可靠，但如果完全取消高层构图判断，会很快形成新的模板感。
- 全量多候选生成与模型排名会成倍增加成本和 timeout 风险，而且当前 Critic 尚不能可靠
  识别坏页面。

v4 以确定性编译器作为可靠基础，只在高层 Page Brief、Grammar 选择和受控审美修订中
使用 LLM；未来若引入候选探索，也只能针对少量高风险页面并服从同一总预算。

## 6. Module 与 Interface

### 6.1 `semantic_modeling`

职责：从 `ContentAtomSet` 派生适合信息设计的语义结构，不做视觉决策。

输入：

- `ContentAtomSet`
- `ContentLock`
- assembler 规范文案的结构信息

输出 Interface：`SemanticContentModel`

```text
SemanticContentModel
├── content_atom_set_sha256
├── fragments[]
│   ├── fragment_id
│   ├── source_atom_id
│   ├── start / end
│   ├── exact_text
│   ├── semantic_role
│   ├── parent_fragment_id
│   └── sequence_index
└── groups[]
    ├── group_id
    ├── group_kind
    ├── fragment_ids[]
    └── ordering
```

初始 `semantic_role` 至少包括：`heading`、`paragraph`、`step`、
`comparison_label`、`comparison_value`、`checklist_item`、`warning`、`evidence`、
`closing` 和 `note`。

关键不变量：

- v4 Content Atomizer 必须先执行确定性的 `VisibleCopyProjection`：从原始 Markdown
  识别可见文本及其 raw source spans，再建立 atom 和 hash。表格 separator、pipe 和其它
  不可见结构标记在 atom 建立前被排除；表头与单元格分别成为 visible-copy units。
- fragment 必须是 source atom 的精确字符切片。
- 同一 atom 的 fragment 按顺序拼接后必须逐字符重建 atom。
- `VisibleCopyProjection` 必须持久化 raw source span 与 canonical visible-copy hash，证明
  atom 来自原始标题、封面和正文；投影后任何 Module 都不得再删除字符。
- Markdown 表格必须保留表头、行和单元格关系，不能把原始管道整行当作展示块。
- 所有 group 只能引用已验证 fragment。

Content Atomizer 仍是 canonical visible-copy producer；v4 的 Markdown 投影只识别可见
source unit 和结构关系，不能把语义判断和分页职责重新塞回 atomizer。

### 6.2 `content_lock_builder`

v4 在 atomizer 之后立即构造并 checkpoint `ContentLock`。它读取 assembler 的 canonical
标题、封面、正文、hashtags 与 `ContentAtomSet.canonical_sha256`，复用发布层当前的
ContentLock payload 规则。后续 Semantic QA、Human Review、Final Guard 与 exporter
读取同一个持久化 lock，不能在最终导出时静默换成另一个版本。

任何 visible-copy edit 必须同时清除 ContentLock、atoms 及全部下游视觉合同，再回
R2/assembler/atomizer/content lock builder。

### 6.3 `visual_authoring`

职责：根据内容语义决定整套叙事与每页任务，不输出坐标。

输入：

- `SemanticContentModel`
- domain/profile 与必要证据上下文
- family Visual DNA
- 近期视觉签名
- 5–18 页、画布和平台约束

输出两个内部 Interface：

```text
CarouselNarrative
├── template_family
├── page_count
├── beats[]
├── density_curve[]
├── variation_strategy
├── continuity_strategy
└── art_direction
```

```text
PageBriefSet
└── pages[]
    ├── page_id / sequence
    ├── narrative_role
    ├── fragment_refs[]
    ├── visual_priority[]
    ├── density_budget
    ├── preferred_compositions[]
    ├── forbidden_patterns[]
    ├── asset_directives[]
    └── continuity_with_previous
```

`PageBrief` 不包含 `x/y/w/h`。页面数量或顺序改变属于 Authoring 层修订；字号、间距或
box 变化不允许回到这一层。

### 6.4 `asset_resolver`

现有 Asset Resolver 的 provider、许可、containment、no-follow、事务、字节哈希、
recovery evidence 和内部 provenance 约束全部保留。

唯一架构变化是：素材需求来自结构化 `PageBrief.asset_directives`，而不是从模糊的
`visual_job` 中推断。只有 `security_status=approved` 的素材可以进入布局编译和 renderer；
AI provenance 仍只存在于内部 manifest。

### 6.5 `composition_planning`

职责：为每页选择并参数化一种 Composition Grammar，输出不含最终坐标的
`LayoutProgram`。

```text
LayoutProgram
├── page_id
├── page_brief_sha256
├── grammar_id
├── regions[]
├── fragment_placements[]
├── asset_placements[]
├── emphasis_rules[]
├── alignment_axes[]
├── density_target
└── responsive_constraints[]
```

首批 Grammar：

- `editorial_hero`
- `comparison_grid`
- `step_flow`
- `diagnostic_matrix`
- `checklist`
- `evidence_card`
- `image_annotation`
- `summary_closing`

Grammar 只能定义布局关系、区域角色、合法组合、对齐轴和密度范围。它不得保存固定文案、
固定坐标、固定页面顺序、family-specific DOM 或可直接渲染的完整页面。

### 6.6 `layout_compiler`

这是 v4 最深的 Module。它隐藏文字测量和几何求解的复杂性，对上只接受
`LayoutProgram`，对下只输出合法 `CarouselDesignPlan`。

内部职责：

- 1080×1440 栅格和安全边距
- family design tokens 与字体角色
- 中文真实文字测量、换行和行高
- 区域、列宽、卡片和素材裁切
- 最小字号、最小留白和最大密度
- 对齐轴、视觉重心和图文比例
- Grammar 内的确定性 reflow
- stable element IDs 和 content/asset refs

相同输入必须生成相同输出。编译器不能静默降低质量约束；无法满足时返回结构化失败：

- `CONTENT_OVERFLOW`
- `DENSITY_EXCEEDED`
- `UNBALANCED_REGIONS`
- `INSUFFICIENT_WHITESPACE`
- `ASSET_ASPECT_MISMATCH`
- `TYPOGRAPHY_CONSTRAINT_CONFLICT`

### 6.7 保留的 renderer Seam

现有 `generic_scene_renderer` 与 Chromium 继续作为唯一 scene execution path。v4 不新增
family renderer，也不让 Grammar 绕过 `CarouselDesignPlan` 直接产生 HTML。

## 7. 发布合同兼容

v4 继续导出当前 10 个 canonical 合同文件及全部 PNG，不增加绕过 attestation 的发布
sidecar：

1. `content_atom_set.json`
2. `visual_direction_plan.json`
3. `asset_manifest.json`
4. `carousel_design_plan.json`
5. `design_plan_qa.json`
6. `render_manifest.json`
7. `render_qa.json`
8. `visual_critique.json`
9. `content_lock.json`
10. `final_policy_attestation.json`

内部 Interface 通过嵌套和哈希绑定进入现有合同：

- `SemanticContentModel`、`CarouselNarrative` 和 `PageBriefSet` 作为 v4 结构化字段进入
  `VisualDirectionPlan`，并分别携带 canonical hash。
- `LayoutProgram` 作为 compiler provenance 进入 `CarouselDesignPlan`，其 hash 同时绑定到
  对应 page scene。
- v4 的 `design_plan_qa.json` 仍是一个发布合同，但其 versioned `DesignPlanQAResult`
  聚合完整 `SemanticQAResult`、`AuthoringQAResult` 和 `DesignMetricsQAResult`，绑定
  Semantic Model、Page Brief、Layout Program 与 Scene Plan hash；overall `passed` 只有
  三个子门全部通过时为 true。
- 不可变 `HumanReviewDecision` 的完整 payload 与 canonical hash 嵌入
  `final_policy_attestation.json`；它不是第 11 个发布合同。
- `PublishAttestation(workflow_version="llm_scene_v4")` 仍重算并绑定上述 10 个合同及
  `pages/*.png`、`contact-sheet.png`。

这样既保留 standalone 发布包审计能力，也不改变“10 个合同 + 每个 PNG”的发布承诺。
v3 与 v4 使用显式 versioned schema；v4 不能让 v3 parser 默默接受未知字段。

`src/editorial_carousel/legacy.py` 仍是旧 v1/v2 checkpoint 的唯一迁移边界。既有 v3
checkpoint 继续由 v3 恢复，不迁移为 v4。

## 8. v4 工作流与硬门

目标链路：

```text
assembler
-> content_atomizer
-> content_lock_builder
-> semantic_modeling
-> semantic_qa
-> visual_authoring
-> authoring_qa
-> asset_resolver
-> composition_planning
-> layout_compiler
-> design_metrics_qa
-> generic_scene_renderer
-> render_qa
-> visual_critic
-> human_review
-> final_policy_guard
-> production: content_writer -> terminal publish exporter
-> shadow: shadow_artifact_writer -> terminal shadow exporter
```

`content_writer` 继续只负责在正式生产通过后写入 `data/xhs_memory.db` 和 Chroma；它不负责
构建发布目录。canonical publish package 仍由 CLI 在 terminal checkpoint 后调用 versioned
exporter，以 staging + 原子提升方式生成。`run_mode=shadow` 禁止进入 `content_writer`，
禁止写正式记忆、Chroma 或 `outputs/publish/`，只允许独立 shadow artifact/exporter。

所有 Q0–Q3 硬门必须通过后才能进入 Human Review：

- Q0 Semantic QA：文字守恒、fragment 边界、表格/步骤/比较结构和哈希。
- Q1 Authoring QA：内容覆盖、页面职责、分页、密度预算、重复页面和节奏可行性。
- Q2 Design Metrics QA：scene 合法性及可量化的留白、密度、对齐、平衡和层级底线。
- Q3 Render QA：最终 DOM/PNG、字体、文字、素材、裁切、尺寸和 hash。

Q4 Aesthetic Review 是独立 Critic 与 Human Review，不允许覆盖 Q0–Q3。

Final Guard 与 versioned exporter 必须重新执行或验证 Q0/Q1/Q2 的确定性证明，并确认聚合
`DesignPlanQAResult` 绑定当前合同。Q0/Q1 不能只保存在 checkpoint，否则 standalone
发布包无法证明它们曾经通过。

## 9. 统一 LLM Gateway

所有 v4 结构化视觉请求、图像生成请求和图像审美请求必须经过唯一 `llm_gateway`
Adapter。各节点和 provider adapter 不再拥有嵌套重试循环。

Gateway 负责：

- connect/read/overall deadline
- request ID、request fingerprint 和 provider request ID
- retryable/fatal 错误分类
- 指数退避和 jitter
- JSON 解析与 schema repair 计数
- token、耗时和错误统计
- 输出清理和 attempt 持久化

如果 provider SDK 支持真正可取消的 async deadline，优先使用该能力；如果同步调用无法
取消，则在独立 worker process 中执行，deadline 到达后终止并回收 worker。不能使用
timeout 后仍继续运行的泄漏线程作为 hard timeout。

一次 Attempt 覆盖 provider 请求、响应解析和 schema 校验，结果分类为：

- `SUCCESS`
- `TRANSPORT_RETRYABLE`
- `TRANSPORT_FATAL`
- `HARD_TIMEOUT`
- `INVALID_JSON`
- `SCHEMA_INVALID`
- `CONTENT_CONTRACT_VIOLATION`
- `UNKNOWN_AFTER_CRASH`

Schema repair 是新的 Attempt，必须消耗公开预算。初始默认预算：

| 范围 | 默认值 |
| --- | ---: |
| 结构化文本请求 deadline | 90 秒 |
| 图像 Critic 请求 deadline | 120 秒 |
| 单节点最大 attempts | 3 |
| 单节点 schema repair | 1 |
| 单 candidate 视觉 LLM attempts | 14 |
| 单 candidate 视觉墙钟时间 | 15 分钟 |

预算集中配置并通过观测数据校准，节点不得私自扩大。

## 10. Attempt Ledger 与恢复

Attempt Ledger 采用 append-only 事件，不使用一条“不可变但稍后更新”的记录：

```text
AttemptStarted
├── attempt_id
├── run_id / workflow_version / run_mode
├── candidate_id / revision_id / parent_revision_id
├── node / page_ids / operation_kind
├── attempt_number / request_fingerprint
└── started_at / deadline_at

AttemptFinished
├── attempt_id
├── completed_at / status / error_class
├── provider_request_id / latency_ms / token_usage
├── sanitized_result_ref / sanitized_result_sha256
└── validated_contract_sha256

AttemptReconciled
├── attempt_id
├── reconciled_at
├── status = UNKNOWN_AFTER_CRASH
└── evidence
```

`AttemptStarted` 必须在 provider 调用前提交，`AttemptFinished` 在结果持久化后追加。
sanitized result 存放在受控本地 result store，事件只保存 containment-safe reference 和
sha256；成功 fingerprint 只有在引用文件和 sha256 都验证通过时才可复用。图像生成结果
仍必须额外满足 Asset Resolver 的事务与安全合同。

由于 LangGraph 只有节点完成后才可靠 checkpoint，attempt events 应使用 run registry 的
向后兼容新增表或等价独立 durable store；不得解析 `checkpoints.sqlite` 内部表结构。
Ledger projection 从事件计算当前 attempt 状态，started 且没有 finished 的事件在恢复时
追加 `AttemptReconciled`，原始事件不修改。

恢复规则：

- resume 从 ledger 计算已消费预算，绝不把失败计数清零。
- crash 时仍处于 started 的 attempt 标记为 `UNKNOWN_AFTER_CRASH` 并消耗预算。
- 相同 fingerprint 的成功结果允许复用；失败结果不能被覆盖。
- 人工发起的新 candidate 获得新的有界 candidate budget，但 run lifetime totals 永久保留。
- `INTERRUPTED_EXHAUSTED` 只有在输入、配置或人工指定策略发生可审计变化后才能创建
  新 candidate；普通 resume 不产生新预算。

运行状态统一为：

- `RUNNING`
- `WAITING_HUMAN`
- `INTERRUPTED_RETRYABLE`
- `INTERRUPTED_EXHAUSTED`
- `FAILED_FATAL`
- `COMPLETED`

现有 `agent_runs.status` 的 SQLite CHECK 保持不变。新增 `execution_state` 或 append-only
run-state event 保存上述六态，并向旧四态投影：

| v4 execution state | legacy `agent_runs.status` |
| --- | --- |
| `RUNNING` | `running` |
| `WAITING_HUMAN` | `awaiting_review` |
| `INTERRUPTED_RETRYABLE` | `interrupted` |
| `INTERRUPTED_EXHAUSTED` | `interrupted` |
| `FAILED_FATAL` | `interrupted` |
| `COMPLETED` | `completed` |

run registry 还必须持久化不可变 `workflow_version` 与 `run_mode`。已有记录或 null version
一律解释为 v3；一旦创建不得在原 thread 上切换版本。

legacy `status` 只用于兼容展示，不能决定 v4 是否可恢复。v4 的 `list_resumable`、显式
`--resume` 和恢复入口必须读取 `execution_state`：

- `INTERRUPTED_RETRYABLE` 可以恢复同一 candidate。
- `INTERRUPTED_EXHAUSTED` 不进入普通 resumable 列表；只有提交已审计的输入、配置或策略
  变化后，才允许追加新 candidate。
- `FAILED_FATAL` 拒绝 resume，只显示失败原因和需要的新运行/外部修复动作。
- `WAITING_HUMAN` 只能提交与当前 candidate/revision 绑定的审核决定。

### 10.1 Candidate artifact identity

v4 的 render、review 和素材事务路径必须包含 `run_id/candidate_id/revision_id`。每个
revision 一旦完成硬 QA，其目录只读；candidate 根目录是 append-only，可以在 Critic
自动修订时追加下一 revision，但不得覆盖旧 revision：

```text
run-root/
└── candidates/<candidate-id>/
    ├── revisions/<revision-id>/render/
    ├── revisions/<revision-id>/review/
    └── revisions/<revision-id>/artifacts/

data/asset_transactions/<run-id>/<candidate-id>/<revision-id>/
```

复用未变化页面或素材必须验证 source bytes sha256，并在新 revision manifest 中绑定新的
不可变路径；不能依赖仍会被后续 renderer 覆盖的共享文件名。Critic 自动修订仍属于同一
candidate 的新 revision；Human Review 请求修订才创建新 candidate。已被 Human Review
看到的 revision 永远不能替换、重写或重新指向。Review Workspace 的 previous-revision
通过这些不可变 identity 读取。

## 11. 分层修订状态机

所有自动或人工反馈先转换成：

```text
RevisionRequest
├── target_layer
├── affected_pages[]
├── failure_codes[]
├── failure_fingerprints[]
├── evidence[]
├── permitted_operations[]
├── forbidden_operations[]
└── prior_revision_id
```

`target_layer` 只能是：`SEMANTIC`、`AUTHORING`、`ASSET`、`COMPOSITION`、`LAYOUT`、
`RENDER` 或 `AESTHETIC`。

| 失败 | 路由 |
| --- | --- |
| 语义结构或字符映射 | `semantic_modeling` |
| 页面职责、密度分配或页序 | `visual_authoring` |
| 素材安全、比例或绑定 | `asset_resolver` |
| Grammar 不适合内容 | `composition_planning` |
| overflow、字号、留白、对齐 | `layout_compiler` |
| Chromium、字体或截图异常 | renderer |
| 审美、重心或整套节奏 | constrained aesthetic revision |

Layout 修复阶梯不优先调用 LLM：

1. 在当前 Grammar 内确定性 reflow。
2. 切换 Page Brief 已批准的备选 Grammar。
3. 如果内容分配不可行，回 Authoring 层重新分页。

每个失败生成稳定 fingerprint：

```text
node + page_id + failure_code + affected_fragment_ids + geometry_region
```

- 同一 fingerprint 第二次出现时禁止重复相同修订动作。
- 第三次出现时终止当前自动路径。
- 硬 QA 预算耗尽进入 `INTERRUPTED_EXHAUSTED`，不能进入 Human Review。
- Critic 最多自动修订两轮；仍失败时带 `visual_needs_attention` 进入 Human Review。
- 除非页数、页序或 family 改变，只重建受影响页面及其下游合同。

## 12. 质量体系

### 12.1 Q0 Semantic QA

- 可见字符逐一映射到 atom slice。
- 无新增、删除、改写或重复文字。
- 表格、步骤、比较和 checklist 关系完整。
- fragment 顺序保持原逻辑。
- ContentLock、ContentAtomSet 与 semantic hash 一致。

### 12.2 Q1 Authoring QA

- 每个 fragment 恰好分配一次。
- page count 为 5–18，sequence 连续。
- 每页 `narrative_role` 清晰且不重复凑页。
- 密度曲线可行，避免多个高密度页面连续堆叠。
- 连续页面不重复使用同一种信息组织方式。
- asset directive 与页面任务一致。
- note 等辅助内容不能挤占主要层级；禁止的免责声明不得进入可见内容。

### 12.3 Q2 Design Metrics QA

硬错误继续包括 hash、覆盖、非法引用、越界、碰撞、安全边距、最小字号、对比度、
缺失文字和素材安全。新增的 Grammar-aware 质量底线包括：

- 页面留白率
- 最大连续文字块面积
- 区域信息密度
- 对齐轴偏差
- 栏目宽度平衡
- 卡片间距一致性
- 标题/正文比例
- 视觉重心偏移
- 强调元素数量
- 行长、孤行和 orphan heading
- 图文面积比例

阈值由 Grammar 和 page role 决定，不能用同一全局值评估 Hero 与 Checklist。每个失败
必须携带 page/element/fragment、实际值、阈值、标注区域和建议 revision 类型。

### 12.4 Q3 Render QA

Render QA 只判断最终输出是否忠实执行已通过的 Scene Plan：

- 所有页面和 contact sheet 完整生成。
- 字体、glyph、emoji、图片和背景正确加载。
- DOM 文本与 fragment 精确一致。
- 实际 bounding box 与 Scene Plan 在容差内。
- 无透明空图、白屏、异常 placeholder、裁切或滚动区。
- PNG 尺寸、顺序和字节 hash 正确。

### 12.5 Q4 独立 Aesthetic Review

`AestheticEvaluator` 必须是独立 Interface：

- 默认使用不同于 Authoring 的模型配置。
- 不共享生成 prompt、修订历史或既有分数。
- 只接收最终 PNG、Page Brief 和必要语义。
- 不知道当前 revision round，避免“已经修过所以应通过”的锚定。
- 无法提供独立模型时标记 `critic_independence=degraded`。

Critic 先做单页评估，再做整套评估。每页至少报告 hierarchy、readability、
composition、whitespace、visual focus 和 asset integration；整套报告 rhythm、repetition、
family consistency 和 cover/body consistency。

通过不能再依赖平均总分：

- 任一页有 critical issue，整套失败。
- 任一页有两个以上核心维度低于质量线，整套失败。
- 整套节奏或重复度失败，不能由其他高分页抵消。
- `issues=[]` 与低维度分并存属于无效 critique。
- 每个 issue 必须引用具体页面和可观察证据。

## 13. Human Review Workspace

Human Review 前生成本地审核工作区：

```text
review/
├── index.html
├── contact-sheet.png
├── pages/
├── overlays/
├── previous-revision/
├── quality-report.json
└── decision.json
```

审核界面必须显示：

- contact sheet 与每页原尺寸预览
- 当前版/上一版对比
- Page Brief 和页面职责
- 密度、留白、对齐和失败区域 overlay
- Critic 页面级问题
- 本轮 revision diff
- ContentLock 状态和全部硬 QA 证明
- 每个素材的预览、provider、license、source、sha256、security status、recovery evidence
  与当前 `human_decision`

人工决定：

- `APPROVE`
- `AESTHETIC_OVERRIDE`，必须记录具体理由
- `REQUEST_REVISION`，产生有类型 RevisionRequest
- `REJECT_OR_REPLACE_ASSET`，产生 `target_layer=ASSET` 的 RevisionRequest，返回
  `asset_resolver` 并清除 manifest、Scene Plan、两级 QA、render、critique 和旧 review
- visible-copy edit，清除 ContentLock、atoms 和全部下游视觉合同，回
  R2/assembler/content atomizer/content lock builder

每个批准或审美覆盖必须形成不可变 `HumanReviewDecision`：

```text
HumanReviewDecision
├── decision_id / decided_at
├── run_id / workflow_version / candidate_id / revision_id
├── decision / rationale
├── content_lock_sha256
├── asset_manifest_sha256
├── asset_decisions[]
│   ├── asset_id / asset_sha256
│   ├── decision
│   └── rationale
├── carousel_design_plan_sha256
├── design_plan_qa_sha256
├── render_manifest_sha256
├── render_qa_sha256
├── visual_critique_sha256
└── page_sha256 + contact_sheet_sha256
```

Final Guard 必须对当前 state 和文件重新计算全部 hash，证明它们与人工看到并批准的
candidate 完全一致。仅有 `review_status=approved` 不足以放行。完整 decision 或其
canonical payload 与 hash 嵌入 `final_policy_attestation.json`，exporter 再次验证后由
PublishAttestation 绑定，避免“批准 A、发布 B”。

Human Review 不修改已经被 Scene Plan、QA、RenderManifest 和 Critique 绑定的原始
AssetManifest；其中 `human_decision` 保持 pre-review 的 `pending` 事实。最终逐素材人工
决定只追加到 `HumanReviewDecision.asset_decisions`。APPROVE/AESTHETIC_OVERRIDE 必须对
每个实际渲染素材给出绑定 asset bytes sha256 的 `approved` 决定；任何 rejected/缺失决定
都返回 Asset Resolver。v4 Final Guard 和 exporter 以“immutable AssetManifest +
hash-bound HumanReviewDecision”作为最终素材批准证明，不能沿用 v3 仅检查 manifest
`human_decision` 字段的实现。

Human Review 是统一检查点：每个 candidate 通过全部硬 QA 后只进入一次；人工请求修订后
生成新 candidate，新 candidate 重新通过硬 QA 再进入一次新的审核记录。历史决定只追加，
不能覆盖。

## 14. 错误与可观测性

`InterruptionReport` 必须区分：

- `failure_node`
- `last_completed_node`
- provider attempts
- schema repairs
- QA revisions
- 每页失败次数
- 首次错误与最终错误
- 重复 failure fingerprints
- 当前 candidate 与 run lifetime budget
- 建议恢复动作

CLI、run registry 和 Review Workspace 使用同一错误模型。禁止继续用 `len(errors)` 代表
实际 attempts，也不能用最近完成节点冒充失败节点。

每次 shadow run 至少汇总：总耗时、provider attempts、模型 token、确定性编译次数、
每层 revision 次数、每页质量指标、Critic decision 和人工 decision。

## 15. 双轨迁移

```text
same canonical assembler copy
├── llm_scene_v3 -> v3 atoms + v3 ContentLock -> current production package
└── llm_scene_v4 -> v4 atoms + v4 ContentLock -> isolated shadow/evaluation package
```

两路共享的是相同的标题、封面文案、正文和 hashtags 输入，不共享已经绑定 atom hash 的
`ContentLock`。每一路分别生成并验证自己的 `ContentAtomSet` 和 `ContentLock`，comparison
report 分别记录两路相对 canonical assembler copy 的 visible-copy projection；v3 的既有
Markdown 缺陷可以作为 baseline 差异暴露，不能为了“比较一致”而改写 v3 artifact。

### 15.1 Versioned graph selection

workflow version 必须在构图和读取 checkpoint 之前确定：

1. run registry 为每个 thread 保存不可变 `workflow_version` 和 `run_mode`。
2. 已有记录、null version 或可识别旧 checkpoint 选择 frozen v3 graph；新 v4 run 显式
   记录 `llm_scene_v4` 后选择 v4 graph。
3. CLI 先读取 run metadata，再调用 versioned graph factory，然后用对应 graph 加载
   checkpoint。不能像当前实现一样先无条件 `create_graph()`。
4. v4 checkpoint 不进入 `hydrate_legacy_editorial_state`；legacy hydration 只处理
   v1/v2 -> v3，未知版本继续 fail-closed。
5. v3 graph、state schema、Pydantic class import path 和 exporter 在迁移期冻结，保证现有
   checkpoint 可以继续反序列化和恢复；v4 使用独立 graph/state/schema/exporter Module。
6. 一个 thread 的 workflow version 不可原位切换；想改版本必须创建新 run，并显式关联
   source run 作为 comparison lineage。

隔离规则：

- v3/v4 不共享未完成视觉 checkpoint。
- v4 shadow 不写 `outputs/publish/`，建议写 `outputs/shadow/<run-id>/`。
- v4 shadow 通过独立 terminal exporter 生成评估包；绝不调用 `content_writer`。
- v4 失败不影响同输入的 v3 run。
- 一次运行中途不能自动从 v4 切回 v3。
- 数据库变更只能新增兼容表/字段，不降级或重建本地状态。

实施分期：

### Phase 0：基线与 replay

- 整理两个问题包的正/负例 fixture 和人工标注。
- 建立离线 replay runner、v3 指标基线和 v3/v4 comparison report。
- 建立 versioned graph factory、run metadata 分派和 frozen v3 checkpoint 恢复测试。
- 建立 production/shadow terminal 分支，证明 shadow 不写正式记忆与 publish root。
- 不改变 v3 node topology、schema import path、发布合同或渲染输出。

### Phase 1：可靠性骨架

- 建立 Gateway、hard timeout、单层 retry、append-only Attempt Ledger、failure fingerprint 和
  InterruptionReport。
- 用 timeout、503、invalid JSON 和 crash injection 验证恢复。
- Gateway 先只服务 v4，避免扩大 v3 风险。

### Phase 2：最小纵向切片

- 完成 Atom -> Semantic -> Brief -> Grammar -> Compiler -> Renderer -> Metrics -> Review。
- 先实现 `editorial_hero`、`comparison_grid`、`step_flow`。
- 必须用真实 Chromium PNG 验证，不能停留在 schema 单测。

### Phase 3：信息设计扩展

- 增加其余五种 Grammar。
- 实现页面密度重分配、备选 Grammar、局部重编译和 carousel rhythm 检查。
- 每个 Grammar 都有正例、边界例和失败例。

### Phase 4：Critic 与 Human Review

- 接入独立 AestheticEvaluator、两阶段 Critic、最差页规则和 Review Workspace。
- 完成前 v4 没有正式发布权限。

### Phase 5：Shadow 生产

- 覆盖至少 10 个不同选题、约 80 页和主要页面类型。
- 同输入生成 v3/v4 comparison report，进行不知道版本来源的人工盲评。

### Phase 6：有限启用与默认切换

1. 仅通过显式 CLI selector 使用 v4。
2. beauty/skincare 新任务默认 v4，保留新运行开始前显式选择 v3。
3. 稳定观察后停止为 v3 增加新视觉能力；v3 退役另行批准。

## 16. Go/No-Go Gate

| Gate | 进入下一阶段的必要条件 |
| --- | --- |
| G0 Baseline | 两个问题包可稳定 replay；v3 checkpoint 恢复和 shadow 隔离测试通过 |
| G1 Reliability | timeout/retry/resume/crash injection 全部通过 |
| G2 Vertical Slice | 三种首批 Grammar 真实渲染并通过全部硬 QA |
| G3 Quality | 已知坏页被拦截，优秀封面保持通过 |
| G4 Shadow | 合同、可靠性和盲评指标达到发布门槛 |
| G5 Cutover | comparison report 经人工批准，回滚演练通过 |

任何 Gate 未通过都停留在当前阶段，不以“后续补测试”为理由推进。

## 17. 发布资格指标

### 合同与安全

- visible copy 与 ContentAtomSet 逐字符一致。
- ContentLock 未被视觉阶段修改。
- 10 个合同及全部 PNG hash 通过 attestation。
- 聚合 DesignPlanQAResult 完整证明 Q0/Q1/Q2 全部通过并绑定当前 v4 内部 Interface。
- HumanReviewDecision 绑定当前 candidate、合同和全部页面 hash，Final Guard/exporter 重算通过。
- Asset Manifest 满足 provider、许可、路径、事务和字节 hash 要求；每个渲染素材另有
  HumanReviewDecision 中的 hash-bound approved 决定。
- 旧 checkpoint 不能被误识别为 v4。
- 所有硬 QA 不存在 override。

### 视觉质量

- 两个已知问题包的人工标记严重缺陷不能再被 Critic 全部漏过。
- 两个优秀封面继续通过。
- shadow 页面不存在裁切、拥挤、低于最小字号或安全边距违规。
- 至少 10 个选题的盲评中，v4“更好或相当”比例达到 80%。
- 不出现任何人工判定为不可发布的严重回归页。
- 每个 candidate 最多两轮自动审美修订。

80% 是切换前预先承诺的初始门槛。可以根据 Phase 0 样本设计在执行前提高或补充分层
指标，但不能在看到失败结果后降低门槛迁就实现。

### 运行可靠性

- 每次请求在 deadline 加固定清理宽限期内结束。
- timeout 后不存在泄漏 worker。
- resume 后 budget 和 failure fingerprint 不变。
- 相同错误不能执行三次相同修订。
- provider attempts 不超过 candidate budget。
- CLI 准确显示失败节点、预算和恢复建议。

### 可维护性

- 每个 Module 有单一清晰 Interface 与有类型错误。
- LLM prompt 不承担最终坐标生成。
- Grammar 与 design tokens 可独立离线测试。
- Layout Compiler 对相同输入确定性输出。
- 新增 Grammar 不修改 renderer。
- 替换 Critic 模型不修改 Authoring Module。

## 18. 回滚与 v3 退出

v4 故障时只改变新运行的 workflow selector：

- 新任务切回 `llm_scene_v3`。
- 保留 v4 artifacts、checkpoint 和 Attempt Ledger 作为诊断证据。
- 不把 v4 中间合同转换成 v3 后继续运行。
- 不覆盖既有 v3 canonical publish package。
- 已开始构建的失败 v4 package 保持隔离，不能标记为可发布。
- 不执行数据库降级或删除状态文件。

只有满足下列条件并获得明确人工批准后，才另行设计 v3 退役：

- v4 连续完成代表性生产任务。
- 核心 Grammar 均有真实发布级样本。
- v4 recovery 和 Human Review 已实际使用。
- 没有只能由 v3 生成的内容类型。
- 历史 v3 checkpoint 有保留策略。

v3 退役不意味着恢复旧 renderer。旧 v1/v2 兼容仍只存在于 `legacy.py`。

## 19. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Grammar 数量少导致模板感 | Grammar 只定义关系；用 Page Brief、tokens 和受控参数产生变化，并用 repetition QA 约束 |
| Compiler 复杂度过高 | 先完成三种 Grammar 纵向切片；每个 Grammar 独立 solver 与 fixture |
| 新 Critic 仍有偏差 | 正/负校准集、盲评、最差页规则、Human Review；总分不参与硬放行 |
| v4 schema 污染 v3 | workflow-version discriminant、独立 checkpoint、versioned parser |
| resume 选错 graph | 构图前读取 immutable run version；冻结 v3 import path；跨版本恢复测试 |
| shadow 成本过高 | 显式启用、总 attempt budget、只对代表性选题运行 |
| 自动修订循环 | failure fingerprint、typed RevisionRequest、三次同类失败中断 |
| Human Review 负担增加 | contact sheet、overlay、diff 和页面级反馈集中到单一 workspace |

## 20. 文档与后续步骤

设计规格经书面复核批准后：

1. 使用 `superpowers:writing-plans` 生成精确实施计划。
2. 计划采用 TDD，按最小纵向切片拆成可验证的小任务。
3. 每个阶段明确文件、测试、命令、提交边界和 Go/No-Go Gate。
4. 实施前更新 `docs/README.md` 的 spec/plan 索引；生产切换时再更新当前架构文档和 README。

本文件是批准设计，不是自动待办；只有后续明确批准的实施计划或 issue 定义执行范围。
