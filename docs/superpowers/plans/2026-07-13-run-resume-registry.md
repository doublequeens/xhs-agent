# Agent Run Resume Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Let a timed-out or interrupted CLI run be identified and resumed from its existing LangGraph checkpoint without asking the user to remember a random thread ID.

**Architecture:** Add src/run_registry.py, an independent SQLite index keyed by the existing LangGraph thread_id; it never reads or writes checkpoints.sqlite. Keep main.py responsible for CLI choices, extracting business summaries from graph state, and lifecycle updates; it marks completed only after the existing safe export returns success.

**Tech Stack:** Python 3.12, standard-library sqlite3, argparse, LangGraph, pytest.

## Global Constraints

- Store the registry at exactly data/agent_runs.sqlite. Do not parse, change, or query LangGraph checkpoint tables.
- Valid statuses are exactly running, interrupted, awaiting_review, completed; resumable means the first three.
- The table has auto-increment run_id and unique non-null thread_id, plus focus_keyword, domain, subdomain, topic_summary, title, last_node, error_summary, created_at, updated_at.
- SQLite must set WAL and busy_timeout. Every write is a short transaction.
- Keep --thread-id compatible. --new, --resume, and --thread-id are mutually exclusive.
- Do not add model retries or alter content generation, human-review decisions, text-card rendering, or publishing behavior.
- Mark completed only after export_completed_publish_package returns True.
- A registry open/query/write failure is a non-zero local-registry error. Never fall back to a random task.

---

## File Structure

| File | Responsibility |
| --- | --- |
| src/run_registry.py | SQLite schema, AgentRun data model, CRUD/query methods, exception truncation, and list formatting. No LangGraph or CLI imports. |
| tests/test_run_registry.py | Temporary database unit tests for schema, uniqueness, filters/order, upsert, truncation, and display. |
| main.py | Parser, run selection, checkpoint-summary extraction, legacy backfill, stream callbacks, and lifecycle state changes. |
| tests/test_main.py | Parser/selection, list-only, lifecycle, exception, human-review, and legacy checkpoint tests. |

### Task 1: Implement the independent run registry

**Files:**
- Create: src/run_registry.py
- Create: tests/test_run_registry.py

**Interfaces:**
- Produces: RunStatus, AgentRun, RunRegistryError, RunRegistry, exception_summary(error), format_run(run, verbose=False).
- Consumes: pathlib, sqlite3, dataclasses, datetime, typing only.
- Later callers use create_run, get_by_run_id, get_by_thread_id, list_resumable, list_recent, update_run, and upsert_run.

- [ ] **Step 1: Write the failing registry tests**

Create tests/test_run_registry.py:

~~~
from datetime import datetime, timezone

import pytest

from src.run_registry import RunRegistry, RunRegistryError, exception_summary, format_run


@pytest.fixture
def registry(tmp_path):
    instance = RunRegistry(tmp_path / "agent_runs.sqlite")
    yield instance
    instance.close()


def test_create_and_update_run_preserves_identity_and_uses_utc(registry):
    created = registry.create_run("thread-a", "通勤防晒")
    updated = registry.update_run(
        "thread-a",
        status="interrupted",
        domain="beauty",
        subdomain="skincare",
        topic_summary="防晒后底妆卡粉怎么办",
        last_node="TITLE_RANKER",
        error_summary="TimeoutError: request timed out",
    )

    assert created.run_id == updated.run_id
    assert updated.status == "interrupted"
    assert updated.title is None
    assert updated.topic_summary == "防晒后底妆卡粉怎么办"
    assert datetime.fromisoformat(updated.created_at.replace("Z", "+00:00")).tzinfo == timezone.utc


def test_resumable_filter_order_and_completed_history(registry):
    registry.create_run("thread-first", "A")
    registry.create_run("thread-second", "B")
    registry.update_run("thread-first", status="completed")
    registry.update_run("thread-second", status="awaiting_review")

    assert [run.thread_id for run in registry.list_resumable()] == ["thread-second"]
    assert [run.thread_id for run in registry.list_recent()] == ["thread-second", "thread-first"]


