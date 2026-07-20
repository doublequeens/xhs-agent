# 模板复刻指南：从原型到生产

> 本文档从 soft_pink 复刻过程中提炼（2026-07-19），记录了每一个正确决策和每一个错误弯路。
> 用于指导 agent 高效无误地复刻其余 5 个模板家族到生产渲染管线。

---

## 第零法则：原型 HTML 就是规格书

**逐行读原型 HTML，精确复制每个 CSS 值，不要"解释"或"改进"。**

- 原型用 `font-size:300px` → 你就用 `300px`。
- 原型用 `line-height:.78` → 你就用 `.78`（如果 probe 阻止，修 probe，不要改值）。
- 原型用 HarmonyOS Sans Medium → 你就去 `template_registry._FONTS` 确认 display 字体文件是 Medium。

**soft_pink 复刻中最大的浪费（~15 轮迭代）来自于"自己发挥"而非忠实复制。** 每当不确定时，重新读原型 HTML。

原型文件位置：`examples/templates-mockup/setN-*/template.html`（6 套家族各一份）。
真实文案原型（7 页 carousel）：`examples/prototype-makeup-port/template.html`（soft_pink 专用）。

---

## 五大致命错误（必须避开）

### 错误 1：在一个 copy atom 里混合不同字号

**发生了什么**：把 300px 数字和 78px 标题放在同一个 `[data-card-copy]` atom 里。
**后果**：`overflow:headline`（字形超出行框）+ `headline_line_count_invalid`（getClientRects 碎片化成 ~6 "行"）。
**根因**：probe 检查每个 atom 的 `scrollHeight/clientHeight` 和 `line_count`（通过 getClientRects）。混合字号导致溢出和碎片。
**正解**：**每个不同字号的可见文字必须是独立的 `[data-card-copy]` atom。** 大数字是 `hero_numeral` atom（300px），标题是 `headline` atom（78px），副标题是 `emphasis` atom。每个 atom 只有一个字号。

### 错误 2：CSS 选择器 `.template-X.composition-Y`（无空格）

**发生了什么**：写了 `.template-soft-pink.composition-sp-cover .sp-row`（无空格 = 同一元素）。但 `template-soft-pink` 在 `<main>` 上，`composition-sp-cover` 在 `<section>` 上——不同元素，选择器**永远不匹配**。
**后果**：所有 composition 专属 CSS 静默失效，页面以默认 16px 渲染（完全没样式）。**没有报错**——只是渲染结果不对。
**正解**：**始终用后代选择器**：`.template-soft-pink .composition-sp-cover .sp-row`（有空格）。

### 错误 3：没检查字体配置

**发生了什么**：生产 `display` 字体是 `Bold`，但原型用的是 `Medium`。
**后果**：标题/数字看起来比原型粗，用户说"字体粗细不一样"。
**正解**：读 `template_registry._FONTS[family]`，确认 display/body/body_bold 字体文件与原型 `@font-face` 声明一致。不一致就改 `_FONTS`。

### 错误 4：headline 放在 header 行而非卡片内

**发生了什么**：`render_card_shell` 默认的 `render_header` 把 kicker+headline 放在顶部 header 网格行。但原型的 headline 在**卡片内部**，只有 kicker（pill）在卡片上方。
**后果**：headline 和卡片内容分属不同 grid 行，视觉割裂。
**正解**：用 `render_card_shell` 的 `header` 参数传 kicker-only header（已实现），headline 放在 bespoke body 里。

### 错误 5：只渲染 content_blocks[0]，忽略多 block

**发生了什么**：bespoke renderer 只渲染 `content_blocks[0]`，但测试 fixture（make_frame）有 3 个 block。未渲染的 block 导致 `actual_copy != _expected_copy`。
**正解**：bespoke renderer 渲染 `content_blocks[0]`（原型结构）+ `content_blocks[1:]`（用 `_render_block` 标准兜底）。生产帧只有 1 个 block，所以只显示原型结构。但 renderer 必须处理多 block 以通过契约。

---

## 正确的架构决策（复刻时要沿用）

### 1. 分离 atom 原则
**每个不同字号的可见文字 = 独立的 copy atom。** 这解决了 99% 的 probe 问题。
- 大数字 → `hero_numeral` atom（独立字段）
- 标题 → `headline` atom（digit 和冒号通过 `cover_title_text()` 移除）
- 副标题/标签 → `emphasis` atom
- 正文 → `content_blocks[N].body` atom
- 列表项 → `content_blocks[N].items[i]` atom

