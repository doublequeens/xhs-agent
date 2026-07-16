# Xiaohongshu 模板样张库（参考模仿）

6 套模板，分别模仿 `references/templates/` 下用户提供的参考样张的**配色 + 版式 + 字体气质**，
用本护肤账号的真实文案。每套一个目录，含可重渲的 `template.html` 与渲染图。

## 套集

| 目录 | 风格 | 配色（PIL 取自参考） | 字体 |
|---|---|---|---|
| `set1-pink-red/` | 粉红粗体 motivational | 粉 `#F4A7BF` / 红 `#DC2333` | 阿里普惠体 Heavy |
| `set2-teal/` | 深青极简 | 深青 `#0E5A5A` / 白 | HarmonyOS Sans |
| `set3-soft-pink/` | 浅粉治愈 | 浅粉 `#F8DADA` / 珊瑚 `#EE5C5C` | HarmonyOS Sans |
| `set4-coral-promo/` | 珊瑚宣传封面（单图） | 珊瑚 `#F45A5A` / 白 | 普惠体 Heavy |
| `set5-green-favorites/` | 墨绿"本月好物"（单图） | 墨绿 `#1E5A2E` + 粉/红文件夹 | HarmonyOS Sans |
| `set6-white-quote/` | 留白手写语录（单图） | 白 + 蓝 `#2A4A8C` | 霞鹜文楷 |

总览图：`gallery-all-6.png`。

## 字体

- `assets/fonts/templates/`：阿里普惠体 Heavy、HarmonyOS Sans Regular/Medium/Bold/Black
- `assets/fonts/beauty-editorial-v1/`：霞鹜文楷 Medium/Regular、Bodoni Moda

`template.html` 用**相对路径**引用字体，仓库内可移植。

## 重新渲染

每页是 `template.html` 里一个 `<div class="page ...">`，1080×1350。用 Playwright 截图即可重渲，例如：

```python
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True); pg = b.new_page(viewport={"width":1080,"height":1350})
    pg.goto((Path("set2-teal/template.html").resolve()).as_uri(), wait_until="networkidle")
    pg.evaluate("document.fonts.ready")
    pg.locator("div.page.c").screenshot(path="set2-teal/01-cover.png")
    b.close()
```

## 状态

样张阶段。选定要落地的套集后，再实现进生产渲染器（`src/rendering/editorial/`）作为可选模板变体。
