# Task 6 report: project and lock v4 visible copy

## Status

DONE_WITH_CONCERNS

## Change summary

- Added frozen, `extra="forbid"` v4 visible-copy contracts:
  `VisibleCopyUnitV4`, `MarkdownTableGroupV4`, `VisibleCopyProjectionV4`,
  `ContentAtomV4`, and `ContentAtomSetV4`.
- Made unit and atom SHA-256 values bind their complete semantic/provenance
  payloads, including source field, raw span, raw-slice hash, role, sequence,
  projection binding, and visible text. Canonical JSON remains deterministic
  UTF-8 JSON with sorted keys and no insignificant whitespace.
- Added deterministic Markdown projection for title, cover copy, and body
  content. It strips structural Markdown, preserves punctuation/emoji/internal
  spaces, treats only valid header-plus-separator pipe blocks as tables, keeps
  rectangular header/cell relations and source spans, and handles escaped pipes.
- Added v4 atomization and ContentLock builder nodes. The builder rehydrates
  serialized contracts, verifies source/canonical hashes and deterministic
  re-projection, then delegates lock payload construction to
  `src.publishing.artifacts.build_content_lock`.
- Added fail-closed visible-copy invalidation for the lock, atoms, projection,
  and all listed downstream v4 artifacts while retaining `publish_package`.
- Added the minimal v4 node test package initializer to avoid the two
  `test_content.py` pytest module-name collision.

## Requirement mapping

| Requirement | Evidence |
| --- | --- |
| Frozen, strict, nested immutable contracts | `_FrozenV4Model` uses `frozen=True` and `extra="forbid"`; nested sequences are tuples; tests cover frozen assignment and extra fields. |
| Complete unit/atom provenance hashes | Unit and atom validators hash every field except their digest; tests prove a valid-shape digest from the original payload rejects raw-span drift. |
| Unicode codepoint half-open source spans | Projection scans Python string offsets and stores `[raw_start, raw_end)` plus raw-slice SHA-256 for title, cover, and content. |
| Deterministic Markdown-only projection | Block/inline structural stripping is deterministic; semantic copy is not rewritten or paginated. |
| Markdown tables and escaped/ordinary pipes | Header-plus-separator detection creates rectangular groups and header/cell units; separator rows are excluded, escaped pipes remain cell text, and standalone/ordinary pipe rows remain ordinary copy. |
| Projection and atom canonical bindings | Projection stores the three source hashes and canonical hash; atoms bind source unit/span/projection; atom sets bind projection and canonical atom payload. |
| Atomizer boundary | `content_atomizer_node` reads only `publish_package.title`, `cover_copy`, and `content`; metadata is ignored; route/issues/current-node outputs are fixed by contract. |
| Immediate lock builder / no payload duplication | `content_lock_builder_node` consumes persisted contracts, revalidates them against current package copy, and calls `build_content_lock`; it does not reproduce lock payload rules. |
| Metadata/copy drift behavior | Hashtag metadata changes preserve the atom set but alter the lock; title/cover/content source drift fails before lock construction. |
| Visible-copy invalidation | `invalidate_visible_copy_artifacts` returns `None` patches for the lock, atoms, projection, and all requested downstream slots; `publish_package` is absent so it is retained by state merge. |
| v3 boundary | No v3 source, graph, publishing helper, or AgentState file was modified; only the mandated v4 files and test package initializer were changed. |

## TDD and verification

The required initial command first reproduced the collection error:

```text
pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py
ERROR: import file mismatch: imported module 'test_content' ...
```

After adding the minimal node-v4 test package initializer, the newly added
full-provenance and standalone-separator regressions produced the expected red
run before the implementation fixes:

```text
pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py
6 failed, 11 passed
```

Fresh green and regression verification:

```text
pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py
19 passed

pytest -q tests/schemas/v4/test_content.py tests/nodes/v4/test_content.py \
  tests/nodes/test_content_atomizer.py tests/schemas/test_content_atoms.py
50 passed

pytest -q
1477 passed, 2 skipped, 2 warnings in 56.19s

python -m compileall -q src main.py
git diff --check
```

The two skipped tests are the documented opt-in live Gemini tests. The two
warnings are the existing macOS pytest temporary-directory cleanup warnings
from `tests/metrics_collector/test_launchd.py`; no live provider or model call
was enabled.

An additional inline invariant smoke check verified deterministic repeated
projection, every raw-slice hash, complete unit/atom digest payloads, and
metadata lock drift behavior.

## Self-review

- Reviewed all staged Task 6 source and test files after the focused and full
  suites; `git diff --cached --check` and `git diff --check` were clean.
- Confirmed no v3, graph, publishing, database, output, or credential files
  were changed. The only publishing interaction is the required call to the
  existing `build_content_lock` helper.
- Confirmed no compatibility aliases are exported from `src.nodes.v4`; its
  `__all__` contains only the canonical projection/atomizer/lock/invalidation
  functions.

## Concerns

- Full offline verification retains two pre-existing pytest cleanup warnings;
  they are unrelated to Task 6 and do not affect test exit status.
- Live Gemini/provider checks were intentionally not run because the repository
  requires explicit opt-in credentials. v4 graph wiring remains outside this
  file-scoped Task 6 change.
