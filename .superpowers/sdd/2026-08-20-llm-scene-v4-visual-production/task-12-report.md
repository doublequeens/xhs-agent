# Task 12 report: v4 Design Plan QA hard gate

## Scope

Task 12 adds the isolated `llm_scene_v4` Q2 quality contract, deterministic
scene metrics, and the narrow aggregate boundary. It does not wire the graph,
render a page, invoke Chromium/LLM/provider/filesystem/clock/random, or modify
the v3 QA path.

Owned files changed:

- `src/schemas/v4/quality.py`
- `src/visual_design/v4/design_metrics.py`
- `src/nodes/v4/design_qa.py`
- `src/schemas/v4/layout.py` (measurement evidence and filesystem-free Q2 provenance revalidation)
- `src/visual_design/v4/typography.py` (persisted Pillow line widths/codepoint counts)
- `src/visual_design/v4/compiler.py` (persist measurement evidence)
- `src/schemas/v4/__init__.py`
- `src/visual_design/v4/__init__.py`
- `tests/schemas/v4/test_quality.py`
- `tests/visual_design/v4/test_design_metrics.py`
- `tests/nodes/v4/test_design_qa.py`

## RED evidence

Before the implementation modules existed, the required focused command failed
during collection with missing-module errors for the new v4 quality contracts
and evaluator (`ModuleNotFoundError: No module named src.schemas.v4.quality` /
`src.visual_design.v4.design_metrics`). This was
the expected RED state recorded in the Task 12 brief.

## Implemented contract

`DesignMetricEvidenceV4`, `DesignMetricsQAResultV4`, `DesignQualityIssueV4`
and `DesignPlanQAResultV4` are frozen, `extra=forbid`, canonical-hash-bound
contracts. `passed` is derived from Q0/Q1/Q2 issues and metric comparisons.
The aggregate revalidates nested models and binds ContentAtomSet,
ContentLock, SemanticContentModel, narrative, PageBriefSet,
VisualDirectionPlan, AssetManifest, canonical family tokens, compiled pages,
candidate, revision and run identities transitively. It has one strict
canonical argument set: Q2 metrics, page metrics, design metrics and caller
family-token payloads are not accepted. Q2 is recomputed from the current
CarouselDesignPlan and exact PageBriefSet. Candidate preflight cannot be
promoted to durable Q1.

Q2 computes all required scene/provenance metrics: safe margin, unintended
overlap, minimum font, contrast, whitespace, largest text block, regional
density, alignment-axis deviation, paired-column balance, spacing
consistency, heading/body hierarchy, visual-center offset, emphasis count,
line length, orphan line, orphan heading and image/text area ratio. Values are
finite and derived from compiled geometry, typography evidence, region
bindings and scene styles. Missing measurable text or impossible denominators
fail closed as structural invariants rather than receiving placeholder scores.
Global metric evidence retains a deterministic canonical region/element/ref
location where one exists.

Threshold selection is canonical and versioned by grammar plus the typed page
role derived from the beat task. Caller-supplied page roles cannot select a
wider envelope. Current policy hashes are:

