# Signal-Driven Topic Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a signal-driven topic generation pipeline that replaces direct LLM topic generation with structured signals, creative briefs, diversity filtering, and traceability.

**Architecture:** Keep the existing downstream workflow stable by continuing to output `state["trends"]`, but replace `trend_scout` with focused nodes: `topic_signal_collector`, `creative_brief_builder`, `topic_ideator`, and `topic_diversity_filter`. Add persistent `trend_signals` and `topic_generation_traces` storage, plus an independent `trend_collector` for low-frequency creator-center hotspot collection.

**Tech Stack:** Python 3.12, LangGraph, Pydantic, SQLite, Playwright via the existing browser-session pattern, pytest, YAML via PyYAML.

## Global Constraints

- User-provided `--domain + --subdomain` has highest priority.
- `--subdomain` is invalid unless `--domain` is also provided.
- Invalid explicit subdomain values fail fast and list allowed subdomains.
- Interactive runs confirm subdomain when only `--domain` is supplied.
- Non-interactive runs use the profile default subdomain and record this in trace metadata.
- First version uses L1/L2 signals only: local calendar/date, Shanghai generalized weather, creator-center note inspiration/activity center cache, and historical memory.
- Creator-center hotspots are normalized into `trend_signals`; they never directly become topics.
- Every generated topic must include a valid `creative_seed`.
- Target framing ratio is `50% evergreen pain + 50% timely framing`.
- Timely framing is a hook, not the only value source.
- The LLM must not invent current events.
- Creator-center trend collection reuses `~/.xhs-agent/browser-profile` but has a separate command, run ledger, logs, and LaunchAgent from `metrics_collector`.
- Trend collector does not open note details, publish, comment, like, follow, search, or paginate aggressively.
- Weather defaults to Shanghai and uses generalized weather signals only.

---

## File Structure

Create or modify these files:

- Modify `main.py`: add `--subdomain`, validate CLI domain/subdomain combinations, and store `subdomain` in initial state.
- Modify `src/schemas/agent_state.py`: add signal, creative brief, trace, and `subdomain` state fields.
- Modify `src/schemas/topic.py`: add `CreativeSeed` and require it on `TopicItem`.
- Create `src/schemas/topic_signal.py`: Pydantic models for `TopicSignal`, `CreativeBrief`, and `TopicGenerationTrace`.
- Modify `src/domain/router.py`: accept explicit subdomain and interactive/non-interactive routing mode.
- Modify `src/nodes/node_a_00_domain_confirmation.py`: support explicit-domain subdomain confirmation.
- Create `config/trend_calendar.yml`: stable calendar signal seed data.
- Create `src/topic_signals/calendar.py`: parse active manual calendar signals.
- Create `src/topic_signals/weather.py`: produce Shanghai generalized weather signals behind a provider interface.
- Create `src/topic_signals/collector.py`: merge calendar, weather, memory, and stored trend signals.
- Create `src/topic_signals/briefs.py`: deterministic weighted creative-brief sampling.
- Create `src/topic_signals/diversity.py`: deterministic candidate filtering and diversity metrics.
- Create `src/nodes/node_a_02_topic_signal_collector.py`: LangGraph node for signal collection.
- Create `src/nodes/node_a_03_creative_brief_builder.py`: LangGraph node for brief generation.
- Create `src/nodes/node_a_04_topic_ideator.py`: LLM node that generates topics from creative briefs.
- Create `src/nodes/node_a_05_topic_diversity_filter.py`: LangGraph node that writes final `state["trends"]`.
- Modify `src/graph.py`: replace `trend_scout` graph edge with the new four-node chain.
- Create `src/prompts/base/topic_ideator.txt`: prompt for seeded topic ideation.
- Modify `src/prompts/composer.py`: register `topic_ideator`.
- Modify `memory/schema.sql`, `memory/migrations.py`, and `memory/memory_manager.py`: add trend signal and generation trace persistence.
- Create `trend_collector/`: independent package for creator-center trend collection.
- Create `tests/topic_signals/`, `tests/nodes/test_signal_topic_nodes.py`, `tests/trend_collector/`: focused tests and fixtures.
- Modify docs only after implementation behavior is verified.

---

### Task 1: CLI and Domain/Subdomain Routing

**Files:**
- Modify: `main.py`
- Modify: `src/domain/router.py`
- Modify: `src/nodes/node_a_00_domain_router.py`
- Modify: `src/nodes/node_a_00_domain_confirmation.py`
- Modify: `src/schemas/agent_state.py`
- Test: `tests/domain/test_router.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: existing `DomainProfile` and `DomainContext`.
- Produces: `resolve_domain(domain: str | None, focus_keyword: str, subdomain: str | None = None, interactive: bool = True) -> DomainContext`.
- Produces: `AgentState["subdomain"]`.

- [ ] **Step 1: Write failing router tests**

Add these tests to `tests/domain/test_router.py`:

```python
import pytest

from src.domain.router import resolve_domain


def test_explicit_domain_and_subdomain_are_used_directly():
    context = resolve_domain(
        domain="healthy_lifestyle",
        subdomain="exercise",
        focus_keyword="",
    )

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "exercise"
    assert context.classification_source == "explicit"
    assert context.classification_confidence == 1


def test_explicit_domain_rejects_invalid_subdomain():
    with pytest.raises(ValueError, match="Unsupported subdomain"):
        resolve_domain(
            domain="healthy_lifestyle",
            subdomain="skincare",
            focus_keyword="",
        )


def test_bare_subdomain_is_rejected():
    with pytest.raises(ValueError, match="subdomain requires domain"):
        resolve_domain(domain=None, subdomain="daily_habits", focus_keyword="")


def test_explicit_domain_without_subdomain_uses_default_when_non_interactive():
    context = resolve_domain(
        domain="healthy_lifestyle",
        subdomain=None,
        focus_keyword="",
        interactive=False,
    )

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "daily_habits"
    assert context.classification_source == "explicit_domain_default_subdomain"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/domain/test_router.py -q`

Expected: FAIL because `resolve_domain()` does not accept `subdomain` or `interactive`.

- [ ] **Step 3: Extend domain models and router**

Modify `src/domain/models.py`:

```python
class DomainContext(BaseModel):
    domain: DomainName
    subdomain: str
    classification_source: Literal[
        "explicit",
        "explicit_domain_default_subdomain",
        "inferred",
        "default",
    ]
    classification_confidence: float = Field(ge=0, le=1)
    profile_version: str
    risk_level: RiskLevel
```

Modify `src/domain/router.py`:

```python
def resolve_domain(
    domain: str | None,
    focus_keyword: str,
    subdomain: str | None = None,
    *,
    interactive: bool = True,
) -> DomainContext:
    keyword = (focus_keyword or "").casefold()

    if subdomain and not domain:
        raise ValueError("subdomain requires domain")

    if domain:
        profile = get_domain_profile(domain)
        if subdomain is not None:
            if subdomain not in profile.allowed_subdomains:
                allowed = ", ".join(profile.allowed_subdomains)
                raise ValueError(
                    f"Unsupported subdomain: {subdomain} for domain {domain}. "
                    f"Allowed subdomains: {allowed}"
                )
            return DomainContext(
                domain=profile.domain,
                subdomain=subdomain,
                classification_source="explicit",
                classification_confidence=1,
                profile_version=profile.version,
                risk_level=_risk_level_for_domain(profile.domain),
            )
        return DomainContext(
            domain=profile.domain,
            subdomain=profile.default_subdomain,
            classification_source="explicit_domain_default_subdomain",
            classification_confidence=0.85 if interactive else 1,
            profile_version=profile.version,
            risk_level=_risk_level_for_domain(profile.domain),
        )

    top_score = 0
    top_candidates: list[tuple[str, str]] = []
    for domain_name, profile in PROFILES.items():
        for candidate_subdomain, keywords in profile.keyword_map.items():
            score = sum(
                1 for candidate in keywords if candidate.casefold() in keyword
            )
            if score <= 0:
                continue
            if score > top_score:
                top_score = score
                top_candidates = [(domain_name, candidate_subdomain)]
            elif score == top_score:
                top_candidates.append((domain_name, candidate_subdomain))

    if not top_candidates:
        profile = get_domain_profile(DEFAULT_DOMAIN)
        return DomainContext(
            domain=profile.domain,
            subdomain=profile.default_subdomain,
            classification_source="default",
            classification_confidence=0.5,
            profile_version=profile.version,
            risk_level=_risk_level_for_domain(profile.domain),
        )

    selected_domain, selected_subdomain = top_candidates[0]
    profile = get_domain_profile(selected_domain)
    confidence = min(0.8 + 0.05 * (top_score - 1), 0.95)
    if len(top_candidates) > 1:
        confidence = 0.6

    return DomainContext(
        domain=profile.domain,
        subdomain=selected_subdomain,
        classification_source="inferred",
        classification_confidence=confidence,
        profile_version=profile.version,
        risk_level=_risk_level_for_domain(profile.domain),
    )
```

- [ ] **Step 4: Extend CLI state**

Modify `main.py` parser:

```python
parser.add_argument(
    "--subdomain",
    type=str,
    help="Explicit subdomain for the selected domain",
)
```

After `args = parser.parse_args()` add:

```python
if args.subdomain and not args.domain:
    parser.error("--subdomain requires --domain")
if args.domain and args.subdomain:
    profile = get_domain_profile(args.domain)
    if args.subdomain not in profile.allowed_subdomains:
        parser.error(
            "--subdomain must be one of "
            f"{', '.join(profile.allowed_subdomains)} for domain {args.domain}"
        )
```

In `initial_state`, add:

```python
"subdomain": args.subdomain,
```

- [ ] **Step 5: Update router and confirmation nodes**

Modify `src/nodes/node_a_00_domain_router.py`:

```python
def domain_router_node(state: AgentState) -> dict:
    context = resolve_domain(
        state.get("domain"),
        state.get("focus_keyword") or "",
        state.get("subdomain"),
        interactive=True,
    )
    profile = get_domain_profile(context.domain, version=context.profile_version)

    return {
        "domain_context": context,
        "content_policy": build_content_policy(profile, context.risk_level),
    }
```

Modify `src/nodes/node_a_00_domain_confirmation.py` so explicit-domain default
subdomain still interrupts:

```python
if (
    context.classification_confidence >= 0.65
    and context.classification_source != "explicit_domain_default_subdomain"
):
    return {}
