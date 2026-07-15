# Domain Profile Expansion Implementation Plan

> 当前状态：已实施；本文保留作历史实施记录，不是自动待办。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing skincare-only Xiaohongshu agent into a shared, domain-aware workflow for beauty, wellness, and healthy-lifestyle content with isolated memory, evidence handling, and enforceable safety policies.

**Architecture:** Add a deterministic domain router and versioned profile registry before memory retrieval. Preserve the existing content-production graph, but inject serializable domain policy into every LLM prompt, partition memory by domain, conditionally collect evidence for factual candidates, and enforce policy again before persistence.

**Tech Stack:** Python 3.12, LangGraph, Pydantic 2, LangChain prompt/messages, SQLite, ChromaDB, Tavily Python SDK, pytest.

---

## File Map

New domain files:

- `src/domain/models.py`: domain, policy, and profile Pydantic contracts.
- `src/domain/profiles.py`: three versioned profile definitions and keyword maps.
- `src/domain/registry.py`: validated profile lookup.
- `src/domain/router.py`: explicit-domain precedence and keyword inference.
- `src/domain/policy_guard.py`: deterministic prohibited-claim checks.
- `src/domain/__init__.py`: public domain-layer exports.
- `src/nodes/node_a_00_domain_router.py`: graph adapter for routing.
- `src/nodes/node_a_00_domain_confirmation.py`: low-confidence interrupt.

New prompt files:

- `src/prompts/composer.py`: deterministic base-plus-fragment composition.
- `src/prompts/base/*.txt`: task-only prompt responsibilities.
- `src/prompts/fragments/safety_common.txt`: shared policy language.
- `src/prompts/fragments/{beauty,wellness,healthy_lifestyle}.txt`: domain language.

New evidence files:

- `src/evidence/models.py`: evidence item and per-topic brief contracts.
- `src/evidence/provider.py`: Tavily search adapter with an allowlist.
- `src/evidence/__init__.py`: evidence exports.
- `src/nodes/node_c_01_evidence_brief.py`: retrieves and structures evidence for selected candidates.

New migration and test files:

- `memory/migrations.py`: idempotent schema migration.
- `tests/domain/test_profiles.py`
- `tests/domain/test_router.py`
- `tests/domain/test_policy_guard.py`
- `tests/prompts/test_composer.py`
- `tests/memory/test_migrations.py`
- `tests/memory/test_domain_retrieval.py`
- `tests/evidence/test_provider.py`
- `tests/nodes/test_domain_nodes.py`
- `tests/nodes/test_evidence_brief.py`
- `tests/nodes/test_final_policy_guard.py`
- `tests/integration/test_domain_workflow.py`

Existing files modified:

- `requirements.txt`
- `main.py`
- `src/graph.py`
- `src/nodes/__init__.py`
- All active LLM nodes under `src/nodes/`
- `src/prompts/__init__.py`
- `src/schemas/agent_state.py`
- `src/schemas/topic.py`
- `src/schemas/r2_output.py`
- `memory/models.py`
- `memory/schema.sql`
- `memory/memory_manager.py`
- `memory/memory_context.py`

## Task 1: Stabilize The Test Entry Point

**Files:**

- Modify: `requirements.txt`
- Modify: `tests/test_nodes.py`
- Create: `pytest.ini`

- [ ] **Step 1: Add the test dependency and pytest configuration**

Append `pytest` to `requirements.txt` and create:

```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -ra
```

- [ ] **Step 2: Prevent network execution during test collection**

Move the final two lines in `tests/test_nodes.py` behind a script guard:

```python
if __name__ == "__main__":
    result = decision_engine_node(mock_state)
    print(result)
```

The module may retain `mock_state`, but importing it must not call an LLM.

- [ ] **Step 3: Verify collection is side-effect free**

Run:

```bash
pytest --collect-only -q
```

Expected: exit code `0`; no model request and no printed decision result.

- [ ] **Step 4: Run the existing model tests**

Run:

```bash
pytest tests/test_models.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini tests/test_nodes.py
git commit -m "test: stabilize pytest collection"
```

## Task 2: Add Domain Contracts And Profiles

**Files:**

- Create: `src/domain/models.py`
- Create: `src/domain/profiles.py`
- Create: `src/domain/registry.py`
- Create: `src/domain/__init__.py`
- Create: `tests/domain/test_profiles.py`

- [ ] **Step 1: Write failing profile tests**

```python
# tests/domain/test_profiles.py
import pytest

from src.domain import get_domain_profile


def test_all_supported_profiles_are_versioned():
    for domain in ("beauty", "wellness", "healthy_lifestyle"):
        profile = get_domain_profile(domain)
        assert profile.domain == domain
        assert profile.version
        assert profile.allowed_subdomains
        assert profile.prohibited_topics
        assert profile.evidence_domains


def test_unknown_profile_fails():
    with pytest.raises(ValueError, match="Unsupported domain"):
        get_domain_profile("medical")


def test_unknown_profile_version_fails():
    with pytest.raises(ValueError, match="Unsupported profile version"):
        get_domain_profile("beauty", version="beauty-v999")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
pytest tests/domain/test_profiles.py -q
```

Expected: collection error because `src.domain` does not exist.

