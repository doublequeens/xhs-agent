# Xiaohongshu Metrics Collector Implementation Plan

> 当前状态：已实施；本文保留作历史实施记录，不是自动待办。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a once-daily, low-access Playwright collector that binds Xiaohongshu note IDs, imports the official creator-center workbook, and stores both latest and historical metrics.

**Architecture:** A new top-level `metrics_collector` package owns browser automation, workbook parsing, matching, coordination, and CLI commands. Existing `memory` modules remain the persistence boundary and gain idempotent migrations, batch metric writes, daily history, and collection-run tracking. Browser behavior is tested only with local fixtures and fakes; real Xiaohongshu access is limited to explicit `auth` and `collect` commands.

**Tech Stack:** Python 3.12, SQLite, Playwright sync API, openpyxl, pytest, macOS launchd.

---

## File Structure

Create or modify these files:

```text
requirements.txt
memory/schema.sql
memory/migrations.py
memory/models.py
memory/memory_manager.py
metrics_collector/__init__.py
metrics_collector/__main__.py
metrics_collector/browser.py
metrics_collector/config.py
metrics_collector/coordinator.py
metrics_collector/exporter.py
metrics_collector/identity.py
metrics_collector/launchd.py
metrics_collector/matcher.py
metrics_collector/models.py
metrics_collector/workbook.py
tests/fixtures/metrics_collector/data_analysis.html
tests/fixtures/metrics_collector/note_manager_page_1.html
tests/fixtures/metrics_collector/note_manager_page_2.html
tests/metrics_collector/test_browser.py
tests/metrics_collector/test_coordinator.py
tests/metrics_collector/test_exporter.py
tests/metrics_collector/test_identity.py
tests/metrics_collector/test_launchd.py
tests/metrics_collector/test_matcher.py
tests/metrics_collector/test_workbook.py
tests/memory/test_metrics_history.py
tests/memory/test_migrations.py
docs/metrics-collector.md
```

Responsibilities:

- `config.py`: immutable paths, URLs, thresholds, timezone, and access limits.
- `models.py`: collector-facing typed records and run results.
- `browser.py`: headed persistent browser lifecycle and auth/risk checks.
- `identity.py`: note-list-only extraction and binding candidates.
- `exporter.py`: one creator-center workbook download.
- `workbook.py`: strict workbook parsing and normalization.
- `matcher.py`: deterministic exact/fuzzy/time-assisted matching.
- `coordinator.py`: daily gate, sequencing, stop conditions, and cleanup.
- `launchd.py`: LaunchAgent plist generation and installation.
- `memory/*`: migrations and transactional persistence only.

### Task 1: Package Skeleton, Dependencies, Configuration, And Types

**Files:**
- Modify: `requirements.txt`
- Create: `metrics_collector/__init__.py`
- Create: `metrics_collector/config.py`
- Create: `metrics_collector/models.py`
- Test: `tests/metrics_collector/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

```python
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from metrics_collector.config import CollectorConfig


def test_default_config_uses_safe_access_limits(tmp_path):
    config = CollectorConfig.default(home=tmp_path)

    assert config.profile_dir == tmp_path / ".xhs-agent" / "browser-profile"
    assert config.max_note_manager_pages == 3
    assert config.headless is False
    assert config.schedule_time == time(22, 0)
    assert config.timezone == ZoneInfo("Asia/Shanghai")
    assert config.data_analysis_url.endswith("/statistics/data-analysis")
    assert config.note_manager_url.endswith("/new/note-manager")


def test_stable_note_url_contains_only_post_id():
    config = CollectorConfig.default(home=Path("/tmp/home"))
    assert config.note_url("6a49ebd3000000001503fdd0") == (
        "https://www.xiaohongshu.com/explore/6a49ebd3000000001503fdd0"
    )
```

- [ ] **Step 2: Run tests and verify the missing-package failure**

Run:

```bash
pytest tests/metrics_collector/test_config.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'metrics_collector'`.

- [ ] **Step 3: Add dependencies and minimal package types**

Append exact dependencies to `requirements.txt`:

```text
openpyxl
playwright
```

Implement `CollectorConfig` as a frozen dataclass with these defaults:

```python
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CollectorConfig:
    db_path: Path
    schema_path: Path
    profile_dir: Path
    download_dir: Path
    diagnostics_dir: Path
    timezone: ZoneInfo
    schedule_time: time
    max_note_manager_pages: int
    diagnostic_retention_days: int
    headless: bool
    browser_channel: str
    title_similarity_threshold: float
    combined_score_threshold: float
    winner_margin: float
    data_analysis_url: str
    note_manager_url: str

    @classmethod
    def default(cls, home: Path | None = None) -> "CollectorConfig":
        user_home = home or Path.home()
        state_dir = user_home / ".xhs-agent"
        return cls(
            db_path=Path("data/xhs_memory.db"),
            schema_path=Path("memory/schema.sql"),
            profile_dir=state_dir / "browser-profile",
            download_dir=state_dir / "downloads",
            diagnostics_dir=state_dir / "diagnostics",
            timezone=ZoneInfo("Asia/Shanghai"),
            schedule_time=time(22, 0),
            max_note_manager_pages=3,
            diagnostic_retention_days=7,
            headless=False,
            browser_channel="chrome",
            title_similarity_threshold=0.82,
            combined_score_threshold=0.80,
            winner_margin=0.05,
            data_analysis_url="https://creator.xiaohongshu.com/statistics/data-analysis",
            note_manager_url="https://creator.xiaohongshu.com/new/note-manager",
        )

    def note_url(self, post_id: str) -> str:
        return f"https://www.xiaohongshu.com/explore/{post_id}"
