# Beauty Account Content Workflow Design

## Status

Implemented on 2026-07-10 on `feature/beauty-account-workflow`. The workflow
now enforces the account contract from domain selection through deterministic
carousel QA before human review.

## Objective

Reorient the Xiaohongshu workflow around one account promise rather than broad
topic categories or a reusable cartoon visual IP.

The workflow serves **23–35-year-old commuting women with basic skincare and
base-makeup needs**. Every published post must help this audience make one
clear beauty-care decision in one concrete situation and leave her with a
standalone asset she can screenshot and use.

## Non-goals

- The account will not generate wellness, nutrition, sleep, exercise, or
  general lifestyle posts in this workflow.
- The account will not use the pink axolotl or any other recurring cartoon
  character as a default visual identity.
- This work will not revive the currently disconnected visual-director,
  image-sourcing, or image-QA pipeline.
- This is not a claim that every post must use photography or that the account
  needs a human face on camera.

## Account Profile

Introduce one immutable `CreatorProfile` for this account and pass it through
the state to all generation and review nodes.

| Field | Value |
| --- | --- |
| audience | 23–35-year-old commuting women with basic skincare and base-makeup needs |
| allowed domains | `beauty` only |
| allowed subdomains | `skincare`, `makeup_basics` |
| primary situations | early commute, sunscreen, air-conditioned office, seasonal changes, makeup preparation, midday touch-up, after-work plans |
| preferred intents | how-to, checklist, decision criteria, comparison, bounded myth correction |
| excluded themes | sleep, stress, exercise, nutrition, supplements, generic healthy lifestyle, disease-like skincare claims |
| visual modes | `text_card`, `text_plus_real_proof`, `comparison_table` |

The profile is not a replacement for `DomainProfile`: the latter remains the
safety and taxonomy policy. `CreatorProfile` is the account-positioning policy.

## Content Contract

Every topic candidate must carry a `ContentContract` before it can be scored.

| Field | Requirement |
| --- | --- |
| audience | Must equal or be a precise subset of the account audience. |
| trigger_situation | A specific moment, not a generic concern. |
| decision_problem | One beauty-care decision the reader cannot easily make alone. |
| first_screen_promise | States audience or scene, problem, and practical gain in one screen. |
| screenshot_asset | A checklist, step sequence, decision rule, or comparison table that works as an independent image. |
| proof_asset | A real product, hand/action, texture, tool, diagram, or `none` when text alone is more honest. Decorative AI art is invalid. |
| visual_mode | One of the profile visual modes. |

A missing or unverifiable contract field disqualifies a candidate before
writing begins.

## Revised Graph

```text
domain routing (beauty only)
  -> memory and topic signals
  -> profile-bound creative brief
  -> topic ideation with ContentContract
  -> diversity and novelty checks
  -> scoring with first-screen and save-value gates
  -> evidence, outline, draft, title, editorial revision, compliance
  -> assembly
  -> text-card storyboard generation
  -> carousel QA
  -> human review, final policy guard, persistence
```

Add `carousel_qa` between `storyboard_generator` and `human_review`. It routes
failed packages back through the existing editorial revision loop. It does not
replace compliance or human review.

## Node Changes

### Domain routing and profile enforcement

- `domain_router` rejects any explicit domain other than `beauty` for this
  account.
- `domain_confirmation` only offers `skincare` and `makeup_basics`.
- Add `creator_profile` to `AgentState` and populate it in initial state.

### Creative briefs and topic generation

- Replace the random audience and pain lists in `topic_signals/briefs.py` with
  values derived from `CreatorProfile`.
- Retain weather, calendar, and historical signals, but translate each only
  into an allowed beauty situation.
- Extend `TopicItem` with `content_contract`.
- Update `topic_ideator` to reject generic themes, unsupported effect claims,
  and topics that cannot produce a screenshot asset.

### Diversity, novelty, and scoring

- Keep `topic_diversity_filter`, but define diversity as different situations,
  decisions, and card forms within the same account audience; it must not
  achieve variety by changing audience or domain.
- Keep `novelty_guard`; add failed historical patterns to its revision advice
  where data is available.
- Extend `virality_scorer` with `first_screen_clarity`,
  `screenshot_asset_value`, `proof_or_honesty`, and `profile_fit`.
- A candidate fails scoring when its first-screen promise is vague, its save
  asset is absent, its proof asset is decorative only, or its audience is out
  of scope.

### Outline, draft, title, and revision