```

Modify its selected context update:

```python
updated_context = resolve_domain(
    domain=selected_domain,
    subdomain=selected_subdomain,
    focus_keyword="",
)
```

- [ ] **Step 6: Add main CLI validation tests**

Add to `tests/test_main.py`:

```python
import pytest


def test_main_rejects_subdomain_without_domain(monkeypatch):
    import main

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--subdomain", "daily_habits"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 2


def test_main_rejects_subdomain_outside_domain(monkeypatch):
    import main

    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--domain", "healthy_lifestyle", "--subdomain", "skincare"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 2
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/domain/test_router.py tests/test_main.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add main.py src/domain/models.py src/domain/router.py src/nodes/node_a_00_domain_router.py src/nodes/node_a_00_domain_confirmation.py src/schemas/agent_state.py tests/domain/test_router.py tests/test_main.py
git commit -m "feat: support explicit subdomain routing"
```

---

### Task 2: Topic Signal and Creative Metadata Schemas

**Files:**
- Create: `src/schemas/topic_signal.py`
- Modify: `src/schemas/topic.py`
- Modify: `src/schemas/agent_state.py`
- Test: `tests/schemas/test_topic_signal.py`

**Interfaces:**
- Produces: `TopicSignal`, `CreativeBrief`, `CreativeSeed`, `TopicGenerationTrace`.
- Produces: `TopicItem.creative_seed: CreativeSeed`.

- [ ] **Step 1: Write schema tests**

Create `tests/schemas/test_topic_signal.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.schemas.topic import TopicItem
from src.schemas.topic_signal import (
    CreativeBrief,
    CreativeSeed,
    TopicGenerationTrace,
    TopicSignal,
)