```

Add collector dataclasses in `metrics_collector/models.py`:

```python
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class ContentCandidate:
    content_id: str
    title: str
    reference_time: datetime
    post_id: str | None = None


@dataclass(frozen=True)
class NoteIdentity:
    post_id: str
    title: str
    published_at: datetime


@dataclass(frozen=True)
class ExportedMetrics:
    title: str
    published_at: datetime
    impressions: int | None
    views: int | None
    cover_click_rate: float | None
    likes: int | None
    comments: int | None
    saves: int | None
    followers_gained: int | None
    shares: int | None
    avg_watch_time_seconds: int | None
    danmaku_count: int | None


@dataclass(frozen=True)
class MatchResult:
    status: Literal["matched", "ambiguous", "unmatched"]
    content_id: str | None
    score: float | None
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True)
class CollectionSummary:
    scheduled_date: date
    execution_date: date
    status: str
    exported_rows: int = 0
    updated_rows: int = 0
    skipped_rows: int = 0
    ambiguous_rows: int = 0
    matched_post_ids: int = 0
    error_summary: str | None = None
```

- [ ] **Step 4: Run configuration tests**

Run:

```bash
pytest tests/metrics_collector/test_config.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt metrics_collector tests/metrics_collector/test_config.py
git commit -m "feat: scaffold metrics collector"
```

### Task 2: Idempotent Metrics Schema Migration

**Files:**
- Modify: `memory/schema.sql`
- Modify: `memory/migrations.py`
- Modify: `memory/memory_manager.py:11-12,127-149`
- Modify: `tests/memory/test_migrations.py`

- [ ] **Step 1: Write failing migration tests**

Add tests that create the current legacy `metrics` table, run migration twice, and assert:

```python
assert {
    "impressions",
    "cover_click_rate",
    "avg_watch_time_seconds",
    "danmaku_count",
} <= set(_table_columns(connection, "metrics"))
assert _table_exists(connection, "metrics_history")
assert _table_exists(connection, "metrics_collection_runs")
assert _primary_key_columns(connection, "metrics_history") == [
    "content_id",
    "collected_date",
]
```

Update helper signatures to accept a table name:

```python
def _table_columns(connection: sqlite3.Connection, table_name: str = "contents") -> list[str]:
    return [row[1] for row in connection.execute(f"PRAGMA table_info({table_name})")]


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _primary_key_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in sorted(rows, key=lambda row: row[5]) if row[5]]
```

- [ ] **Step 2: Run the migration tests and verify failure**

Run:

```bash
pytest tests/memory/test_migrations.py -v
```

Expected: failures report missing metric columns and tables.

- [ ] **Step 3: Implement schema and migration**

Add nullable columns to `metrics` in `memory/schema.sql`:

```sql
impressions INTEGER,
cover_click_rate REAL,
avg_watch_time_seconds INTEGER,
danmaku_count INTEGER,
```

Add `metrics_history` with a composite primary key and the full current metric/rate fields. Add `metrics_collection_runs` with:

```sql
scheduled_date TEXT PRIMARY KEY,
execution_date TEXT NOT NULL,
status TEXT NOT NULL,
started_at TEXT NOT NULL,
completed_at TEXT,
exported_rows INTEGER NOT NULL DEFAULT 0,
updated_rows INTEGER NOT NULL DEFAULT 0,
skipped_rows INTEGER NOT NULL DEFAULT 0,
ambiguous_rows INTEGER NOT NULL DEFAULT 0,
matched_post_ids INTEGER NOT NULL DEFAULT 0,
error_summary TEXT
```

Implement `migrate_metrics_collection_schema(connection)` in `memory/migrations.py` using a savepoint. It must:

1. Add each missing metrics column with `ALTER TABLE`.
2. Create `metrics_history`.
3. Create `metrics_collection_runs`.
4. Be safe to execute repeatedly.
5. Roll back all migration changes when any statement fails.

Call it from `XHSMemoryManager.init_db()` immediately after `migrate_contents_domain_fields(conn)`.

- [ ] **Step 4: Run migration and existing memory tests**

Run:

```bash
pytest tests/memory/test_migrations.py tests/memory/test_memory_manager.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add memory/schema.sql memory/migrations.py memory/memory_manager.py tests/memory/test_migrations.py
git commit -m "feat: migrate metrics collection schema"
```

### Task 3: Transactional Latest Metrics, History, Identity, And Run Ledger

**Files:**
- Modify: `memory/models.py:55-73`
- Modify: `memory/memory_manager.py:459-570`
- Create: `tests/memory/test_metrics_history.py`

- [ ] **Step 1: Write failing persistence tests**

Cover these exact behaviors:

```python
def test_batch_update_writes_latest_and_daily_history(manager, published_content):
    manager.update_metrics_batch(
        [
            MetricsRecord(
                content_id=published_content,
                views=100,
                likes=10,
                saves=5,
                comments=2,
                shares=1,
                followers_gained=1,
                impressions=1000,
                cover_click_rate=0.1,
                avg_watch_time_seconds=17,
                danmaku_count=0,
            )
        ],
        collected_date="2026-07-05",
        source="creator_center_note_export_v1",
    )
    latest = manager.get_metrics(published_content)
    history = manager.get_metrics_history(published_content)
    assert latest["impressions"] == 1000
    assert history[0]["collected_date"] == "2026-07-05"


