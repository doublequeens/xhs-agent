# Task 8 report: adaptive template variant resolution

## Outcome

- Added Unicode grapheme-aware copy measurement across every visible storyboard
  field.
- Emoji are measured as grapheme clusters and remain optional; no emoji policy was
  introduced.
- Added immutable definitions for all six template families and all fifteen page
  archetypes.
- Added family-specific colors, repository-local display/body fonts, composition
  variants, density thresholds, and minimum font sizes.
- Added deterministic density and composition resolution driven by measured copy,
  item cardinality, archetype, template family, and an optional explicit density
  hint.
- Added the pinned Noto Color Emoji v2.051 font and license from repository commit
  `8998f5dd683424a73e2314a8c1f1e359c19e8742`.

## Contract details

- `measure_frame_copy(frame)` counts graphemes, Han characters, Latin words, emoji,
  blocks, items, longest-item graphemes, and estimated lines.
- `resolve_variant(...)` uses sparse/standard/dense thresholds plus item limits.
  Explicit hints fail closed when measured copy does not fit.
- Collection/checklist, comparison, steps, and quote archetypes select structural
  variants from item cardinality and density; other archetypes use the registered
  family focus/stack/grid progression.
- Registry mappings are immutable and every font path is repository-local.

## Verification

- Initial RED: `109 failed` because all three modules were absent.
- Focused metrics/registry/variant plus schema suite:
  `116 passed in 0.06s`
- Pinned resource hashes:
  - font: `72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b`
  - license: `500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b`
- `python -m compileall -q src main.py`: passed
- `git diff --check`: passed

External subagent review remained unavailable because of the existing local Codex
usage limit. The controller reviewed the complete implementation and found no
remaining Critical or Important issue.
