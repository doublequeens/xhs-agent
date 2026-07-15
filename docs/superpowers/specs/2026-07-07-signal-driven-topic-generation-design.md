# Signal-Driven Topic Generation Design

## Status

Approved for implementation planning on 2026-07-07.

当前状态：已实施；本文保留作设计记录。

## Objective

Replace direct LLM topic generation with a signal-driven topic generation
pipeline. The new pipeline should produce candidates that feel timely,
specific, and diverse while preserving the existing domain, novelty, virality,
compliance, and human-review gates.

The design targets this current weakness:

- `trend_scout` asks an LLM to generate topics from `domain_context`,
  `memory_context`, and `focus_keyword`.
- This often produces safe but generic topics, because the model has no
  structured source of current timing, seasonal context, platform inspiration,
  or forced creative variation.

The new mechanism makes topical freshness an explicit input instead of an
implicit prompt request.

## Non-Goals

This design does not:

- Let external hotspots directly become publishable topics.
- Scrape individual notes or interact with user content.
- Chase entertainment gossip, disasters, disputes, or medical news in the
  first version.
- Replace the downstream `novelty_guard`, `virality_scorer`, R1/R2 review,
  human review, or final policy guard.
- Require the user to manually provide `domain` and `subdomain` every run.

## Domain and Subdomain Routing

Topic generation still needs `domain` and `subdomain` as hard boundaries. They
determine which signals are eligible, which historical memory is queried, which
creative briefs are sampled, and which policy rules apply.

Routing precedence:

1. If the user provides `--domain` and `--subdomain`, use them directly.
2. If the user provides only `--domain`:
   - In interactive CLI runs, ask the user to confirm `subdomain`.
   - In non-interactive runs, use the domain profile's `default_subdomain` and
     record this in generation trace metadata.
3. If the user provides neither but gives `focus_keyword`, infer both from the
   keyword. Low-confidence inference interrupts for confirmation in interactive
   runs.
4. If no useful input exists, default to `healthy_lifestyle/daily_habits` and
   record the source as defaulted.

CLI validation rules:

- `--subdomain` is valid only when `--domain` is also present.
- The supplied `--subdomain` must belong to the selected domain profile.
- Explicit invalid values fail fast with the allowed subdomains listed.
- The system does not infer a domain from a bare `--subdomain` in the first
  version.

## Architecture

Replace the single `trend_scout` responsibility with four focused nodes:

```text
memory_retriever
  -> topic_signal_collector
  -> creative_brief_builder
  -> topic_ideator
  -> topic_diversity_filter
  -> angle_strategist
```

Downstream nodes continue to consume `state["trends"]`. This keeps the rest of
the workflow stable while making topic generation testable and observable.

Add a separate creator-center trend collector:

```text
trend_collector
  -> browser login profile
  -> creator center note inspiration and activity center
  -> hotspot normalization
  -> trend_signals storage
```

The trend collector is independent from `metrics_collector`. It reuses the same
browser profile but has its own command, run ledger, logs, and LaunchAgent.

## Signal Sources

The first version uses L1 and L2 signals only.

### L1 Deterministic Signals

Generated locally without network dependency:

- Current date, weekday, month, season, and nearby solar terms.
- Workday/weekend rhythm.
- Stable annual content nodes, such as Spring Festival, May Day, summer break,
  back-to-school season, 618, Double 11, year-end review, and seasonal
  transitions.
- Domain and subdomain scene libraries.
- Historical memory, including recent topics to avoid, recent angles to avoid,
  high-performing patterns, and low-performing patterns.

### L2 Managed and Collected Signals

Stored or collected separately:

- `config/trend_calendar.yml` for manually maintained long-lived content
  timing signals.
- Shanghai generalized weather signals, such as high heat, cold wave, rainy,
  humid, dry, windy, or normal.
- Creator-center cached signals from note inspiration and activity center.

The first version excludes broad social hot searches, entertainment topics,
disasters, disputes, and medical news because their relevance is noisy and the
compliance risk is high.

## Trend Calendar

Manual calendar data should store signals and boundaries, not finished topics.

Example:

```yaml
signals:
  - id: summer_heat
    signal_type: seasonal
    signal_name: 高温天
    active_from: 2026-06-15
    active_to: 2026-08-31
    applicable_domains:
      healthy_lifestyle:
        subdomains: [hydration, exercise, daily_habits]
        angles:
          - 高温天喝水容易忽略的细节
          - 不想运动时的低门槛活动量
          - 午后困倦和作息安排
    avoid:
      - 中暑治疗建议
      - 电解质补充剂推荐
```

