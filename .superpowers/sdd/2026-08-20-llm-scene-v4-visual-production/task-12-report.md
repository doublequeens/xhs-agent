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
VisualDirectionPlan, AssetManifest, family tokens, compiled pages, candidate,
revision and run identities transitively. Candidate preflight cannot be
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
| editorial_hero / cover_hook | cover | `c9683a92534c3cf896f4216fb6210126877d863bafc2c13a47420f6be8d2f91c` | 0.42 | 0.46 | 48 |
| editorial_hero / context | body | `1430de9036ca921db338709f3d28dcb0a52ce3c438740e6f4e5ea154401e3fa5` | 0.40 | 0.46 | 48 |
| editorial_hero / summary | closing | `cc23f617a6c5cad7a65a9b670ce236dedfeea8b8bc2aecac4051c252a917a1ed` | 0.41 | 0.46 | 48 |
| editorial_hero / closing | closing | `6945c93f15fdc97fc7f222813f8cf9bd5708a7dd95afad9d082185c4483645a3` | 0.41 | 0.46 | 48 |
| comparison_grid / diagnosis | body | `bdc1799b0a9e366623541d7906210fcb4ee47cd7cedade99a1da90f9a204fa68` | 0.22 | 0.38 | 260 |
| comparison_grid / comparison | body | `568862a29f0a59c1bff6a4f6fbaf55b489bde096e5270798e737454f3755fa3d` | 0.22 | 0.38 | 260 |
| comparison_grid / evidence | body | `d499e280a7d5585dcd1571a454c825dc8cb206ccbfe0d415e01b07beb2311797` | 0.22 | 0.38 | 260 |
| step_flow / step | body | `d71219ea471c967cad8d97ee2ecc351fb5fbef95420c35fc834ef7ba174a1b0a` | 0.28 | 0.44 | 36 |
| step_flow / checklist | body | `9dfce7a872e48985f7f9dc8fcc74afe1d07500b3e6784f78415acb6b985e773f` | 0.28 | 0.44 | 36 |

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

The warning is the pre-existing Pydantic serializer warning from the tampered
nested semantic-model test. No v3 source or renderer files were modified.

## Concerns / handoff

Q2 remains a deterministic layout/provenance gate and does not establish final
DOM/PNG fidelity; that evidence belongs to Task 13 Q3. Orphan detection uses
the compiler's persisted break-offset evidence without copying visible text.
The controller should run its fresh offline full-suite verification and then
review/commit this Task 12 boundary as `feat: hard gate v4 design quality`.