- `outline_architect` uses this card order by default: first-screen promise,
  decision rule or common mistake, three to five actionable items, standalone
  screenshot asset, scope or exception, optional focused discussion prompt.
- `draft_writer` writes a short caption that adds scene, applicability, and
  boundaries. It must not invent first-person experience or use emotional
  filler as evidence.
- `title_lab` and `title_ranker` require at least two of audience/scene,
  problem, and gain in title plus cover copy. They reject generic inflated
  language such as `神技`, `急救`, `亲测有效`, `救命`, `无缝`, and `隐形`.
- `r1_reflector` treats a missing contract field, screenshot asset, or
  first-screen clarity as mandatory editorial work.
- `r2_compliance` additionally flags pseudo-experience, unbounded mechanism
  explanations, and performance promises.

### Visual and carousel generation

- Repurpose `storyboards_generator` as a text-card layout generator.
- Remove all pink-axolotl instructions, character fields, character-reference
  requirements, and fixed top-title/middle-character/bottom-narration layout.
- Generate six to eight cards rather than forcing eight to ten cards.
- Default first card: one high-contrast promise; no decorative illustration.
- Require one screenshot-ready card with all needed information visible on the
  card itself.
- Permit real proof visuals only when they substantiate an instruction.
- Update `storyboards_images_generator` so it renders text-led cards and only
  optional proof visuals; it must never insert a character or decorative AI
  scene.

### Carousel QA

`carousel_qa` validates:

1. Card one communicates audience or scene, problem, and gain.
2. One card is a standalone screenshot asset.
3. The visual mode matches the contract.
4. No cartoon IP or decorative AI illustration substitutes for evidence.
5. Card count is six to eight and visible text is not duplicated across cards.

It returns atomic edit tasks compatible with the existing `decision_engine` /
`r1_reflector` loop.

The implemented deterministic QA rules reject a package when its contract
visual mode is outside the active CreatorProfile, it has fewer than six or more
than eight cards, its first card is not a cover, its first-card copy does not
exactly equal the contract's `first_screen_promise`, no card is marked as a
screenshot asset, any card's visual mode differs from the contract, a
decorative/cartoon term appears in a decorative field, or visible on-image copy
is duplicated. A rejected package receives atomic edit tasks and routes to R1;
a passing package routes to human review.

## Prompt Architecture

Add a shared `creator_profile` prompt fragment after the safety fragment and
before the domain fragment. Do not copy account-profile wording independently
into every task file.

Each relevant task prompt will add the following rules in its task-specific
section:

- Topic Ideator: output and validate `ContentContract`.
- Angle Strategist: vary scenario, decision, or presentation only; never the
  audience.
- Virality Scorer: use contract fields as hard rejection gates.
- Outline Architect: reserve a standalone screenshot card.
- Draft Writer: no fabricated anecdotes; caption supplements cards rather than
  repeating them.
- Title Lab and Ranker: enforce concrete promise and ban inflated filler.
- Storyboard Generator: text-led card system with optional proof visual.
- R1 and R2: review the contract and visible card text as first-class output.

## Nodes to Keep, Repurpose, or Defer

| Status | Components |
| --- | --- |
| Keep | routing, memory retrieval, topic signals, diversity, novelty, scoring, evidence, outline, draft, title, decision, R1, R2, hashtag, assembler, human review, final guard, persistence |
| Repurpose | `storyboards_generator`, `storyboards_images_generator` |
| Add | `carousel_qa` |
| Do not activate now | `visual_director`, `image_sourcing`, `image_qa` |
| Deferred cleanup | `trend_scout`, which is not wired into the main graph; duplicate legacy storyboard prompt files |

## Validation

- Unit tests for beauty-only routing and CreatorProfile propagation.
- Unit tests for rejecting missing or invalid ContentContract fields.
- Snapshot tests for topic, score, outline, and storyboard prompt payloads.
- Graph-routing tests for `carousel_qa` reject and pass paths.
- Final-package tests ensuring 6–8 cards, no character prompt language, and a
  screenshot-ready frame.
- A manual review of the first ten generated candidates before publication.

## Rollout

1. Land profile, contract schemas, and prompt composition changes.
2. Land topic/scoring/outline/title changes with tests.
3. Replace storyboard prompts and add Carousel QA with graph tests.
4. Generate ten unpublished packages and review them against the contract.
5. Publish only approved packages, then compare first-screen, save, and
   engagement metrics before changing the account scope again.