def test_topic_signal_requires_valid_confidence():
    signal = TopicSignal(
        signal_id="sig_001",
        source="calendar",
        signal_type="seasonal",
        signal_name="高温天",
        normalized_signal="高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="夏季高温提升饮水相关内容的时机感。",
        domain_translation="转译为低风险饮水提醒。",
        risk_level="low",
        avoid_topics=["中暑治疗建议"],
        confidence=0.9,
        active_from=date(2026, 6, 15),
        expires_at=date(2026, 8, 31),
        collected_at=datetime(2026, 7, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )

    assert signal.signal_name == "高温天"


def test_topic_signal_rejects_invalid_confidence():
    with pytest.raises(ValueError):
        TopicSignal(
            signal_id="sig_bad",
            source="calendar",
            signal_type="seasonal",
            signal_name="bad",
            normalized_signal="bad",
            domain="healthy_lifestyle",
            subdomain="daily_habits",
            why_now="bad",
            domain_translation="bad",
            risk_level="low",
            avoid_topics=[],
            confidence=1.5,
            active_from=date(2026, 1, 1),
            expires_at=date(2026, 1, 2),
            collected_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
            metadata={},
        )


def test_topic_item_requires_creative_seed():
    seed = CreativeSeed(
        signal_type="weather",
        signal_name="高温天",
        why_now="上海高温天让低门槛补水提醒更有时机感。",
        domain_translation="转译为健康生活方式下的饮水习惯提醒。",
        evergreen_pain="忙起来容易忘记喝水。",
        timely_framing="高温天更容易注意到补水问题。",
    )

    item = TopicItem(
        topic_id="tp_001",
        topic="高温通勤日，上班族的低门槛补水提醒",
        target_group="上班族",
        core_pain="忙起来忘记喝水",
        hook="不是猛灌水，而是把提醒放进通勤和办公节奏里。",
        content_form="checklist",
        risk_note="不涉及疾病治疗或补剂建议。",
        domain="healthy_lifestyle",
        subdomain="hydration",
        content_intent="checklist",
        risk_level="low",
        risk_flags=[],
        creative_seed=seed,
    )

    assert item.creative_seed.signal_name == "高温天"


def test_generation_trace_records_diversity_metrics():
    trace = TopicGenerationTrace(
        run_id="tg_001",
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        trends_num=10,
        signals_used=["sig_001"],
        creative_briefs_sampled=["br_001"],
        generated_candidates_count=20,
        filtered_candidates_count=10,
        final_trends=["tp_001"],
        diversity_metrics={"unique_signal_count": 1},
        degraded_reason=None,
        created_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert trace.diversity_metrics["unique_signal_count"] == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/schemas/test_topic_signal.py -q`

Expected: FAIL because `src.schemas.topic_signal` and `CreativeSeed` do not exist.

- [ ] **Step 3: Create schema models**

Create `src/schemas/topic_signal.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.domain.models import ContentIntent, DomainName, RiskLevel


SignalType = Literal[
    "seasonal",
    "calendar",
    "weather",
    "creator_center",
    "historical_pattern",
    "weekday_rhythm",
    "evergreen_context",
]
SignalRiskLevel = Literal["low", "medium", "high"]


class TopicSignal(BaseModel):
    signal_id: str
    source: str
    signal_type: SignalType
    signal_name: str
    normalized_signal: str
    domain: DomainName
    subdomain: str
    why_now: str
    domain_translation: str
    risk_level: SignalRiskLevel
    avoid_topics: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    active_from: date
    expires_at: date
    collected_at: datetime
    source_url: str | None = None
    raw_title: str | None = None
    metadata: dict = Field(default_factory=dict)


class CreativeSeed(BaseModel):
    signal_type: SignalType
    signal_name: str
    why_now: str
    domain_translation: str
    evergreen_pain: str
    timely_framing: str


class CreativeBrief(BaseModel):
    brief_id: str
    signal: TopicSignal
    audience: str
    pain: str
    content_intent: ContentIntent
    contrast_frame: str
    historical_pattern_hint: str | None = None


class TopicGenerationTrace(BaseModel):
    run_id: str
    domain: DomainName
    subdomain: str
    trends_num: int = Field(gt=0)
    signals_used: list[str]
    creative_briefs_sampled: list[str]
    generated_candidates_count: int = Field(ge=0)
    filtered_candidates_count: int = Field(ge=0)
    final_trends: list[str]
    diversity_metrics: dict
    degraded_reason: str | None = None
    created_at: datetime
```

Modify `src/schemas/topic.py`:

```python
from pydantic import BaseModel

from src.domain.models import ContentIntent, DomainName, RiskLevel
from src.schemas.topic_signal import CreativeSeed


class TopicItem(BaseModel):
    topic_id: str
    topic: str
    target_group: str
    core_pain: str
    hook: str
    content_form: str
    risk_note: str
    domain: DomainName
    subdomain: str
    content_intent: ContentIntent
    risk_level: RiskLevel
    risk_flags: list[str]
    creative_seed: CreativeSeed
```

Modify `src/schemas/agent_state.py` imports and fields:

```python
from src.schemas.topic_signal import CreativeBrief, TopicGenerationTrace, TopicSignal
```

Add fields:

```python
subdomain: Optional[str]
topic_signals: List[TopicSignal]
creative_briefs: List[CreativeBrief]
topic_generation_trace: Optional[TopicGenerationTrace]
```

- [ ] **Step 4: Update legacy tests that construct TopicItem**

Search:

Run: `rg -n "TopicItem\\(" tests src`

For each test fixture constructing `TopicItem`, add a `creative_seed`:

```python
creative_seed={
    "signal_type": "evergreen_context",
    "signal_name": "测试默认信号",
    "why_now": "测试中使用稳定 evergreen 信号。",
    "domain_translation": "测试中保持原 domain/subdomain。",
    "evergreen_pain": "测试核心痛点。",
    "timely_framing": "测试时机包装。",
}
```

- [ ] **Step 5: Run schema tests**

Run: `pytest tests/schemas/test_topic_signal.py -q`

Expected: PASS.

- [ ] **Step 6: Run topic-related tests**

Run: `pytest tests/nodes tests/schemas -q`

Expected: PASS after fixture updates.

- [ ] **Step 7: Commit**

```bash
git add src/schemas tests/schemas tests/nodes
git commit -m "feat: add topic signal schemas"
```

---

### Task 3: Trend Signal and Trace Persistence

**Files:**
- Modify: `memory/schema.sql`
- Modify: `memory/migrations.py`
- Modify: `memory/memory_manager.py`
- Test: `tests/memory/test_trend_signals.py`
- Test: `tests/memory/test_migrations.py`

**Interfaces:**
- Produces: `XHSMemoryManager.upsert_trend_signals(signals: list[TopicSignal]) -> None`.
- Produces: `XHSMemoryManager.get_active_trend_signals(domain: str, subdomain: str, today: str) -> list[dict[str, object]]`.
- Produces: `XHSMemoryManager.save_topic_generation_trace(trace: TopicGenerationTrace) -> None`.

- [ ] **Step 1: Write persistence tests**

Create `tests/memory/test_trend_signals.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.schemas.topic_signal import TopicGenerationTrace, TopicSignal


TZ = ZoneInfo("Asia/Shanghai")


def _manager(tmp_path):
    manager = XHSMemoryManager(tmp_path / "memory.db")
    manager.init_db("memory/schema.sql")
    return manager


def test_upsert_and_query_active_trend_signals(tmp_path):
    manager = _manager(tmp_path)
    signal = TopicSignal(
        signal_id="sig_001",
        source="calendar",
        signal_type="seasonal",
        signal_name="高温天",
        normalized_signal="高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="夏季高温提升饮水提醒的时机感。",
        domain_translation="转译为低风险饮水习惯提醒。",
        risk_level="low",
        avoid_topics=["中暑治疗建议"],
        confidence=0.9,
        active_from=date(2026, 6, 15),
        expires_at=date(2026, 8, 31),
        collected_at=datetime(2026, 7, 7, tzinfo=TZ),
        metadata={"source_rank": 1},
    )

    manager.upsert_trend_signals([signal])

    rows = manager.get_active_trend_signals(
        domain="healthy_lifestyle",
        subdomain="hydration",
        today="2026-07-07",
    )

    assert len(rows) == 1
    assert rows[0]["signal_id"] == "sig_001"
    assert rows[0]["avoid_topics"] == ["中暑治疗建议"]


def test_active_trend_signals_exclude_expired_low_confidence_and_high_risk(tmp_path):
    manager = _manager(tmp_path)
    base = {
        "source": "creator_center",
        "signal_type": "creator_center",
        "signal_name": "活动话题",
        "normalized_signal": "活动话题",
        "domain": "healthy_lifestyle",
        "subdomain": "daily_habits",
        "why_now": "当前活动中心展示。",
        "domain_translation": "转译为生活习惯场景。",
        "avoid_topics": [],
        "active_from": date(2026, 7, 1),
        "collected_at": datetime(2026, 7, 7, tzinfo=TZ),
        "metadata": {},
    }
    manager.upsert_trend_signals([
        TopicSignal(signal_id="sig_ok", risk_level="low", confidence=0.8, expires_at=date(2026, 7, 10), **base),
        TopicSignal(signal_id="sig_old", risk_level="low", confidence=0.8, expires_at=date(2026, 7, 1), **base),
        TopicSignal(signal_id="sig_low", risk_level="low", confidence=0.5, expires_at=date(2026, 7, 10), **base),
        TopicSignal(signal_id="sig_high", risk_level="high", confidence=0.8, expires_at=date(2026, 7, 10), **base),
    ])

    rows = manager.get_active_trend_signals(
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        today="2026-07-07",
    )

    assert [row["signal_id"] for row in rows] == ["sig_ok"]


def test_save_topic_generation_trace(tmp_path):
    manager = _manager(tmp_path)
    trace = TopicGenerationTrace(
        run_id="tg_001",
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        trends_num=10,
        signals_used=["sig_001"],
        creative_briefs_sampled=["br_001"],
        generated_candidates_count=20,
        filtered_candidates_count=10,
        final_trends=["tp_001"],
        diversity_metrics={"unique_signal_count": 1},
        degraded_reason=None,
        created_at=datetime(2026, 7, 7, tzinfo=TZ),
    )

    manager.save_topic_generation_trace(trace)

    row = manager.connect().execute(
        "SELECT * FROM topic_generation_traces WHERE run_id = ?",
        ("tg_001",),
    ).fetchone()

    assert row["domain"] == "healthy_lifestyle"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/memory/test_trend_signals.py -q`

Expected: FAIL because tables and manager methods do not exist.

- [ ] **Step 3: Add schema tables**

Add to `memory/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS trend_signals (
    signal_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT,
    raw_title TEXT,
    normalized_signal TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_name TEXT NOT NULL,
    domain TEXT NOT NULL,
    subdomain TEXT NOT NULL,
    why_now TEXT NOT NULL,
    domain_translation TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    avoid_topics TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL,
    active_from TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trend_signals_scope_active
ON trend_signals(domain, subdomain, active_from, expires_at);

CREATE TABLE IF NOT EXISTS topic_generation_traces (
    run_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    subdomain TEXT NOT NULL,
    trends_num INTEGER NOT NULL,
    signals_used TEXT NOT NULL,
    creative_briefs_sampled TEXT NOT NULL,
    generated_candidates_count INTEGER NOT NULL,
    filtered_candidates_count INTEGER NOT NULL,
    final_trends TEXT NOT NULL,
    diversity_metrics TEXT NOT NULL,
    degraded_reason TEXT,
    created_at TEXT NOT NULL
);
```

- [ ] **Step 4: Add migration**

Modify `memory/migrations.py` with a function:

```python
def migrate_topic_generation_schema(connection: sqlite3.Connection) -> None:
    connection.execute("SAVEPOINT migrate_topic_generation_schema")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_signals (
                signal_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_url TEXT,
                raw_title TEXT,
                normalized_signal TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                signal_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                subdomain TEXT NOT NULL,
                why_now TEXT NOT NULL,
                domain_translation TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                avoid_topics TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL,
                active_from TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_trend_signals_scope_active
            ON trend_signals(domain, subdomain, active_from, expires_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_generation_traces (
                run_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                subdomain TEXT NOT NULL,
                trends_num INTEGER NOT NULL,
                signals_used TEXT NOT NULL,
                creative_briefs_sampled TEXT NOT NULL,
                generated_candidates_count INTEGER NOT NULL,
                filtered_candidates_count INTEGER NOT NULL,
                final_trends TEXT NOT NULL,
                diversity_metrics TEXT NOT NULL,
                degraded_reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
    except Exception:
        connection.execute("ROLLBACK TO migrate_topic_generation_schema")
        connection.execute("RELEASE migrate_topic_generation_schema")
        raise
    else:
        connection.execute("RELEASE migrate_topic_generation_schema")
```

Call it from the existing migration path used by `XHSMemoryManager.init_db()`.

- [ ] **Step 5: Add manager methods**

Modify `memory/memory_manager.py`:

```python
import json
```

Add methods:

```python
def upsert_trend_signals(self, signals: list[object]) -> None:
    with self._immediate_transaction() as conn:
        for signal in signals:
            payload = signal.model_dump() if hasattr(signal, "model_dump") else dict(signal)
            conn.execute(
                """
                INSERT INTO trend_signals (
                    signal_id, source, source_url, raw_title,
                    normalized_signal, signal_type, signal_name,
                    domain, subdomain, why_now, domain_translation,
                    risk_level, avoid_topics, confidence, active_from,
                    expires_at, collected_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    source = excluded.source,
                    source_url = excluded.source_url,
                    raw_title = excluded.raw_title,
                    normalized_signal = excluded.normalized_signal,
                    signal_type = excluded.signal_type,
                    signal_name = excluded.signal_name,
                    domain = excluded.domain,
                    subdomain = excluded.subdomain,
                    why_now = excluded.why_now,
                    domain_translation = excluded.domain_translation,
                    risk_level = excluded.risk_level,
                    avoid_topics = excluded.avoid_topics,
                    confidence = excluded.confidence,
                    active_from = excluded.active_from,
                    expires_at = excluded.expires_at,
                    collected_at = excluded.collected_at,
                    metadata = excluded.metadata
                """,
                (
                    payload["signal_id"],
                    payload["source"],
                    payload.get("source_url"),
                    payload.get("raw_title"),
                    payload["normalized_signal"],
                    payload["signal_type"],
                    payload["signal_name"],
                    payload["domain"],
                    payload["subdomain"],
                    payload["why_now"],
                    payload["domain_translation"],
                    payload["risk_level"],
                    json.dumps(payload.get("avoid_topics", []), ensure_ascii=False),
                    payload["confidence"],
                    str(payload["active_from"]),
                    str(payload["expires_at"]),
                    payload["collected_at"].isoformat()
                    if hasattr(payload["collected_at"], "isoformat")
                    else str(payload["collected_at"]),
                    json.dumps(payload.get("metadata", {}), ensure_ascii=False),
                ),
            )

def get_active_trend_signals(
    self,
    domain: str,
    subdomain: str,
    today: str,
    *,
    min_confidence: float = 0.75,
) -> list[dict[str, object]]:
    with self.connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM trend_signals
            WHERE domain = ?
              AND subdomain = ?
              AND active_from <= ?
              AND expires_at >= ?
              AND confidence >= ?
              AND risk_level != 'high'
            ORDER BY confidence DESC, collected_at DESC, signal_id
            """,
            (domain, subdomain, today, today, min_confidence),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["avoid_topics"] = json.loads(item["avoid_topics"])
        item["metadata"] = json.loads(item["metadata"])
        result.append(item)
    return result

def save_topic_generation_trace(self, trace: object) -> None:
    payload = trace.model_dump() if hasattr(trace, "model_dump") else dict(trace)
    with self._immediate_transaction() as conn:
        conn.execute(
            """
            INSERT INTO topic_generation_traces (
                run_id, domain, subdomain, trends_num, signals_used,
                creative_briefs_sampled, generated_candidates_count,
                filtered_candidates_count, final_trends, diversity_metrics,
                degraded_reason, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["domain"],
                payload["subdomain"],
                payload["trends_num"],
                json.dumps(payload["signals_used"], ensure_ascii=False),
                json.dumps(payload["creative_briefs_sampled"], ensure_ascii=False),
                payload["generated_candidates_count"],
                payload["filtered_candidates_count"],
                json.dumps(payload["final_trends"], ensure_ascii=False),
                json.dumps(payload["diversity_metrics"], ensure_ascii=False),
                payload.get("degraded_reason"),
                payload["created_at"].isoformat()
                if hasattr(payload["created_at"], "isoformat")
                else str(payload["created_at"]),
            ),
        )
```

- [ ] **Step 6: Run persistence tests**

Run: `pytest tests/memory/test_trend_signals.py tests/memory/test_migrations.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add memory/schema.sql memory/migrations.py memory/memory_manager.py tests/memory/test_trend_signals.py tests/memory/test_migrations.py
git commit -m "feat: persist topic trend signals"
```

---

### Task 4: Calendar and Shanghai Weather Signals

**Files:**
- Create: `config/trend_calendar.yml`
- Create: `src/topic_signals/__init__.py`
- Create: `src/topic_signals/calendar.py`
- Create: `src/topic_signals/weather.py`
- Test: `tests/topic_signals/test_calendar.py`
- Test: `tests/topic_signals/test_weather.py`

**Interfaces:**
- Produces: `load_calendar_signals(path: Path, today: date, domain: str, subdomain: str, collected_at: datetime) -> list[TopicSignal]`.
- Produces: `WeatherProvider.get_weather(city: str, today: date) -> WeatherSnapshot`.
- Produces: `weather_signal_from_snapshot(snapshot: WeatherSnapshot, domain: str, subdomain: str, collected_at: datetime) -> TopicSignal | None`.

- [ ] **Step 1: Write tests**

Create `tests/topic_signals/test_calendar.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.topic_signals.calendar import load_calendar_signals


def test_loads_active_calendar_signal_for_scope(tmp_path):
    path = tmp_path / "trend_calendar.yml"
    path.write_text(
        """
signals:
  - id: summer_heat
    signal_type: seasonal
    signal_name: 高温天
    active_from: 2026-06-15
    active_to: 2026-08-31
    applicable_domains:
      healthy_lifestyle:
        subdomains: [hydration, daily_habits]
        angles: [低门槛补水提醒]
    avoid: [中暑治疗建议]
""",
        encoding="utf-8",
    )

    signals = load_calendar_signals(
        path,
        today=date(2026, 7, 7),
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert len(signals) == 1
    assert signals[0].signal_id == "calendar_summer_heat"
    assert signals[0].avoid_topics == ["中暑治疗建议"]


def test_ignores_inactive_or_wrong_scope_calendar_signal(tmp_path):
    path = tmp_path / "trend_calendar.yml"
    path.write_text(
        """
signals:
  - id: winter_dry
    signal_type: seasonal
    signal_name: 冬季干燥
    active_from: 2026-12-01
    active_to: 2027-02-28
    applicable_domains:
      beauty:
        subdomains: [skincare]
        angles: [保湿护理]
    avoid: []
""",
        encoding="utf-8",
    )

    signals = load_calendar_signals(
        path,
        today=date(2026, 7, 7),
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert signals == []
```

Create `tests/topic_signals/test_weather.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.topic_signals.weather import WeatherSnapshot, weather_signal_from_snapshot


def test_high_heat_weather_creates_shanghai_signal():
    snapshot = WeatherSnapshot(
        city="上海",
        date=date(2026, 7, 7),
        weather_type="high_heat",
        temperature_high=36,
        temperature_low=28,
        humidity_bucket="humid",
        source="fake",
    )

    signal = weather_signal_from_snapshot(
        snapshot,
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert signal is not None
    assert signal.signal_type == "weather"
    assert signal.signal_name == "上海高温天"
    assert "高温" in signal.why_now


def test_normal_weather_returns_none():
    snapshot = WeatherSnapshot(
        city="上海",
        date=date(2026, 7, 7),
        weather_type="normal",
        temperature_high=28,
        temperature_low=22,
        humidity_bucket="normal",
        source="fake",
    )

    assert weather_signal_from_snapshot(
        snapshot,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    ) is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/topic_signals/test_calendar.py tests/topic_signals/test_weather.py -q`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Add calendar config**

Create `config/trend_calendar.yml`:

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
      beauty:
        subdomains: [skincare, bodycare]
        angles:
          - 高温通勤后的清爽护理
          - 出汗后的温和清洁
    avoid:
      - 中暑治疗建议
      - 电解质补充剂推荐
      - 疾病诊断

  - id: back_to_school
    signal_type: calendar
    signal_name: 开学季
    active_from: 2026-08-15
    active_to: 2026-09-15
    applicable_domains:
      healthy_lifestyle:
        subdomains: [daily_habits, nutrition_basics, sedentary_habits]
        angles:
          - 作息重建
          - 早餐准备
          - 久坐学习间隙活动
      wellness:
        subdomains: [sleep, daily_routine]
        angles:
          - 晚睡后逐步拉回节奏
          - 开学前一周的低压力准备
    avoid:
      - 治疗焦虑
      - 提高成绩承诺
      - 药物建议
```

- [ ] **Step 4: Implement calendar loader**

Create `src/topic_signals/__init__.py`:

```python
"""Signal-driven topic generation helpers."""
```

Create `src/topic_signals/calendar.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from src.schemas.topic_signal import TopicSignal


def load_calendar_signals(
    path: Path,
    *,
    today: date,
    domain: str,
    subdomain: str,
    collected_at: datetime,
) -> list[TopicSignal]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    signals = payload.get("signals") or []
    result: list[TopicSignal] = []
    for item in signals:
        active_from = date.fromisoformat(str(item["active_from"]))
        expires_at = date.fromisoformat(str(item["active_to"]))
        if not active_from <= today <= expires_at:
            continue
        domain_config = (item.get("applicable_domains") or {}).get(domain)
        if not domain_config:
            continue
        if subdomain not in list(domain_config.get("subdomains") or []):
            continue
        signal_name = str(item["signal_name"])
        angles = list(domain_config.get("angles") or [])
        result.append(
            TopicSignal(
                signal_id=f"calendar_{item['id']}",
                source="calendar",
                signal_type=item["signal_type"],
                signal_name=signal_name,
                normalized_signal=signal_name,
                domain=domain,
                subdomain=subdomain,
                why_now=f"{signal_name}处于当前内容时机窗口。",
                domain_translation="；".join(angles) if angles else signal_name,
                risk_level="low",
                avoid_topics=list(item.get("avoid") or []),
                confidence=0.9,
                active_from=active_from,
                expires_at=expires_at,
                collected_at=collected_at,
                metadata={"angles": angles},
            )
        )
    return result
```

- [ ] **Step 5: Implement weather signal model**

Create `src/topic_signals/weather.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Protocol

from src.schemas.topic_signal import TopicSignal


WeatherType = Literal["high_heat", "cold_wave", "rainy", "humid", "dry", "windy", "normal"]


@dataclass(frozen=True)
class WeatherSnapshot:
    city: str
    date: date
    weather_type: WeatherType
    temperature_high: int | None
    temperature_low: int | None
    humidity_bucket: str
    source: str


class WeatherProvider(Protocol):
    def get_weather(self, city: str, today: date) -> WeatherSnapshot:
        ...


def weather_signal_from_snapshot(
    snapshot: WeatherSnapshot,
    *,
    domain: str,
    subdomain: str,
    collected_at: datetime,
) -> TopicSignal | None:
    if snapshot.weather_type == "normal":
        return None

    name_by_type = {
        "high_heat": f"{snapshot.city}高温天",
        "cold_wave": f"{snapshot.city}降温天",
        "rainy": f"{snapshot.city}连续阴雨",
        "humid": f"{snapshot.city}潮湿天",
        "dry": f"{snapshot.city}空气干燥",
        "windy": f"{snapshot.city}大风天",
    }
    translation_by_type = {
        "high_heat": "转译为补水、低门槛活动和通勤节奏提醒。",
        "cold_wave": "转译为保暖、作息和室内活动提醒。",
        "rainy": "转译为通勤、居家活动和睡眠环境提醒。",
        "humid": "转译为潮闷环境下的生活习惯提醒。",
        "dry": "转译为饮水、皮肤护理和室内环境提醒。",
        "windy": "转译为通勤防护和低风险生活提醒。",
    }
    signal_name = name_by_type[snapshot.weather_type]
    return TopicSignal(
        signal_id=f"weather_{snapshot.city}_{snapshot.date.isoformat()}_{snapshot.weather_type}",
        source="weather",
        signal_type="weather",
        signal_name=signal_name,
        normalized_signal=signal_name,
        domain=domain,
        subdomain=subdomain,
        why_now=f"{snapshot.city}当前天气为{signal_name}，适合做泛化生活场景切入。",
        domain_translation=translation_by_type[snapshot.weather_type],
        risk_level="low",
        avoid_topics=["疾病诊断", "治疗建议", "药物建议"],
        confidence=0.8,
        active_from=snapshot.date,
        expires_at=snapshot.date + timedelta(days=2),
        collected_at=collected_at,
        metadata={
            "city": snapshot.city,
            "temperature_high": snapshot.temperature_high,
            "temperature_low": snapshot.temperature_low,
            "humidity_bucket": snapshot.humidity_bucket,
            "source": snapshot.source,
        },
    )
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/topic_signals/test_calendar.py tests/topic_signals/test_weather.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config/trend_calendar.yml src/topic_signals tests/topic_signals
git commit -m "feat: collect calendar and weather topic signals"
```

---

### Task 5: Signal Collector and Creative Brief Builder

**Files:**
- Create: `src/topic_signals/collector.py`
- Create: `src/topic_signals/briefs.py`
- Test: `tests/topic_signals/test_collector.py`
- Test: `tests/topic_signals/test_briefs.py`

**Interfaces:**
- Produces: `collect_topic_signals(...) -> tuple[list[TopicSignal], str | None]`.
- Produces: `build_creative_briefs(signals: list[TopicSignal], trends_num: int, memory_context: dict, seed: int = 0) -> list[CreativeBrief]`.

- [ ] **Step 1: Write tests**

Create `tests/topic_signals/test_collector.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.collector import collect_topic_signals


class FakeManager:
    def get_active_trend_signals(self, domain, subdomain, today):
        return [
            {
                "signal_id": "sig_db",
                "source": "creator_center",
                "signal_type": "creator_center",
                "signal_name": "活动话题",
                "normalized_signal": "活动话题",
                "domain": domain,
                "subdomain": subdomain,
                "why_now": "创作中心当前展示。",
                "domain_translation": "转译为生活习惯场景。",
                "risk_level": "low",
                "avoid_topics": [],
                "confidence": 0.8,
                "active_from": "2026-07-01",
                "expires_at": "2026-07-10",
                "collected_at": "2026-07-07T10:00:00+08:00",
                "metadata": {},
                "source_url": None,
                "raw_title": None,
            }
        ]


def test_collect_topic_signals_merges_sources(tmp_path):
    calendar = tmp_path / "trend_calendar.yml"
    calendar.write_text(
        """
signals:
  - id: summer_heat
    signal_type: seasonal
    signal_name: 高温天
    active_from: 2026-06-15
    active_to: 2026-08-31
    applicable_domains:
      healthy_lifestyle:
        subdomains: [daily_habits]
        angles: [作息安排]
    avoid: []
""",
        encoding="utf-8",
    )

    signals, degraded = collect_topic_signals(
        manager=FakeManager(),
        calendar_path=calendar,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        today=date(2026, 7, 7),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        weather_signal=None,
    )

    assert degraded is None
    assert [signal.signal_id for signal in signals] == [
        "calendar_summer_heat",
        "sig_db",
    ]
```

Create `tests/topic_signals/test_briefs.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.briefs import build_creative_briefs


def _signal(signal_id, name):
    return TopicSignal(
        signal_id=signal_id,
        source="calendar",
        signal_type="seasonal",
        signal_name=name,
        normalized_signal=name,
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        why_now=f"{name}当前有效。",
        domain_translation="转译为生活习惯场景。",
        risk_level="low",
        avoid_topics=[],
        confidence=0.9,
        active_from=date(2026, 7, 1),
        expires_at=date(2026, 7, 31),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )


def test_build_creative_briefs_generates_two_x_trends_num():
    briefs = build_creative_briefs(
        [_signal("sig_1", "高温天"), _signal("sig_2", "周一开工")],
        trends_num=5,
        memory_context={"high_performing_patterns": []},
        seed=7,
    )

    assert len(briefs) == 10
    assert len({brief.signal.signal_id for brief in briefs}) > 1
    assert len({brief.content_intent for brief in briefs}) >= 2
    assert all(brief.brief_id.startswith("br_") for brief in briefs)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/topic_signals/test_collector.py tests/topic_signals/test_briefs.py -q`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Implement signal collector**

Create `src/topic_signals/collector.py`:

```python
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.schemas.topic_signal import TopicSignal
from src.topic_signals.calendar import load_calendar_signals


def _signal_from_mapping(row: dict[str, object]) -> TopicSignal:
    payload = dict(row)
    payload["active_from"] = date.fromisoformat(str(payload["active_from"]))
    payload["expires_at"] = date.fromisoformat(str(payload["expires_at"]))
    payload["collected_at"] = datetime.fromisoformat(str(payload["collected_at"]))
    return TopicSignal(**payload)


def collect_topic_signals(
    *,
    manager,
    calendar_path: Path,
    domain: str,
    subdomain: str,
    today: date,
    collected_at: datetime,
    weather_signal: TopicSignal | None,
) -> tuple[list[TopicSignal], str | None]:
    signals: list[TopicSignal] = []
    degraded_reasons: list[str] = []

    calendar_signals = load_calendar_signals(
        calendar_path,
        today=today,
        domain=domain,
        subdomain=subdomain,
        collected_at=collected_at,
    )
    signals.extend(calendar_signals)

    if weather_signal is not None:
        signals.append(weather_signal)
    else:
        degraded_reasons.append("weather_signal_unavailable")

    stored_rows = manager.get_active_trend_signals(
        domain=domain,
        subdomain=subdomain,
        today=today.isoformat(),
    )
    signals.extend(_signal_from_mapping(row) for row in stored_rows)

    if not signals:
        degraded_reasons.append("no_active_signals")

    unique: dict[str, TopicSignal] = {}
    for signal in signals:
        unique.setdefault(signal.signal_id, signal)

    degraded_reason = ";".join(degraded_reasons) if degraded_reasons else None
    return list(unique.values()), degraded_reason
```

- [ ] **Step 4: Implement brief builder**

Create `src/topic_signals/briefs.py`:

```python
from __future__ import annotations

import random

from src.domain.models import ContentIntent
from src.schemas.topic_signal import CreativeBrief, TopicSignal


AUDIENCES = ["上班族", "学生党", "久坐人群", "健身新手", "生活习惯新手"]
PAINS = ["没时间", "懒得做", "做了没效果", "怕麻烦", "不知道对错"]
INTENTS: list[ContentIntent] = ["how_to", "checklist", "myth_busting", "experience"]
CONTRAST_FRAMES = ["低门槛", "误区纠偏", "场景清单", "3分钟行动", "反常识"]


def _historical_hint(memory_context: dict, index: int) -> str | None:
    patterns = list(memory_context.get("high_performing_patterns") or [])
    if not patterns:
        return None
    pattern = patterns[index % len(patterns)]
    return str(pattern.get("topic") or pattern.get("title") or "参考高表现结构")


def build_creative_briefs(
    signals: list[TopicSignal],
    *,
    trends_num: int,
    memory_context: dict,
    seed: int = 0,
) -> list[CreativeBrief]:
    if trends_num <= 0:
        raise ValueError("trends_num must be positive")
    if not signals:
        raise ValueError("signals must not be empty")

    rng = random.Random(seed)
    target_count = trends_num * 2
    sorted_signals = sorted(
        signals,
        key=lambda item: (-item.confidence, item.signal_id),
    )
    briefs: list[CreativeBrief] = []
    signal_counts: dict[str, int] = {}

    attempt = 0
    while len(briefs) < target_count and attempt < target_count * 20:
        attempt += 1
        signal_pool = sorted(
            sorted_signals,
            key=lambda item: (signal_counts.get(item.signal_id, 0), -item.confidence, item.signal_id),
        )
        signal = signal_pool[0]
        signal_counts[signal.signal_id] = signal_counts.get(signal.signal_id, 0) + 1
        index = len(briefs)
        briefs.append(
            CreativeBrief(
                brief_id=f"br_{index + 1:03d}",
                signal=signal,
                audience=AUDIENCES[index % len(AUDIENCES)],
                pain=PAINS[(index + rng.randrange(len(PAINS))) % len(PAINS)],
                content_intent=INTENTS[index % len(INTENTS)],
                contrast_frame=CONTRAST_FRAMES[index % len(CONTRAST_FRAMES)],
                historical_pattern_hint=_historical_hint(memory_context, index),
            )
        )

    return briefs
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/topic_signals/test_collector.py tests/topic_signals/test_briefs.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/topic_signals/collector.py src/topic_signals/briefs.py tests/topic_signals/test_collector.py tests/topic_signals/test_briefs.py
git commit -m "feat: build topic signals and creative briefs"
```

---

### Task 6: Topic Ideator Prompt and Node

**Files:**
- Create: `src/prompts/base/topic_ideator.txt`
- Modify: `src/prompts/composer.py`
- Create: `src/nodes/node_a_04_topic_ideator.py`
- Modify: `src/nodes/__init__.py`
- Test: `tests/nodes/test_topic_ideator.py`

**Interfaces:**
- Consumes: `state["creative_briefs"]`, `state["domain_context"]`, `state["content_policy"]`.
- Produces: `state["topic_candidates"]: list[TopicItem]`.

- [ ] **Step 1: Write node test**

Create `tests/nodes/test_topic_ideator.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.schemas.topic_signal import CreativeBrief, TopicSignal


class FakeModel:
    def execute(self, messages):
        return [
            {
                "topic_id": "tp_001",
                "topic": "高温通勤日，上班族的低门槛补水提醒",
                "target_group": "上班族",
                "core_pain": "忙起来忘记喝水",
                "hook": "不是猛灌水，而是把提醒放进通勤和办公节奏里。",
                "content_form": "checklist",
                "risk_note": "不涉及疾病治疗或补剂建议。",
                "domain": "healthy_lifestyle",
                "subdomain": "hydration",
                "content_intent": "checklist",
                "risk_level": "low",
                "risk_flags": [],
                "creative_seed": {
                    "signal_type": "weather",
                    "signal_name": "上海高温天",
                    "why_now": "高温天让补水提醒更有时机感。",
                    "domain_translation": "转译为健康生活方式下的饮水习惯提醒。",
                    "evergreen_pain": "忙起来容易忘记喝水。",
                    "timely_framing": "高温天更容易注意到补水问题。",
                },
            }
        ]


def _brief():
    signal = TopicSignal(
        signal_id="sig_001",
        source="weather",
        signal_type="weather",
        signal_name="上海高温天",
        normalized_signal="上海高温天",
        domain="healthy_lifestyle",
        subdomain="hydration",
        why_now="高温天让补水提醒更有时机感。",
        domain_translation="转译为健康生活方式下的饮水习惯提醒。",
        risk_level="low",
        avoid_topics=[],
        confidence=0.8,
        active_from=date(2026, 7, 7),
        expires_at=date(2026, 7, 9),
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        metadata={},
    )
    return CreativeBrief(
        brief_id="br_001",
        signal=signal,
        audience="上班族",
        pain="没时间",
        content_intent="checklist",
        contrast_frame="低门槛",
        historical_pattern_hint=None,
    )


def test_topic_ideator_generates_topic_candidates(monkeypatch):
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.get_model",
        lambda: FakeModel(),
    )
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    result = topic_ideator_node(
        {
            "creative_briefs": [_brief()],
            "domain_context": {"domain": "healthy_lifestyle", "subdomain": "hydration"},
            "content_policy": {"risk_level": "low"},
        }
    )

    assert result["topic_candidates"][0].creative_seed.signal_name == "上海高温天"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/nodes/test_topic_ideator.py -q`

Expected: FAIL because node and prompt do not exist.

- [ ] **Step 3: Add prompt**

Create `src/prompts/base/topic_ideator.txt`:

```text
【Task Identity】
Topic Ideator

【角色】
你负责把 creative_briefs 转化为小红书候选主题。你不能自由编造热点；每个主题都必须严格绑定输入 brief 中的 signal。

【输入】
- creative_briefs
- domain_context
- content_policy

【硬性规则】
- 每个输出主题必须包含 creative_seed。
- creative_seed.signal_name 必须来自对应 brief.signal.signal_name。
- creative_seed.why_now 必须基于对应 signal.why_now。
- creative_seed.domain_translation 必须基于对应 signal.domain_translation。
- 不得声称“最近很火”“大家都在讨论”，除非 signal.source 明确支持。
- 核心痛点必须是 evergreen pain，timely framing 只能作为切入口。
- 不得输出疾病诊断、治疗方案、药物建议、检查指标解读或个体化处方。

【输出格式】
仅输出严格 JSON 数组：
[
  {
    "topic_id": "tp_001",
    "topic": "string",
    "target_group": "string",
    "core_pain": "string",
    "hook": "string",
    "content_form": "string",
    "risk_note": "string",
    "domain": "string",
    "subdomain": "string",
    "content_intent": "experience | myth_busting | how_to | checklist | basic_science",
    "risk_level": "low | medium",
    "risk_flags": ["string"],
    "creative_seed": {
      "signal_type": "seasonal | calendar | weather | creator_center | historical_pattern | weekday_rhythm | evergreen_context",
      "signal_name": "string",
      "why_now": "string",
      "domain_translation": "string",
      "evergreen_pain": "string",
      "timely_framing": "string"
    }
  }
]
```

Modify `src/prompts/composer.py`:

```python
TASK_TO_BASE_PROMPT = {
    # existing entries...
    "topic_ideator": "topic_ideator.txt",
}
```

- [ ] **Step 4: Implement node**

Create `src/nodes/node_a_04_topic_ideator.py`:

```python
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate

from src.models import get_model
from src.prompts.composer import compose_prompt_for_state, serialize_prompt_value
from src.schemas import AgentState, TopicItem


def topic_ideator_node(state: AgentState) -> dict:
    creative_briefs = state.get("creative_briefs", [])
    domain_context = state.get("domain_context", {})
    content_policy = state.get("content_policy", {})

    system_prompt = compose_prompt_for_state("topic_ideator", state)
    template = PromptTemplate(
        input_variables=["creative_briefs", "domain_context", "content_policy"],
        template=(
            "输入参数如下：\n"
            "- creative_briefs:\n{creative_briefs}\n"
            "- domain_context:\n{domain_context}\n"
            "- content_policy:\n{content_policy}\n"
            "请根据 system 规则生成候选主题。"
        ),
    )
    human_prompt = template.format(
        creative_briefs=serialize_prompt_value(creative_briefs),
        domain_context=serialize_prompt_value(domain_context),
        content_policy=serialize_prompt_value(content_policy),
    )
    topic_json = get_model().execute(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
    )

    try:
        candidates = [TopicItem(**item) for item in topic_json]
    except Exception as error:
        raise RuntimeError(
            f"Process terminated due to topic ideator schema error: {error}"
        ) from error

    return {"topic_candidates": candidates}
```

Modify `src/nodes/__init__.py`:

```python
from .node_a_04_topic_ideator import topic_ideator_node
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/nodes/test_topic_ideator.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/prompts/base/topic_ideator.txt src/prompts/composer.py src/nodes/node_a_04_topic_ideator.py src/nodes/__init__.py tests/nodes/test_topic_ideator.py
git commit -m "feat: generate topics from creative briefs"
```

---

### Task 7: Topic Diversity Filter and Trace Node

**Files:**
- Create: `src/topic_signals/diversity.py`
- Create: `src/nodes/node_a_05_topic_diversity_filter.py`
- Test: `tests/topic_signals/test_diversity.py`
- Test: `tests/nodes/test_topic_diversity_filter.py`

**Interfaces:**
- Produces: `filter_topic_candidates(candidates: list[TopicItem], trends_num: int) -> tuple[list[TopicItem], dict[str, object]]`.
- Consumes: `state["topic_candidates"]`.
- Produces: `state["trends"]` and `state["topic_generation_trace"]`.

- [ ] **Step 1: Write diversity tests**

Create `tests/topic_signals/test_diversity.py`:

```python
from src.schemas.topic import TopicItem
from src.topic_signals.diversity import filter_topic_candidates


def _topic(topic_id, topic, signal_name, content_intent="checklist"):
    return TopicItem(
        topic_id=topic_id,
        topic=topic,
        target_group="上班族",
        core_pain=f"{topic}痛点",
        hook="hook",
        content_form="list",
        risk_note="low risk",
        domain="healthy_lifestyle",
        subdomain="daily_habits",
        content_intent=content_intent,
        risk_level="low",
        risk_flags=[],
        creative_seed={
            "signal_type": "calendar",
            "signal_name": signal_name,
            "why_now": "当前有效。",
            "domain_translation": "转译为生活习惯。",
            "evergreen_pain": "长期痛点。",
            "timely_framing": "当前时机。",
        },
    )


def test_filter_topic_candidates_removes_near_duplicates():
    selected, metrics = filter_topic_candidates(
        [
            _topic("tp_001", "高温天上班族补水提醒", "高温天"),
            _topic("tp_002", "高温天上班族补水清单", "高温天"),
            _topic("tp_003", "周一开工低门槛拉伸", "周一开工", "how_to"),
        ],
        trends_num=2,
    )

    assert [item.topic_id for item in selected] == ["tp_001", "tp_003"]
    assert metrics["unique_signal_count"] == 2
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/topic_signals/test_diversity.py -q`

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement diversity filter**

Create `src/topic_signals/diversity.py`:

```python
from __future__ import annotations

from difflib import SequenceMatcher

from metrics_collector.matcher import normalize_title
from src.schemas.topic import TopicItem


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def _average_pairwise_similarity(items: list[TopicItem]) -> float:
    if len(items) < 2:
        return 0.0
    scores = []
    for index, left in enumerate(items):
        for right in items[index + 1:]:
            scores.append(_similarity(left.topic, right.topic))
    return sum(scores) / len(scores)


def filter_topic_candidates(
    candidates: list[TopicItem],
    *,
    trends_num: int,
    duplicate_threshold: float = 0.72,
) -> tuple[list[TopicItem], dict[str, object]]:
    if trends_num <= 0:
        raise ValueError("trends_num must be positive")

    selected: list[TopicItem] = []
    signal_counts: dict[str, int] = {}
    for candidate in candidates:
        seed = candidate.creative_seed
        if not seed.why_now or not seed.domain_translation:
            continue
        if any(_similarity(candidate.topic, item.topic) >= duplicate_threshold for item in selected):
            continue
        if signal_counts.get(seed.signal_name, 0) >= max(1, trends_num // 3):
            continue
        selected.append(candidate)
        signal_counts[seed.signal_name] = signal_counts.get(seed.signal_name, 0) + 1
        if len(selected) == trends_num:
            break

    metrics = {
        "unique_signal_count": len({item.creative_seed.signal_name for item in selected}),
        "unique_target_group_count": len({item.target_group for item in selected}),
        "unique_core_pain_count": len({item.core_pain for item in selected}),
        "unique_content_intent_count": len({item.content_intent for item in selected}),
        "average_pairwise_title_similarity": round(_average_pairwise_similarity(selected), 4),
        "timely_signal_ratio": 1.0 if selected else 0.0,
        "evergreen_pain_ratio": 1.0 if selected else 0.0,
    }
    return selected, metrics
```

- [ ] **Step 4: Write node test**

Create `tests/nodes/test_topic_diversity_filter.py` with a fake manager that records traces:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_05_topic_diversity_filter import topic_diversity_filter_node
from tests.topic_signals.test_diversity import _topic


class FakeManager:
    def __init__(self):
        self.traces = []

    def save_topic_generation_trace(self, trace):
        self.traces.append(trace)


def test_topic_diversity_filter_writes_trends_and_trace(monkeypatch):
    manager = FakeManager()
    monkeypatch.setattr(
        "src.nodes.node_a_05_topic_diversity_filter.XHSMemoryManager",
        lambda path: manager,
    )

    result = topic_diversity_filter_node(
        {
            "topic_candidates": [
                _topic("tp_001", "高温天补水提醒", "高温天"),
                _topic("tp_002", "周一开工拉伸", "周一开工"),
            ],
            "trends_num": 2,
            "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
            "topic_signals": [],
            "creative_briefs": [],
            "topic_generation_degraded_reason": None,
            "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        }
    )

    assert len(result["trends"]) == 2
    assert manager.traces[0].domain == "healthy_lifestyle"
```

- [ ] **Step 5: Implement node**

Create `src/nodes/node_a_05_topic_diversity_filter.py`:

```python
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.prompts.composer import serialize_prompt_value
from src.schemas import AgentState
from src.schemas.topic_signal import TopicGenerationTrace
from src.topic_signals.diversity import filter_topic_candidates


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def topic_diversity_filter_node(state: AgentState) -> dict:
    candidates = state.get("topic_candidates", [])
    trends_num = state.get("trends_num") or 10
    selected, metrics = filter_topic_candidates(candidates, trends_num=trends_num)

    domain_context = state["domain_context"]
    now = state.get("_now_for_test") or datetime.now(ZoneInfo("Asia/Shanghai"))
    trace = TopicGenerationTrace(
        run_id=f"tg_{uuid4().hex[:12]}",
        domain=_get_value(domain_context, "domain"),
        subdomain=_get_value(domain_context, "subdomain"),
        trends_num=trends_num,
        signals_used=[signal.signal_id for signal in state.get("topic_signals", [])],
        creative_briefs_sampled=[brief.brief_id for brief in state.get("creative_briefs", [])],
        generated_candidates_count=len(candidates),
        filtered_candidates_count=len(selected),
        final_trends=[item.topic_id for item in selected],
        diversity_metrics=metrics,
        degraded_reason=state.get("topic_generation_degraded_reason"),
        created_at=now,
    )
    manager = XHSMemoryManager("data/xhs_memory.db")
    manager.init_db("memory/schema.sql")
    manager.save_topic_generation_trace(trace)

    return {
        "trends": selected,
        "topic_generation_trace": trace,
    }
```

Modify `src/nodes/__init__.py`:

```python
from .node_a_05_topic_diversity_filter import topic_diversity_filter_node
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/topic_signals/test_diversity.py tests/nodes/test_topic_diversity_filter.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/topic_signals/diversity.py src/nodes/node_a_05_topic_diversity_filter.py src/nodes/__init__.py tests/topic_signals/test_diversity.py tests/nodes/test_topic_diversity_filter.py
git commit -m "feat: filter topic candidates for diversity"
```

---

### Task 8: Signal Collector and Brief Builder Nodes

**Files:**
- Create: `src/nodes/node_a_02_topic_signal_collector.py`
- Create: `src/nodes/node_a_03_creative_brief_builder.py`
- Modify: `src/nodes/__init__.py`
- Test: `tests/nodes/test_topic_signal_nodes.py`

**Interfaces:**
- Consumes: `state["domain_context"]`, `state["memory_context"]`, `state["trends_num"]`.
- Produces: `state["topic_signals"]`, `state["topic_generation_degraded_reason"]`, `state["creative_briefs"]`.

- [ ] **Step 1: Write node tests**

Create `tests/nodes/test_topic_signal_nodes.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_02_topic_signal_collector import topic_signal_collector_node
from src.nodes.node_a_03_creative_brief_builder import creative_brief_builder_node


def test_topic_signal_collector_uses_calendar(monkeypatch, tmp_path):
    calendar = tmp_path / "trend_calendar.yml"
    calendar.write_text(
        """
signals:
  - id: summer_heat
    signal_type: seasonal
    signal_name: 高温天
    active_from: 2026-06-15
    active_to: 2026-08-31
    applicable_domains:
      healthy_lifestyle:
        subdomains: [daily_habits]
        angles: [作息安排]
    avoid: []
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.nodes.node_a_02_topic_signal_collector.CALENDAR_PATH",
        calendar,
    )

    result = topic_signal_collector_node(
        {
            "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
            "_today_for_test": date(2026, 7, 7),
            "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
        }
    )

    assert result["topic_signals"][0].signal_name == "高温天"


def test_creative_brief_builder_uses_topic_signals():
    result = creative_brief_builder_node(
        {
            "topic_signals": [
                {
                    "signal_id": "sig_001",
                    "source": "calendar",
                    "signal_type": "seasonal",
                    "signal_name": "高温天",
                    "normalized_signal": "高温天",
                    "domain": "healthy_lifestyle",
                    "subdomain": "daily_habits",
                    "why_now": "当前有效。",
                    "domain_translation": "转译为生活习惯。",
                    "risk_level": "low",
                    "avoid_topics": [],
                    "confidence": 0.9,
                    "active_from": "2026-07-01",
                    "expires_at": "2026-07-31",
                    "collected_at": "2026-07-07T00:00:00+08:00",
                    "metadata": {},
                }
            ],
            "trends_num": 3,
            "memory_context": {},
        }
    )

    assert len(result["creative_briefs"]) == 6
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/nodes/test_topic_signal_nodes.py -q`

Expected: FAIL because nodes do not exist.

- [ ] **Step 3: Implement signal collector node**

Create `src/nodes/node_a_02_topic_signal_collector.py`:

```python
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from memory.memory_manager import XHSMemoryManager
from src.schemas import AgentState
from src.topic_signals.collector import collect_topic_signals


CALENDAR_PATH = Path("config/trend_calendar.yml")


def _get_value(payload, key):
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


def topic_signal_collector_node(state: AgentState) -> dict:
    domain_context = state["domain_context"]
    domain = _get_value(domain_context, "domain")
    subdomain = _get_value(domain_context, "subdomain")
    now = state.get("_now_for_test") or datetime.now(ZoneInfo("Asia/Shanghai"))
    today = state.get("_today_for_test") or now.date()

    manager = XHSMemoryManager("data/xhs_memory.db")
    manager.init_db("memory/schema.sql")
    signals, degraded_reason = collect_topic_signals(
        manager=manager,
        calendar_path=CALENDAR_PATH,
        domain=domain,
        subdomain=subdomain,
        today=today,
        collected_at=now,
        weather_signal=None,
    )

    return {
        "topic_signals": signals,
        "topic_generation_degraded_reason": degraded_reason,
    }
```

- [ ] **Step 4: Implement brief builder node**

Create `src/nodes/node_a_03_creative_brief_builder.py`:

```python
from datetime import date, datetime

from src.schemas import AgentState
from src.schemas.topic_signal import TopicSignal
from src.topic_signals.briefs import build_creative_briefs


def _as_signal(value):
    if isinstance(value, TopicSignal):
        return value
    payload = dict(value)
    payload["active_from"] = date.fromisoformat(str(payload["active_from"]))
    payload["expires_at"] = date.fromisoformat(str(payload["expires_at"]))
    payload["collected_at"] = datetime.fromisoformat(str(payload["collected_at"]))
    return TopicSignal(**payload)


def creative_brief_builder_node(state: AgentState) -> dict:
    signals = [_as_signal(item) for item in state.get("topic_signals", [])]
    briefs = build_creative_briefs(
        signals,
        trends_num=state.get("trends_num") or 10,
        memory_context=state.get("memory_context") or {},
        seed=0,
    )
    return {"creative_briefs": briefs}
```

Modify `src/nodes/__init__.py`:

```python
from .node_a_02_topic_signal_collector import topic_signal_collector_node
from .node_a_03_creative_brief_builder import creative_brief_builder_node
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/nodes/test_topic_signal_nodes.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/nodes/node_a_02_topic_signal_collector.py src/nodes/node_a_03_creative_brief_builder.py src/nodes/__init__.py tests/nodes/test_topic_signal_nodes.py
git commit -m "feat: add signal and brief graph nodes"
```

---

### Task 9: Graph Integration

**Files:**
- Modify: `src/graph.py`
- Modify: `main.py`
- Test: `tests/test_graph.py` or `tests/test_nodes.py`

**Interfaces:**
- Replaces graph path `memory_retriever -> trend_scout -> angle_strategist`.
- Produces path `memory_retriever -> topic_signal_collector -> creative_brief_builder -> topic_ideator -> topic_diversity_filter -> angle_strategist`.

- [ ] **Step 1: Write graph test**

Add to `tests/test_nodes.py` or create `tests/test_graph.py`:

```python
def test_graph_contains_signal_driven_topic_nodes():
    from src.graph import create_graph

    graph = create_graph()
    nodes = set(graph.get_graph().nodes)

    assert "topic_signal_collector" in nodes
    assert "creative_brief_builder" in nodes
    assert "topic_ideator" in nodes
    assert "topic_diversity_filter" in nodes
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_graph.py tests/test_nodes.py -q`

Expected: FAIL because nodes are not in graph.

- [ ] **Step 3: Modify graph**

In `src/graph.py`, add nodes:

```python
builder.add_node("topic_signal_collector", nodes.topic_signal_collector_node)
builder.add_node("creative_brief_builder", nodes.creative_brief_builder_node)
builder.add_node("topic_ideator", nodes.topic_ideator_node)
builder.add_node("topic_diversity_filter", nodes.topic_diversity_filter_node)
```

Replace edges:

```python
builder.add_edge("memory_retriever", "topic_signal_collector")
builder.add_edge("topic_signal_collector", "creative_brief_builder")
builder.add_edge("creative_brief_builder", "topic_ideator")
builder.add_edge("topic_ideator", "topic_diversity_filter")
builder.add_edge("topic_diversity_filter", "angle_strategist")
```

Remove or bypass:

```python
builder.add_node("trend_scout", nodes.trend_scout_node)
builder.add_edge("memory_retriever", "trend_scout")
builder.add_edge("trend_scout", "angle_strategist")
```

In `main.py` initial state add:

```python
"topic_signals": [],
"creative_briefs": [],
"topic_candidates": [],
"topic_generation_trace": None,
"topic_generation_degraded_reason": None,
```

- [ ] **Step 4: Run graph tests**

Run: `pytest tests/test_graph.py tests/test_nodes.py -q`

Expected: PASS.

- [ ] **Step 5: Run node test suite**

Run: `pytest tests/nodes tests/topic_signals -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/graph.py main.py tests/test_graph.py tests/test_nodes.py
git commit -m "feat: route graph through signal topic generation"
```

---

### Task 10: Creator-Center Trend Collector Package

**Files:**
- Create: `trend_collector/__init__.py`
- Create: `trend_collector/config.py`
- Create: `trend_collector/models.py`
- Create: `trend_collector/extractor.py`
- Create: `trend_collector/coordinator.py`
- Create: `trend_collector/__main__.py`
- Test: `tests/trend_collector/test_extractor.py`
- Test: `tests/fixtures/trend_collector/creator_center_trends.html`

**Interfaces:**
- Produces: `TrendCollectorConfig.default()`.
- Produces: `extract_creator_center_signals(page, domain_profiles, collected_at) -> list[TopicSignal]`.
- Produces CLI command `python -m trend_collector collect`.

- [ ] **Step 1: Add fixture and extractor test**

Create `tests/fixtures/trend_collector/creator_center_trends.html`:

```html
<main>
  <section data-block="note-inspiration">
    <h2>笔记灵感</h2>
    <div class="trend-card">
      <span class="trend-title">高温天通勤补水</span>
    </div>
  </section>
  <section data-block="activity-center">
    <h2>活动中心</h2>
    <div class="trend-card">
      <span class="trend-title">夏日健康生活打卡</span>
    </div>
  </section>
</main>
```

Create `tests/trend_collector/test_extractor.py`:

```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trend_collector.extractor import extract_trend_titles_from_html, normalize_creator_trends


FIXTURE = Path(__file__).parents[1] / "fixtures" / "trend_collector" / "creator_center_trends.html"


def test_extract_trend_titles_from_html_fixture():
    titles = extract_trend_titles_from_html(FIXTURE.read_text(encoding="utf-8"))

    assert titles == ["高温天通勤补水", "夏日健康生活打卡"]


def test_normalize_creator_trends_to_signals():
    signals = normalize_creator_trends(
        ["高温天通勤补水"],
        domain="healthy_lifestyle",
        subdomain="hydration",
        collected_at=datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert signals[0].source == "creator_center"
    assert signals[0].signal_type == "creator_center"
    assert signals[0].risk_level == "low"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/trend_collector/test_extractor.py -q`

Expected: FAIL because package does not exist.

- [ ] **Step 3: Implement collector models and config**

Create `trend_collector/__init__.py`:

```python
"""Creator-center trend signal collection package."""
```

Create `trend_collector/config.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TrendCollectorConfig:
    db_path: Path
    schema_path: Path
    profile_dir: Path
    timezone: ZoneInfo
    creator_center_url: str
    max_items_per_block: int

    @classmethod
    def default(cls, home: Path | None = None) -> "TrendCollectorConfig":
        state_dir = (home if home is not None else Path.home()) / ".xhs-agent"
        return cls(
            db_path=Path("data/xhs_memory.db"),
            schema_path=Path("memory/schema.sql"),
            profile_dir=state_dir / "browser-profile",
            timezone=ZoneInfo("Asia/Shanghai"),
            creator_center_url="https://creator.xiaohongshu.com/",
            max_items_per_block=20,
        )
```

Create `trend_collector/models.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TrendCollectionSummary:
    status: str
    collected_signals: int = 0
    error_summary: str | None = None
```

- [ ] **Step 4: Implement extractor**

Create `trend_collector/extractor.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha1
from html.parser import HTMLParser

from src.schemas.topic_signal import TopicSignal


class _TrendTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles: list[str] = []
        self._capture = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if "trend-title" in classes:
            self._capture = True
            self._buffer = []

    def handle_data(self, data):
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._capture:
            title = "".join(self._buffer).strip()
            if title:
                self.titles.append(title)
            self._capture = False
            self._buffer = []


def extract_trend_titles_from_html(html: str) -> list[str]:
    parser = _TrendTitleParser()
    parser.feed(html)
    unique: list[str] = []
    seen = set()
    for title in parser.titles:
        if title not in seen:
            seen.add(title)
            unique.append(title)
    return unique


def normalize_creator_trends(
    titles: list[str],
    *,
    domain: str,
    subdomain: str,
    collected_at: datetime,
) -> list[TopicSignal]:
    signals: list[TopicSignal] = []
    for title in titles:
        digest = sha1(f"{domain}:{subdomain}:{title}".encode("utf-8")).hexdigest()[:12]
        signals.append(
            TopicSignal(
                signal_id=f"creator_{digest}",
                source="creator_center",
                signal_type="creator_center",
                signal_name=title,
                normalized_signal=title,
                domain=domain,
                subdomain=subdomain,
                why_now="创作中心当前展示该灵感或活动方向。",
                domain_translation="将创作中心趋势转译为当前领域下的低风险生活场景。",
                risk_level="low",
                avoid_topics=["疾病诊断", "治疗建议", "药物建议", "事故灾害蹭热点"],
                confidence=0.78,
                active_from=collected_at.date(),
                expires_at=(collected_at + timedelta(days=7)).date(),
                collected_at=collected_at,
                raw_title=title,
                metadata={},
            )
        )
    return signals
```

- [ ] **Step 5: Run extractor tests**

Run: `pytest tests/trend_collector/test_extractor.py -q`

Expected: PASS.

- [ ] **Step 6: Implement coordinator and CLI**

Create `trend_collector/coordinator.py`:

```python
from __future__ import annotations

from datetime import datetime

from memory.memory_manager import XHSMemoryManager
from metrics_collector.browser import BrowserSession
from metrics_collector.config import CollectorConfig
from trend_collector.config import TrendCollectorConfig
from trend_collector.extractor import extract_trend_titles_from_html, normalize_creator_trends
from trend_collector.models import TrendCollectionSummary


class TrendCollectionCoordinator:
    def __init__(self, config: TrendCollectorConfig | None = None):
        self.config = config or TrendCollectorConfig.default()

    def collect(self) -> TrendCollectionSummary:
        manager = XHSMemoryManager(self.config.db_path)
        manager.init_db(self.config.schema_path)
        browser_config = CollectorConfig.default()
        now = datetime.now(self.config.timezone)
        try:
            with BrowserSession(browser_config) as browser:
                browser.navigate(self.config.creator_center_url)
                html = browser.page.content()
            titles = extract_trend_titles_from_html(html)[: self.config.max_items_per_block]
            signals = normalize_creator_trends(
                titles,
                domain="healthy_lifestyle",
                subdomain="daily_habits",
                collected_at=now,
            )
            manager.upsert_trend_signals(signals)
            return TrendCollectionSummary(
                status="success",
                collected_signals=len(signals),
            )
        except Exception as error:
            return TrendCollectionSummary(
                status="failed",
                error_summary=f"{type(error).__name__}: operation failed",
            )
```

Create `trend_collector/__main__.py`:

```python
from __future__ import annotations

import argparse
from typing import Sequence

from trend_collector.coordinator import TrendCollectionCoordinator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m trend_collector",
        description="Collect creator-center trend signals.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("collect", help="run one trend signal collection")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        summary = TrendCollectionCoordinator().collect()
        print(
            f"status={summary.status} collected_signals={summary.collected_signals}"
        )
        if summary.error_summary:
            print(f"error={summary.error_summary}")
        return 0 if summary.status == "success" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run trend collector tests**

Run: `pytest tests/trend_collector -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add trend_collector tests/trend_collector tests/fixtures/trend_collector
git commit -m "feat: add creator center trend collector"
```

---

### Task 11: LaunchAgent and Documentation for Trend Collector

**Files:**
- Create: `trend_collector/launchd.py`
- Modify: `trend_collector/__main__.py`
- Create: `docs/trend-collector.md`
- Test: `tests/trend_collector/test_launchd.py`

**Interfaces:**
- Produces CLI command `python -m trend_collector install-launchagent`.
- Produces plist label `com.xhs-agent.trend-collector`.

- [ ] **Step 1: Write LaunchAgent tests**

Create `tests/trend_collector/test_launchd.py`:

```python
from pathlib import Path

from trend_collector.launchd import LABEL, build_launchagent_payload


def test_trend_collector_launchagent_payload():
    payload = build_launchagent_payload(
        python_path=Path("/usr/bin/python3"),
        repo_root=Path("/repo"),
        log_dir=Path("/Users/example/.xhs-agent/logs"),
    )

    assert LABEL == "com.xhs-agent.trend-collector"
    assert payload["ProgramArguments"] == [
        "/usr/bin/python3",
        "-m",
        "trend_collector",
        "collect",
    ]
    assert payload["StartCalendarInterval"] == {"Hour": 16, "Minute": 30}
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/trend_collector/test_launchd.py -q`

Expected: FAIL because launchd module does not exist.

- [ ] **Step 3: Implement launchd helper**

Create `trend_collector/launchd.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from metrics_collector.launchd import install_launchagent


LABEL = "com.xhs-agent.trend-collector"


def build_launchagent_payload(
    python_path: Path | str,
    repo_root: Path | str,
    log_dir: Path | str,
) -> dict[str, Any]:
    logs = Path(log_dir)
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python_path),
            "-m",
            "trend_collector",
            "collect",
        ],
        "WorkingDirectory": str(repo_root),
        "StartCalendarInterval": {"Hour": 16, "Minute": 30},
        "RunAtLoad": False,
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "trend_collector.out.log"),
        "StandardErrorPath": str(logs / "trend_collector.err.log"),
    }


def install_trend_launchagent(payload: dict[str, Any], user_home: Path | str) -> Path:
    return install_launchagent(payload, user_home)
```

- [ ] **Step 4: Add install CLI**

Modify `trend_collector/__main__.py`:

```python
import os
import shlex
import sys
from pathlib import Path

from trend_collector.launchd import build_launchagent_payload, install_trend_launchagent
```

Add parser command:

```python
subparsers.add_parser(
    "install-launchagent",
    help="install the daily trend collector LaunchAgent plist",
)
```

Add command branch:

```python
if args.command == "install-launchagent":
    user_home = Path.home()
    repo_root = Path(__file__).resolve().parent.parent
    payload = build_launchagent_payload(
        sys.executable,
        repo_root,
        user_home / ".xhs-agent" / "logs",
    )
    plist_path = install_trend_launchagent(payload, user_home)
    print(
        shlex.join(
            [
                "launchctl",
                "bootstrap",
                f"gui/{os.getuid()}",
                str(plist_path),
            ]
        )
    )
    return 0
```

- [ ] **Step 5: Add docs**

Create `docs/trend-collector.md`:

```markdown
# Trend Collector

Run commands from the repository root.

Install the LaunchAgent:

```bash
python -m trend_collector install-launchagent
```

Then run the printed `launchctl bootstrap ...` command.

The collector reuses `~/.xhs-agent/browser-profile`, writes logs to
`~/.xhs-agent/logs/trend_collector.out.log` and
`~/.xhs-agent/logs/trend_collector.err.log`, and stores normalized signals in
`data/xhs_memory.db`.

The collector reads creator-center trend surfaces only. It does not open note
details, publish, comment, like, follow, search, or paginate aggressively.
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/trend_collector/test_launchd.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add trend_collector/launchd.py trend_collector/__main__.py docs/trend-collector.md tests/trend_collector/test_launchd.py
git commit -m "feat: schedule creator trend collection"
```

---

### Task 12: End-to-End Offline Integration

**Files:**
- Test: `tests/test_signal_driven_topic_generation_integration.py`
- Modify: any files needed to make integration pass.

**Interfaces:**
- Verifies graph-level no-network signal-driven topic generation up to `state["trends"]`.

- [ ] **Step 1: Write offline integration test**

Create `tests/test_signal_driven_topic_generation_integration.py`:

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.nodes.node_a_02_topic_signal_collector import topic_signal_collector_node
from src.nodes.node_a_03_creative_brief_builder import creative_brief_builder_node
from src.nodes.node_a_04_topic_ideator import topic_ideator_node
from src.nodes.node_a_05_topic_diversity_filter import topic_diversity_filter_node


class FakeModel:
    def execute(self, messages):
        return [
            {
                "topic_id": "tp_001",
                "topic": "高温通勤日，上班族的低门槛补水提醒",
                "target_group": "上班族",
                "core_pain": "忙起来忘记喝水",
                "hook": "不是猛灌水，而是把提醒放进通勤和办公节奏里。",
                "content_form": "checklist",
                "risk_note": "不涉及疾病治疗或补剂建议。",
                "domain": "healthy_lifestyle",
                "subdomain": "daily_habits",
                "content_intent": "checklist",
                "risk_level": "low",
                "risk_flags": [],
                "creative_seed": {
                    "signal_type": "seasonal",
                    "signal_name": "高温天",
                    "why_now": "高温天让补水提醒更有时机感。",
                    "domain_translation": "转译为健康生活方式下的饮水习惯提醒。",
                    "evergreen_pain": "忙起来容易忘记喝水。",
                    "timely_framing": "高温天更容易注意到补水问题。",
                },
            }
        ]


def test_signal_driven_topic_generation_offline(monkeypatch):
    monkeypatch.setattr("src.nodes.node_a_04_topic_ideator.get_model", lambda: FakeModel())
    monkeypatch.setattr(
        "src.nodes.node_a_04_topic_ideator.compose_prompt_for_state",
        lambda task, state: "system prompt",
    )

    state = {
        "domain_context": {"domain": "healthy_lifestyle", "subdomain": "daily_habits"},
        "content_policy": {"risk_level": "low"},
        "memory_context": {},
        "trends_num": 1,
        "_today_for_test": date(2026, 7, 7),
        "_now_for_test": datetime(2026, 7, 7, tzinfo=ZoneInfo("Asia/Shanghai")),
    }

    state.update(topic_signal_collector_node(state))
    state.update(creative_brief_builder_node(state))
    state.update(topic_ideator_node(state))
    state.update(topic_diversity_filter_node(state))

    assert state["trends"][0].creative_seed.why_now
    assert state["topic_generation_trace"].filtered_candidates_count == 1
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_signal_driven_topic_generation_integration.py -q`

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_signal_driven_topic_generation_integration.py
git commit -m "test: cover signal-driven topic generation flow"
```

---

## Self-Review

Spec coverage:

- Domain/subdomain precedence is covered in Task 1.
- `creative_seed` contract is covered in Task 2 and Task 6.
- Persistent `trend_signals` and `topic_generation_trace` are covered in Task 3.
- Calendar and Shanghai weather signals are covered in Task 4.
- Signal merging and creative brief sampling are covered in Task 5.
- LLM topic generation from briefs is covered in Task 6.
- Diversity filtering and trace writing are covered in Task 7.
- Graph integration is covered in Task 9.
- Creator-center hotspot collection is covered in Task 10.
- Independent LaunchAgent and docs are covered in Task 11.
- Offline integration is covered in Task 12.

Known intentional deferrals:

- Broad hot-search crawling is excluded by spec.
- Entertainment, disaster, dispute, and medical news ingestion are excluded by spec.
- Full live creator-center extraction selectors are introduced behind fixtures first; live selector hardening should happen only after fixture tests pass and manual inspection confirms stable DOM.

Execution order:

1. Complete Tasks 1-9 to land the signal-driven generation chain without live creator-center dependency.
2. Complete Tasks 10-11 to add creator-center hotspot collection.
3. Complete Task 12 and then run the full suite before merging.