def test_unavailable_latest_field_preserves_previous_value(manager, published_content):
    manager.update_metrics(published_content, 100, 10, 5, 2, impressions=1000)
    manager.update_metrics(published_content, 110, 11, 6, 3, impressions=None)
    assert manager.get_metrics(published_content)["impressions"] == 1000


def test_same_day_history_is_upserted(manager, published_content):
    first = MetricsRecord(content_id=published_content, views=100, likes=1, saves=1, comments=1)
    second = MetricsRecord(content_id=published_content, views=120, likes=2, saves=1, comments=1)
    manager.update_metrics_batch([first], "2026-07-05", "creator_center_note_export_v1")
    manager.update_metrics_batch([second], "2026-07-05", "creator_center_note_export_v1")
    assert len(manager.get_metrics_history(published_content)) == 1
    assert manager.get_metrics_history(published_content)[0]["views"] == 120


def test_batch_failure_rolls_back_every_content(manager, two_published_contents, monkeypatch):
    original = manager._insert_metrics_history
    call_count = 0

    def fail_on_second_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("history write failed")
        return original(*args, **kwargs)

    records = [
        MetricsRecord(content_id=two_published_contents[0], views=100, likes=1, saves=1, comments=1),
        MetricsRecord(content_id=two_published_contents[1], views=200, likes=2, saves=2, comments=2),
    ]
    monkeypatch.setattr(manager, "_insert_metrics_history", fail_on_second_call)
    with pytest.raises(RuntimeError, match="history write failed"):
        manager.update_metrics_batch(records, "2026-07-05", "creator_center_note_export_v1")
    assert manager.get_metrics(two_published_contents[0]) is None
    assert manager.get_metrics(two_published_contents[1]) is None
```

Also test:

- `bind_post_identity()` writes `post_id`, generated URL, actual `published_at`, and `status="published"` in one transaction.
- `start_collection_run()` and `finish_collection_run()` persist sanitized counters.
- `has_completed_execution_date()` treats `success` and `partial_success` as completed.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
pytest tests/memory/test_metrics_history.py -v
```

Expected: missing methods and fields fail.

- [ ] **Step 3: Implement persistence methods**

Allow `None` for every raw count imported from the workbook while retaining the existing zero defaults for backward compatibility. Extend `MetricsRecord` with:

```python
views: Optional[int] = 0
likes: Optional[int] = 0
saves: Optional[int] = 0
comments: Optional[int] = 0
shares: Optional[int] = 0
followers_gained: Optional[int] = 0
impressions: Optional[int] = None
cover_click_rate: Optional[float] = None
avg_watch_time_seconds: Optional[int] = None
danmaku_count: Optional[int] = None
```

Extend `update_metrics()` with the same optional keyword arguments while preserving all existing positional arguments. Replace `INSERT OR REPLACE` with a SQLite `ON CONFLICT(content_id) DO UPDATE` upsert; each nullable raw field must use `COALESCE(excluded.field, metrics.field)`.

Add:

```python
def update_metrics_batch(
    self,
    records: list[MetricsRecord],
    collected_date: str,
    source: str,
) -> list[MetricsRecord]:
```

This method must use one `with self.connect() as conn:` transaction for all current and history writes. Extract rate calculation and SQL helpers that accept the existing connection so nested commits cannot occur.

Add:

```python
def bind_post_identity(
    self,
    content_id: str,
    post_id: str,
    url: str,
    published_at: str,
) -> None:

def get_unbound_published_candidates(self) -> list[dict[str, object]]:

def start_collection_run(self, scheduled_date: str, execution_date: str) -> None:

def finish_collection_run(self, summary: dict[str, object]) -> None:

def has_completed_execution_date(self, execution_date: str) -> bool:

def get_metrics(self, content_id: str) -> dict[str, object] | None:

def get_metrics_history(self, content_id: str) -> list[dict[str, object]]:
```

Do not import collector models into `memory`; accept primitive values or a plain dictionary for run summaries to keep dependency direction one-way.

- [ ] **Step 4: Run all memory tests**

Run:

```bash
pytest tests/memory -v
```