### 2. `cover_title_text(headline, hero_numeral)` 助手
位置：`src/rendering/editorial/primitives.py`。
从 headline 中移除 hero numeral digit 和冒号，返回 `pre + suf`。
- 标题 atom 渲染 `pre<br>suf`（textContent = pre+suf = `cover_title_text()` 结果）
- `_expected_copy` 和 `_expected_probe_text` 都调用它（保持一致）
- headline 本身不变（`first_screen_promise` 不受影响，carousel QA 通过）

### 3. `_curate_frames_for_publish` — 锁定前确定性 curation
位置：`src/nodes/node_o_storyboards_generator.py`。
在 ContentLock 之前对每帧做确定性修改：
- `footer = None`（所有家族，永不渲染免责声明）
- `persona = _ACCOUNT_PERSONA`（soft_pink 专属）
- `hero_numeral` 提取（cover 的 N步 digit）
- `emphasis` 去重（cover 去掉与 hero 重复的第一项）

### 4. `render_card_shell(header=..., footer=...)` — 自定义 header/footer
位置：`src/rendering/editorial/primitives.py`（已添加 `header`/`footer` 可选参数）。
- `header`：kicker-only（pill），headline 在 body 里
- `footer`：persona atom（卡片底部行）

### 5. Persona 在 footer 槽 + `position:absolute`
Persona 通过 `footer` 参数传给 `render_card_shell`（成为 `.card` 的直接子元素），加 `position:absolute; bottom:54px` 相对 `.card` 定位。

### 6. 字体检查扩展
位置：`src/rendering/editorial/renderer.py` + `src/nodes/node_p_render_qa.py`。
`hero_numeral` 角色允许使用 display 字体（和 headline 一样）。
检查代码：`expected_family = display_family if role in ("headline", "hero_numeral") else body_family`。

### 7. ｜分隔符隐藏
列表项（explanation/steps）用 ｜ 分隔段落。渲染时用 `<span class="sp-sep" style="display:none">｜</span>` 连接各段——textContent 保留 ｜（契约匹配），视觉隐藏（不显示分隔符，不占行）。

### 8. 装饰元素（序号圆圈、勾选圆圈）用 `aria-hidden="true"`
装饰性的数字/符号（enum 圆圈里的数字、chk 圆圈里的序号）**不是** `[data-card-copy]`——它们用 `aria-hidden="true"`，不进入 actual_copy。

### 9. 每个 `[data-card-copy]` atom 必须有显式 `font-size` 和 `line-height`
CSS 里没有显式 `line-height` → computed 值为 `"normal"` → probe 读到 `nan` → `PageProbeAttestation` 验证失败。
**检查清单**：对每个 copy atom 的 CSS 类，确认有 `font-size` 和 `line-height`。

### 10. body/items 角色：行高/字号比必须在 [1.345, 1.555]
role 以 `.body` 结尾或含 `.items[` 的 atom，其 `line-height / font-size` 比值必须在 [1.345, 1.555] 范围内。

---

## 渐进式复刻流程（7 步）

### 步骤 1：读原型，提取参数表
读 `examples/templates-mockup/setN-*/template.html`。对每个 archetype，提取：
- 结构（DOM 层级、flex/grid 布局）
- 每个 CSS 类的 `font-family` / `font-size` / `font-weight` / `line-height` / `color` / `margin` / `padding`
- 字体声明（`@font-face` 的 src 文件）
- 文案结构（标题/副标题/列表项/标签 如何组织）

输出：一份参数表（markdown 表格或注释），作为后续编码的精确参考。

### 步骤 2：检查并修正字体配置
读 `template_registry._FONTS[family]`。对照原型 `@font-face` 声明：
- `display` 字体文件是否与原型的标题字体一致？
- `body` 字体文件是否与原型的正文字体一致？
- 不一致 → 修改 `_FONTS[family]`。

