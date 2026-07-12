# 本地文字卡渲染工作流设计

## 目标

在不调用任何图像生成 API、也不依赖实拍或外部图片素材的前提下，让 Agent 为每篇小红书美容内容生成 6 张可直接发布的中文文字卡 PNG。成图应保持同一账号的设计系统，同时按内容结构使用不同版式，而不是让图像模型猜测中文排版。

## 非目标

- 不接入 gpt-image-2、其他图像生成 API 或网络图片服务。
- 不生成插画、人物、产品图、背景素材或实拍图。
- 不在第一版中提供可视化编辑器、拖拽编辑或用户自定义模板。
- 不更改内容选题、文案生成、合规策略或发布流程的业务规则。

## 决策

使用本地 HTML/CSS 模板渲染文字卡，并由本地浏览器截图输出 PNG。HTML/CSS 是唯一的排版真源；LLM 只能生成受限的内容块和模板选择，不能生成最终图片、字体说明或自由布局指令。

该选择优于 SVG/Pillow 的原因是：中文自动换行、表格、层级、间距和主题样式可以集中在 CSS 维护，模板迭代不需要在绘图坐标代码中修改。

## 数据流

```text
publish_package + content_contract
  -> storyboard generator produces structured card specifications
  -> local text-card renderer validates and renders HTML/CSS
  -> local browser captures PNG cards
  -> render QA validates image files and card constraints
  -> publish package exports images/01-*.png through images/06-*.png
```

现有 `storyboards` 是 Agent 与渲染器之间的合同。其字段从图像生成提示词转为结构化展示信息；`image_prompt_cn`、`image_prompt_en`、`visual_description`、`scene_background`、`composition` 和 `text_area` 不再是渲染合同的一部分。

## 卡片规格

每个卡片必须包含：

- `frame_id`：同一篇内唯一，按生成顺序排列。
- `template`：下表定义的枚举之一。
- `theme`：`warm_neutral` 或 `cool_sage`，一篇内容内必须相同。
- `kicker`：可选的短标签，最多 10 个汉字。
- `headline`：主标题，最多 28 个汉字；渲染时最多两行、每行最多 14 个汉字。
- `footer`：可选底部规则或提示，最多 18 个汉字。
- 模板特有字段：只能使用当前模板要求的列表、对照项或问题。

禁止将正文段落、免责声明或互动引导与主标题拼接。正文中的免责声明仍在正文中保留；若卡片需要显示，只能作为不超过 18 个汉字的页脚。

## 模板库

第一版只支持以下 6 个模板，每篇内容固定使用 6 张卡，顺序固定：

| 顺序 | 模板 | 作用 | 必需内容 |
| --- | --- | --- | --- |
| 1 | `cover_statement` | 首屏承诺 | `headline` 必须等于 `content_contract.first_screen_promise`；可选 `kicker` |
| 2 | `wrong_vs_right` | 纠正一个常见误区 | `wrong_items` 2–3 项，`right_items` 2–4 项 |
| 3 | `step_timeline` | 展示行动顺序 | `steps` 3–5 项；每项有名称和短提示 |
| 4 | `saveable_checklist` | 可截图保存的清单 | `checklist_items` 3–5 项；至少一项对应 `content_contract.screenshot_asset` |
| 5 | `decision_rule` | 给出适用边界或判断标准 | `conditions` 2–3 项，每项有“情况”和“建议” |
| 6 | `question_closer` | 互动收尾 | `question` 1 个，最多 22 个汉字 |

`content_intent` 只影响每个模板中填入的内容，不改变卡片顺序：`checklist` 强调步骤与保存页，`myth_busting` 强调错误/正确页，`how_to` 强调时间轴，`basic_science` 只用简化因果关系而不生成医学断言。

## 设计系统

所有卡片输出为 `1080 × 1440` PNG，使用同一份 CSS 设计 token：

- 画布四周安全边距：84 px；正文区域不得越界。
- 字体：系统可用的中文无衬线字体栈；标题使用 semibold，正文使用 regular。
- 标题：76 px，行高 1.18；正文：36 px，行高 1.45；页脚：28 px，行高 1.35。
- 每张卡最多三个信息层级：kicker、headline、列表/页脚。
- 禁止表情符号、贴纸、卡通插画、产品瓶身、品牌 logo、水印、渐变字和装饰性边框。

主题只能从以下两套中选择：

| Theme | 背景 | 正文 | 强调色 |
| --- | --- | --- | --- |
| `warm_neutral` | `#F7F2EB` | `#292622` | `#B85C56` |
| `cool_sage` | `#EEF2ED` | `#243128` | `#607A69` |

同一篇内容必须使用同一主题；错误项固定使用低饱和红色，正确项固定使用低饱和绿色。这种一致性是账号识别，而模板不同保证内容不重复。

## 节点与产物边界

### Storyboard Generator

保留为 LLM 节点，但输出受结构化 schema 约束的卡片规格。它不得再输出图像模型提示词、自由构图描述或长段 `narration`。它必须根据 `content_contract` 生成 6 个模板对应的内容块。

### Local Text Card Renderer

新增确定性节点，职责仅为：验证卡片规格、把模板和主题映射到 HTML/CSS、调用本地浏览器截图、把 6 张 PNG 写入当前发布目录。它不调用 LLM，不访问网络，也不改写内容。

### Render QA

新增确定性检查，职责仅为：确认有 6 张 PNG、全部为 1080 × 1440、文件按 `01` 至 `06` 排序、每张对应一个有效模板、封面标题满足首屏承诺、保存页存在。字体渲染和文字溢出由渲染前 HTML 布局检查阻止：任何目标元素的 `scrollHeight` 大于 `clientHeight` 均为失败。

### 发布导出

发布包保留 `storyboards` 用于审计，并新增按顺序的本地图片路径。旧的 `Storyboard_images_generator_prompt.txt` 不再导出；发布目录直接包含 `images/01-cover.png` 至 `images/06-question.png`。

## 错误处理

- 模板未知、字段缺失、字数超限或同一篇存在多个主题时：在本地渲染前失败，并输出具体 frame 和字段。
- HTML 元素发生文字溢出时：渲染失败，返回对应 frame；不得缩小字体绕过限制。
- 浏览器不可用或截图失败时：渲染失败；不得生成空白或部分图片。
- 任一 PNG 尺寸、数量或顺序不符合要求时：Render QA 失败，阻止发布。

## 测试与验收

- Schema 测试：每种模板可接受的最小结构、字段缺失、字数超限与错误模板专属字段。
- 渲染测试：每种模板输出 1080 × 1440 PNG，主题色与预期 CSS token 一致。
- 溢出测试：过长标题、过长列表项和过长收尾问题都被拒绝。
- 集成测试：给出一个美容 `content_contract`，完整工作流产出 6 张有序 PNG，并包含首屏承诺与可截图保存页。
- 回归测试：现有 carousel 合同仍会拦截缺失首屏、缺失截图清单或错误卡片数量的输出。

验收标准是：无图像 API、无网络素材情况下，每次运行均能生成 6 张固定尺寸、中文文本可控、可上传小红书的文字卡；同一篇保持统一主题，不同内容通过模板和内容块形成不同版式。
