# Xiaohongshu 模板样张库（参考模仿）

6 套模板，分别模仿 `references/templates/` 下用户提供的参考样张的**配色 + 版式 + 字体气质**，
用本护肤账号的真实文案。每套一个目录，含可重渲的 `template.html` 与渲染图。

> **重要说明：样张图片数量不等于生产套图页数。**
> 生产输出固定为 1080×1440 PNG，每套 `5–7` 页，由生产渲染器
> （`src/rendering/editorial/`）按 `CarouselPayload` 与 `VisualPlan` 动态决定。
> 这里展示的页面数只是**人工撰写的视觉参考**，用来对照各模板家族的配色、版式与字体气质，
> 既不进入生产 prompt，也不被生产 Python planner 引用。

## 套集

| 目录 | 家族 | 风格 | 配色（PIL 取自参考） | 字体 |
|---|---|---|---|---|
| `set1-pink-red/` | `pink_red` | 粉红粗体 motivational | 粉 `#F4A7BF` / 红 `#DC2333` | 阿里普惠体 Heavy |
| `set2-teal/` | `deep_teal` | 深青极简 | 深青 `#0E5A5A` / 浅青 `#7FD6D6` | HarmonyOS Sans |
| `set3-soft-pink/` | `soft_pink` | 浅粉治愈 | 浅粉 `#F8DADA` / 珊瑚 `#EE5C5C` | HarmonyOS Sans |
| `set4-coral-promo/` | `coral_impact` | 珊瑚宣传 | 珊瑚 `#F45A5A` / 浅粉 `#FFE3E3` | 普惠体 Heavy |
| `set5-green-favorites/` | `green_catalog` | 墨绿「本月好物」 | 墨绿 `#1E5A2E` / 米 `#F3E9D2` | HarmonyOS Sans |
| `set6-white-quote/` | `white_quote` | 留白手写语录 | 白 + 蓝 `#2A4A8C` | 霞鹜文楷 |

总览图：`gallery-all-6.png`（封面合集）；每套另有 `contact-sheet.png`（同套所有 archetype 拼图）。

## 页面 archetype

每个 `template.html` 用 `<div class="page" data-page="...">` 标记不同的 archetype，例如
`cover`、`steps-standard`、`comparison-dense`、`save` 等。**展示的 archetype 数量与生产页数无关**——
生产渲染器会根据 `CarouselPayload` 选择真实分页。

## 字体

- `assets/fonts/templates/`：阿里普惠体 Heavy、HarmonyOS Sans Regular/Medium/Bold/Black
- `assets/fonts/beauty-editorial-v1/`：霞鹜文楷 Medium/Regular、Bodoni Moda

`template.html` 用**相对路径**引用字体，仓库内可移植。

## 重新渲染

每页是 `template.html` 里一个 `<div class="page" data-page="...">`，画布固定 1080×1440。
运行根目录下的脚本即可重渲所有 PNG 与 contact sheet：

```bash
python examples/templates-mockup/render_mockups.py
```

脚本会用 Playwright 截图，等待 `document.fonts.ready`，按 `SETS` 字典里每个 selector 各取一张
1080×1440 截图，然后用 Pillow 合成各套的 `contact-sheet.png` 与封面合集 `gallery-all-6.png`。
脚本会拒绝未知 selector。

## 状态

样张阶段（人工视觉参考）。生产模板家族已落地在 `src/rendering/editorial/templates/`，
mockup 仅用于对照配色与版式气质，不再以「样张数量」决定生产套图页数。