### 步骤 3：编写 bespoke 渲染函数
在 `src/rendering/editorial/templates/{family}.py` 中：
- 为每个 archetype 编写 body builder（返回 HTML section）。
- 所有可见文字通过 `copy_atom(value, role=..., class_name=..., tag=...)` 渲染。
- 装饰元素（序号圆圈、图标）用 `aria-hidden="true"`。
- ｜分隔的列表项用 `_render_copy_value(seg)` + `<span class="sp-sep">｜</span>` 连接。
- **DOM 顺序必须匹配 `_expected_copy` 顺序**：kicker, [hero_numeral], headline, [content_blocks: heading, body, items], [emphasis], [persona]。

### 步骤 4：编写 CSS
在 `{family}.py` 的 `FAMILY_CSS` 常量中：
- 从原型逐值复制 CSS（font-size, line-height, color, padding, margin, gap 等）。
- **每个 `[data-card-copy]` atom 的类必须有显式 `font-size` 和 `line-height`**。
- body/items 类的 `line-height/font-size` 比在 [1.345, 1.555]。
- 用**后代选择器**：`.template-{family} .composition-{variant} .element`（有空格）。
- 标签/名称等非 headline 元素需要 Medium 字体时，用 `font-family:var(--template-display)` 嵌套在 atom 内部的 span 上（atom 本身保持 body 字体给 probe 检查）。

### 步骤 5：更新 curation
在 `src/nodes/node_o_storyboards_generator.py::_curate_frames_for_publish` 中：
- 为新 family 添加 persona 注入（如果原型有 persona 落款）。
- 检查 footer 是否需要 strip（所有家族都应该 strip 免责声明——已全局处理）。
- 检查 cover 是否需要 hero_numeral 提取（如果 cover headline 有 N步 pattern）。

### 步骤 6：更新契约助手
- `_expected_copy`（`renderer.py`）：如果加了新字段（如 hero_numeral），插入正确的 role 和位置。
- `_expected_probe_text`（`node_p_render_qa.py`）：**完全一致**地同步。
- 字体检查（renderer.py + render_qa）：如果新角色需要 display 字体，扩展检查。
- 如果有 `cover_title_text` 类的标题变换，两个助手都要应用。

### 步骤 7：验证
1. `python -m compileall -q src main.py` — 语法检查。
2. 写验证脚本（类似 `/tmp/verify_softpink.py`）：加载已发布的 payload → curation（模拟 generator）→ `render_carousel` → `validate_render`。
3. 断言 `validate_render` 返回 `issues: 0`。
4. 构建 contact sheet（Pillow 拼图），人工检查视觉效果。
5. `pytest -q tests/rendering/editorial tests/schemas tests/editorial_carousel tests/nodes/test_render_qa.py tests/nodes/test_carousel_qa.py tests/examples/test_template_mockups.py`。
6. `git diff --check`。

**如果 `validate_render` 报错**：
- `overflow:headline` → atom 混合字号（拆成独立 atom）或 line-height 太小（加大到包含字形）。
- `headline_line_count_invalid` → atom 混合字号导致 getClientRects 碎片（拆成独立 atom）。
- `line_height nan` → CSS 类缺少显式 `line-height`（加上）。
- `body_line_height_invalid` → 行高/字号比超出 [1.345, 1.555]（调整）。
- `actual_copy != _expected_copy` → DOM 顺序不对（重排）或有字段未渲染（补上）。
- `unexpected font` → 角色需要 display 但被判 body（扩展字体检查）或字体配置错误。
- `ink_clip` → 内容超出 `.template-card` 边界（缩小或移位）。

---

## 文件改动清单（每个家族复刻需要碰的文件）

| 文件 | 改什么 |
|---|---|
| `src/rendering/editorial/templates/{family}.py` | bespoke 渲染函数 + FAMILY_CSS |
| `src/rendering/editorial/template_registry.py` | `_FONTS[family]`（如需改字体文件） |
| `src/nodes/node_o_storyboards_generator.py` | `_curate_frames_for_publish`（persona、hero_numeral 等） |
| `src/rendering/editorial/renderer.py` | `_expected_copy`（新角色/变换）、字体检查 |
| `src/nodes/node_p_render_qa.py` | `_expected_probe_text`（同步）、字体检查 |
| `src/rendering/editorial/primitives.py` | 如有新的 text 变换助手（如 `cover_title_text`） |
| `tests/rendering/editorial/test_{family}_bespoke.py` | 新增契约测试 |

---