Expected: all tests pass, including existing `update_metrics()` callers.

- [ ] **Step 5: Commit**

```bash
git add memory/models.py memory/memory_manager.py tests/memory/test_metrics_history.py
git commit -m "feat: persist metric history and collection runs"
```

### Task 4: Deterministic Title And Time Matcher

**Files:**
- Create: `metrics_collector/matcher.py`
- Create: `tests/metrics_collector/test_matcher.py`

- [ ] **Step 1: Write failing matcher tests**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from metrics_collector.matcher import ContentMatcher, normalize_title
from metrics_collector.models import ContentCandidate


TZ = ZoneInfo("Asia/Shanghai")


def test_normalize_title_removes_non_semantic_differences():
    assert normalize_title("油皮晨间别过度清洁！ 要做减法!") == normalize_title(
        "油皮晨间别过度清洁 要做减法"
    )


def test_unique_exact_title_matches():
    matcher = ContentMatcher()
    result = matcher.match(
        "油皮晨间别过度清洁！要做减法!",
        datetime(2026, 5, 15, 7, 30, tzinfo=TZ),
        [ContentCandidate("c1", "油皮晨间别过度清洁 要做减法", datetime(2026, 5, 15, 7, 0, tzinfo=TZ))],
    )
    assert result.status == "matched"
    assert result.content_id == "c1"


def test_small_title_edit_uses_time_as_secondary_signal():
    candidates = [
        ContentCandidate("c1", "室外补防晒技巧", datetime(2026, 5, 16, 9, 0, tzinfo=TZ)),
        ContentCandidate("c2", "室外补防晒步骤", datetime(2026, 4, 1, 9, 0, tzinfo=TZ)),
    ]
    result = ContentMatcher().match(
        "室外不破坏底妆的补防晒技巧",
        datetime(2026, 5, 16, 9, 55, tzinfo=TZ),
        candidates,
    )
    assert result.content_id == "c1"


def test_close_candidates_are_ambiguous():
    candidates = [
        ContentCandidate("c1", "久坐肩颈放松动作", datetime(2026, 7, 5, 12, 0, tzinfo=TZ)),
        ContentCandidate("c2", "久坐肩颈放松方法", datetime(2026, 7, 5, 13, 0, tzinfo=TZ)),
    ]
    result = ContentMatcher().match(
        "久坐肩颈放松技巧",
        datetime(2026, 7, 5, 13, 29, tzinfo=TZ),
        candidates,
    )
    assert result.status == "ambiguous"
    assert result.content_id is None
```

- [ ] **Step 2: Run matcher tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_matcher.py -v
```

Expected: import failure for `metrics_collector.matcher`.

- [ ] **Step 3: Implement normalization and scoring**

Use only the standard library:

```python
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def time_score(left: datetime, right: datetime) -> float:
    hours = abs((left - right).total_seconds()) / 3600
    if hours <= 24:
        return 1.0
    if hours <= 72:
        return 0.8
    if hours <= 168:
        return 0.5
    if hours <= 720:
        return 0.2
    return 0.0
```

Implement `ContentMatcher.match()` with:

- unique normalized exact match first;
- minimum title similarity `0.82`;
- combined score `0.90 * title + 0.10 * time`;
- minimum combined score `0.80`;
- winner margin `0.05`;
- ambiguous result when multiple exact matches cannot be separated by time or the winner margin is too small.

- [ ] **Step 4: Run matcher tests**

Run:

```bash
pytest tests/metrics_collector/test_matcher.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/matcher.py tests/metrics_collector/test_matcher.py
git commit -m "feat: match exported notes to content"
```

### Task 5: Strict Official Workbook Parser

**Files:**
- Create: `metrics_collector/workbook.py`
- Create: `tests/metrics_collector/test_workbook.py`

- [ ] **Step 1: Write failing parser tests with generated workbooks**

Use openpyxl in tests to create a workbook with:

```python
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Asia/Shanghai")
DATE = "2026年07月05日13时29分55秒"

HEADERS = [
    "笔记标题",
    "首次发布时间",
    "体裁",
    "曝光",
    "观看量",
    "封面点击率",
    "点赞",
    "评论",
    "收藏",
    "涨粉",
    "分享",
    "人均观看时长",
    "弹幕",
]
```

Test:

```python
def test_parse_official_workbook_maps_types(tmp_path):
    path = build_workbook(
        tmp_path,
        [
            [
                "室外补防晒技巧",
                "2026年05月16日09时55分23秒",
                "图文",
                1191,
                72,
                0.06,
                0,
                0,
                1,
                0,
                0,
                17,
                0,
            ]
        ],
    )
    rows = parse_metrics_workbook(path, ZoneInfo("Asia/Shanghai"))
    assert rows[0].impressions == 1191
    assert rows[0].views == 72
    assert rows[0].cover_click_rate == 0.06
    assert rows[0].avg_watch_time_seconds == 17


def test_dash_is_none_but_zero_remains_zero(tmp_path):
    path = build_workbook(tmp_path, [["新笔记", DATE, "图文", "-", 9, "-", 0, 0, 0, "-", 0, "-", "-"]])
    row = parse_metrics_workbook(path, TZ)[0]
    assert row.impressions is None
    assert row.likes == 0
    assert row.followers_gained is None


def test_changed_required_header_rejects_entire_workbook(tmp_path):
    path = build_workbook(tmp_path, rows=[], headers=["标题已改名"])
    with pytest.raises(WorkbookFormatError, match="missing required headers"):
        parse_metrics_workbook(path, TZ)
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_workbook.py -v
```

