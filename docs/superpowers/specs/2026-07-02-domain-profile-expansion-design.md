# XHS Agent Domain Profile Expansion Design

## Status

Approved for implementation planning on 2026-07-02.

## Objective

Expand the agent from skincare-only content generation to three related content
domains while preserving one shared LangGraph workflow:

- `beauty`: skincare, haircare, body care, and basic makeup.
- `wellness`: sleep, stress management, daily routines, and recovery.
- `healthy_lifestyle`: basic nutrition, exercise, hydration, and sedentary
  behavior.

The caller may explicitly provide `domain`. When it is absent, the agent infers
the domain and subdomain from `focus_keyword`.

## Scope

The system generates general lifestyle and educational content. It must not
generate:

- Disease diagnosis or treatment advice.
- Medication advice.
- Medical test or biomarker interpretation.
- Individualized diet or exercise prescriptions.
- Supplement or herbal dosage recommendations.
- Guaranteed, absolute, or precisely quantified health outcomes.

This design does not introduce diagnosis-oriented medical content or a
full-scale medical retrieval system.

## Current Constraints

The existing graph can be retained, but several components assume skincare:

- Prompts identify every node as a skincare specialist.
- `TopicItem`, `AgentState`, and downstream content schemas do not preserve
  domain information.
- Structured and vector memory do not support domain filtering.
- Compliance checks are skincare-specific.
- Hashtags and storyboard guidance contain skincare vocabulary.
- `content_writer_node` hardcodes the content format and visual style.

Replacing the word "skincare" in prompts is insufficient because each domain
has different topic boundaries, claims, language, hashtags, and visual rules.

## Architecture

Add a domain routing and policy layer before memory retrieval:

```text
input
  -> domain_router
  -> domain_confirmation (only for low-confidence inference)
  -> memory_retriever
  -> trend_scout
  -> evidence_brief (only for medium-risk or basic-science topics)
  -> remaining content generation workflow
  -> R1 and R2 review loop
  -> assembler and storyboard_generator
  -> human_review
  -> content_writer
```

`domain_router` is the only component that classifies the request.
`DomainProfile` determines how the selected domain is handled. Downstream nodes
consume the resulting context and policy instead of independently inferring a
domain.

### Domain Routing

Routing precedence:

1. Use a valid caller-provided `domain`.
2. Otherwise infer `domain` and `subdomain` from `focus_keyword`.
3. If inference confidence is below the configured threshold, interrupt at
   `domain_confirmation`.
4. If no useful keyword is available, use `healthy_lifestyle` with a generic
   `daily_habits` subdomain and mark the source as `default`.

An explicitly supplied unknown domain is a validation error. It must not be
silently mapped to a different domain.

## Data Contracts

Add serializable Pydantic models for domain state:

```python
class DomainContext(BaseModel):
    domain: Literal["beauty", "wellness", "healthy_lifestyle"]
    subdomain: str
    classification_source: Literal["explicit", "inferred", "default"]
    classification_confidence: float
    profile_version: str
    risk_level: Literal["low", "medium"]


class ContentPolicy(BaseModel):
    allowed_topics: list[str]
    prohibited_topics: list[str]
    prohibited_claims: list[str]
    required_disclaimers: list[str]
    risk_level: Literal["low", "medium"]
    require_evidence_brief: bool
    require_human_review: bool = True
```

Add these fields to `AgentState`:

```python
domain: Optional[str]
domain_context: DomainContext
content_policy: ContentPolicy
evidence_brief: Optional[EvidenceBrief]
```

Extend `TopicItem` with:

```python
domain: str
subdomain: str
content_intent: Literal[
    "experience",
    "myth_busting",
    "how_to",
    "checklist",
    "basic_science",
]
risk_flags: list[str]
```

`domain_context` is the runtime source of truth. `publish_package` and
`ContentRecord` duplicate only persistence and analytics fields:

- `domain`
- `subdomain`
- `content_intent`
- `profile_version`
- `risk_level`