The LLM may use these signals for transformation, but it must not invent
unsupported current events.

## Creator-Center Trend Collector

The creator-center trend collector reads only cached or visible trend surfaces:

- Note inspiration.
- Activity center.

Behavioral constraints:

- Reuse `~/.xhs-agent/browser-profile`.
- Use a separate package or module, for example `trend_collector`.
- Use a separate LaunchAgent label, for example
  `com.xhs-agent.trend-collector`.
- Run at a different time from `metrics_collector`.
- At most one successful collection per local day.
- Read at most the configured top items from each allowed block.
- Do not open note details.
- Do not publish, comment, like, follow, search, or paginate aggressively.
- Fail closed when the page requires verification or the structure is unknown.

Collected hotspots are normalized into signals. They do not directly become
topics.

## Weather Signals

Weather support uses a configured city, not device location. The first version
uses Shanghai.

Stored weather signal fields:

- `date`
- `city`
- `weather_type`
- `temperature_high`
- `temperature_low`
- `humidity_bucket`
- `source`
- `expires_at`

Generated content should use generalized language such as "高温天" or
"连续阴雨", not "你所在城市". Weather lookup failure must not block topic
generation.

## Signal Storage

Use two storage layers:

- YAML for stable, human-edited calendar signals.
- SQLite for automatically collected and generated dynamic signals.

Add a `trend_signals` table with fields conceptually equivalent to:

```text
signal_id
source
source_url
raw_title
normalized_signal
signal_type
domain
subdomain
why_now
domain_translation
risk_level
avoid_topics
confidence
active_from
expires_at
collected_at
metadata
```

Signals with `risk_level=high`, expired signals, or low confidence do not enter
topic ideation.

## Creative Seed Contract

Every generated topic must include a `creative_seed`. A topic without a valid
seed is invalid and cannot enter downstream review.

Required fields:

```json
{
  "signal_type": "seasonal | calendar | weather | creator_center | historical_pattern | weekday_rhythm | evergreen_context",
  "signal_name": "string",
  "why_now": "string",
  "domain_translation": "string",
  "evergreen_pain": "string",
  "timely_framing": "string"
}
```

The design target is `50% evergreen pain + 50% timely framing`:

- The core pain must remain meaningful after the signal expires.
- The timely framing must explain why this is especially relevant now.
- Timely framing is a hook, not the only value source.
- If the timely frame is removed, the topic should still be convertible into a
  useful evergreen piece.

## Creative Brief Builder

The system should not ask the LLM to freely generate topics from raw signals.
Instead, deterministic code builds `creative_brief` objects by combining:

- `signal`
- `audience`
- `pain`
- `content_intent`
- `contrast_frame`
- `historical_pattern_hint`

Example:

```json
{
  "brief_id": "br_001",
  "signal": "高温天",
  "audience": "上班族",
  "pain": "没时间",
  "content_intent": "checklist",
  "contrast_frame": "低门槛",
  "historical_pattern_hint": "清单型内容表现较好"
}
```

The builder uses weighted sampling instead of exhaustive enumeration.

Sampling rules:

- Generate `2-3x trends_num` creative briefs.
- Prefer fresh, active signals.
- Prefer strong domain and subdomain fit.
- Prefer low-risk signals.
- Use historical high-performing structures as a positive weight.
- Penalize overused signals, audiences, pains, intents, and contrast frames
  within the same run.

Distribution constraints:

- One signal should not dominate the batch.
- One audience should not dominate the batch.
- `content_intent` should cover at least two or three types when enough
  candidates exist.
- `contrast_frame` should cover at least two or three types when enough
  candidates exist.

## Topic Ideator

`topic_ideator` is the only LLM-based topic generation node in the new chain.
It receives structured creative briefs and produces candidates.

Output requirements extend `TopicItem` with creative metadata:

```json
{
  "topic_id": "tp_001",
  "topic": "string",
  "target_group": "string",
  "core_pain": "string",
  "hook": "string",
  "content_form": "string",
  "risk_note": "string",
  "domain": "healthy_lifestyle",
  "subdomain": "daily_habits",
  "content_intent": "experience | myth_busting | how_to | checklist | basic_science",
  "risk_level": "low | medium",
  "risk_flags": ["string"],
  "creative_seed": {
    "signal_type": "string",
    "signal_name": "string",
    "why_now": "string",
    "domain_translation": "string",
    "evergreen_pain": "string",
    "timely_framing": "string"
  }
}
```

