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

## Emoji 集成（soft_pink 专属）

- 在 storyboard generator prompt（`src/prompts/base/storyboards_generator.txt`）中指示 LLM 在 emphasis/body 里加 1–2 个 emoji。
- curated emoji 集（15 个非粉/红色系）：💧 ✨ 🌿 ☀️ 🧴 🪞 💡 📝 ⭐ 💚 🌱 🍋 💤 🌙 🌟
- headline 不加 emoji（保 == first_screen_promise）。
- 零代码改动——`_render_copy_value` 自动包裹 emoji，probe 已支持 emoji 渲染检查。