Do not store a runtime Python profile object in LangGraph state. Store only
serializable context and a policy snapshot so checkpoint replay remains stable.

## Domain Profiles

Implement profiles as validated Python configuration:

```text
src/domain/
  models.py
  router.py
  registry.py
  profiles/
    beauty.py
    wellness.py
    healthy_lifestyle.py
```

Each profile defines:

- Supported subdomains and keyword mappings.
- Allowed and prohibited topics.
- Claim and disclaimer rules.
- Default content intents.
- Tone and audience guidance.
- Hashtag seeds.
- Visual and storyboard guidance.
- Risk classification rules.
- A version identifier.

The registry loads a profile by domain and fails fast if the profile or version
is unavailable.

## Prompt Composition

Retain one base prompt per task and compose it with reusable fragments:

```text
src/prompts/
  base/
    trend_scout.txt
    angle_strategist.txt
    draft_writer.txt
    r2_compliance.txt
    ...
  fragments/
    safety_common.txt
    beauty.txt
    wellness.txt
    healthy_lifestyle.txt
```

All LLM nodes use one prompt builder:

```python
compose_prompt(
    task="draft_writer",
    domain_context=state["domain_context"],
    content_policy=state["content_policy"],
)
```

Prompt order is deterministic:

1. Node responsibility and output schema.
2. Shared Xiaohongshu writing rules.
3. Domain rules.
4. Subdomain rules.
5. Request-specific policy and risk boundaries.

Node-specific behavior:

- `trend_scout` generates only profile-approved topics.
- `angle_strategist` uses `content_intent` to select an experience,
  myth-busting, tutorial, checklist, or basic-science angle.
- `draft_writer` separates first-person experience from educational writing and
  never invents personal experience for educational claims.
- `r1_reflector` checks structure, usefulness, and domain consistency.
- `r2_compliance` applies shared and domain-specific rules.
- `hashtag` selects terms from domain and subdomain taxonomies.
- `storyboard_generator` uses profile visual guidance rather than skincare
  props or a hardcoded visual style.

## Evidence Handling

Low-risk experience, routine, and checklist content can continue directly to
the outline stage.

Content classified as `medium` risk or `basic_science` must pass through a
conditional `evidence_brief` node. The node produces a compact, structured
brief for later prompts:

```python
class EvidenceItem(BaseModel):
    claim: str
    summary: str
    source_title: str
    source_url: str
    source_type: str


class EvidenceBrief(BaseModel):
    items: list[EvidenceItem]
    unsupported_claims: list[str]
```

The evidence brief is internal context, not final prose. Unsupported claims
must be removed or rewritten as non-causal, non-prescriptive statements.
Sources should be authoritative public-health, academic, or professional
organizations. The implementation plan must define the retrieval provider and
source allowlist before this node is enabled.

## Memory Design

Memory retrieval occurs after domain routing and uses three levels:

1. Same subdomain for recent topic, angle, and hashtag deduplication.
2. Same domain for high- and low-performing patterns.
3. Global content for format-only patterns such as title and card structure.

Update `MemoryContext`:

```python
class MemoryContext:
    same_subdomain_recent: list[dict]
    same_domain_patterns: list[dict]
    global_format_patterns: list[dict]
    topics_to_avoid: list[str]
    angles_to_avoid: list[str]
```

Add columns and an index to structured memory. The migration script must inspect
`PRAGMA table_info(contents)` and add only missing columns:

```sql
ALTER TABLE contents ADD COLUMN domain TEXT;
ALTER TABLE contents ADD COLUMN subdomain TEXT;
ALTER TABLE contents ADD COLUMN content_intent TEXT;
ALTER TABLE contents ADD COLUMN profile_version TEXT;
ALTER TABLE contents ADD COLUMN risk_level TEXT;

CREATE INDEX idx_contents_domain_subdomain
ON contents(domain, subdomain);
```

Add the same fields to vector metadata and filter semantic retrieval by domain
and subdomain. Existing records are migrated as:

```text
domain = beauty
subdomain = skincare
profile_version = legacy-v1
risk_level = low
```

