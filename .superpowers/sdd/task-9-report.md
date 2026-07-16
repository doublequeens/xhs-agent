# Task 9 Implementation Report

## Outcome

Implemented the shared production-card primitives and six approved visual
families:

- `pink_red`
- `deep_teal`
- `soft_pink`
- `coral_impact`
- `green_catalog`
- `white_quote`

Each family renders all 15 semantic page archetypes through
`render_frame(frame, assets, variant)`. Dispatch is keyed only by the selected
`template_family`; internal rendering is keyed by `page_archetype` and the
resolved density/composition variant.

The mockups define visual identity, not page cardinality. No family renderer
contains a fixed carousel page count. List and step blocks consume the actual
storyboard item collection and are covered for one through six items.

## TDD Evidence

### RED

The first focused run produced 108 expected failures because
`TEMPLATE_RENDERERS` and the six family implementations did not exist.

After replacing the dispatch, the next run exposed one integration seam:
package initialization eagerly imported the legacy renderer, which still
referenced removed `LAYOUT_RENDERERS`. The package export is now lazy until
Task 10 connects Chromium rendering to the v2 dispatch.

### GREEN

Focused family, dispatch, copy-metrics, registry, and variant suite:

```bash
pytest -q \
  tests/rendering/editorial/test_templates.py \
  tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_copy_metrics.py \
  tests/rendering/editorial/test_template_registry.py \
  tests/rendering/editorial/test_variant_resolver.py
```

Result: `218 passed`.

Static verification:

```bash
python -m compileall -q src/rendering/editorial \
  tests/rendering/editorial/test_templates.py \
  tests/rendering/editorial/test_layouts.py \
  tests/rendering/editorial/test_copy_metrics.py
git diff --check
```

Both commands passed.

## Contract Coverage

- Every visible storyboard string is HTML-escaped and emitted exactly once
  with `data-card-copy` and a stable `data-copy-role`, including emphasis
  strings.
- Empty asset lists render no placeholder.
- Non-empty assets must be resolved, existing, absolute local files.
- Every family supports all semantic archetypes and all registered density
  variants.
- Family roots preserve the approved mockup palettes and motifs.
- `pink_red` uses the red full-panel variant for standard narrative beats.
- Emoji remain permitted; copy measurement counts them as grapheme clusters
  without requiring them.
- Dispatch is immutable and contains exactly the six approved families.

## Deferred Integration

`renderer.py`, browser font loading, probes, screenshots, and Render QA are
intentionally handled in Task 10. Legacy Chromium/probe tests are therefore
not part of this task's green gate.