Expected: missing parser import.

- [ ] **Step 3: Implement workbook validation and parsing**

`parse_metrics_workbook(path, timezone)` must:

1. Load with `openpyxl.load_workbook(path, read_only=True, data_only=True)`.
2. Find the exact header row because the official workbook has a leading notice row.
3. Require every header in `HEADERS`.
4. Parse all non-empty data rows into `ExportedMetrics`.
5. Convert `-`, blank, and `None` to `None`.
6. Preserve explicit `0`.
7. Parse Excel numeric percentages and strings ending in `%`.
8. Parse the Chinese publication timestamp with `%Y年%m月%d日%H时%M分%S秒`.
9. Parse watch durations from numeric seconds or strings such as `17s`.
10. Reject duplicate headers and rows with missing titles or publication times.

Define `WorkbookFormatError(ValueError)` for actionable validation errors.

- [ ] **Step 4: Run parser tests**

Run:

```bash
pytest tests/metrics_collector/test_workbook.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/workbook.py tests/metrics_collector/test_workbook.py
git commit -m "feat: parse creator metrics workbook"
```

### Task 6: Persistent Headed Browser And Stop Conditions

**Files:**
- Create: `metrics_collector/browser.py`
- Create: `tests/fixtures/metrics_collector/data_analysis.html`
- Create: `tests/metrics_collector/test_browser.py`

- [ ] **Step 1: Write browser-policy tests against fakes**

Create fake context/page objects and verify:

```python
def test_browser_launch_is_headed_and_persistent(tmp_path, fake_playwright):
    config = CollectorConfig.default(home=tmp_path)
    session = BrowserSession(config, playwright_factory=lambda: fake_playwright)
    session.start()
    assert fake_playwright.user_data_dir == config.profile_dir
    assert fake_playwright.launch_options["headless"] is False
    assert fake_playwright.launch_options["accept_downloads"] is True


@pytest.mark.parametrize(
    ("url", "body", "error"),
    [
        ("https://creator.xiaohongshu.com/login", "短信登录", AuthenticationRequired),
        ("https://creator.xiaohongshu.com/verify", "请完成安全验证", VerificationRequired),
        ("https://creator.xiaohongshu.com/statistics/data-analysis", "操作频繁", AccessBlocked),
    ],
)
def test_risk_state_stops_collection(url, body, error, fake_page):
    fake_page.url = url
    fake_page.body_text = body
    with pytest.raises(error):
        assert_creator_center_ready(fake_page)
```

- [ ] **Step 2: Run browser tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_browser.py -v
```

Expected: missing browser module.

- [ ] **Step 3: Implement browser lifecycle**

Define:

```python
class CollectorBrowserError(RuntimeError):
    pass


class AuthenticationRequired(CollectorBrowserError):
    pass


class VerificationRequired(CollectorBrowserError):
    pass


class AccessBlocked(CollectorBrowserError):
    pass
```

`BrowserSession.start()` must call:

```python
self._playwright = sync_playwright().start()
self.context = self._playwright.chromium.launch_persistent_context(
    user_data_dir=str(config.profile_dir),
    channel=config.browser_channel,
    headless=False,
    accept_downloads=True,
)
self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
```

`assert_creator_center_ready(page)` must inspect the current URL and bounded visible body text for login, verification, rate-limit, and access-denied states. It must not inspect or log cookies, local storage, request headers, or credentials.

Implement context-manager cleanup that closes the context and Playwright runtime even when collection raises.

- [ ] **Step 4: Run browser tests**

Run:

```bash
pytest tests/metrics_collector/test_browser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/browser.py tests/metrics_collector/test_browser.py tests/fixtures/metrics_collector/data_analysis.html
git commit -m "feat: add persistent collector browser"
```

### Task 7: Note-List Identity Collection Without Note Visits

**Files:**
- Create: `metrics_collector/identity.py`
- Create: `tests/fixtures/metrics_collector/note_manager_page_1.html`
- Create: `tests/fixtures/metrics_collector/note_manager_page_2.html`
- Create: `tests/metrics_collector/test_identity.py`

- [ ] **Step 1: Write failing identity extraction tests**

Fixture cards must mirror the observed attributes:

```html
<div
  class="note-card"
  data-impression='{"noteTarget":{"type":"NoteTarget","value":{"noteId":"6a49ebd3000000001503fdd0"}}}'
>
  <span class="note-card__title">工位摸鱼放松法：5个隐蔽动作缓解久坐僵硬</span>
  <span class="note-card__time">2026-07-05 13:29</span>