def test_unique_thread_id_and_legacy_upsert_keep_existing_fields(registry):
    registry.create_run("legacy-thread", "旧关键词")

    with pytest.raises(RunRegistryError, match="already exists"):
        registry.create_run("legacy-thread", "重复")

    run = registry.upsert_run(
        "legacy-thread",
        status="running",
        title="通勤底妆指南",
        domain="beauty",
    )
    assert run.focus_keyword == "旧关键词"
    assert run.title == "通勤底妆指南"
    assert run.domain == "beauty"


def test_error_truncation_and_compact_display_hide_full_thread_id(registry):
    summary = exception_summary(TimeoutError("x" * 400))
    run = registry.create_run("xhs_conversation_20260713T063200_abcdef", "通勤防晒")
    run = registry.update_run(
        run.thread_id,
        status="interrupted",
        last_node="TITLE_RANKER",
        error_summary=summary,
    )

    assert summary == "TimeoutError: " + "x" * 240
    assert "TITLE_RANKER" in format_run(run)
    assert run.thread_id not in format_run(run)
    assert "xhs_conversation_20260713T0632..." in format_run(run)
    assert run.thread_id in format_run(run, verbose=True)
~~~

- [ ] **Step 2: Verify the tests fail before implementation**

Run: python -m pytest tests/test_run_registry.py -v

Expected: collection fails because src.run_registry does not exist.

- [ ] **Step 3: Implement the SQLite module**

Create src/run_registry.py with these complete contracts:

~~~
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

RunStatus = Literal["running", "interrupted", "awaiting_review", "completed"]
RUN_STATUSES = ("running", "interrupted", "awaiting_review", "completed")
RESUMABLE_STATUSES = ("running", "interrupted", "awaiting_review")
_UNSET = object()


class RunRegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRun:
    run_id: int
    thread_id: str
    status: RunStatus
    focus_keyword: str | None
    domain: str | None
    subdomain: str | None
    topic_summary: str | None
    title: str | None
    last_node: str | None
    error_summary: str | None
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def exception_summary(error: BaseException) -> str:
    return f"{type(error).__name__}: {str(error)[:240]}"


def format_run(run: AgentRun, *, verbose: bool = False) -> str:
    labels = {
        "running": "运行中", "interrupted": "已中断",
        "awaiting_review": "等待审核", "completed": "已完成",
    }
    subject = run.title or run.topic_summary or run.focus_keyword or "（尚无选题摘要）"
    short_id = run.thread_id if len(run.thread_id) <= 31 else run.thread_id[:28] + "..."
    lines = [
        f"[{run.run_id}] {run.updated_at.replace('T', ' ').replace('Z', ' UTC')} ｜"
        f"{labels[run.status]}｜断在：{run.last_node or '未知'}",
        f"     当前选题：{subject}",
    ]
    if run.focus_keyword:
        lines.insert(1, f"     主题词：{run.focus_keyword}")
    if run.error_summary:
        lines.append(f"     原因：{run.error_summary}")
    lines.append(f"     ID：{run.thread_id if verbose else short_id}")
    return "\n".join(lines)
~~~

The RunRegistry constructor must create the parent directory, open sqlite3.connect(path), set row_factory to sqlite3.Row, execute PRAGMA journal_mode=WAL and PRAGMA busy_timeout=5000, and create this schema in one committed setup transaction:

