# Task 11 Report: Retire the Fixed Text-Card Production Path

## Outcome

Task 11 leaves one production editorial pipeline:

`VisualPlan -> CarouselPayload -> AssetManifest -> RenderManifest -> Human Review -> Final Guard -> publish package`

The fixed-card renderer, its graph node, old image-search nodes/tool, legacy
prompt lane, schemas/exports, QA bypasses, fixed filenames, and old state slots
are gone. The only compatibility seam is
`src/editorial_carousel/legacy.py`. It decodes persisted checkpoint shape and
content-contract keys, builds a deterministic modern `VisualPlan`, invalidates
old storyboard/render artifacts, and safely re-enters at the modern storyboard
seam. It never imports or invokes a retired renderer, resolver, schema, or
prompt.

## Deleted Surfaces

Production modules:

- `src/schemas/text_card.py`
- `src/rendering/text_cards.py`
- `src/nodes/node_p_text_card_renderer.py`
- `src/nodes/node_l_visual_director.py`
- `src/nodes/node_m_image_sourcing.py`
- `src/nodes/node_n_image_qa.py`
- `src/tools/pexels_search.py`

Prompts:

- `src/prompts/base/storyboards_generator_legacy.txt`
- `src/prompts/node_l_visual_director.txt`
- `src/prompts/node_m_image_sourcing.txt`
- `src/prompts/node_n_image_qa.txt`
- `src/prompts/node_o_storyboards_images_generator.txt`

Dedicated fixed-card tests:

- `tests/rendering/test_text_cards.py`
- `tests/nodes/test_text_card_renderer.py`
- `tests/schemas/test_text_card.py`

The lazy node exports, text-card schema exports/aliases, `AgentState` image
script/candidate/final-image slots, initial-state values, and assembler's obsolete
final-image prompt input were removed. `requirements.txt` was unchanged because
Task 11 introduced no direct dependency. The semantic storyboard prompt retained
its acceptance behavior; only its sentence spelling out retired theme tokens was
generalized to forbid every free theme value, allowing the required forbidden-
reference scan to be clean.

## Migration Semantics

Old contracts receive only the five required editorial strategy fields, with
their existing content/copy preserved. The adapter then calls the same
deterministic strategy builder as a fresh run, clears old storyboards,
`rendered_image_paths`, render errors, manifests, and QA results, sets the modern
workflow marker, and uses `as_node=visual_strategy_planner` so the next node is
`storyboard_generator`.

Coverage includes persisted successors at the old storyboard, Carousel QA,
retired renderer, Render QA, Human Review, and Final Guard seams. A task-scoped
self-review found one additional real checkpoint case: after old Carousel QA,
the persisted successor itself can be the deleted renderer. LangGraph omits an
unknown node from `StateSnapshot.next`, making it look terminal. A RED regression
proved this. The adapter now reads the raw checkpointer only when visible `next`
is empty, accepts exactly one supported `branch:to:<retired-node>` channel, and
otherwise leaves terminal state untouched. That exact checkpoint now migrates
through the modern path.

Modern checkpoints remain untouched, stale legacy markers on modern artifacts
are cleared, unknown workflow versions fail closed, and malformed/partial modern
state is never downgraded into legacy behavior.

## TDD Evidence

New-path baseline before deletion:

```text
291 passed, 2 skipped, 1 warning in 44.77s
```

The first retirement tests were intentionally RED:

```text
4 failed, 2 passed
```

They proved the compiled graph still contained the retired renderer and legacy
storyboard edge, a missing `VisualPlan` still selected the legacy prompt, and the
legacy prompt task was still registered.

The replacement exact-successor migration suite was also intentionally RED:

```text
5 failed
```

It showed old successors stayed on `legacy_v1` or resumed downstream without
modern artifacts. After the adapter/graph change, the focused retirement suite
passed (`11 passed`). The task-scoped review then added the hidden deleted-
successor case; it failed with `current.next == ()` before the raw-checkpoint
recovery and the expanded migration suite passed afterward (`6 passed`).

The final old assembler state seam got a focused RED assertion because
`image_final_choices` still appeared in its human prompt. Removing the obsolete
state read and prompt input made it GREEN (`1 passed`).

## Forbidden References and Static Verification

Command:

```text
rg -n "REQUIRED_TEXT_CARD_TEMPLATES|TextCardPayload|text_card_renderer|pexels_search|visual_director_node|image_sourcing_node|image_qa_node|question_closer|warm_neutral|cool_sage" src main.py
```

Result: one allowed, documented persisted migration-key occurrence:

```text
src/editorial_carousel/legacy.py:29:        "text_card_renderer",
```

The adapter comment explicitly states that this is a persisted checkpoint key,
the node is absent from the graph, and no implementation is imported or invoked.

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m compileall -q src main.py
# exit 0, no output

