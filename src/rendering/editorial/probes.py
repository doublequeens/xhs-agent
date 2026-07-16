from __future__ import annotations

from typing import Any


EXPECTED_FONT_FAMILIES = frozenset(
    {"Source Han Serif SC", "Source Han Sans SC", "Bodoni Moda"}
)


FONT_PROBE_SCRIPT = r"""
async () => {
  /* EDITORIAL_FONT_PROBE */
  const expected = [
    ["Source Han Serif SC", "字"],
    ["Source Han Sans SC", "字"],
    ["Bodoni Moda", "01"]
  ];
  await Promise.all(expected.map(([family, sample]) =>
    document.fonts.load(`16px "${family}"`, sample)
  ));
  await document.fonts.ready;
  const selectors = [
    ".font-probe-display",
    ".font-probe-body",
    ".font-probe-numeral"
  ];
  const computedFamilies = selectors.map(selector => {
    const element = document.querySelector(selector);
    if (!element) return "";
    return getComputedStyle(element).fontFamily.split(",")[0].trim().replace(/^['"]|['"]$/g, "");
  });
  const allLoaded = expected.every(([family, sample]) =>
    document.fonts.check(`16px "${family}"`, sample)
  ) && computedFamilies.every((family, index) => family === expected[index][0]);
  return {all_loaded: allLoaded, computed_families: [...new Set(computedFamilies.filter(Boolean))]};
}
"""


LAYOUT_PROBE_SCRIPT = r"""
() => {
  /* EDITORIAL_LAYOUT_PROBE */
  const issues = [];
  const texts = [];
  const assets = [];
  const card = document.querySelector(".card");
  if (!card) return {canvas: {width: 0, height: 0}, safe_margin: 0, texts, assets, issues: [{kind: "missing_card"}]};
  const rect = card.getBoundingClientRect();
  if (Math.round(rect.width) !== 1080 || Math.round(rect.height) !== 1440) {
    issues.push({kind: "canvas_geometry", width: rect.width, height: rect.height});
  }
  if (!card.dataset.layout || !card.dataset.frameRole) {
    issues.push({kind: "missing_semantics"});
  }
  document.querySelectorAll("[data-card-copy]").forEach(element => {
    const role = element.dataset.copyRole || "unknown";
    const copyRect = element.getBoundingClientRect();
    const visible = copyRect.width > 0 && copyRect.height > 0;
    if (!visible) {
      issues.push({kind: "hidden_copy", role});
    }
    const overflow = element.scrollWidth > element.clientWidth + 2;
    if (overflow) {
      issues.push({kind: "overflow", role});
    }
    const range = document.createRange();
    range.selectNodeContents(element);
    const inkRects = [...range.getClientRects()].filter(rect => rect.width > 0 && rect.height > 0);
    const style = getComputedStyle(element);
    const fontSize = parseFloat(style.fontSize);
    const lineHeight = parseFloat(style.lineHeight);
    if (element.matches(".block-body, .item-copy")) {
      const ratio = lineHeight / fontSize;
      if (!Number.isFinite(ratio) || ratio < 1.4 - 0.005 || ratio > 1.5 + 0.005) {
        issues.push({kind: "body_line_height", role, ratio});
      }
    }
    const lineTops = new Set(inkRects.map(rect => Math.round(rect.top * 2) / 2));
    if (element.matches(".headline")) {
      if (lineTops.size > 2) {
        issues.push({kind: "headline_lines", role, lines: lineTops.size});
      }
    }
    let ancestor = element;
    let inkClipped = false;
    while (ancestor && ancestor !== card.parentElement && !inkClipped) {
      const style = getComputedStyle(ancestor);
      const clipsX = ["hidden", "clip", "auto", "scroll"].includes(style.overflowX);
      const clipsY = ["hidden", "clip", "auto", "scroll"].includes(style.overflowY);
      if (clipsX || clipsY) {
        const ancestorRect = ancestor.getBoundingClientRect();
        const clipLeft = ancestorRect.left + ancestor.clientLeft;
        const clipTop = ancestorRect.top + ancestor.clientTop;
        const clipRight = clipLeft + ancestor.clientWidth;
        const clipBottom = clipTop + ancestor.clientHeight;
        inkClipped = inkRects.some(rect =>
          (clipsX && (rect.left < clipLeft - 0.75 || rect.right > clipRight + 0.75)) ||
          (clipsY && (rect.top < clipTop - 0.75 || rect.bottom > clipBottom + 0.75))
        );
      }
      ancestor = ancestor.parentElement;
    }
    if (inkClipped) {
      issues.push({kind: "ink_clip", role});
    }
    const body = element.closest(".layout-body");
    let layoutClipped = false;
    if (body) {
      const bodyRect = body.getBoundingClientRect();
      layoutClipped = copyRect.left < bodyRect.left - 1 || copyRect.right > bodyRect.right + 1 ||
          copyRect.top < bodyRect.top - 1 || copyRect.bottom > bodyRect.bottom + 1;
      if (layoutClipped) {
        issues.push({kind: "layout_clip", role});
      }
    }
    texts.push({
      role,
      text: element.textContent || "",
      visible,
      overflow,
      ink_clipped: inkClipped,
      layout_clipped: layoutClipped,
      font_family: style.fontFamily.split(",")[0].trim().replace(/^['"]|['"]$/g, ""),
      font_size: fontSize,
      line_height: lineHeight,
      line_count: Math.max(1, lineTops.size),
      x: Math.max(0, copyRect.x),
      y: Math.max(0, copyRect.y),
      width: copyRect.width,
      height: copyRect.height
    });
  });
  document.querySelectorAll("img[data-asset-slot]").forEach(element => {
    if (!element.complete || element.naturalWidth < 1 || element.naturalHeight < 1) {
      issues.push({kind: "asset_load", slot_id: element.dataset.assetSlot});
    }
    const imageRect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const naturalRatio = element.naturalWidth / element.naturalHeight;
    const renderedRatio = imageRect.width / imageRect.height;
    const aspectRatioError = Number.isFinite(naturalRatio) && naturalRatio > 0 && Number.isFinite(renderedRatio)
      ? Math.abs(renderedRatio - naturalRatio) / naturalRatio
      : 1;
    assets.push({
      slot_id: element.dataset.assetSlot || "unknown",
      natural_width: element.naturalWidth,
      natural_height: element.naturalHeight,
      rendered_width: imageRect.width,
      rendered_height: imageRect.height,
      object_fit: style.objectFit,
      cropped: style.objectFit === "cover",
      aspect_ratio_error: aspectRatioError
    });
  });
  return {
    canvas: {width: Math.round(rect.width), height: Math.round(rect.height)},
    safe_margin: parseFloat(getComputedStyle(card).paddingLeft),
    texts,
    assets,
    issues
  };
}
"""


def probe_fonts(page) -> dict[str, Any]:
    report = page.evaluate(FONT_PROBE_SCRIPT)
    if not isinstance(report, dict):
        raise RuntimeError("font probe returned an invalid report")
    return report


def probe_layout(page) -> dict[str, Any]:
    report = page.evaluate(LAYOUT_PROBE_SCRIPT)
    if not isinstance(report, dict):
        raise RuntimeError("layout probe returned an invalid report")
    return report