~~~
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('running', 'interrupted', 'awaiting_review', 'completed')),
    focus_keyword TEXT,
    domain TEXT,
    subdomain TEXT,
    topic_summary TEXT,
    title TEXT,
    last_node TEXT,
    error_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_id ON agent_runs(thread_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status_updated_at
    ON agent_runs(status, updated_at DESC);
~~~

Implement methods named close, create_run, get_by_run_id, get_by_thread_id, list_resumable, list_recent, update_run, and upsert_run with the return/argument shapes stated in the Interfaces section. Use UPDATE only for explicitly supplied fields, always append updated_at, reject invalid status, and raise RunRegistryError for an unknown ID, duplicate create, or any sqlite3.Error. list_resumable and list_recent sort by updated_at DESC, run_id DESC. upsert must preserve values omitted by the caller and must not overwrite pre-existing focus_keyword during legacy backfill.

- [ ] **Step 4: Verify registry behavior**

Run:

~~~
python -m pytest tests/test_run_registry.py -v
python -m pytest
~~~

Expected: both commands pass.

- [ ] **Step 5: Commit the registry slice**

~~~
git add src/run_registry.py tests/test_run_registry.py
git commit -m "feat: add persistent agent run registry"
~~~

### Task 2: Add parser, selection, and summary-extraction seams

**Files:**
- Modify: main.py:1-40
- Modify: main.py:318-407
- Modify: tests/test_main.py:1-70
- Modify: tests/test_main.py:408-482

**Interfaces:**
- Consumes: Task 1 RunRegistry, AgentRun, RunRegistryError, exception_summary, format_run.
- Produces: parse_cli_args, create_initial_state, extract_run_updates, select_run, backfill_legacy_run.
- select_run returns None for normal q and tuple[str, bool] for actionable choices; bool is True only for a new row.

- [ ] **Step 1: Write failing parser and selection tests**

Append to tests/test_main.py:

~~~
from src.run_registry import RunRegistry


def test_parse_cli_args_makes_new_resume_and_thread_id_mutually_exclusive(monkeypatch):
    main = _load_main(monkeypatch)

    with pytest.raises(SystemExit) as exc_info:
        main.parse_cli_args(["--new", "--thread-id", "old-thread"])

    assert exc_info.value.code == 2


def test_default_selection_shows_business_summary_and_reuses_chosen_thread(monkeypatch, tmp_path, capsys):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    older = registry.create_run("thread-older", "旧关键词")
    chosen = registry.create_run("thread-newer", "通勤防晒")
    registry.update_run(chosen.thread_id, status="interrupted", title="防晒后底妆卡粉怎么办")
    args = main.parse_cli_args([])

    selection = main.select_run(registry, args, input_fn=lambda _prompt: str(chosen.run_id))

    assert selection == (chosen.thread_id, False)
    assert registry.get_by_thread_id(chosen.thread_id).status == "running"
    assert older.focus_keyword in capsys.readouterr().out


def test_default_selection_accepts_n_and_q(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    registry.create_run("thread-existing", "通勤防晒")
    args = main.parse_cli_args([])

    new_selection = main.select_run(registry, args, input_fn=lambda _prompt: "n")
    quit_selection = main.select_run(registry, args, input_fn=lambda _prompt: "q")

    assert new_selection is not None and new_selection[1] is True
    assert registry.get_by_thread_id(new_selection[0]).status == "running"
    assert quit_selection is None


def test_resume_accepts_run_id_or_full_thread_id(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("full-thread-id", "通勤防晒")
    registry.update_run(run.thread_id, status="interrupted")

    assert main.select_run(registry, main.parse_cli_args(["--resume", str(run.run_id)])) == (run.thread_id, False)
    registry.update_run(run.thread_id, status="interrupted")
    assert main.select_run(registry, main.parse_cli_args(["--resume", run.thread_id])) == (run.thread_id, False)


def test_extract_run_updates_prefers_publish_package_then_first_trend(monkeypatch):
    main = _load_main(monkeypatch)

    assert main.extract_run_updates(
        {"trends": [{"topic": "防晒后底妆卡粉"}]}, "trend_scout"
    ) == {"topic_summary": "防晒后底妆卡粉", "last_node": "trend_scout"}

    assert main.extract_run_updates(
        {
            "domain_context": {"domain": "beauty", "subdomain": "skincare"},
            "publish_package": {"title": "通勤底妆指南", "topic": "防晒后底妆卡粉"},
            "trends": [{"topic": "不应覆盖"}],
        },
        "TEXT_CARD_RENDERER",
    ) == {
        "domain": "beauty", "subdomain": "skincare", "title": "通勤底妆指南",
        "topic_summary": "防晒后底妆卡粉", "last_node": "TEXT_CARD_RENDERER",
    }
~~~

- [ ] **Step 2: Verify tests fail**

Run: python -m pytest tests/test_main.py -k 'parse_cli_args or selection or resume_accepts or extract_run_updates' -v

Expected: failure because these helpers do not exist.

- [ ] **Step 3: Implement CLI parser and pure helpers**

At main.py module scope add:

~~~
from src.run_registry import AgentRun, RunRegistry, RunRegistryError, exception_summary, format_run

RUN_REGISTRY_PATH = Path("data/agent_runs.sqlite")
~~~

Replace the inline parser with:

~~~
def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xiaohongshu Agent CLI")
    parser.add_argument("--domain", type=str, choices=SUPPORTED_DOMAINS, help="Explicit domain for routing")
    parser.add_argument("--subdomain", type=str, help="Explicit subdomain for the selected domain")
    run_group = parser.add_mutually_exclusive_group()
    run_group.add_argument("--new", action="store_true", help="Force a new agent run")
    run_group.add_argument("--resume", nargs="?", const="", metavar="RUN", help="Resume by run ID or thread ID")
    run_group.add_argument("--thread-id", type=str, help="Existing conversation thread ID to resume")
    parser.add_argument("--runs", action="store_true", help="List the latest 20 runs and exit")
    parser.add_argument("--verbose", action="store_true", help="Show full IDs in --runs output")
    parser.add_argument("--focus_keyword", type=str, help="Focus keyword for the post")
    parser.add_argument("--topic_num", type=int, default=10, help="Topic of the post")
    parser.add_argument("--provider", type=str, help="Model provider (glm, gemini, deepseek)")
    args = parser.parse_args(argv)
    if args.runs and (args.new or args.resume is not None or args.thread_id):
        parser.error("--runs cannot be combined with --new, --resume, or --thread-id")
    if args.subdomain and not args.domain:
        parser.error("--subdomain requires --domain")
    if args.domain and args.subdomain:
        profile = get_domain_profile(args.domain)
        if args.subdomain not in profile.allowed_subdomains:
            parser.error("--subdomain must be one of " + ", ".join(profile.allowed_subdomains) + f" for domain {args.domain}")
    return args
~~~

Move the current initial_state literal, with every existing key unchanged, into create_initial_state(args). Add these helpers below load_run_state:

~~~
def _value(item, name: str):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def extract_run_updates(values: dict, last_node: str | None = None) -> dict[str, str]:
    context = values.get("domain_context")
    package = values.get("publish_package") or {}
    trends = values.get("trends") or []
    candidate = _value(trends[0], "topic") if trends else None
    fields = {
        "domain": _value(context, "domain") or values.get("domain"),
        "subdomain": _value(context, "subdomain") or values.get("subdomain"),
        "title": _value(package, "title"),
        "topic_summary": _value(package, "topic") or candidate,
        "last_node": values.get("current_node") or last_node,
    }
    return {name: value for name, value in fields.items() if isinstance(value, str) and value}


def _print_run_choices(runs: list[AgentRun], output_fn=print) -> None:
    output_fn("\n可恢复的任务：")
    for run in runs:
        output_fn(format_run(run))
    output_fn("输入任务编号恢复；输入 n 新建任务；输入 q 退出。")


def select_run(registry: RunRegistry, args: argparse.Namespace, input_fn=input, output_fn=print):
    if args.new:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    if args.thread_id:
        return args.thread_id, False
    if args.resume not in (None, ""):
        run = registry.get_by_run_id(int(args.resume)) if args.resume.isdigit() else registry.get_by_thread_id(args.resume)
        if run is None:
            raise RunRegistryError(f"找不到要恢复的任务：{args.resume}")
        registry.update_run(run.thread_id, status="running", error_summary=None)
        return run.thread_id, False
    runs = registry.list_resumable()
    if not runs:
        thread_id = build_thread_id(None)
        registry.create_run(thread_id, args.focus_keyword)
        return thread_id, True
    _print_run_choices(runs, output_fn)
    while True:
        choice = input_fn("请选择：").strip().lower()
        if choice == "n":
            thread_id = build_thread_id(None)
            registry.create_run(thread_id, args.focus_keyword)
            return thread_id, True
        if choice == "q":
            return None
        if choice.isdigit():
            run = registry.get_by_run_id(int(choice))
            if run in runs:
                registry.update_run(run.thread_id, status="running", error_summary=None)
                return run.thread_id, False
        output_fn("无效选择，请输入列表中的任务编号、n 或 q。")


def backfill_legacy_run(registry: RunRegistry, thread_id: str, current_state) -> None:
    values = getattr(current_state, "values", None) or {}
    if not values or registry.get_by_thread_id(thread_id) is not None:
        return
    status = "completed" if not getattr(current_state, "next", ()) else "running"
    registry.upsert_run(thread_id, status=status, **extract_run_updates(values))
~~~

--resume with no argument must use the same interactive list as the default command. --runs must initialize the registry, print list_recent(20) through format_run(run, verbose=args.verbose), and return before creating XHSMemoryManager or graph. An explicit --thread-id checkpoint with no values continues the existing new-task behavior and gets a running row later; backfill_legacy_run must not create any row for it.

- [ ] **Step 4: Verify parser and selection behavior**

Run:

~~~
python -m pytest tests/test_main.py -k 'parse_cli_args or selection or resume_accepts or extract_run_updates or initial_state' -v
python -m pytest
~~~

Expected: all pass, including existing subdomain-validation and interactive-state tests.

- [ ] **Step 5: Commit the selection slice**

~~~
git add main.py tests/test_main.py
git commit -m "feat: add interactive agent run recovery selection"
~~~

### Task 3: Record graph lifecycle transitions and legacy resume

**Files:**
- Modify: main.py:277-315
- Modify: main.py:318-407
- Modify: tests/test_main.py:464-482

**Interfaces:**
- Consumes: Task 1 registry and Task 2 helper interfaces.
- Produces: sync_run_from_graph and a boolean stream_graph_until_stop return.
- stream_graph_until_stop returns True only when export_completed_publish_package returns True.

- [ ] **Step 1: Write failing lifecycle and compatibility tests**

Append to tests/test_main.py:

~~~
def test_stream_syncs_last_node_and_summary_before_clean_export(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("stream-thread", "通勤防晒")

    class FakeGraph:
        def stream(self, _run_input, config):
            assert config["configurable"]["thread_id"] == run.thread_id
            yield {"title_ranker": {}}
        def get_state(self, _config):
            return SimpleNamespace(
                values={"current_node": "TITLE_RANKER", "trends": [{"topic": "防晒后底妆卡粉"}]},
                next=(),
            )

    monkeypatch.setattr(main, "export_completed_publish_package", lambda *_args: True)
    assert main.stream_graph_until_stop(
        FakeGraph(), {}, main.build_run_config(run.thread_id), registry=registry, thread_id=run.thread_id
    ) is True

    updated = registry.get_by_thread_id(run.thread_id)
    assert updated.status == "running"
    assert updated.last_node == "TITLE_RANKER"
    assert updated.topic_summary == "防晒后底妆卡粉"


def test_main_marks_timeout_interrupted_with_truncated_reason(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    path = tmp_path / "agent_runs.sqlite"
    registry = RunRegistry(path)
    run = registry.create_run("timeout-thread", "通勤防晒")
    registry.close()
    monkeypatch.setattr(main, "RUN_REGISTRY_PATH", path)
    monkeypatch.setattr(main, "select_run", lambda *_args, **_kwargs: (run.thread_id, False))
    monkeypatch.setattr(main, "XHSMemoryManager", lambda *_args: SimpleNamespace(init_db=lambda *_: None))
    monkeypatch.setattr(main, "create_graph", lambda: SimpleNamespace(
        get_state=lambda _config: SimpleNamespace(values={"trends": []}, next=("node",))
    ))
    monkeypatch.setattr(
        main, "stream_graph_until_stop",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("request timed out")),
    )
    monkeypatch.setattr("sys.argv", ["main.py"])

    with pytest.raises(SystemExit) as exc_info:
        main.main()

    assert exc_info.value.code == 1
    check = RunRegistry(path)
    assert check.get_by_thread_id(run.thread_id).status == "interrupted"
    assert check.get_by_thread_id(run.thread_id).error_summary == "TimeoutError: request timed out"
    check.close()


def test_review_interrupt_remains_awaiting_review_when_input_stops(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    run = registry.create_run("review-thread", "通勤防晒")

    class Interrupt:
        value = {"kind": "publish_review", "message": "请审核", "publish_package": {"title": "标题"}}
    class FakeGraph:
        def stream(self, *_args, **_kwargs):
            yield {"__interrupt__": [Interrupt()]}
        def get_state(self, _config):
            return SimpleNamespace(values={"review_status": None}, next=("human_review",))

    monkeypatch.setattr(
        main, "collect_interrupt_response",
        lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        main.stream_graph_until_stop(
            FakeGraph(), {}, main.build_run_config(run.thread_id), registry=registry, thread_id=run.thread_id
        )
    assert registry.get_by_thread_id(run.thread_id).status == "awaiting_review"


def test_legacy_thread_id_backfills_only_real_checkpoints(monkeypatch, tmp_path):
    main = _load_main(monkeypatch)
    registry = RunRegistry(tmp_path / "agent_runs.sqlite")
    active = SimpleNamespace(values={"trends": [{"topic": "防晒后底妆卡粉"}]}, next=("title_ranker",))
    terminal = SimpleNamespace(values={"publish_package": {"title": "通勤底妆指南"}}, next=())
    empty = SimpleNamespace(values={}, next=())

    main.backfill_legacy_run(registry, "active-legacy", active)
    main.backfill_legacy_run(registry, "terminal-legacy", terminal)
    main.backfill_legacy_run(registry, "empty-legacy", empty)

    assert registry.get_by_thread_id("active-legacy").status == "running"
    assert registry.get_by_thread_id("active-legacy").topic_summary == "防晒后底妆卡粉"
    assert registry.get_by_thread_id("terminal-legacy").status == "completed"
    assert registry.get_by_thread_id("empty-legacy") is None
~~~

- [ ] **Step 2: Verify lifecycle tests fail**

Run: python -m pytest tests/test_main.py -k 'stream_syncs or timeout_interrupted or review_interrupt or legacy_thread' -v

Expected: failure because streaming has no registry callback/return and main has no lifecycle integration.

- [ ] **Step 3: Implement state synchronization around graph.stream**

Add this helper and replace stream_graph_until_stop with this contract while retaining current human-review commands and prompts:

~~~
def sync_run_from_graph(registry: RunRegistry, graph, config: dict, thread_id: str, last_node: str | None) -> None:
    state = graph.get_state(config)
    values = getattr(state, "values", None) or {}
    registry.update_run(
        thread_id,
        status="running",
        error_summary=None,
        **extract_run_updates(values, last_node),
    )


def stream_graph_until_stop(graph, run_input, config, *, registry: RunRegistry | None = None, thread_id: str | None = None) -> bool:
    next_input = run_input
    while True:
        interrupted = False
        for output in graph.stream(next_input, config=config):
            for key, value in output.items():
                if key == "__interrupt__":
                    interrupted = True
                    payload = value[0].value
                    if not isinstance(payload, dict):
                        raise ValueError("Interrupt payload must be a dict.")
                    if registry is not None and thread_id is not None:
                        registry.update_run(thread_id, status="awaiting_review")
                    next_input = Command(resume=collect_interrupt_response(payload))
                    if registry is not None and thread_id is not None:
                        registry.update_run(thread_id, status="running", error_summary=None)
                    break
                print(f"Finished processing node: {key}")
                if registry is not None and thread_id is not None:
                    sync_run_from_graph(registry, graph, config, thread_id, key)
            if interrupted:
                break
        if not interrupted:
            return export_completed_publish_package(graph, config)
~~~

If collect_interrupt_response raises KeyboardInterrupt, it must not be caught by main's Exception handler, so the previously written awaiting_review status remains intact. When an ordinary graph exception propagates, main handles it in the next step.

- [ ] **Step 4: Refactor main ownership and lifecycle updates**

Use this exact order in main():

~~~
def main():
    args = parse_cli_args()
    try:
        registry = RunRegistry(RUN_REGISTRY_PATH)
    except RunRegistryError as exc:
        print(f"本地运行注册表错误：{exc}", file=sys.stderr)
        sys.exit(1)

    thread_id = None
    try:
        if args.runs:
            for run in registry.list_recent(20):
                print(format_run(run, verbose=args.verbose))
            return

        selection = select_run(registry, args)
        if selection is None:
            return
        thread_id, is_new = selection

        # Keep the existing startup status text and optional provider setup here.
        if args.provider:
            set_default_provider(args.provider)
        database = XHSMemoryManager("data/xhs_memory.db")
        database.init_db("memory/schema.sql")
        graph = create_graph()
        initial_state = create_initial_state(args)
        config = build_run_config(thread_id)
        current_state, run_input = load_run_state(graph, config, initial_state)

        if args.thread_id:
            backfill_legacy_run(registry, thread_id, current_state)
        if not current_state.values:
            if not is_new and args.resume is not None:
                raise RunRegistryError("所选任务的 LangGraph checkpoint 不存在，请使用 --new 创建新任务")
            if registry.get_by_thread_id(thread_id) is None:
                registry.create_run(thread_id, args.focus_keyword)
        else:
            registry.update_run(
                thread_id, status="running", error_summary=None,
                **extract_run_updates(current_state.values),
            )

        if current_state.values and not current_state.next:
            if export_completed_publish_package(graph, config):
                registry.update_run(thread_id, status="completed", error_summary=None)
            else:
                registry.update_run(thread_id, status="awaiting_review")
            return

        exported = stream_graph_until_stop(
            graph, run_input, config, registry=registry, thread_id=thread_id,
        )
        registry.update_run(
            thread_id,
            status="completed" if exported else "awaiting_review",
            error_summary=None if exported else _UNSET,
        )
    except Exception as exc:
        if thread_id is not None:
            try:
                if registry.get_by_thread_id(thread_id) is not None:
                    registry.update_run(
                        thread_id, status="interrupted", error_summary=exception_summary(exc),
                    )
            except RunRegistryError as registry_exc:
                print(f"本地运行注册表错误：{registry_exc}", file=sys.stderr)
        print(f"Error running agent: {exc}")
        sys.exit(1)
    finally:
        registry.close()
~~~

Do not literally reference _UNSET from main.py. Implement the last update as two branches: exported writes status completed and clears error_summary; non-export writes only status awaiting_review. This ensures the registry module remains the sole owner of its sentinel. Preserve the current behavior for an old --thread-id with no checkpoint: it becomes a fresh running row with that supplied ID, never a fake completed row. A selected --resume row without checkpoint instead errors with the displayed Chinese message.

- [ ] **Step 5: Verify implementation**

Run:

~~~
python -m pytest tests/test_run_registry.py tests/test_main.py -v
python -m pytest
python main.py --help
~~~

Expected: all tests pass; help shows --new, --resume [RUN], --runs, and --verbose and does not call a model.

- [ ] **Step 6: Commit the lifecycle slice**

~~~
git add main.py tests/test_main.py
git commit -m "feat: resume agent runs after interruption"
~~~

### Task 4: Run acceptance verification and review the branch

**Files:**
- Verify: src/run_registry.py
- Verify: main.py
- Verify: tests/test_run_registry.py
- Verify: tests/test_main.py

**Interfaces:**
- Consumes: all prior work.
- Produces: evidence that meaningful list selection restores the same checkpoint thread ID.

- [ ] **Step 1: Test the complete offline recovery sequence**

Run:

~~~
python -m pytest tests/test_main.py -k 'default_selection_shows_business_summary or resume_accepts or timeout_interrupted or legacy_thread' -v
~~~

Expected: a listed interrupted run displays its business fields, selection returns its original thread ID, and a timeout row persists as interrupted.

- [ ] **Step 2: Check each acceptance condition**

| Event | Required observable result |
| --- | --- |
| python main.py with no resumable rows | creates one running registry row and runs with its thread ID |
| python main.py with one or more resumable rows | displays updated time, title/topic/keyword, last node, reason, and shortened ID; waits for run_id, n, or q |
| selecting a run_id | same stored thread_id is passed into graph config and status becomes running |
| --new | always creates a new row |
| --resume RUN | accepts run_id or full ID and resumes that row |
| --runs --verbose | prints at most 20 rows with full IDs and creates no graph |
| stream timeout/Exception | status interrupted; error starts with exception class and retains no more than 240 message characters |
| human review interrupted before response | status awaiting_review |
| final-policy-clean terminal export | this and only this path writes completed |
| old --thread-id with checkpoint/no registry row | backfills running or completed from real checkpoint values; an empty checkpoint produces no fake completed record |

- [ ] **Step 3: Run final verification and inspect the diff**

Run:

~~~
python -m pytest
git diff main...HEAD -- src/run_registry.py main.py tests/test_run_registry.py tests/test_main.py
git status --short
~~~

Expected: full test suite passes. The diff contains only registry/CLI/tests plus existing design and plan documents; no checkpoints.sqlite, data/agent_runs.sqlite, or generated publish output is tracked.

- [ ] **Step 4: Commit a final acceptance test only if one was added**

~~~
git add tests/test_main.py
git commit -m "test: cover agent run recovery workflow"
~~~