## soft_pink 复刻中的错误时间线（供反思）

| 轮次 | 错误 | 浪费的迭代 |
|---|---|---|
| 1 | 只移植 cover+steps，漏掉其余 5 页 | 1 轮（用户指出） |
| 2 | hero_numeral 放在 headline atom 内（混合字号） | ~5 轮（overflow + line_count 反复调） |
| 3 | 不读原型 HTML，靠猜 CSS 值 | ~3 轮 |
| 4 | 字体配置是 Bold 不是 Medium | 1 轮 |
| 5 | CSS 选择器无空格（.template-X.composition-Y） | 1 轮（静默失效） |
| 6 | 白卡套在封面上 | 1 轮 |
| 7 | persona 位置反复调 | ~3 轮 |
| 8 | ｜分隔符可见 | 1 轮 |
| 9 | 只渲染 block[0]，多 block 契约失败 | 1 轮 |
| **总计** | | **~17 轮浪费** |

如果遵循本指南的 7 步流程，每个家族应该在 **2-3 轮** 内完成（写代码 → 验证 → 微调）。

---

## white_quote 复刻经验（2026-07-20）

> 第二个被复刻的家族（霞鹜文楷语录风）。暴露了 soft_pink 没遇到的 **grid 布局** 和 **margin 重置** 两类新坑；也验证了 `<br>` 断行、font-weight 借 Medium 等技巧可跨家族复用。

### 新增致命错误（white_quote 暴露，soft_pink 未遇到）

#### 错误 6：`_BASE_TEMPLATE_CSS` 不 reset margin
**发生了什么**：自定义的 col 标题用 `<h3 class="wq-col-h">`、正文用 `<p class="wq-col-p">`。`_BASE_TEMPLATE_CSS` 只写了 `*{box-sizing:border-box}`，**没有** `margin:0;padding:0`。于是 `<h3>`/`<p>` 带浏览器默认 margin-block（~38px），每个 col 被撑高近一倍，3 个 col 合计把页面撑到 ~1260px，超出可用区裁切（`ink_clip:emphasis`）。
**后果**：内容溢出 `.template-card` 底部，emphasis 被 `overflow:hidden` 裁掉，probe 失败。
**正解**：**任何用 `<h1>-<h6>`/`<p>` 等带默认 margin 标签的自定义 copy 类，必须显式 `margin:0`。** base 只有 `.block-heading{margin:0}`/`.block-body{margin:0}` 两处 preset，自定义类名都要自己加。
**教训**：写自定义类前，先 grep `_BASE_TEMPLATE_CSS` 确认它 reset 了什么（只 reset box-sizing，**不** reset margin/padding）。

#### 错误 7：grid auto-placement + 空 header 字符串导致 bespoke section 掉进 row1
**发生了什么**：`render_card_shell` 的 `.template-card` 是 `display:grid;grid-template-rows:auto 1fr auto`。为了不重复 kicker+headline，bespoke 路径传 `header=''`（空**字符串**，非 None）。空串 → 不渲染 `<header>` 元素。font-probes 和 footer 又都是 `position:absolute`（脱流）。于是 bespoke `<section>` 成了**唯一的 in-flow grid item**，被 auto-placement 放到 **row1（auto）**，而不是预期的 row2（1fr）。section 高度只剩内容自身高度（~573px），`justify-content:center` 在这么矮的盒子里居中＝无效，内容堆在上半部。
**后果**：cover/quote/boundary 文字偏上，没垂直居中。
**正解**：**传一个空的 `<header>` 元素**（`'<header class="template-header"></header>'`）占住 row1，bespoke section 才会落到 row2（1fr）满高，居中才生效。或让 section `grid-row:1/-1` 跨满（但对 generic fallback 有重叠风险，不推荐）。
**soft_pink 为何没遇到**：soft_pink 总传 kicker-only 的真实 `<header>`，天然占住 row1。

