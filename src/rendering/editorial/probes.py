from __future__ import annotations

from typing import Any

import regex

from src.schemas.editorial_templates import TemplateFamily


GRAPHEME_RE = regex.compile(r"\X")
EMOJI_RE = regex.compile(r"\p{Extended_Pictographic}")


def template_font_families(
    family: TemplateFamily,
) -> tuple[str, str, str]:
    prefix = f"template-{family.replace('_', '-')}"
    return (
        f"{prefix}-display",
        f"{prefix}-body",
        "Noto Color Emoji",
    )


def expected_font_families(
    family: TemplateFamily,
) -> frozenset[str]:
    return frozenset(template_font_families(family))


def extract_emoji_graphemes(text: str) -> list[str]:
    return [
        grapheme
        for grapheme in GRAPHEME_RE.findall(text)
        if EMOJI_RE.search(grapheme)
    ]


FONT_PROBE_SCRIPT = r"""
async () => {
  /* EDITORIAL_FONT_PROBE */
  const root = document.querySelector(".card, .contact-sheet");
  if (!root) {
    return {all_loaded: false, computed_families: []};
  }
  const expected = [
    [root.dataset.displayFontFamily || "", "字", ".font-probe-display"],
    [root.dataset.bodyFontFamily || "", "字", ".font-probe-body"],
    [root.dataset.emojiFontFamily || "", "✨", ".font-probe-emoji"]
  ];
  await Promise.all(expected.map(([family, sample]) =>
    document.fonts.load(`32px "${family}"`, sample)
  ));
  await document.fonts.ready;
  const firstFamily = element => {
    if (!element) return "";
    return getComputedStyle(element).fontFamily
      .split(",")[0].trim().replace(/^['"]|['"]$/g, "");
  };
  const computedFamilies = expected.map(([_family, _sample, selector]) =>
    firstFamily(document.querySelector(selector))
  );
  const allLoaded = expected.every(([family, sample], index) =>
    Boolean(family) &&
    document.fonts.check(`32px "${family}"`, sample) &&
    computedFamilies[index] === family
  );
  return {
    all_loaded: allLoaded,
    computed_families: [...new Set(computedFamilies.filter(Boolean))]
  };
}
"""