The LLM must not claim that a topic is "recently hot" unless that claim is
backed by an input signal.

## Topic Diversity Filter

`topic_diversity_filter` runs before `angle_strategist`. It reduces the
overgenerated candidate set to `trends_num`.

Responsibilities:

- Remove candidates with missing or invalid `creative_seed`.
- Remove topics outside the selected domain or subdomain.
- Remove candidates that violate obvious prohibited topics or claims.
- Deduplicate highly similar topics within the current run.
- Enforce distribution limits for signal, target group, core pain,
  `content_intent`, and keyword clusters.
- Prefer candidates with stronger `why_now`, clearer domain translation, and
  safer risk notes.

If too few candidates remain, the node may request one regeneration pass with a
specific deficit, such as avoiding the already overused signal or adding missing
content intents.

## Traceability

Each topic generation run writes a `topic_generation_trace`.

Trace fields:

```text
run_id
domain
subdomain
trends_num
signals_used
creative_briefs_sampled
generated_candidates_count
filtered_candidates_count
final_trends
diversity_metrics
degraded_reason
created_at
```

Initial diversity metrics:

- `unique_signal_count`
- `unique_target_group_count`
- `unique_core_pain_count`
- `unique_content_intent_count`
- `average_pairwise_title_similarity`
- `timely_signal_ratio`
- `evergreen_pain_ratio`

The trace is for debugging and improvement. It should make it clear whether a
weak generation came from poor signals, narrow brief sampling, LLM noncompliance,
or an overly permissive diversity filter.

## Degradation Behavior

Generation must degrade explicitly and safely:

1. Use creator-center signals, calendar signals, weather signals, deterministic
   date signals, and memory signals when all are available.
2. If creator-center collection fails, use calendar, weather, deterministic
   date, and memory signals.
3. If weather lookup fails, use calendar, deterministic date, and memory
   signals.
4. If no timely signal is available, use evergreen scene-library signals with
   `signal_type=evergreen_context`.

Hard rules:

- The LLM must not invent current events.
- Missing trend data must be recorded in `degraded_reason`.
- Every final topic still requires a `creative_seed`.
- The system should keep generating useful evergreen topics rather than fail
  simply because an optional signal source is unavailable.

## Integration With Existing Workflow

The downstream workflow remains structurally the same:

```text
topic_diversity_filter
  -> angle_strategist
  -> novelty_guard
  -> virality_scorer
  -> evidence_brief
  -> outline_architect
  -> draft_writer
  -> title and review workflow
```

Existing downstream nodes should receive the same logical `state["trends"]`
list, but each trend will include `creative_seed` metadata. Downstream prompts
may use this metadata for stronger hooks, better title ranking, and review
traceability, but the metadata is not a substitute for novelty, virality, or
compliance review.

## Testing Strategy

Unit tests:

- Domain/subdomain CLI validation and routing precedence.
- Calendar signal parsing and active-window filtering.
- Weather signal normalization for Shanghai.
- Creator-center hotspot normalization from local HTML fixtures.
- `trend_signals` insertion, deduplication, expiration, and confidence filters.
- Creative brief weighted sampling and distribution limits.
- Topic diversity filtering, including missing `creative_seed` rejection.
- Degradation behavior when optional signal sources fail.

Integration tests:

- A no-network run that combines calendar, fake weather, fake creator-center
  signals, and memory context into final `state["trends"]`.
- A degraded no-hotspot run that still produces seeded evergreen topics.
- A run proving downstream `angle_strategist` can consume the new trend schema.

Manual smoke tests:

- Run `healthy_lifestyle/daily_habits` in July with Shanghai weather and verify
  topics include timely but evergreen-compatible framing.
- Run `beauty/skincare` during a seasonal transition and verify signal filtering
  does not leak unrelated health or wellness topics.
- Verify creator-center trend collection writes signals without opening note
  details.

## Implementation Boundaries

First implementation should focus on:

- CLI support for `--subdomain`.
- New topic generation nodes and state fields.
- YAML calendar signals.
- SQLite `trend_signals` and `topic_generation_trace`.
- Shanghai generalized weather provider behind a replaceable interface.
- Creator-center trend collector with local fixture tests before live access.

It should not add broad hot-search crawling, entertainment trend ingestion, or
large-scale platform scraping.