| grammar / narrative role | page role | policy SHA-256 | whitespace | largest text block | spacing |
| --- | --- | --- | ---: | ---: | ---: |
| editorial_hero / cover_hook | cover | `40f9ab605c40f254473564c7344e97518c89df698bb48fdd23cba8ec5e4d3435` | 0.38 | 0.46 | 48 |
| editorial_hero / context | body | `0669d75044922a81a14035172c28d697f0ad9269dc77df102ba746ac4eed5feb` | 0.36 | 0.46 | 48 |
| editorial_hero / summary | closing | `db3d43e1c055d5741a0f3abebea31b2704e9d23e6f5ecb7e190344ce52fd53bb` | 0.37 | 0.46 | 48 |
| editorial_hero / closing | closing | `6d422b5d149985b961c63010d7bd5bf8478396bfc333d28d3167915087db9138` | 0.37 | 0.46 | 48 |
| comparison_grid / diagnosis | body | `fa8a056a192b7a5319ae52ab890ad3df766bd5c6e3d06216b43fa6272611c40e` | 0.18 | 0.38 | 260 |
| comparison_grid / comparison | body | `161df8764c6b2e6c1771b71eeeb9fae81498191fab7ba91d422141f4c943a5fb` | 0.18 | 0.38 | 260 |
| comparison_grid / evidence | body | `8e62cb26f7aab43176f5502f4dd1ec18b05bc17301227be2c25b1f254272883b` | 0.18 | 0.38 | 260 |
| step_flow / step | body | `30b4927fa77deee1e054ee2498741cf2c423b6e22117127898c75a5ebb1fec6b` | 0.20 | 0.44 | 36 |
| step_flow / checklist | body | `d705be82c68160b1d2876e66be9953290a1dc1143d9bcbcf784d773203fce431` | 0.20 | 0.44 | 36 |

Metric misses use closed issue codes, canonical safe messages, finite actual
and threshold values, structural page/region/element/fragment references and
one revision target. Provider/path/license/provenance/prompt and visible-copy
sentinels are rejected from issue evidence. Unknown metric/policy kinds and
contradictory hashes remain exceptions; a failed metric is never converted to
an exception-free pass.

## GREEN evidence

- Focused Task 12: `34 passed`.
- Adjacent v4 semantic/authoring/compiler plus Task 12: `117 passed, 1 warning`.
- Existing v3 plan/node QA: `39 passed`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

## Fix round 1: fresh RED/GREEN and calibration

Reviewer attack tests were added before the fixes. The first `-x -vv` run
stopped RED at `test_public_q2_requires_exact_page_brief_set_not_single_brief`:
the old evaluator accepted a single `page_brief`; the strict boundary now
raises `TypeError`. Additional probes cover external `999999` actuals,
`VisibleCopyLeak` locations, stale `ffff...` page-brief hashes, missing failed
metric issues, unknown aggregate keyword aliases, and a no-`Path.read_bytes`
Q2 revalidation seam.

The fix recomputes Q2 internally, validates every failed metric against one
matching issue, rejects issues for passed metrics, checks exact page/sequence/
brief/policy/source bindings and structural evidence locations, and derives
family tokens only from the canonical registry. Task 11 evidence now persists
Pillow `line_widths_px` plus non-visible `line_codepoint_counts`, bound into
the measurement payload; real compile/measure still resolves and hashes font
bytes, while Q2 provenance validation uses only the canonical registry digest.

Fresh canonical evaluator fixtures all pass: hero+asset, comparison+asset,
step 3 fragments without assets, and step 5 fragments without assets. Reachable
failure fixtures prove `line_length=901` against the legal `<920` threshold and
regional density `1.0` against `<1`; spacing ignores cross-region gaps and
unions step icon/text rows. Auto-wrap and explicit-newline line evidence is
checked, including an empty explicit final line that deterministically fails.

Fresh verification after round 1:

- Task 12 focused: `45 passed`.
- Adjacent v4 quality/semantic/authoring/compiler: `128 passed, 1 warning`.
- v3 plan/node QA: `39 passed`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.
- Filtered offline suite (known Chromium smoke excluded): `1760 passed, 3 skipped, 4 warnings`.

The filtered-suite warnings are the existing Pydantic serializer warnings for
tampered nested semantic fixtures and pytest temporary-directory cleanup
warnings; no Task 12 assertion failed.

The warning is the pre-existing Pydantic serializer warning from the tampered
nested semantic-model test. No v3 source or renderer files were modified.

## Fix round 2: bind v4 typography evidence and close orphan-line ambiguity

The fresh RED attack compiled a real page, replaced every persisted line width
with `1.0` and every line code-point count with `100`, retained the original
measurement digest, and recomputed the enclosing provenance/page digests. The
old boundary accepted this payload. The new boundary rejects it while
constructing the durable evidence/provenance object, before Q2 can observe a
false `line_length=1` result.