- [ ] **Step 3: Implement the contracts**

```python
# src/domain/models.py
from typing import Literal

from pydantic import BaseModel, Field

DomainName = Literal["beauty", "wellness", "healthy_lifestyle"]
RiskLevel = Literal["low", "medium"]
ContentIntent = Literal[
    "experience", "myth_busting", "how_to", "checklist", "basic_science"
]


class DomainContext(BaseModel):
    domain: DomainName
    subdomain: str
    classification_source: Literal["explicit", "inferred", "default"]
    classification_confidence: float = Field(ge=0, le=1)
    profile_version: str
    risk_level: RiskLevel


class ContentPolicy(BaseModel):
    allowed_topics: list[str]
    prohibited_topics: list[str]
    prohibited_claims: list[str]
    required_disclaimers: list[str]
    risk_level: RiskLevel
    require_evidence_brief: bool
    require_human_review: bool = True


class DomainProfile(BaseModel):
    domain: DomainName
    version: str
    default_subdomain: str
    allowed_subdomains: tuple[str, ...]
    keyword_map: dict[str, tuple[str, ...]]
    prohibited_topics: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    required_disclaimers: tuple[str, ...]
    hashtag_seeds: tuple[str, ...]
    visual_guidelines: tuple[str, ...]
    evidence_domains: tuple[str, ...]
```

- [ ] **Step 4: Define the three profiles and registry**

Use these exact subdomains and evidence allowlist:

```python
# src/domain/profiles.py
from src.domain.models import DomainProfile

EVIDENCE_DOMAINS = (
    "who.int", "nih.gov", "cdc.gov", "nhs.uk", "nhc.gov.cn", "chinacdc.cn"
)

PROHIBITED_TOPICS = (
    "疾病诊断", "治疗方案", "药物建议", "检查指标解读", "个体化处方"
)

PROHIBITED_CLAIMS = (
    "保证有效", "根治", "永久改善", "立即见效", "替代治疗"
)

PROFILES = {
    "beauty": DomainProfile(
        domain="beauty",
        version="beauty-v1",
        default_subdomain="skincare",
        allowed_subdomains=("skincare", "haircare", "bodycare", "makeup_basics"),
        keyword_map={
            "skincare": ("护肤", "防晒", "保湿", "清洁", "抗老"),
            "haircare": ("护发", "头发", "发质"),
            "bodycare": ("身体护理", "身体乳"),
            "makeup_basics": ("美妆", "化妆", "底妆"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般美容与生活方式分享",),
        hashtag_seeds=("美容", "护肤", "日常护理"),
        visual_guidelines=("使用日常护理和真实生活场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
    "wellness": DomainProfile(
        domain="wellness",
        version="wellness-v1",
        default_subdomain="daily_routine",
        allowed_subdomains=("sleep", "stress_management", "daily_routine", "recovery"),
        keyword_map={
            "sleep": ("睡眠", "熬夜", "早睡", "失眠"),
            "stress_management": ("压力", "放松", "情绪"),
            "daily_routine": ("养生", "作息", "习惯"),
            "recovery": ("恢复", "休息", "疲劳"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般生活方式科普",),
        hashtag_seeds=("养生习惯", "睡眠管理", "生活方式"),
        visual_guidelines=("使用睡眠、通勤、休息和居家场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
    "healthy_lifestyle": DomainProfile(
        domain="healthy_lifestyle",
        version="healthy-lifestyle-v1",
        default_subdomain="daily_habits",
        allowed_subdomains=(
            "nutrition_basics", "exercise", "hydration",
            "sedentary_habits", "daily_habits"
        ),
        keyword_map={
            "nutrition_basics": ("饮食", "营养", "早餐", "蔬菜"),
            "exercise": ("运动", "健身", "走路", "拉伸"),
            "hydration": ("喝水", "补水", "饮水"),
            "sedentary_habits": ("久坐", "办公"),
            "daily_habits": ("健康", "生活习惯"),
        },
        prohibited_topics=PROHIBITED_TOPICS,
        prohibited_claims=PROHIBITED_CLAIMS,
        required_disclaimers=("内容仅作一般健康生活方式科普",),
        hashtag_seeds=("健康生活", "生活习惯", "健康科普"),
        visual_guidelines=("使用饮食、运动、饮水和办公生活场景",),
        evidence_domains=EVIDENCE_DOMAINS,
    ),
}
```

```python
# src/domain/registry.py
from src.domain.models import ContentPolicy, DomainProfile
from src.domain.profiles import PROFILES


def get_domain_profile(
    domain: str,
    version: str | None = None,
) -> DomainProfile:
    try:
        profile = PROFILES[domain]
    except KeyError as exc:
        raise ValueError(f"Unsupported domain: {domain}") from exc
    if version is not None and profile.version != version:
        raise ValueError(
            f"Unsupported profile version for {domain}: {version}"
        )
    return profile


def build_content_policy(
    profile: DomainProfile,
    risk_level: str = "low",
) -> ContentPolicy:
    return ContentPolicy(
        allowed_topics=list(profile.allowed_subdomains),
        prohibited_topics=list(profile.prohibited_topics),
        prohibited_claims=list(profile.prohibited_claims),
        required_disclaimers=list(profile.required_disclaimers),
        risk_level=risk_level,
        require_evidence_brief=profile.domain != "beauty",
        require_human_review=True,
    )
```