git diff --check
# exit 0, no output
```

## Four Golden Visual Inspections

The four real golden cases were regenerated with local Chromium under
`/tmp/xhs-task11-visual-review`; no review artifact is in the worktree or commit.
All four generated-case tests passed (`4 passed`). Every contact sheet was opened
with `view_image` at original detail.

| Fixture | Layout/content inspection | Safety/design inspection |
| --- | --- | --- |
| `zone_diagnosis` | Six distinct pages: cover, texture baseline, two face-zone diagrams, three-state feedback, saveable reference. Chinese copy and numbered checks are readable. | Fixed ivory/ink/mauve/coral/sage system is coherent; abstract face diagrams are not identifiable people; no salamander, logo, watermark, or meaningless decoration. |
| `ordered_routine` | Five pages visibly change composition across cover, numbered timeline, morning/evening split, decision branch, and saveable checklist. | Fonts and palette match the account system; the checklist is independently saveable; no face requirement or unsafe decoration. |
| `multi_option_decision` | Five pages cover comparison panels, three-state diagnosis, decision tree, and final reference. Copy remains readable and semantically placed. | Consistent local-font editorial treatment; abstract product/texture assets only; no salamander or identifiable face. |
| `reference_checklist` | Five pages cover checklist, decision, comparison, and final reference compositions. The checklist/reference pages remain useful when saved alone. | Same design system and local fonts; no system fallback, person, cartoon IP, or irrelevant visual element. |

The first `view_image` call for the original `reference_checklist` path displayed
black tiles and apparently clipped text. This was a viewer path-cache/decode
artifact, not renderer output: a single-fixture rerun passed, and the supposedly
bad and visibly good `01-cover.png` files were byte-identical with SHA-256
`6c09c03137a767eee52607147a31b26d8bd6e8885724844a2d6e0d7110183a71`;
both contact sheets were byte-identical with SHA-256
`092ce9e629b664a78cb1416a423b2d9ee40b2d4eb166647488347170c2ed7d23`.
The rerun path decoded normally while the original path repeatedly returned the
cached bad visualization. No production or QA change was made for identical PNG
bytes.

## Publish Package Inspection

For each of the four packages, `publish-copy.txt` was compared to audit JSON and
exactly matched title, content, and space-joined hashtags.

Every `codex-image-regeneration-prompt.txt` was read and checked against its own
audit JSON:

- canonical JSON exactly equals `content_lock` without `canonical_sha256`;
- the printed SHA-256 exactly equals `content_lock.canonical_sha256`;
- every locked storyboard string, frame order, role, and layout comes from that
  package;
- no prompt contains another fixture's title;
- input/output paths point only to its own package and a new versioned rescue
  directory;
- the prompt permits visual-only changes and explicitly forbids topic, audience,
  pain, copy, fact, step, dosage, judgment, and frame drift.

All four checks returned `canonical=yes`, `hash=yes`, and `foreign=0`.

## Full Verification

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
1302 passed, 2 skipped, 1 warning in 78.21s
```

The two skips are the explicit opt-in live Pexels/Unsplash tests. The suite made
no live provider call. The one test-summary warning is the known LangGraph
serializer pending-deprecation warning; pytest also printed an environment-level
temporary-directory cleanup warning after its successful summary.

## Task-Scoped Self-Review

- Confirmed the compiled graph contains no retired renderer and always routes
  storyboard generation to the modern resolver.
- Confirmed Carousel QA, Render QA, Final Guard, and content persistence have no
  legacy bypass and require modern contracts/manifests.
- Confirmed the adapter has no import of retired code or prompt and uses only a
  documented migration-key string.
- Confirmed modern resume does not repeat completed downloads; old artifacts are
  deliberately regenerated through the modern seam.
- Confirmed all listed deletions, exports, state fields, prompt references, fixed
  filename checks, and direct-dependency requirements are resolved.
- The review found and fixed the hidden deleted-successor checkpoint gap and the
  obsolete assembler state seam before final verification.
- The root agent will perform the separate whole-branch review requested after
  this task commit.

---

## Independent Review Fix (review handoff `task11-to-fix.md`)

An independent review of commit `d55d1c5` reported
`Critical 0 / Important 3 / Minor 2 / Ready: No`. A follow-up fix agent began
the review fixes and was interrupted mid-patch. This section records the
resumed fix: it preserves that dirty patch, repairs it, and adds the missing
regression coverage. The original implementation history above is unchanged.

### Interrupted-patch baseline

The worktree was dirty at handoff. The focused suite (Final Guard, legacy
resume, publish profile) was run before any edit to establish what the
interrupted agent left:

```text
1 failed, 74 passed
```

The single failure was `test_human_review_can_explicitly_replace_storyboards`.
Root cause (systematic-debugging): the interrupted patch's
`_validate_modern_storyboards` re-serialized human edits through
`CarouselPayload.model_dump()`, which injects default slots
(`composition=None`, `palette_tags=[]`) and so broke exact-equality with the
human's replacement. Because `CarouselPayload` already uses `extra="forbid"`,
re-serialization was unnecessary for rejecting retired keys.

