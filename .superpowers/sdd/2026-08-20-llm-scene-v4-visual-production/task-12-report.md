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

## Concerns / handoff

Q2 remains a deterministic layout/provenance gate and does not establish final
DOM/PNG fidelity; that evidence belongs to Task 13 Q3. Orphan detection uses
the compiler's persisted line widths/counts without copying visible text.
The controller should run its filtered offline full-suite verification and
review/commit this Task 12 boundary as `fix: recompute v4 design metrics at hard gate`.