Export the models, `get_domain_profile`, and `build_content_policy` from
`src/domain/__init__.py`.

- [ ] **Step 5: Run the profile tests**

Run:

```bash
pytest tests/domain/test_profiles.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/domain tests/domain/test_profiles.py
git commit -m "feat: add versioned domain profiles"
```

## Task 3: Implement Routing And Domain Confirmation

**Files:**

- Create: `src/domain/router.py`
- Create: `src/nodes/node_a_00_domain_router.py`
- Create: `src/nodes/node_a_00_domain_confirmation.py`
- Create: `tests/domain/test_router.py`
- Create: `tests/nodes/test_domain_nodes.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `main.py`

- [ ] **Step 1: Write failing routing tests**

```python
# tests/domain/test_router.py
import pytest

from src.domain.router import resolve_domain


def test_explicit_domain_wins_over_keyword():
    result = resolve_domain("beauty", "改善睡眠")
    assert result.domain == "beauty"
    assert result.subdomain == "skincare"
    assert result.classification_source == "explicit"
    assert result.classification_confidence == 1.0


def test_keyword_infers_subdomain():
    result = resolve_domain(None, "久坐办公怎么活动")
    assert result.domain == "healthy_lifestyle"
    assert result.subdomain == "sedentary_habits"
    assert result.classification_source == "inferred"
    assert result.classification_confidence >= 0.8


def test_missing_keyword_uses_low_confidence_default():
    result = resolve_domain(None, "")
    assert result.domain == "healthy_lifestyle"
    assert result.classification_source == "default"
    assert result.classification_confidence < 0.65


def test_invalid_explicit_domain_fails():
    with pytest.raises(ValueError, match="Unsupported domain"):
        resolve_domain("medical", "睡眠")
```

- [ ] **Step 2: Run the routing tests to verify they fail**

Run:

```bash
pytest tests/domain/test_router.py -q
```

Expected: import error for `src.domain.router`.

- [ ] **Step 3: Implement deterministic routing**

```python
# src/domain/router.py
from src.domain.models import DomainContext
from src.domain.profiles import PROFILES
from src.domain.registry import get_domain_profile


def resolve_domain(domain: str | None, focus_keyword: str) -> DomainContext:
    if domain:
        profile = get_domain_profile(domain)
        return DomainContext(
            domain=profile.domain,
            subdomain=profile.default_subdomain,
            classification_source="explicit",
            classification_confidence=1.0,
            profile_version=profile.version,
            risk_level="low",
        )

    normalized = focus_keyword.strip().lower()
    matches: list[tuple[str, str, int]] = []
    for profile in PROFILES.values():
        for subdomain, keywords in profile.keyword_map.items():
            score = sum(keyword.lower() in normalized for keyword in keywords)
            if score:
                matches.append((profile.domain, subdomain, score))

    if matches:
        selected_domain, subdomain, score = max(matches, key=lambda item: item[2])
        profile = get_domain_profile(selected_domain)
        return DomainContext(
            domain=profile.domain,
            subdomain=subdomain,
            classification_source="inferred",
            classification_confidence=min(0.8 + 0.05 * (score - 1), 0.95),
            profile_version=profile.version,
            risk_level="low",
        )

    profile = get_domain_profile("healthy_lifestyle")
    return DomainContext(
        domain=profile.domain,
        subdomain=profile.default_subdomain,
        classification_source="default",
        classification_confidence=0.5,
        profile_version=profile.version,
        risk_level="low",
    )
```

- [ ] **Step 4: Add graph adapters**

`domain_router_node` calls `resolve_domain`, loads the profile, and returns
`domain_context` plus a serializable `ContentPolicy`. Set
`require_evidence_brief=True` for `wellness` and `healthy_lifestyle`; topic-level
risk still determines whether retrieval occurs.

```python
def domain_confirmation_node(state: AgentState) -> dict:
    context = state["domain_context"]
    if context.classification_confidence >= 0.65:
        return {}
    response = interrupt({
        "kind": "domain_confirmation",
        "domain_context": context.model_dump(),
        "message": "领域分类置信度较低，请确认或修改 domain/subdomain。",
    })
    profile = get_domain_profile(response["domain"])
    if response["subdomain"] not in profile.allowed_subdomains:
        raise ValueError("Unsupported subdomain for selected domain")
    return {
        "domain_context": context.model_copy(update={
            "domain": profile.domain,
            "subdomain": response["subdomain"],
            "classification_source": "explicit",
            "classification_confidence": 1.0,
            "profile_version": profile.version,
        }),
        "content_policy": build_content_policy(profile),
    }