</div>
```

Tests:

```python
def test_extract_note_identities_reads_cards_only(page):
    identities = extract_note_identities(page, TZ)
    assert identities == [
        NoteIdentity(
            post_id="6a49ebd3000000001503fdd0",
            title="工位摸鱼放松法：5个隐蔽动作缓解久坐僵硬",
            published_at=datetime(2026, 7, 5, 13, 29, tzinfo=TZ),
        )
    ]
    assert page.clicked_note_cards == 0


def test_collector_stops_after_configured_page_limit(fake_paginated_page):
    identities = collect_note_identities(fake_paginated_page, max_pages=3, timezone=TZ)
    assert fake_paginated_page.visited_pages == [1, 2, 3]
    assert fake_paginated_page.clicked_note_cards == 0
```

Also test malformed `data-impression`, missing `noteId`, duplicate IDs, and no next page.

- [ ] **Step 2: Run identity tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_identity.py -v
```

Expected: missing identity module.

- [ ] **Step 3: Implement bounded list extraction**

Use `page.locator(".note-card").evaluate_all()` once per page to return only:

- `data-impression`;
- `.note-card__title` text;
- `.note-card__time` text.

Parse `data-impression` with `json.loads()` and read:

```python
payload["noteTarget"]["value"]["noteId"]
```

Pagination must:

- stop when all requested missing identities are confidently matched;
- otherwise stop at `max_note_manager_pages`;
- never call `page.goto()` for a public note URL;
- never click `.note-card`, `.note-card__media`, `.note-card__title`, or note-detail controls;
- use only the visible next-page control discovered from the current page.

Add a source-level test asserting forbidden detail selectors and `/explore/` navigation do not appear in `identity.py`.

- [ ] **Step 4: Run identity tests**

Run:

```bash
pytest tests/metrics_collector/test_identity.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/identity.py tests/metrics_collector/test_identity.py tests/fixtures/metrics_collector/note_manager_page_1.html tests/fixtures/metrics_collector/note_manager_page_2.html
git commit -m "feat: collect note ids from list cards"
```

### Task 8: Single Official Workbook Export

**Files:**
- Create: `metrics_collector/exporter.py`
- Create: `tests/metrics_collector/test_exporter.py`

- [ ] **Step 1: Write failing exporter tests**

```python
def test_export_clicks_once_and_saves_completed_xlsx(tmp_path, fake_page):
    exporter = MetricsExporter(download_dir=tmp_path)
    path = exporter.export(fake_page)
    assert fake_page.export_clicks == 1
    assert path.suffix == ".xlsx"
    assert path.exists()


def test_export_rejects_non_xlsx_download(tmp_path, fake_page):
    fake_page.download_name = "error.html"
    with pytest.raises(ExportError, match="expected .xlsx"):
        MetricsExporter(tmp_path).export(fake_page)


def test_export_timeout_does_not_retry(tmp_path, fake_page):
    fake_page.raise_timeout = True
    with pytest.raises(ExportError, match="timed out"):
        MetricsExporter(tmp_path).export(fake_page)
    assert fake_page.export_clicks == 1
```

- [ ] **Step 2: Run exporter tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_exporter.py -v
```

Expected: missing exporter module.

- [ ] **Step 3: Implement one-click export**

`MetricsExporter.export(page)` must:

1. Assert creator-center readiness.
2. Require exactly one `button.download-btn`.
3. Use one `page.expect_download()` block and one click.
4. Require suggested filename suffix `.xlsx`.
5. Save to a unique temporary path under `config.download_dir`.
6. Reject `.crdownload`, empty files, non-zip signatures, and non-`.xlsx` names.
7. Never retry the click.

Use the ZIP signature check:

```python
with path.open("rb") as file:
    if file.read(4) != b"PK\x03\x04":
        raise ExportError("download is not a valid xlsx container")
```

- [ ] **Step 4: Run exporter tests**

Run:

```bash
pytest tests/metrics_collector/test_exporter.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/exporter.py tests/metrics_collector/test_exporter.py
git commit -m "feat: export creator metrics once"
```

### Task 9: Coordinator, Daily Gate, CLI, And Atomic Import

**Files:**
- Create: `metrics_collector/coordinator.py`
- Create: `metrics_collector/__main__.py`
- Create: `tests/metrics_collector/test_coordinator.py`

- [ ] **Step 1: Write failing coordinator tests**

Cover:

```python
def test_completed_today_skips_browser(deps, now):
    deps.manager.start_collection_run(
        scheduled_date=now.date().isoformat(),
        execution_date=now.date().isoformat(),
    )
    deps.manager.finish_collection_run(
        {
            "scheduled_date": now.date().isoformat(),
            "execution_date": now.date().isoformat(),
            "status": "success",
            "exported_rows": 1,
            "updated_rows": 1,
            "skipped_rows": 0,
            "ambiguous_rows": 0,
            "matched_post_ids": 0,
            "error_summary": None,
        }
    )
    result = deps.coordinator.collect(now=now)
    assert result.status == "skipped_already_completed"
    assert deps.browser_factory.calls == 0