#### 错误 8：`.template-footer{display:none}` 误伤 footer atom
**发生了什么**：想让 white_quote 卡片底部干净（persona 走绝对定位的 wq-handle），写了 `.template-footer{display:none}`。但 **smoke 测试不跑 curation**，make_frame 的 `footer` 文本仍在 → `render_footer` 产出 footer-copy atom（role=footer）→ 被 display:none 隐藏成 0×0 → probe `width/height > 0` 校验失败。
**后果**：`text_results.N.width Input should be greater than 0`。
**正解**：**不要 display:none 掉可能含 atom 的容器。** 改为只隐藏 `page-number`（aria-hidden，安全）+ `.template-footer{border-top:none;padding-top:0}`。生产环境 curation 把 footer 设 None，footer 元素自然为空不可见；smoke 测试带 footer 文本时 atom 仍可见。

#### 错误 9：centered cover 塞不下 content_blocks → 溢出裁切
**发生了什么**：bespoke cover 是居中极简版式（headline + 副标题），但 make_frame 给 cover 3 个 content_blocks（带 items）。居中布局把它们全堆进来，总高 > 可用区，底部裁切（`ink_clip:kicker`）。
**soft_pink 为何没遇到**：soft_pink cover 仅在 headline 含"N步"数字时才 bespoke，否则走 generic（generic 的 grid 能装下多 block）。
**正解**：**cover 条件 bespoke**——仅当 `frame.content_blocks` 为空时 bespoke（生产 curation 已清空 cover 的 content_blocks），否则 generic 兜底。镜像 soft_pink 的条件 bespoke 模式。

#### 错误 10：`<br>` 断行与通用测试 `escape(headline) in html` 冲突
**发生了什么**：为了让短标题（"为什么慢即是快"，7 字）在宽卡片上分两行，在首个"，"处插 `<br>`。但 `tests/rendering/editorial/test_templates.py::test_every_family_renders_every_archetype` 断言 `escape(headline) in html`（headline 连续出现在 HTML）→ `<br>` 打断字符串 → 4 个 bespoke archetype 全挂。
**关键认知**：`<br>` **不改变 textContent**，所以 probe 的 `actual_copy == _expected_copy` 契约照过；冲突的只是这个**字符串级**测试。
**正解**：把断言改为 `escape(headline) in html.replace("<br>", "")`——`<br>` 是纯渲染换行（非内容），strip 后匹配，对所有家族安全（其他家族无 `<br>`，replace 是空操作）。

### 做对的事情（white_quote 复刻要沿用）

1. **先读契约助手的 DOM 顺序**：`renderer._expected_copy` / `render_qa._expected_probe_text` 的顺序（kicker → hero_numeral → headline → content_blocks[heading/body/items] → emphasis → persona → footer）是 atom 排列的唯一真理来源。写 builder 前先读，写完用 `re.findall(r'data-copy-role="([^"]+)"', html)` 对照 expected 打印 diff。
2. **用 `page.evaluate()` 量实际坐标定位 bug**：垂直居中失效（section 只 573px）、h3 margin 撑高，都是量出实际 `y/h/display/justifyContent` 后才定位根因，而非盲调 CSS。
3. **font-weight 借 Medium 视觉**：display family 仅注册 700 一个 face（任意 weight 都映射到它），body family 有 400/700。非 headline atom（kicker/小标题/persona）想要 Medium 观感时，**保持 body family + `font-weight:700`**（命中 body_bold=Medium），computed fontFamily 仍是 body family，过 font 检查。比"内层 span 换 display 字体"更简单。
4. **`<br>` 在首个"，"处断行**：`idx = text.find("，")`，`line1=text[:idx+1]`（逗号留在行尾），无逗号则取 `(len-1)//2` 中点。textContent 不变，契约安全；断点符合 mockup 编辑习惯。
5. **persona 在 bespoke + generic 两条路径都渲染**：white_quote 的 render_frame 把 `footer=_persona_atom(frame)` 穿进两条路径。soft_pink 因常见 archetype 全 bespoke 未暴露此问题；white_quote 任何走 generic 的 archetype（如 scene/diagnostic）也必须渲染 persona，否则 actual≠expected。
6. **先验证再交签字**：每轮改动后跑 `render_carousel`（等价 `validate_render issues:0`）+ Pillow contact sheet + 图像分析自检，再交用户。避免把"测试过但视觉错"的产物交出去。

### 与 mockup 冲突时：以用户最终意愿为准

复刻中两处 mockup 有、用户明确不要的元素：
- 顶部中间细分割线（mockup `.rule`，每页都有）→ 用户要求去掉。
- 装饰引号 `"` mark（mockup `.mark`，quote/boundary 有）→ 一度因变形（120px/line-height:1 + 内容未居中导致裁切）被用户当成"暂停⏸"要求去掉；**居中修好后字形正常**，用户又要求恢复。