```

- [ ] **Step 5: Insert the nodes before memory retrieval**

In `src/graph.py`, add:

```python
builder.add_node("domain_router", domain_router_node)
builder.add_node("domain_confirmation", domain_confirmation_node)
builder.add_edge("domain_router", "domain_confirmation")
builder.add_edge("domain_confirmation", "memory_retriever")
builder.set_entry_point("domain_router")
```

Remove `builder.set_entry_point("memory_retriever")`.

- [ ] **Step 6: Add CLI input and interrupt dispatch**

Add:

```python
parser.add_argument(
    "--domain",
    choices=["beauty", "wellness", "healthy_lifestyle"],
    help="Optional content domain; inferred from focus_keyword when omitted",
)
```

Set `"domain": args.domain` in `initial_state`. Change interrupt handling to
dispatch on `interrupt_event.value["kind"]`. Add `"kind": "publish_review"` to
the existing final-review interrupt payload. Domain confirmation must ask for
domain and subdomain, then resume with:

```python
Command(resume={"domain": selected_domain, "subdomain": selected_subdomain})
```

- [ ] **Step 7: Run routing and node tests**

Run:

```bash
pytest tests/domain/test_router.py tests/nodes/test_domain_nodes.py -q
```

Expected: all tests pass; low-confidence state invokes an interrupt and
high-confidence state does not.

- [ ] **Step 8: Commit**

```bash
git add src/domain/router.py src/nodes src/graph.py src/schemas/agent_state.py main.py tests/domain/test_router.py tests/nodes/test_domain_nodes.py
git commit -m "feat: route requests through domain profiles"
```

## Task 4: Extend Topic And Runtime Metadata

**Files:**

- Modify: `src/schemas/topic.py`
- Modify: `src/schemas/agent_state.py`
- Modify: `src/schemas/decision.py`
- Create: `src/domain/topic_metadata.py`
- Create: `tests/domain/test_topic_metadata.py`

- [ ] **Step 1: Write failing metadata tests**

```python
from src.domain.topic_metadata import get_topic_metadata
from src.schemas import TopicItem


def test_get_topic_metadata_uses_original_topic():
    topic = TopicItem(
        topic_id="tp_1",
        topic="久坐后的轻量活动清单",
        target_group="办公室人群",
        core_pain="久坐",
        hook="每小时动一动",
        content_form="清单",
        risk_note="不提供治疗建议",
        domain="healthy_lifestyle",
        subdomain="sedentary_habits",
        content_intent="checklist",
        risk_level="low",
        risk_flags=[],
    )
    metadata = get_topic_metadata([topic], "tp_1")
    assert metadata["content_intent"] == "checklist"
    assert metadata["subdomain"] == "sedentary_habits"
```

- [ ] **Step 2: Extend `TopicItem`**

Add:

```python
domain: str
subdomain: str
content_intent: ContentIntent
risk_level: RiskLevel
risk_flags: list[str]
```

- [ ] **Step 3: Add deterministic lookup**

```python
def get_topic_metadata(topics: list[TopicItem], topic_id: str) -> dict:
    for topic in topics:
        if topic.topic_id == topic_id:
            return {
                "domain": topic.domain,
                "subdomain": topic.subdomain,
                "content_intent": topic.content_intent,
                "risk_level": topic.risk_level,
                "risk_flags": topic.risk_flags,
            }
    raise ValueError(f"Unknown topic_id: {topic_id}")