`canonical_text_measurement_payload_v4` and
`canonical_text_measurement_sha256_v4` now define one exact, pure producer /
consumer payload. It persists the complete non-visible Pillow facts required
for recomputation: font role/bytes/nominal weight and size, width/height,
advance and ink dimensions/bounds, line count/height/max width, line widths and
code-point counts, break offsets/spans, insets, painted offsets/bounds, wrap
policy and newline count. `TextMeasurementEvidenceV4` recomputes this digest
with the same helper. It also records the exact reserved scene box and
`CompiledPageV4` cross-checks fragment reference, font role/weight, font size,
line height, max width and all box coordinates against scene/style/provenance.
The producer continues to read and byte-verify canonical fonts; Q2 remains
filesystem-free (the `Path.read_bytes` probe reports zero calls).

The reviewer tamper matrix covers `line_widths_px`, `line_codepoint_counts`,
`max_width_px`, `line_height` and `measurement_sha256`. The line-length fail
fixture recomputes the canonical measurement digest intentionally, proving the
metric itself reaches `901` against the canonical `<920` threshold rather than
depending on a stale-hash shortcut.

Orphan detection now uses every persisted `line_codepoint_counts` entry,
including the final wrapped line and explicit-newline lines; any count `<= 1`
in a multi-line display/heading increments both orphan metrics, and count `0`
remains a deterministic failure. Fresh regressions prove `美*11 -> (10,1)`
fails, `美\n美美美美 -> (1,4)` fails, and `美美\n美美 -> (2,2)` passes. Canonical hero+asset, comparison+asset, and step-flow 3/5-fragment
no-asset fixtures remain passing.

Fresh verification after round 2:

- v4 visual-design suite (Task 12 + Task 11 typography/compiler): `144 passed, 1 warning`.
- Task 12 quality/node focused: `29 passed`.
- Existing v3 plan/node QA: `39 passed`.
- Filtered offline suite (Chromium smoke excluded): `1768 passed, 3 skipped, 4 warnings`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

## Fix round 3: derive hard line metrics from exact semantic source

The reviewer RED probe extended the previous attack by recomputing the
measurement, compiler-provenance, and compiled-page hashes after replacing
persisted widths with `(1, 1)` and line counts with `(100, 100)`. The old
public evaluator did not accept an exact semantic model at all, so this probe
recorded the missing source boundary before implementation. A second aggregate
probe proves the same self-rehashed payload is rejected at the durable Q2
boundary.

The public `evaluate_page_metrics` and complete-plan evaluator now require the
exact hash-bound `SemanticContentModelV4`. Each text element binds its
`fragment_ref`, `source_atom_id`, and `exact_text_sha256` to the compiled page
evidence and exact `SemanticFragmentV4`; a passed aggregate also recomputes Q0
against the supplied atom set and lock. No visible text enters metric evidence,
issues, or errors.

`reconstruct_source_lines_v4` is one pure producer/consumer function. It
requires explicit spans to equal the real CRLF/LF/CR locations, inserted breaks
to be ordered, segment-contained, non-overlapping with newlines, and at
grapheme boundaries. It reconstructs source lines and derives code-point and
grapheme counts. The compiler persists both count sets; Q2 rejects any
self-rehashed evidence that disagrees with those source-derived values. A
valid changed break layout is therefore evaluated against its new source lines
and cannot hide an orphan line through arbitrary offsets.

Q2 orphan metrics use source-derived grapheme counts only. Line length uses the
versioned conservative source bound
`max(persisted_pillow_width_px, grapheme_count * scene_font_size_px)` with
`metric_unit=px` and
`metric_version=source-grapheme-em-upper-bound-v1` bound in both policy and
metric evidence. Rehashed narrow Pillow widths therefore cannot lower the hard
decision, while the reachable `901 px` Pillow fail boundary remains covered.
Canonical hero/comparison/step 3/5-fragment fixtures remain passing.