**教训**：当 mockup 与用户明确意愿冲突，或某元素"渲染异常"时，**先查是不是布局 bug 导致的渲染异常**（如裁切），而非立刻删元素。删/留以用户最终确认为准，但要把"为什么异常"查清楚。

### white_quote 错误时间线

| 轮次 | 错误 | 根因归类 |
|---|---|---|
| 1 | cover/quote/boundary 没垂直居中 | grid auto-placement + 空 header（错误7） |
| 2 | 装饰引号 `"` 变形成"暂停⏸" | 内容未居中→mark 被挤到顶部裁切（先误删后恢复） |
| 3 | smoke 测试 `cover layout probe invalid evidence: width=0` | `.template-footer{display:none}` 误伤 footer atom（错误8） |
| 4 | `cover visible text does not match storyboard` | cover/quote 把 emphasis 渲染在 content_blocks 之前（DOM 顺序） |
| 5 | `cover visible text does not match` | quote/boundary 漏渲染 kicker（make_frame 带 kicker） |
| 6 | `checklist layout probe invalid: line_height nan` | `wq-cell-copy` 缺显式 line-height（指南决策9，漏一个类） |
| 7 | `baseline(cover) ink_clip:kicker` | centered cover 塞不下 3 个 content_blocks（错误9） |
| 8 | `baseline(explanation) ink_clip:emphasis` | `<h3>`/`<p>` 默认 margin 撑高（错误6） |
| 9 | `test_every_family_renders_every_archetype` 4 挂 | `<br>` 断行打断 headline 连续子串（错误10） |
| 10 | 文案里出现字面 `<br>` | verify 脚本把 `<br>` 当文案塞进 headline（脚本 bug，非渲染器） |
| 11 | explanation/checklist 标题居中、应左对齐 | section 多写了 `align-items:center` |
| **总计** | | **~11 轮** |

**结论**：第二个家族仍花了 ~11 轮，主要消耗在 **grid 居中机制**（错误7）和 **margin 重置**（错误6）这两个 soft_pink 未遇到的系统级坑上。把这两条加入"动手前检查清单"后，后续家族应回到 2-3 轮。

### 动手前检查清单（white_quote 后新增）

在写 bespoke CSS 前逐条确认：
- [ ] `_BASE_TEMPLATE_CSS` **不 reset margin**——自定义 heading/p/li 类都要 `margin:0`。
- [ ] bespoke section 要落到 grid row2（1fr）：传空 `<header>` 元素占 row1，**不要**传 `header=''`。
- [ ] centered 页面（cover/quote/boundary）：section 必须 `display:flex;flex-direction:column;justify-content:center`，且确认 section 高度 = 可用区（用 `evaluate` 量 `h` 验证）。
- [ ] 条件 bespoke：cover 在 content_blocks 非空时走 generic（镜像 soft_pink）。
- [ ] 两行断行：`<br>` 不影响 textContent，但要让 `test_every_family_renders_every_archetype` 的断言 strip `<br>`。
- [ ] 不要 `display:none` 含 `[data-card-copy]` atom 的容器；隐藏装饰用 `aria-hidden` + 针对性 class。

---

## pink_red 复刻经验（2026-07-20）

> 第三个被复刻的家族（粉红粗体 motivational）。复用了 white_quote 的 checklist（grid/margin/条件 cover/`<br>` 断行），仍暴露了 **`<br>` 与 FakePage 解析器**、**ascender 裁切**、**家族招牌特征（交替底色）如何落地** 三类新问题。

### 新增致命错误（pink_red 暴露，前两个家族未遇到）