Schema migration must be idempotent and must not rely on `CREATE TABLE IF NOT
EXISTS` to add columns to an existing database.

## Compliance And Human Review

`r2_compliance` checks:

- Diagnosis, treatment, medication, test-result, and individualized
  prescription language.
- Supplement and herbal dosage or efficacy claims.
- Causal claims unsupported by the evidence brief.
- Exact outcome and time-to-effect claims.
- Fabricated expert identity or personal experience.
- Fear-based, body-shaming, or anxiety-inducing language.

The R2 result adds:

```python
block_publish: bool
matched_policy_rules: list[str]
unresolved_claims: list[str]
```

`block_publish=True` prevents assembly or persistence until the content is
revised and passes the decision loop.

The final human review payload displays:

- Domain and subdomain.
- Risk level and risk flags.
- Matched compliance rules.
- Evidence summary and source links when present.
- The complete editable publish package.

Only explicit approval permits `content_writer_node` to persist content.

## Error Handling

- Invalid explicit domain: return a validation error.
- Low-confidence inference: interrupt for domain confirmation.
- Missing or invalid profile: stop before memory retrieval.
- Evidence retrieval failure for required evidence: block the run instead of
  generating unsupported educational claims.
- Compliance block: return to the existing revision loop.
- Human rejection: retain feedback and interrupt again without writing memory.
- Database migration failure: roll back the migration and leave existing data
  unchanged.

## Implementation Phases

### Phase 1: Domain Foundation

- Add domain schemas, registry, profiles, and deterministic routing.
- Add `domain_router` and low-confidence `domain_confirmation`.
- Extend state and topic schemas.
- Add unit tests for routing and profiles.

### Phase 2: Prompt Generalization

- Introduce the centralized prompt composer.
- Move existing prompts into base prompts and domain fragments.
- Update the content nodes to consume domain context and policy.
- Remove skincare-specific role, hashtag, and storyboard assumptions.

### Phase 3: Memory Migration

- Add an explicit, idempotent SQLite migration.
- Update `ContentRecord`, write paths, and vector metadata.
- Implement tiered domain-aware retrieval.
- Backfill legacy records as beauty/skincare.

### Phase 4: Safety And Evidence

- Generalize R2 compliance and add publish blocking fields.
- Add conditional evidence brief generation for medium-risk and basic-science
  content.
- Extend human review with domain, risk, and evidence context.

### Phase 5: Output And Analytics

- Remove hardcoded content format and visual style.
- Persist profile and intent metadata.
- Add performance reporting by domain, subdomain, and content intent.

## Testing Strategy

Unit tests:

- Explicit domain overrides keyword inference.
- Keyword inference selects expected domains and subdomains.
- Low-confidence inference enters confirmation.
- Unknown explicit domains fail validation.
- Profile registration and version loading are deterministic.
- Prompt composition includes the selected profile and no stale skincare role.
- Policy checks block diagnosis, treatment, dosage, and efficacy claims.
- Memory queries apply correct domain filters.
- Migration and backfill are idempotent.

Integration tests:

- One representative request for each domain reaches final review.
- Medium-risk and basic-science requests pass through evidence brief.
- Low-risk experience content skips evidence brief.
- R2-blocked content cannot reach persistence.
- Rejected human review cannot write structured or vector memory.
- Approved edited content is persisted with correct domain metadata.

Regression tests:

- Existing skincare generation still routes to `beauty/skincare`.
- Existing review and checkpoint resume behavior remains functional.
- Legacy memory remains retrievable after migration.

## Acceptance Criteria

- The same graph supports all three domains without duplicated end-to-end
  workflows.
- Explicit domain selection takes precedence over inference.
- Every generated topic and persisted content record has domain metadata.
- Memory deduplication does not mix unrelated domains.
- Domain and safety rules are versioned and centrally testable.
- Prohibited health advice cannot reach `content_writer_node`.
- Medium-risk factual content has an evidence brief.
- Existing skincare behavior remains supported.