```

Use this helper when building final `HashTagInput` and `publish_package` so LLM
outputs cannot silently invent or drop domain metadata.

- [ ] **Step 4: Extend state**

Add typed fields for `domain`, `domain_context`, `content_policy`,
`evidence_briefs`, and `final_policy_issues`. Initialize them in `main.py`.

Extend `HashTagInput` in `src/schemas/decision.py` so the selected candidate
retains deterministic identifiers and metadata:

```python
topic_id: str
angle_id: str
domain: str
subdomain: str
content_intent: ContentIntent
risk_level: RiskLevel
risk_flags: list[str]
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/domain/test_topic_metadata.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/schemas src/domain/topic_metadata.py tests/domain/test_topic_metadata.py main.py
git commit -m "feat: propagate domain metadata through state"
```

## Task 5: Introduce Prompt Composition

**Files:**

- Create: `src/prompts/composer.py`
- Create: `src/prompts/base/*.txt`
- Create: `src/prompts/fragments/*.txt`
- Modify: `src/prompts/__init__.py`
- Modify: active LLM node files in `src/nodes/`
- Create: `tests/prompts/test_composer.py`

- [ ] **Step 1: Write failing composer tests**

```python
from src.domain import get_domain_profile
from src.prompts.composer import compose_prompt


def test_compose_prompt_includes_task_and_domain_rules():
    prompt = compose_prompt("draft_writer", get_domain_profile("wellness"))
    assert "Draft Writer" in prompt
    assert "睡眠、压力、作息与恢复" in prompt
    assert "疾病诊断" in prompt


def test_healthy_lifestyle_prompt_has_no_skincare_identity():
    prompt = compose_prompt(
        "trend_scout", get_domain_profile("healthy_lifestyle")
    )
    assert "护肤趋势侦察兵" not in prompt
```

- [ ] **Step 2: Implement the composer**

```python
# src/prompts/composer.py
from pathlib import Path

from src.domain.models import DomainProfile

PROMPT_DIR = Path(__file__).parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def compose_prompt(task: str, profile: DomainProfile) -> str:
    parts = [
        _read(PROMPT_DIR / "base" / f"{task}.txt"),
        _read(PROMPT_DIR / "fragments" / "safety_common.txt"),
        _read(PROMPT_DIR / "fragments" / f"{profile.domain}.txt"),
        "本次领域配置：\n" + profile.model_dump_json(indent=2),
    ]
    return "\n\n".join(parts)
```

- [ ] **Step 3: Create exact shared fragments**

`safety_common.txt` must state that content may not provide diagnosis,
treatment, medication, test interpretation, individualized prescriptions,
supplement dosage, fabricated experience, or guaranteed outcomes.

The domain fragments must include:

```text
beauty: 日常美容、护肤、护发、身体护理与基础美妆。
wellness: 睡眠、压力、作息与恢复，只讨论一般生活方式。
healthy_lifestyle: 基础饮食、运动、饮水、久坐与日常健康习惯。
```

- [ ] **Step 4: Move task responsibilities into base prompts**

Create base files for these active tasks:

```text
trend_scout
angle_strategist
novelty_guard
virality_scorer
outline_architect
draft_writer
title_lab
title_ranker
r1_reflector
r2_compliance
decision_engine
hashtag_seo
assembler
storyboards_generator
storyboards_images_generator
```

Preserve each current output JSON contract. Remove skincare-specific identity,
examples, prop lists, and safety rules now supplied by fragments.

- [ ] **Step 5: Update every active LLM node**

Replace direct `all_prompts[...]` access with:

```python
profile = get_domain_profile(state["domain_context"].domain)
system_prompt = compose_prompt("draft_writer", profile)
```

Use the matching task name in each node. Include
`state["domain_context"].model_dump()`, `state["content_policy"].model_dump()`,
and relevant `evidence_briefs` in the human prompt.

- [ ] **Step 6: Run prompt tests and a stale-role scan**

Run:

```bash
pytest tests/prompts/test_composer.py -q
rg -n "你是.*护肤|只讨论日常护肤" src/prompts/base src/prompts/fragments
```

Expected: tests pass; `rg` returns no matches.

- [ ] **Step 7: Commit**

```bash
git add src/prompts src/nodes tests/prompts
git commit -m "refactor: compose prompts from domain profiles"
```

## Task 6: Add Idempotent Memory Migration And Persistence

**Files:**

- Create: `memory/migrations.py`
- Modify: `memory/schema.sql`
- Modify: `memory/models.py`
- Modify: `memory/memory_manager.py`
- Modify: `src/nodes/node_p_content_writer.py`
- Create: `tests/memory/test_migrations.py`

- [ ] **Step 1: Write failing migration tests**

```python
import sqlite3

from memory.migrations import migrate_contents_domain_fields


def test_migration_adds_and_backfills_domain_fields(tmp_path):
    connection = sqlite3.connect(tmp_path / "memory.db")
    connection.execute(
        "CREATE TABLE contents (content_id TEXT PRIMARY KEY, topic TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT INTO contents(content_id, topic) VALUES ('c1', '防晒')"
    )
    migrate_contents_domain_fields(connection)
    migrate_contents_domain_fields(connection)

    row = connection.execute(
        "SELECT domain, subdomain, profile_version, risk_level FROM contents"
    ).fetchone()
    assert row == ("beauty", "skincare", "legacy-v1", "low")
```

- [ ] **Step 2: Implement the migration**

```python
DOMAIN_COLUMNS = {
    "domain": "TEXT",
    "subdomain": "TEXT",
    "content_intent": "TEXT",
    "profile_version": "TEXT",
    "risk_level": "TEXT",
}


def migrate_contents_domain_fields(connection: sqlite3.Connection) -> None:
    with connection:
        existing = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(contents)"
            )
        }
        for name, sql_type in DOMAIN_COLUMNS.items():
            if name not in existing:
                connection.execute(
                    f"ALTER TABLE contents ADD COLUMN {name} {sql_type}"
                )
        connection.execute(
            """
            UPDATE contents
            SET domain = COALESCE(domain, 'beauty'),
                subdomain = COALESCE(subdomain, 'skincare'),
                profile_version = COALESCE(profile_version, 'legacy-v1'),
                risk_level = COALESCE(risk_level, 'low')
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_contents_domain_subdomain
            ON contents(domain, subdomain)
            """
        )
```

- [ ] **Step 3: Fix connection isolation**

Replace the single class-level `_shared_conn` with connections keyed by resolved
database path:

```python
_connections: dict[Path, sqlite3.Connection] = {}

def connect(self) -> sqlite3.Connection:
    key = self.db_path.resolve()
    if key not in self._connections:
        connection = sqlite3.connect(key, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
        self._connections[key] = connection
    return self._connections[key]
```

This prevents tests or multiple environments from sharing the wrong database.

- [ ] **Step 4: Update fresh schema and write path**

Add the five columns to `memory/schema.sql`, call the migration from `init_db`,
and add corresponding fields to `ContentRecord`. Extend the insert column list,
placeholders, and values in `save_generated_content`.

Build these values in `content_writer_node` from `domain_context` and the
selected topic metadata. Replace hardcoded `compliance_status` with the actual
R2 result.

- [ ] **Step 5: Run migration tests**

Run:

```bash
pytest tests/memory/test_migrations.py -q
```

Expected: migration and repeated migration both pass.

- [ ] **Step 6: Commit**

```bash
git add memory src/nodes/node_p_content_writer.py tests/memory/test_migrations.py
git commit -m "feat: persist domain metadata in memory"
```

## Task 7: Partition Structured And Vector Memory

**Files:**

- Modify: `memory/models.py`
- Modify: `memory/memory_manager.py`
- Modify: `memory/memory_context.py`
- Modify: `memory/vector_memory.py`
- Modify: `src/nodes/node_a_01_retrieve_memory.py`
- Create: `tests/memory/test_domain_retrieval.py`

- [ ] **Step 1: Write failing retrieval tests**

Seed beauty/skincare, wellness/sleep, and healthy-lifestyle/exercise records in
a temporary database. Assert:

```python
context = manager.build_memory_context(
    domain="wellness",
    subdomain="sleep",
    recent_days=14,
)
assert {item["topic"] for item in context.same_subdomain_recent} == {
    "睡前作息清单"
}
assert all(
    item["domain"] == "wellness"
    for item in context.same_domain_patterns
)
```

- [ ] **Step 2: Replace `MemoryContext` fields**

```python
@dataclass
class MemoryContext:
    same_subdomain_recent: list[dict[str, Any]]
    same_domain_patterns: list[dict[str, Any]]
    global_format_patterns: list[dict[str, Any]]
    topics_to_avoid: list[str]
    angles_to_avoid: list[str]
    recent_hashtags: list[str]
```

- [ ] **Step 3: Add query filters**

`get_recent_contents` accepts `domain` and `subdomain` and adds:

```sql
WHERE created_at >= ?
  AND domain = ?
  AND subdomain = ?
```

High/low performance queries filter `c.domain = ?`. Global format patterns may
read all domains but must return only `title`, `content_format`,
`visual_style`, and engagement metrics.

- [ ] **Step 4: Filter vector metadata**

Write `domain`, `subdomain`, `content_intent`, and `profile_version` in
`save_embedding_content`. Semantic queries use:

```python
where={"$and": [
    {"domain": {"$eq": domain}},
    {"subdomain": {"$eq": subdomain}},
]}
```

- [ ] **Step 5: Pass domain context from the retrieval node**

```python
context = state["domain_context"]
memory_context = database.build_memory_context(
    domain=context.domain,
    subdomain=context.subdomain,
    recent_days=14,
)
```

- [ ] **Step 6: Run memory tests**

Run:

```bash
pytest tests/memory/test_domain_retrieval.py -q
```

Expected: no cross-domain semantic deduplication and same-domain performance
patterns only.

- [ ] **Step 7: Commit**

```bash
git add memory src/nodes/node_a_01_retrieve_memory.py tests/memory/test_domain_retrieval.py
git commit -m "feat: partition memory by content domain"
```

## Task 8: Add Per-Topic Evidence Briefs

**Files:**

- Modify: `requirements.txt`
- Create: `.env.example`
- Create: `src/evidence/models.py`
- Create: `src/evidence/provider.py`
- Create: `src/evidence/__init__.py`
- Create: `src/nodes/node_c_01_evidence_brief.py`
- Modify: `src/nodes/__init__.py`
- Modify: `src/graph.py`
- Modify: `src/schemas/agent_state.py`
- Create: `tests/evidence/test_provider.py`
- Create: `tests/nodes/test_evidence_brief.py`

- [ ] **Step 1: Add dependency and environment contract**

Append `tavily-python` to `requirements.txt`. Add:

```dotenv
# .env.example
TAVILY_API_KEY=
```

- [ ] **Step 2: Write provider tests**

Mock `TavilyClient.search` and assert the provider sends:

```python
{
    "query": "久坐后的轻量活动 基础健康科普",
    "search_depth": "basic",
    "max_results": 5,
    "include_answer": False,
    "include_raw_content": False,
    "include_domains": list(EVIDENCE_DOMAINS),
}
```

Also assert a missing API key raises
`RuntimeError("TAVILY_API_KEY is required for evidence retrieval")`.

- [ ] **Step 3: Add evidence contracts**

```python
class EvidenceItem(BaseModel):
    claim: str
    summary: str
    source_title: str
    source_url: HttpUrl
    source_type: Literal["public_health", "academic", "professional"]


class EvidenceBrief(BaseModel):
    topic_id: str
    items: list[EvidenceItem]
    unsupported_claims: list[str]
```

State stores `evidence_briefs: dict[str, EvidenceBrief]`.

- [ ] **Step 4: Implement the Tavily provider**

```python
class TavilyEvidenceProvider:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError(
                "TAVILY_API_KEY is required for evidence retrieval"
            )
        self.client = TavilyClient(api_key=key)

    def search(self, query: str, domains: tuple[str, ...]) -> list[dict]:
        response = self.client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=False,
            include_raw_content=False,
            include_domains=list(domains),
        )
        return response.get("results", [])
```

- [ ] **Step 5: Implement the evidence node**

The node receives `scores` and indexes original `trends` by `topic_id`. For each
unique selected topic whose `risk_level == "medium"` or
`content_intent == "basic_science"`, search the profile allowlist. If no results
are returned, raise `RuntimeError` and block generation.

Pass result title, URL, and extracted content to the model with a strict prompt
that produces `EvidenceBrief`. Validate every returned URL belongs to the
profile allowlist before storing it.

- [ ] **Step 6: Insert evidence before outline generation**

```python
builder.add_node("evidence_brief", evidence_brief_node)
builder.add_edge("virality_score", "evidence_brief")
builder.add_edge("evidence_brief", "outline_architect")
```

Remove the direct `virality_score -> outline_architect` edge. The node returns
an empty map without network access when no selected topic requires evidence.

- [ ] **Step 7: Run evidence tests**

Run:

```bash
pytest tests/evidence/test_provider.py tests/nodes/test_evidence_brief.py -q
```

Expected: provider parameters, allowlist validation, no-op behavior, and
required-evidence failure all pass.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .env.example src/evidence src/nodes src/graph.py src/schemas/agent_state.py tests/evidence tests/nodes/test_evidence_brief.py
git commit -m "feat: ground factual topics with evidence briefs"
```

## Task 9: Enforce Compliance Before Persistence

**Files:**

- Create: `src/domain/policy_guard.py`
- Modify: `src/schemas/r2_output.py`
- Modify: `src/nodes/node_i_r2_compliance.py`
- Modify: `src/nodes/node_j_decision_engine.py`
- Create: `src/nodes/node_q_01_final_policy_guard.py`
- Modify: `src/nodes/node_q_human_review.py`
- Modify: `src/graph.py`
- Create: `tests/domain/test_policy_guard.py`
- Create: `tests/nodes/test_final_policy_guard.py`

- [ ] **Step 1: Write failing guard tests**

```python
from src.domain.policy_guard import find_policy_violations


def test_guard_blocks_treatment_and_guaranteed_result():
    issues = find_policy_violations(
        "这个方法可以治疗失眠，三天保证见效"
    )
    assert {issue.rule_id for issue in issues} == {
        "medical_treatment",
        "guaranteed_outcome",
    }


def test_guard_allows_general_lifestyle_language():
    assert find_policy_violations(
        "规律作息有助于形成更稳定的睡眠习惯。"
    ) == []
```

- [ ] **Step 2: Implement deterministic rules**

Define `PolicyIssue(rule_id, matched_text, message)` and compiled patterns for:

```text
medical_treatment: 治疗|治愈|根治|替代药物
medication_advice: 服用.*药|停药|处方药
test_interpretation: 指标.*说明|化验.*代表
supplement_dosage: 每天.*毫克|每日.*粒
guaranteed_outcome: 保证|一定会|百分百|永久|立即见效
```

- [ ] **Step 3: Extend R2 output**

Add to `R2ComplianceAudit`:

```python
block_publish: bool
matched_policy_rules: list[str]
unresolved_claims: list[str]
```

`r2_compliance_node` runs the deterministic guard before the LLM call, includes
its issues in the prompt, and forces `block_publish=True` while any mandatory
issue remains.

- [ ] **Step 4: Enforce the decision edge**

In `next_node`, prevent a blocked R2 result from selecting `HASHTAG_SEO`:

```python
if (
    next_node_value == "HASHTAG_SEO"
    and state.get("r2_output")
    and state["r2_output"].compliance_audit.block_publish
):
    return "R1_REFLECTOR"
```

- [ ] **Step 5: Add a final policy guard**

The human may edit `publish_package` after R2. Add
`final_policy_guard_node`, concatenate title, content, cover copy, and hashtags,
then return `final_policy_issues`.

```python
def route_after_final_guard(state: AgentState) -> str:
    return "human_review" if state["final_policy_issues"] else "content_writer"
```

Change graph edges to:

```text
human_review -> final_policy_guard
final_policy_guard -> content_writer | human_review
```

When looping back, include policy issues in the next review interrupt. This
prevents edited text from bypassing compliance.

- [ ] **Step 6: Run safety tests**

Run:

```bash
pytest tests/domain/test_policy_guard.py tests/nodes/test_final_policy_guard.py -q
```

Expected: prohibited claims cannot route to `content_writer`; clean content can.

- [ ] **Step 7: Commit**

```bash
git add src/domain src/schemas/r2_output.py src/nodes src/graph.py tests/domain/test_policy_guard.py tests/nodes/test_final_policy_guard.py
git commit -m "feat: block unsafe content before persistence"
```

## Task 10: Generalize Assembly, Review, And Visual Output

**Files:**

- Modify: `src/nodes/node_o_assembler.py`
- Modify: `src/nodes/node_o_storyboards_generator.py`
- Modify: `src/nodes/node_q_human_review.py`
- Modify: `src/nodes/node_p_content_writer.py`
- Modify: `memory/memory_manager.py`
- Modify: `main.py`
- Create: `tests/nodes/test_publish_metadata.py`
- Create: `tests/memory/test_domain_analytics.py`

- [ ] **Step 1: Write failing publish metadata test**

Build a wellness state and assert the assembled/persisted record contains:

```python
assert package["domain"] == "wellness"
assert package["subdomain"] == "sleep"
assert package["content_intent"] == "checklist"
assert package["profile_version"] == "wellness-v1"
assert package["risk_level"] == "low"
```

- [ ] **Step 2: Add deterministic package metadata**

After LLM assembly, overwrite metadata from state:

```python
publish_package_json.update({
    "domain": context.domain,
    "subdomain": topic_metadata["subdomain"],
    "content_intent": topic_metadata["content_intent"],
    "profile_version": context.profile_version,
    "risk_level": topic_metadata["risk_level"],
})
```

- [ ] **Step 3: Remove hardcoded visual persistence**

Replace:

```python
content_format="illustration"
visual_style="hexagonal_dinosaur_fish_toothless"
```

with values from `publish_package`, defaulting to profile-owned values:

```python
content_format=publish_package.get("content_format", "educational_cards")
visual_style=publish_package.get("visual_style", "domain_editorial")
```

- [ ] **Step 4: Enrich final review**

Include domain, subdomain, risk level, risk flags, matched rules, and serialized
evidence items in the `publish_review` interrupt. Preserve editable
`publish_package` and existing review rounds.

- [ ] **Step 5: Export domain metadata**

Include domain and subdomain in the output directory slug so similarly titled
posts from different domains do not collide:

```python
post_dir = f"{date_str}-{publish_package['domain']}-{title}"
```

Build the storyboard image-generation prompt with
`compose_prompt("storyboards_images_generator", profile)` using the package
domain; do not read the legacy global skincare prompt.

- [ ] **Step 6: Add domain performance analytics**

Add `get_performance_by_domain()` to `XHSMemoryManager`. It must join
`contents` to `metrics`, group by `domain`, `subdomain`, and `content_intent`,
and return content count plus average views, save rate, and engagement rate:

```sql
SELECT
    c.domain,
    c.subdomain,
    c.content_intent,
    COUNT(*) AS content_count,
    AVG(m.views) AS avg_views,
    AVG(m.save_rate) AS avg_save_rate,
    AVG(m.engagement_rate) AS avg_engagement_rate
FROM contents c
JOIN metrics m ON m.content_id = c.content_id
GROUP BY c.domain, c.subdomain, c.content_intent
ORDER BY c.domain, c.subdomain, c.content_intent
```

Test that beauty and wellness metrics produce separate rows.

- [ ] **Step 7: Run output and analytics tests**

Run:

```bash
pytest tests/nodes/test_publish_metadata.py tests/memory/test_domain_analytics.py -q
```

Expected: all persisted and exported metadata originates from state, not LLM
invention or hardcoded skincare defaults.

- [ ] **Step 8: Commit**

```bash
git add src/nodes memory/memory_manager.py main.py tests/nodes/test_publish_metadata.py tests/memory/test_domain_analytics.py
git commit -m "feat: generalize reviewed publish packages"
```

## Task 11: Add End-To-End Regression Coverage

**Files:**

- Create: `tests/integration/test_domain_workflow.py`
- Create: `docs/domain-profiles.md`

- [ ] **Step 1: Build a fully mocked graph fixture**

Mock model outputs at the model boundary and use a temporary SQLite checkpointer.
Provide one fixture each for:

```text
beauty / skincare / experience / low
wellness / sleep / basic_science / medium
healthy_lifestyle / exercise / checklist / low
```

Do not call external LLM, Tavily, Chroma, or the repository's real databases.

- [ ] **Step 2: Test the three domain paths**

Assert:

- Explicit beauty bypasses confirmation and keeps skincare behavior.
- Inferred sleep enters wellness and creates an evidence brief.
- Exercise checklist skips evidence retrieval.
- Every final package includes domain metadata.

- [ ] **Step 3: Test blocking paths**

Assert:

- Unknown explicit domain fails before memory retrieval.
- Missing required evidence stops before outline generation.
- R2 `block_publish=True` cannot reach hashtags.
- Human-edited treatment language loops back to review.
- Rejected final review does not call either memory write method.

- [ ] **Step 4: Document runtime usage**

Document:

```bash
python main.py --domain beauty --focus_keyword "夏季防晒"
python main.py --focus_keyword "睡前作息"
python main.py --domain healthy_lifestyle --focus_keyword "久坐办公"
```

Also document `TAVILY_API_KEY`, the evidence allowlist, domain confirmation,
legacy migration, and the rule that only approved clean content is persisted.

- [ ] **Step 5: Run the complete suite**

Run:

```bash
pytest -q
```

Expected: all tests pass with no network request.

- [ ] **Step 6: Run static verification**

Run:

```bash
python -m compileall src memory main.py
git diff --check
rg -n "content_format=\"illustration\"|hexagonal_dinosaur|你是.*护肤" src
```

Expected: compile succeeds; diff check is empty; stale hardcoded scan returns no
matches.

- [ ] **Step 7: Commit**

```bash
git add tests docs/domain-profiles.md
git commit -m "test: cover domain-aware content workflows"
```

## Final Verification

- [ ] Run `pytest -q`.
- [ ] Run `python -m compileall src memory main.py`.
- [ ] Run `git diff --check`.
- [ ] Confirm `git status --short` contains no generated databases, checkpoints,
  Chroma files, or output artifacts staged for commit.
- [ ] Run one mocked checkpoint-resume test through final approval.
- [ ] Confirm the existing `checkpoints.sqlite` user change remains untouched.