#### 错误 11：`<br>` 破坏 FakePage CopyParser 的 void 元素深度追踪
**发生了什么**：`<br>` 断行后，`test_renderer.py` 11 个测试全挂（"save visible text does not match"），但真 Chromium `test_chromium_smoke` 全过。
**根因**：测试用的 FakePage（`conftest.py::CopyParser`，基于 `HTMLParser`）在 `handle_starttag` 里对**任何**开始标签 `depth += 1`。`<br>` 是 void 元素，HTMLParser 只调 `handle_starttag`、**不**调 `handle_endtag` → depth 只增不减 → 当前 atom 永不闭合 → 吞掉后续所有 `[data-card-copy]`，actual 只剩第一个 atom。
**关键认知**：**真 probe 读 `textContent`，`<br>` 不影响它**；冲突的只是 FakePage 这个**测试基础设施**。white_quote 也用 `<br>` 却没暴露，因为 `test_renderer` 的 conftest fixture 固定用 `pink_red`（不是 white_quote）。
**正解**：`CopyParser.handle_starttag` 对 void 元素（br/img/hr/input/…）**不增 depth**（与真 probe 行为对齐）。

#### 错误 12：headline 紧贴 section 顶 → Heavy 字体 ascender 被 `overflow:hidden` 裁
**发生了什么**：comparison 页无 kicker，60px Heavy 标题紧贴 section 顶部（y=90），Heavy 字体 ascender 越过 section 的 `overflow:hidden` 边界 → `ink_clip:headline`。
**根因**：base `.template-body{overflow:hidden}` 在 section 顶裁切；而卡片还有 90px padding 余量没被利用。
**正解**：bespoke section 加 `overflow:visible`，让内容呼吸进卡片 padding 区——**卡片自身的 `overflow:hidden` 仍在卡边界裁切**（安全），probe 的 `layout_clip` 仍按 section 盒子判定（内容若真溢出仍被抓）。

### 正确决策（pink_red 新增，复刻要沿用）

#### 决策 11：家族招牌视觉特征（如"交替底色"）由页码决定，配以 CSS 变量两套 scheme
pink_red 的招牌是 **pink/red 严格交替**（pink, red, pink, red…，不连续同色）。实现：
- **底色按页码，不按 archetype**：从 `frame_id`（生产格式 `frame-NN-archetype`）正则解析 NN，**偶数页=red，奇数页=pink**。无数字时（测试 fixture）默认 pink。
- 这才是"严格交替"的唯一保证——archetype 顺序不可控，按 archetype 写死无法避免连续同色。
- **bespoke 配色全部用 CSS 变量**（`--pr-ink/--pr-sub/--pr-cell-*/--pr-panel-*`）：pink 为默认（写在 FAMILY_CSS 的 `.template-card.template-{family}` 上），red 页用 **per-frame `<style>`**（每页是独立 HTML 文档）覆盖同一组变量。这样**任何 archetype 落在 pink 或 red 底上都自适应**（红字/白字、白卡/半透明卡），不会出现"steps 落到 pink 页白字不可见"。
- per-frame `<style>` 在 FAMILY_CSS **之后**（同 `<style>` 块内、源序在后），同特异性后者胜 → 变量覆盖生效。不改 `render_card_shell` 签名。

#### 决策 12：无 mockup 的 archetype 用设计 skill 做 bespoke，2×N 卡片网格 1–N 递增
pink_red 的 scene 在 mockup 里没有对应页。用户要求有设计感、内容多时也要好看。用 `high-end-visual-design` skill 的 **Double-Bezel 嵌套卡片 + eyebrow 标签 + Asymmetrical Bento + 字体层级** 落地：
- 每个 content_block → 一张白卡（hairline ring + inset 高光 + 大圆角，非扁平文本）。
- **2 列网格，卡片数 1–4 随内容递增，最多 4 张**；CSS `:last-child:nth-child(odd)` 让奇数张末卡跨满列（1→满宽 / 2→并排 / 3→2+1 / 4→2×2），自动平衡。
- **超过 4 个 block 时，多出的并入第 4 张卡**（保所有 heading/body/items 的契约角色，不丢内容、不破 `actual≠expected`）。
- **generic 兜底也要放大字号**：非 bespoke archetype（走 generic）用基础小字号，在粗体家族下显得空旷。给 generic 兜底的 `block-heading/block-body/item-copy/emphasis-chip` 覆盖放大字号（贴合家族气质），bespoke 页用自家 `pr-*` 类互不干扰。

#### 决策 13：heading/body 角色取 Heavy 观感用"内层 span 套 display 字体"
`content_blocks[*].heading` 角色要求 body 字体（font 检查），但 mockup 标题用 Heavy。直接给 heading atom 用 display 字体类 → `unexpected font`。正解：atom 用 body 字体（过探针），**内层 `<span>` 套 `font-family:var(--template-display)` 取 Heavy 观感**（textContent 不变）。比"整个 atom 换 display"安全。