def test_no_unbound_content_skips_note_manager(deps):
    deps.manager.unbound_candidates = []
    result = deps.coordinator.collect(now=AT_22)
    assert deps.identity_collector.calls == 0
    assert deps.exporter.calls == 1


def test_unbound_content_reads_list_and_generates_stable_url(deps):
    deps.manager.unbound_candidates = [candidate]
    deps.identity_collector.identities = [identity]
    deps.coordinator.collect(now=AT_22)
    deps.manager.bind_post_identity.assert_called_once_with(
        content_id=candidate.content_id,
        post_id=identity.post_id,
        url=f"https://www.xiaohongshu.com/explore/{identity.post_id}",
        published_at=identity.published_at.isoformat(),
    )


def test_auth_failure_stops_before_export(deps):
    deps.browser.raise_on_ready = AuthenticationRequired("login required")
    result = deps.coordinator.collect(now=AT_22)
    assert result.status == "auth_required"
    assert deps.exporter.calls == 0


def test_ambiguous_rows_are_skipped_but_confident_rows_update(deps):
    result = deps.coordinator.collect(now=AT_22)
    assert result.status == "partial_success"
    assert result.updated_rows == 1
    assert result.ambiguous_rows == 1
```

Also test:

- a first-ever `RunAtLoad` invocation is due;
- before 22:00, a missed prior scheduled date is due;
- after a catch-up success, the 22:00 invocation on the same local date skips;
- workbook validation failure preserves the file in diagnostics and writes no metrics;
- database batch failure marks the run failed and leaves latest/history unchanged;
- verification and access-block errors are sanitized and not retried.
- failed workbooks are moved to diagnostics and files older than seven days are pruned without touching newer files.

- [ ] **Step 2: Run coordinator tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_coordinator.py -v
```

Expected: missing coordinator and CLI behavior.

- [ ] **Step 3: Implement due-date calculation and orchestration**

Add:

```python
def scheduled_date_for(now: datetime, schedule_time: time) -> date:
    if now.timetz().replace(tzinfo=None) >= schedule_time:
        return now.date()
    return now.date() - timedelta(days=1)
```

`CollectionCoordinator.collect(now)` must follow the design flow exactly:

1. Check `has_completed_execution_date(now.date())` before creating a browser.
2. Start a run ledger entry.
3. Open one browser context.
4. Validate authentication.
5. Query unbound candidates.
6. Visit note management only when candidates exist.
7. Bind confident identity matches using generated stable URLs.
8. Visit data analysis and perform exactly one export.
9. Parse the complete workbook.
10. Match rows and build `MetricsRecord` values.
11. Call one `update_metrics_batch()`.
12. Mark `success` or `partial_success`.
13. Delete a successfully imported workbook.
14. Sanitize errors and mark the exact terminal status.

Implement `preserve_diagnostic_workbook(path, diagnostics_dir, retention_days, now)` to move a failed workbook into the user-only diagnostics directory, set file mode `0o600`, and delete only diagnostic files whose modification time is older than the configured seven-day retention.

Use dependency injection for manager, browser factory, matcher, identity collector, exporter, parser, clock, and filesystem operations so tests never access Xiaohongshu.

Implement CLI commands:

```text
python -m metrics_collector auth
python -m metrics_collector collect
```

`auth` opens the dedicated profile at the data-analysis URL, tells the user to log in manually, waits for Enter, validates readiness, and exits. It must never accept password or verification-code arguments.

- [ ] **Step 4: Run coordinator and CLI tests**

Run:

```bash
pytest tests/metrics_collector/test_coordinator.py tests/metrics_collector/test_browser.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/coordinator.py metrics_collector/__main__.py tests/metrics_collector/test_coordinator.py
git commit -m "feat: coordinate daily metrics collection"
```

### Task 10: macOS LaunchAgent Installation And Operator Documentation

**Files:**
- Create: `metrics_collector/launchd.py`
- Create: `tests/metrics_collector/test_launchd.py`
- Create: `docs/metrics-collector.md`
- Modify: `metrics_collector/__main__.py`

- [ ] **Step 1: Write failing LaunchAgent tests**

```python
def test_build_launchagent_plist_runs_at_22_and_on_login(tmp_path):
    payload = build_launchagent_payload(
        python_path=Path("/opt/anaconda3/bin/python"),
        repo_root=tmp_path,
        log_dir=tmp_path / "logs",
    )
    assert payload["ProgramArguments"] == [
        "/opt/anaconda3/bin/python",
        "-m",
        "metrics_collector",
        "collect",
    ]
    assert payload["StartCalendarInterval"] == {"Hour": 22, "Minute": 0}
    assert payload["RunAtLoad"] is True
    assert payload["WorkingDirectory"] == str(tmp_path)


def test_install_writes_only_user_launchagents_directory(tmp_path):
    payload = build_launchagent_payload(
        python_path=Path("/opt/anaconda3/bin/python"),
        repo_root=tmp_path / "repo",
        log_dir=tmp_path / ".xhs-agent" / "logs",
    )
    target = install_launchagent(payload=payload, user_home=tmp_path)
    assert target == tmp_path / "Library" / "LaunchAgents" / "com.xhs-agent.metrics-collector.plist"
```

