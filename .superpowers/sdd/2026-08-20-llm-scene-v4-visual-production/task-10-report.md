# Task 10 report: v4 composition grammars

Status: implemented and verified.

## Scope

Implemented the frozen structural-intent contracts, six-family token projection,
the first three family-neutral Composition Grammars, and deterministic page
composition planning. No v3 schema/node/renderer, graph wiring, publish
contract, state, asset, output, or database files were changed.

## RED/GREEN proof

Initial command (before implementation):

```text
pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
```

It failed during collection with three expected missing-module errors:
`ModuleNotFoundError: No module named 'src.schemas.v4.layout'` and the
corresponding missing `src.nodes.v4.composition` module.

After implementation, the focused suite passed: `15 passed`.

## Changed files

- `src/schemas/v4/layout.py`: frozen extra-forbid grammar, token, placement,
  and `LayoutProgramV4` contracts with canonical hash/integrity checks.
- `src/visual_design/v4/tokens.py`: immutable six-family token registry derived
  from `load_style_registry()`.
- `src/visual_design/v4/grammars.py`: immutable `editorial_hero`,
  `comparison_grid`, and `step_flow` definitions with reference validation.
- `src/nodes/v4/composition.py`: strict PageBrief/hash/grammar checks and
  deterministic fragment/asset placement construction without provider or
  renderer calls.
- `tests/schemas/v4/test_layout.py`
- `tests/visual_design/v4/test_grammars.py`
- `tests/nodes/v4/test_composition.py`

## Verification

- Focused Task 10 plus style registry: `17 passed`.
- Adjacent v4 direction/authoring/QA regressions: `30 passed`.
- Full offline suite: `1600 passed, 3 skipped` (live provider/Gemini tests
  skipped by their existing environment gates).
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The full suite emitted four existing warnings: two Pydantic serializer
warnings in tampered semantic-model tests and two pytest temporary-directory
cleanup warnings. No warning originated from the Task 10 modules.

## Self-review and remaining concerns

- Layout programs contain only IDs, named regions, relationships, abstract
  density/alignment/response rules, and hashes; nested models reject geometry,
  markup, paths, provider metadata, and unknown fields.
- Fragment and asset references are page-local and unique; stale PageBrief or
  LayoutProgram hashes fail closed, and an allowed-but-unimplemented grammar
  has no fallback.
- The compiler/typography measurement layer remains intentionally unimplemented
  for Task 11; this task only supplies its structural input boundary.

## Fix round 1

Independent review identified three fail-open boundaries: caller-supplied
family-token payloads and density envelopes, free-form page/narrative role
compatibility, and visual-priority emphasis binding.  It also required
recursive nested-payload scans and durable beat checks.

### RED/GREEN proof

The review regression suite was run before the fix:

```text
pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
20 failed, 8 passed
```

The failures covered the missing canonical family-token hash, missing required
family/beat API, stale role matrices, absent family density enforcement, and
ignored visual-priority order.  Additional RED checks caught stale beat
sequences and recomputed-hash path payloads before their respective guards were
added.

After the fix, the focused suite passed: `32 passed`.  The implementation now
resolves only a required family ID through the read-only canonical registry,
binds and revalidates `family_tokens_sha256`, applies `.25/.50/.75` density
targets against both grammar and family envelopes, derives controlled page
roles from typed narrative duties, and emits reverse-bound emphasis rules in
durable `visual_priority` order.  Grammar, token, and program tests recursively
scan nested serialized keys and values for render/provider/path/copy payloads.

### Fix round 1 verification

- Focused Task 10 plus style registry: `35 passed, 2 warnings`.
- Adjacent v4 direction/authoring/QA regressions: `30 passed`.
- Full offline suite: `1617 passed, 3 skipped, 4 warnings`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The four full-suite warnings remain the existing two Pydantic serializer
warnings and two pytest temporary-directory cleanup warnings; none originates
from the Task 10 modules.  Task 11 compiler integration remains outside this
task's ownership.

## Fix round 2

The second independent review closed the remaining free-string and narrative
authority gaps.  Family style descriptions now share one allowlist validator
for font roles, motifs, and composition principles; the canonical manifest's
six families remain loadable while CSS, DOM, provider/provenance, event,
URL, and path payloads fail before hash acceptance.  Composition now accepts
only a hash-bound `CarouselNarrativeV4` (or persisted mapping), resolves the
page's unique beat internally, and binds the narrative hash, beat reference,
and typed task kind into `LayoutProgramV4`.  Emphasis priorities are also
required to be unique and continuous from zero.

### RED/GREEN proof

The review regression suite was run before the production changes:

```text
pytest -q tests/schemas/v4/test_layout.py tests/visual_design/v4/test_grammars.py tests/nodes/v4/test_composition.py
26 failed, 19 passed
```

The failures covered the old standalone-beat API, missing narrative binding
fields, free-string payload acceptance, and duplicate emphasis priorities.
The persisted-narrative fixture was then normalized to the direction contract;
the production changes were applied only after the expected RED behavior was
observed.

After the fix, the focused suite passed: `45 passed`.  A recomputed narrative
hash is treated as a new durable candidate and is persisted in the resulting
program; an unchanged hash with `model_copy` tampering fails integrity before
beat selection.

### Fix round 2 verification

- Focused Task 10 plus style registry: `48 passed, 2 warnings`.
- Adjacent v4 direction/authoring/QA regressions: `30 passed`.
- Full offline suite: `1630 passed, 3 skipped, 4 warnings`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The four full-suite warnings remain the two existing Pydantic serializer
warnings and two pytest temporary-directory cleanup warnings.  Task 11
compiler integration remains outside this task's ownership.

## Fix round 3

The final narrow review found that a character-only allowlist still admitted
semantic provider/provenance payloads such as `provider pexels provenance ai`
and `javascript alert`.  The shared style-token validator now normalizes word
tokens and rejects generic provider/provenance terms, known provider names,
AI/script/DOM terms, normalized local-path terms, and common `on*` event
handler tokens.  Word-boundary matching preserves canonical names such as
`Alibaba PuHuiTi`; all six current style-registry families remain valid.

### RED/GREEN proof

The new no-punctuation, correctly rehashed token regressions failed before the
semantic-token guard:

```text
pytest -q tests/visual_design/v4/test_grammars.py -k semantic_style_tokens
4 failed, 19 deselected
```

After adding the normalized forbidden-token set, those regressions passed:
`12 passed, 11 deselected` for the focused style-token selection and `49
passed` for the complete Task 10 focus.

### Fix round 3 verification

- Focused Task 10 plus style registry: `52 passed, 2 warnings`.
- Adjacent v4 direction/authoring/QA regressions: `30 passed`.
- Full offline suite: `1634 passed, 3 skipped, 4 warnings`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The four full-suite warnings remain the existing two Pydantic serializer
warnings and two pytest temporary-directory cleanup warnings.  Task 11
compiler integration remains outside this task's ownership.