Round 3 policy hashes (the policy payload now includes the line metric unit and
version) are:

| grammar / narrative role | page role | policy SHA-256 |
| --- | --- | --- |
| editorial_hero / cover_hook | cover | `b7c10c5d0d22be3993baf08d5f6f7fd645106d273bee6d5eb1485f399357d7ad` |
| editorial_hero / context | body | `a85f14370c469e9a8adab13779a82f7b7f9ecb1983008a38a65468189f8c29f2` |
| editorial_hero / summary | closing | `9d31646942d0dbdbba8cd3be28eaccd164386bf2c70064b8cc0d99718a2346d1` |
| editorial_hero / closing | closing | `6e6b50c7266ea8b921aedf1e56d3b38a5df52898289cd53e7f08fc0abeee4979` |
| comparison_grid / diagnosis | body | `5a491a95bfbd64457017a11dcf9b98bb14cfcdedc037ed275447dc65a9a7fc02` |
| comparison_grid / comparison | body | `e4aa06ec305fb7561f37b44a1756ba8f7bfcd8379303e0e1545a7dfb713df7e9` |
| comparison_grid / evidence | body | `dddc90d5b96643f60c171e5b0f4108bd12325b4d37efcc035d6b92c4bcde1490` |
| step_flow / step | body | `edc4886a0bcc26fd62e7c588d693d8bde46c73912814c74ad3c0ce927d8f0921` |
| step_flow / checklist | body | `250bcea7bb2ef844707a3ec184c4d34d77006d5c2e99c56c86b577f4f7cd8fcf` |

Fresh verification after round 3:

- Task 12 focused: `51 passed`.
- Task 11 typography/compiler plus v4 semantic/authoring/layout: `162 passed, 1 warning`.
- Existing v3 plan/node QA: `39 passed`.
- Filtered offline full suite (Chromium smoke excluded): `1774 passed, 2 skipped, 1 deselected, 2 warnings`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

## Fix round 4: reject unconsumed line-break offsets

The fresh RED used `美美\n美美` with a self-rehashed inserted offset `(3,)`,
which is the first source position after the explicit LF. The old
`reconstruct_source_lines_v4` selected offsets independently for each segment
with `cursor < offset < segment_end`; `(3,)` matched neither segment and was
silently discarded. The same probe failed for LF, CRLF and CR, while the
rehash-bound measurement/provenance/page still passed the complete Q2 page
evaluation. The targeted RED command reported `4 failed` for those three
separator cases plus the Q2 attack.

The reconstruction loop now owns one monotonic consumption index. An inserted
offset is consumed exactly once only when it strictly satisfies
`segment_start < offset < segment_end`; segment starts, segment ends, newline
spans, source offset zero/end, duplicates, unsorted offsets and any final
unconsumed offset fail closed. The terminal consumption assertion prevents a
future filtering change from silently dropping offsets. Errors remain
sanitized and contain no visible source text. Legal grapheme-boundary offsets
inside both explicit segments reconstruct the exact lines and code-point /
grapheme counts for LF, CRLF and CR.

Fresh verification after round 4:

- Typography plus design-metrics regression: `47 passed`.
- Typography/design-metrics/quality/design-QA focused: `77 passed`.
- Adjacent v4 typography/design-metrics/design-QA/semantic/authoring/compiler:
  `147 passed, 1 warning`.
- Existing v3 plan/node QA: `39 passed`.
- `python -m compileall -q src main.py`: passed.
- `git diff --check`: passed.

The warning is the existing Pydantic serializer warning from the intentionally
tampered nested semantic-model fixture; no Task 12 assertion failed.

## Concerns / handoff

Q2 remains a deterministic layout/provenance gate and does not establish final
DOM/PNG fidelity; that evidence belongs to Task 13 Q3. The unfiltered suite's
known local Chromium smoke failed at browser launch with the sandbox
`mach_port_rendezvous` permission error; it is excluded from the offline full
suite above. This round is ready for commit as
`fix: reject unconsumed v4 line break offsets`.