- [ ] **Step 2: Run LaunchAgent tests and verify failure**

Run:

```bash
pytest tests/metrics_collector/test_launchd.py -v
```

Expected: missing launchd module.

- [ ] **Step 3: Implement plist generation and install command**

Use `plistlib.dump()` rather than shell string substitution. The payload must include:

```python
{
    "Label": "com.xhs-agent.metrics-collector",
    "ProgramArguments": [str(python_path), "-m", "metrics_collector", "collect"],
    "WorkingDirectory": str(repo_root),
    "StartCalendarInterval": {"Hour": 22, "Minute": 0},
    "RunAtLoad": True,
    "ProcessType": "Background",
    "StandardOutPath": str(log_dir / "collector.out.log"),
    "StandardErrorPath": str(log_dir / "collector.err.log"),
}
```

Add:

```text
python -m metrics_collector install-launchagent
```

The command writes the plist under `~/Library/LaunchAgents`, creates the log directory with user-only permissions, prints the exact `launchctl bootstrap gui/$UID <plist>` command, and does not invoke `sudo`.

Document:

1. `pip install -r requirements.txt`.
2. `playwright install chromium`.
3. `python -m metrics_collector auth`.
4. `python -m metrics_collector collect` for a manual smoke test.
5. `python -m metrics_collector install-launchagent`.
6. How to bootstrap, inspect, and remove the LaunchAgent.
7. Login expiry and `auth_required` recovery.
8. Diagnostic workbook location and retention.
9. The explicit statement that automated tests never access Xiaohongshu.

- [ ] **Step 4: Run LaunchAgent tests and inspect CLI help**

Run:

```bash
pytest tests/metrics_collector/test_launchd.py -v
python -m metrics_collector --help
```

Expected: tests pass and help lists `auth`, `collect`, and `install-launchagent`.

- [ ] **Step 5: Commit**

```bash
git add metrics_collector/launchd.py metrics_collector/__main__.py tests/metrics_collector/test_launchd.py docs/metrics-collector.md
git commit -m "feat: install daily metrics launchagent"
```

### Task 11: Full Integration Verification

**Files:**
- Create: `tests/metrics_collector/test_integration.py`
- Modify only if failures reveal a defect: files introduced in Tasks 1-10

- [ ] **Step 1: Write a local end-to-end integration test**

The test must use:

- a temporary SQLite database initialized from `memory/schema.sql`;
- two internal content records;
- fake note-list identities;
- a generated official-format workbook;
- a fake browser that records every navigation and click.

Assert:

```python
assert summary.status == "partial_success"
assert summary.updated_rows == 1
assert summary.ambiguous_rows == 1
assert fake_browser.note_detail_visits == 0
assert fake_browser.export_clicks == 1
assert manager.get_content_by_id("content-1")["post_id"] == "6a49ebd3000000001503fdd0"
assert manager.get_content_by_id("content-1")["url"] == (
    "https://www.xiaohongshu.com/explore/6a49ebd3000000001503fdd0"
)
assert len(manager.get_metrics_history("content-1")) == 1
```

- [ ] **Step 2: Run the integration test**

Run:

```bash
pytest tests/metrics_collector/test_integration.py -v
```

Expected: pass without any network connection.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
pytest -q
```

Expected: all existing and new tests pass.

- [ ] **Step 4: Verify imports and repository cleanliness**

Run:

```bash
python -m metrics_collector --help
git diff --check
git status --short
```

Expected:

- CLI help succeeds.
- `git diff --check` prints nothing.
- `git status --short` shows only intentional implementation files before the final commit.

- [ ] **Step 5: Perform an explicit manual smoke test only with user approval**

Run only after the user explicitly authorizes live creator-center access:

```bash
python -m metrics_collector auth
python -m metrics_collector collect
```

Verify:

- no individual note opens;
- note management is skipped when no `post_id` is missing;
- only one workbook is downloaded;
- metrics latest/history rows are written;
- the browser closes after completion.

- [ ] **Step 6: Commit final integration coverage**

```bash
git add tests/metrics_collector/test_integration.py
git commit -m "test: cover metrics collector end to end"
```

## Final Verification Checklist

- [ ] `pytest -q` passes.
- [ ] `python -m metrics_collector --help` succeeds.
- [ ] Existing `update_metrics()` callers remain compatible.
- [ ] Legacy database migration is idempotent and rollback-safe.
- [ ] A completed run cannot execute twice on the same local date.
- [ ] Catch-up executes after a missed 22:00 run.
- [ ] Note management is visited only when `post_id` is missing.
- [ ] No code path opens `/explore/{post_id}`.
- [ ] One run can click the export button at most once.
- [ ] Ambiguous matches never write metrics or identities.
- [ ] Logs and database events contain no credentials or browser tokens.
- [ ] Persistent profile and downloaded workbooks remain outside Git.