LAYOUT_PROBE_SCRIPT = r"""
() => {
  /* EDITORIAL_LAYOUT_PROBE */
  const issues = [];
  const texts = [];
  const assets = [];
  const card = document.querySelector(".card");
  if (!card) {
    return {
      canvas: {width: 0, height: 0},
      safe_margin: 0,
      texts,
      assets,
      issues: [{kind: "missing_card"}]
    };
  }
  const rect = card.getBoundingClientRect();
  if (Math.round(rect.width) !== 1080 || Math.round(rect.height) !== 1440) {
    issues.push({
      kind: "canvas_geometry",
      width: rect.width,
      height: rect.height
    });
  }
  if (
    !card.dataset.templateFamily ||
    !card.dataset.pageArchetype ||
    !card.dataset.frameRole
  ) {
    issues.push({kind: "missing_semantics"});
  }
  const firstFamily = style => style.fontFamily
    .split(",")[0].trim().replace(/^['"]|['"]$/g, "");
  const emojiHasInk = grapheme => {
    const canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = 96;
    const context = canvas.getContext("2d", {willReadFrequently: true});
    context.clearRect(0, 0, 96, 96);
    context.font = '48px "Noto Color Emoji"';
    context.textBaseline = "top";
    context.fillText(grapheme, 8, 8);
    const pixels = context.getImageData(0, 0, 96, 96).data;
    for (let index = 3; index < pixels.length; index += 4) {
      if (pixels[index] > 0) return true;
    }
    return false;
  };

  document.querySelectorAll("[data-card-copy]").forEach(element => {
    const role = element.dataset.copyRole || "unknown";
    const text = element.textContent || "";
    const copyRect = element.getBoundingClientRect();
    const visible = copyRect.width > 0 && copyRect.height > 0;
    if (!visible) issues.push({kind: "hidden_copy", role});
    const style = getComputedStyle(element);
    const fontSize = parseFloat(style.fontSize);
    const lineHeight = parseFloat(style.lineHeight);
    const overflowTolerance = Math.max(2, fontSize * 0.15);
    const overflow = (
      element.scrollWidth > element.clientWidth + overflowTolerance ||
      element.scrollHeight > element.clientHeight + overflowTolerance
    );
    if (overflow) issues.push({kind: "overflow", role});
    const range = document.createRange();
    range.selectNodeContents(element);
    const inkRects = [...range.getClientRects()].filter(
      rect => rect.width > 0 && rect.height > 0
    );
    if (!inkRects.length) issues.push({kind: "empty_glyph_box", role});
    if (text.includes("\uFFFD")) {
      issues.push({kind: "replacement_glyph", role});
    }
    if (style.textOverflow === "ellipsis") {
      issues.push({kind: "ellipsis", role});
    }
    if (element.matches(".block-body, .item-copy")) {
      const ratio = lineHeight / fontSize;
      if (
        !Number.isFinite(ratio) ||
        ratio < 1.35 - 0.005 ||
        ratio > 1.55 + 0.005
      ) {
        issues.push({kind: "body_line_height", role, ratio});
      }
    }
    const lineTops = new Set(
      inkRects.map(rect => Math.round(rect.top * 2) / 2)
    );
    if (element.matches(".template-headline")) {
      const density = card.dataset.density || "standard";
      const maximum = density === "sparse" ? 2 : density === "dense" ? 4 : 3;
      if (lineTops.size > maximum) {
        issues.push({
          kind: "headline_lines",
          role,
          lines: lineTops.size,
          maximum
        });
      }
    }
    let ancestor = element;
    let inkClipped = false;
    while (ancestor && ancestor !== card.parentElement && !inkClipped) {
      const ancestorStyle = getComputedStyle(ancestor);
      const clipsX = ["hidden", "clip", "auto", "scroll"].includes(
        ancestorStyle.overflowX
      );
      const clipsY = ["hidden", "clip", "auto", "scroll"].includes(
        ancestorStyle.overflowY
      );
      if (clipsX || clipsY) {
        const ancestorRect = ancestor.getBoundingClientRect();
        const clipLeft = ancestorRect.left + ancestor.clientLeft;
        const clipTop = ancestorRect.top + ancestor.clientTop;
        const clipRight = clipLeft + ancestor.clientWidth;
        const clipBottom = clipTop + ancestor.clientHeight;
        inkClipped = inkRects.some(rect =>
          (
            clipsX &&
            (rect.left < clipLeft - 0.75 || rect.right > clipRight + 0.75)
          ) || (
            clipsY &&
            (rect.top < clipTop - 0.75 || rect.bottom > clipBottom + 0.75)
          )
        );
      }
      ancestor = ancestor.parentElement;
    }
    if (inkClipped) issues.push({kind: "ink_clip", role});
    const body = element.closest(".template-body");
    let layoutClipped = false;
    if (body) {
      const bodyRect = body.getBoundingClientRect();
      layoutClipped = (
        copyRect.left < bodyRect.left - 1 ||
        copyRect.right > bodyRect.right + 1 ||
        copyRect.top < bodyRect.top - 1 ||
        copyRect.bottom > bodyRect.bottom + 1
      );
      if (layoutClipped) issues.push({kind: "layout_clip", role});
    }
    const emojiGraphemes = [
      ...element.querySelectorAll("[data-emoji-grapheme]")
    ].map(span => span.dataset.emojiGrapheme || span.textContent || "");
    emojiGraphemes.forEach(grapheme => {
      const span = [...element.querySelectorAll("[data-emoji-grapheme]")]
        .find(item => (
          item.dataset.emojiGrapheme || item.textContent || ""
        ) === grapheme);
      const emojiRect = span ? span.getBoundingClientRect() : null;
      const loaded = document.fonts.check(
        '32px "Noto Color Emoji"',
        grapheme
      );
      if (
        !loaded ||
        !emojiRect ||
        emojiRect.width <= 0 ||
        emojiRect.height <= 0 ||
        !emojiHasInk(grapheme)
      ) {
        issues.push({kind: "missing_glyph", role, grapheme});
      }
    });
    texts.push({
      role,
      text,
      emoji_graphemes: emojiGraphemes,
      visible,
      overflow,
      ink_clipped: inkClipped,
      layout_clipped: layoutClipped,
      font_family: firstFamily(style),
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
    const aspectRatioError = (
      Number.isFinite(naturalRatio) &&
      naturalRatio > 0 &&
      Number.isFinite(renderedRatio)
    ) ? Math.abs(renderedRatio - naturalRatio) / naturalRatio : 1;
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
    canvas: {
      width: Math.round(rect.width),
      height: Math.round(rect.height)
    },
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