### Important 1 — `legacy.py` is the only fixed-card seam

- `StoryboardVisibleText` (`src/schemas/decision.py`) now carries `role` +
  `layout` with `extra="forbid"` and no `template`.
- `publish_patch.py` extracts/merges only modern frame identity and
  `content_blocks` visible text; the retired `wrong_items` / `right_items` /
  `checklist_items` / `steps` / `conditions` / `question` / `template` atoms
  are gone from `STORYBOARD_VISIBLE_*`.
- Human Review storyboard edits cross a strict `CarouselPayload` boundary via
  `_validate_modern_storyboards`, changed to **validate-only** so the human
  edit is enforced but not mutated. Retired keys are rejected by
  `extra="forbid"` and never reach the publish package.
- Prompts (`decision_engine.txt`, `r1_reflector.txt`) stopped asking for
  retired fields: `template`→`role`/`layout`, and the stale
  `checklist_items[1]` example became the modern `content_blocks[0].items[1]`
  location key.

RED→GREEN: `test_human_review_can_explicitly_replace_storyboards` failed before
the validate-only change and passes after. The rejection test was parametrized
over all seven retired fields (`template`, `wrong_items`, `right_items`,
`checklist_items`, `steps`, `conditions`, `question`); all seven are rejected
(`7 passed`).

### Important 2 — Final Guard behavior matrix rebuilt with modern artifacts

The interrupted patch had already rebuilt the behavior matrix around a complete
modern state fixture. Two gaps remained versus the review brief and are now
closed:

- Missing/empty required fields: parametrized over every
  `_REQUIRED_PUBLISH_FIELDS` member plus the `hashtags` empty-string-item case
  (`10 cases`).
- URL exclusion teeth: added
  `test_complete_final_guard_url_exclusion_keeps_unsafe_prose_outside_url`,
  which places unsafe prose *outside* a URL and asserts it is still flagged.
  This directly answers the review concern that "both can return the same
  broken result if policy scanning is disabled" — if scanning were disabled or
  the URL pattern over-matched, this test would fail.

No production change was needed; the existing `_URL_PATTERN` and recursive
`_storyboard_visible_text` already cover title, body, `content_blocks[*]`,
and `content_blocks[*].items[*]`. The full matrix (`19 passed`): missing
required fields, unsafe title, unsafe body, unsafe content-block body, unsafe
content-block items, URL false-positive exclusion, URL-prose teeth, clean
package success route, post-Human-Review unsafe-edit recheck, and the
supplementary validator↔node equivalence test.

### Important 3 — `final_policy_guard -> content_writer` successor

`tests/integration/test_legacy_editorial_resume.py` was extended with the exact
case `("final_policy_guard", "content_writer")`. The shared parametrized test
proves recovery recognizes the persisted successor, migrates to
`MODERN_EDITORIAL_V2` with a fresh `visual_plan`, invalidates old
storyboard/render artifacts, re-enters at `storyboard_generator` via
`visual_strategy_planner`, runs `content_writer` only *after* full modern
regeneration, and never persists the old package (`1 passed`).

### Minor 1 — single publish-profile resolution

`src/editorial_carousel/publish_profile.resolve_publish_package_profile` is now
the one helper used by both `main.py` (export entry points) and
`node_p_editorial_carousel_renderer.py`. Tests cover valid resolution, missing
domain, missing profile version, unknown domain, unknown profile version, and
consistent `ValueError` behavior from both the renderer and the export entry
point (`6 passed`).

### Minor 2 — raw-checkpoint documentation

`persisted_checkpoint_nodes` docstring now states all four safety conditions
explicitly: raw checkpoint channels are consulted only when visible
`StateSnapshot.next` is empty; only allowlisted legacy successors are
considered; recovery occurs only when the filtered result is unique; missing
or ambiguous values leave terminal state unchanged. The runtime allowlist is
unchanged.

### Final verification

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m compileall -q src main.py   # exit 0
git diff --check                                                        # clean
```

Forbidden-reference scan: one allowed, documented persisted migration key:

```text
src/editorial_carousel/legacy.py:29:        "text_card_renderer",
```

Retired-field scan outside `legacy.py`: every remaining hit is part of the
modern domain contract — CSS `grid-template-*` properties, LangChain
`PromptTemplate` locals, the `template_stiffness` render-QA metric, the
publishing-artifact file-template directory, and the prose "conditions to
decisions" in the decision-tree strategy description. No hit implements
fixed-card compatibility.

```text
/opt/anaconda3/envs/xhs-agent/bin/python -m pytest -q
1330 passed, 2 skipped, 1 warning in 80.91s
```

The two skips are the explicit opt-in live asset-provider tests
(`RUN_LIVE_ASSET_PROVIDER_TESTS`). The single warning is the known LangGraph
serializer pending-deprecation warning. No remaining Minor concerns. The fix
is not complete until an independent reviewer rechecks the new commit range.