#### 决策 14：cover hero 用 `flex:1` 居中
cover section 若用 `justify-content:space-between` 但只有 2 个 in-flow 子（topbar + hero，persona 绝对定位脱流）→ space-between 把 hero 推到底。hero 加 `flex:1;justify-content:center` 占满中间、内容垂直居中。

### 做对的事情（pink_red 沿用）
1. 每改一版用 `re.findall(r'data-copy-role="([^"]+)"', html)` 对照 `_expected_copy` 打印 diff，定位 DOM 顺序/缺字段问题（比盲调快）。
2. mismatch 时用 FakePage 的 CopyParser 复现 + 量实际 `y/h`，定位到 `<br>` 吞 atom、margin 撑高等根因。
3. 条件 bespoke cover（`content_blocks` 空才 bespoke），镜像 soft_pink/white_quote。
4. 每轮 `render_carousel`（等价 `validate_render issues:0`）+ Pillow contact sheet + 图像分析自检后再交签字。

### pink_red 错误时间线

| 轮次 | 错误 | 根因归类 |
|---|---|---|
| 1 | steps/comparison 漏渲染 emphasis | make_frame 带 emphasis，契约要求渲染 |
| 2 | `unexpected font for content_blocks[0].heading` | heading atom 误用 display 字体类（决策13） |
| 3 | comparison `visible text does not match` | 漏 ｜ 分隔符 span（决策7） |
| 4 | block heading/body 在有 items 时不渲染 | lead 条件写反（漏字段） |
| 5 | `ink_clip:headline`（comparison） | headline 紧贴 section 顶被裁（错误12） |
| 6 | save DOM 顺序写反（heading→items→body） | 契约顺序 |
| 7 | test_renderer 11 挂 | `<br>` 破坏 FakePage CopyParser（错误11） |
| 8 | cover 标题在底部 | hero 没 flex:1（决策14） |
| 9 | scene（generic 兜底）排版乱/空 | 用设计 skill 做 bespoke scene（决策12） |
| 10 | scene 4 块密集溢出 | 改 2×2 bento + 最多 4 卡 |
| **总计** | | **~10 轮** |

**结论**：第三个家族 ~10 轮。复用 white_quote checklist 后，grid/margin/条件 cover/`<br>` 断行类坑基本免了；新坑集中在 **`<br>` vs FakePage**（测试基建）和**家族招牌特征落地**（交替底色 + CSS 变量 scheme）。把这两类加入检查清单后，后续家族应进一步收敛。

### 动手前检查清单（pink_red 后新增）
- [ ] 用 `<br>` 断行的家族，确认 FakePage CopyParser 对 void 元素不增 depth（否则 test_renderer 全挂、真 probe 却过）。
- [ ] headline 可能紧贴 section 顶的版式：bespoke section 加 `overflow:visible`，用 `evaluate` 量 headline 顶部是否越过 section 盒。
- [ ] 家族有招牌视觉规律（交替/渐变等）：底色按 `frame_id` 页码决定，bespoke 配色全用 CSS 变量 + per-frame `<style>` 覆盖，保证任意 archetype 在任意底色自适应。
- [ ] heading/body 角色想要比 body_bold 更重的字体：用内层 span 套 display 字体，atom 保 body 过探针。
- [ ] 无 mockup 的 archetype：用设计 skill（Double-Bezel + bento）做 bespoke，2×N 卡片 1–N 递增、超出并入末卡保全契约。
- [ ] generic 兜底字号别太小：给 `block-*` 类覆盖放大，贴合家族气质，避免稀疏页空旷。

---

## Emoji 集成（soft_pink 专属）

- 在 storyboard generator prompt（`src/prompts/base/storyboards_generator.txt`）中指示 LLM 在 emphasis/body 里加 1–2 个 emoji。
- curated emoji 集（15 个非粉/红色系）：💧 ✨ 🌿 ☀️ 🧴 🪞 💡 📝 ⭐ 💚 🌱 🍋 💤 🌙 🌟
- headline 不加 emoji（保 == first_screen_promise）。
- 零代码改动——`_render_copy_value` 自动包裹 emoji，probe 已支持 emoji 渲染检查。
