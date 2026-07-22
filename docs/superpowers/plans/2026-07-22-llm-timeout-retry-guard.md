# LLM Timeout and Retry Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace overlapping synchronous LLM timeout retries with one cancellable total async budget and remove provider SDK retry amplification.

**Architecture:** Keep the synchronous model-wrapper interface while running guarded `ainvoke()` calls on one process-scoped `asyncio.Runner`. A single deadline covers all sequential transient retries and backoff; provider clients disable their own retries and GLM returns complete non-streaming JSON responses.

**Tech Stack:** Python 3.12, asyncio, LangChain `ChatOpenAI` / `ChatDeepSeek`, pytest

## Global Constraints

- Preserve model selection, prompts, JSON parsing, tool handling, DeepSeek thinking mode, and `reasoning_effort="high"`.
- Do not change workflow topology, QA/review routing, checkpoints, content contracts, or publishing behavior.
- Do not log messages, generated content, API keys, headers, or full provider exception bodies.
- `hard_timeout` is one wall-clock budget across invocation, retries, and backoff.
- Provider SDK retry counts are zero; the guard is the only retry owner.
- Live provider calls remain outside the default offline test suite.
- The unrelated missing `src.editorial_carousel.strategy` integration dependency is out of scope.

## File map

- Create `tests/models/test_guard.py`: cancellation, retry, deadline, validation, and diagnostic regression tests.
- Modify `src/models/_guard.py`: process-scoped runner, total deadline, cancellation, and redacted diagnostics.
- Modify `tests/test_models.py`: provider construction contracts.
- Modify `src/models/zhipu_model.py`: bounded timeout, no SDK retry, non-streaming response.
- Modify `src/models/deepseek_model.py`: bounded timeout and no SDK retry.

---

### Task 1: Cancellable total-budget guard

**Files:**
- Create: `tests/models/test_guard.py`
- Modify: `src/models/_guard.py:1-64`

**Interfaces:**
- Consumes: a LangChain-compatible object exposing `async ainvoke(messages)`.
- Produces: the existing synchronous `invoke_with_hard_timeout(chat_model, messages, *, attempts=4, hard_timeout=240)` call shape.
- Produces: one reusable event loop for cached async provider clients.

- [ ] **Step 1: Write the cancellation regression test**

Create `tests/models/test_guard.py`:

```python
import asyncio
import time

import pytest

from src.models._guard import invoke_with_hard_timeout


class NeverCompletesModel:
    model_name = "never-completes"

    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.cancelled = False

    async def ainvoke(self, messages):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.active -= 1


def test_hard_timeout_cancels_one_active_request_without_retrying():
    model = NeverCompletesModel()
    started = time.monotonic()

    with pytest.raises(TimeoutError) as caught:
        invoke_with_hard_timeout(model, ["message"], attempts=4, hard_timeout=0.03)

    assert time.monotonic() - started < 0.25
    assert model.calls == 1
    assert model.max_active == 1
    assert model.active == 0
    assert model.cancelled is True
    assert "budget=0.03s" in str(caught.value)
    assert "attempt=1/4" in str(caught.value)
    assert "model=never-completes" in str(caught.value)
```

- [ ] **Step 2: Run it and verify RED**

Run:

```bash
pytest -q tests/models/test_guard.py::test_hard_timeout_cancels_one_active_request_without_retrying
```

Expected: FAIL because the current helper calls synchronous `invoke`, creates executor workers, and raises an empty timeout.

- [ ] **Step 3: Add retry, validation, and diagnostic tests**

Append:

```python
class FlakyModel:
    model_name = "flaky-model"

    def __init__(self, failures, error_factory=lambda: ConnectionError("connection reset")):
        self.failures = failures
        self.error_factory = error_factory
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def ainvoke(self, messages):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.calls <= self.failures:
                raise self.error_factory()
            return {"ok": True}
        finally:
            self.active -= 1


def test_transient_failures_retry_sequentially(monkeypatch):
    async def no_backoff(_seconds):
        return None

    monkeypatch.setattr("src.models._guard.asyncio.sleep", no_backoff)
    model = FlakyModel(failures=2)
    assert invoke_with_hard_timeout(model, [], attempts=4, hard_timeout=1) == {"ok": True}
    assert model.calls == 3
    assert model.max_active == 1


def test_non_transient_failure_is_not_retried():
    model = FlakyModel(4, lambda: ValueError("invalid request"))
    with pytest.raises(ValueError, match="invalid request"):
        invoke_with_hard_timeout(model, [], attempts=4, hard_timeout=1)
    assert model.calls == 1


@pytest.mark.parametrize(
    ("attempts", "hard_timeout", "message"),
    [
        (0, 1, "attempts must be at least 1"),
        (1, 0, "hard_timeout must be greater than 0"),
        (1, -1, "hard_timeout must be greater than 0"),
    ],
)
def test_invalid_policy_fails_before_invocation(attempts, hard_timeout, message):
    model = FlakyModel(0)
    with pytest.raises(ValueError, match=message):
        invoke_with_hard_timeout(
            model, [], attempts=attempts, hard_timeout=hard_timeout
        )
    assert model.calls == 0


def test_sync_guard_rejects_a_running_event_loop():
    model = FlakyModel(0)

    async def call_sync_guard():
        with pytest.raises(RuntimeError, match="running asyncio event loop"):
            invoke_with_hard_timeout(model, [], hard_timeout=1)

    asyncio.run(call_sync_guard())
    assert model.calls == 0


def test_retry_log_redacts_exception_body(monkeypatch, capsys):
    async def no_backoff(_seconds):
        return None

    monkeypatch.setattr("src.models._guard.asyncio.sleep", no_backoff)
    model = FlakyModel(1, lambda: ConnectionError("secret provider response"))
    invoke_with_hard_timeout(model, [], attempts=2, hard_timeout=1)

    output = capsys.readouterr().out
    assert "model=flaky-model" in output
    assert "attempt=1/2" in output
    assert "transient=ConnectionError" in output
    assert "remaining=" in output
    assert "secret provider response" not in output


class LoopRecordingModel:
    model_name = "loop-recorder"

    def __init__(self):
        self.loop_ids = []

    async def ainvoke(self, messages):
        self.loop_ids.append(id(asyncio.get_running_loop()))
        return {"ok": True}


def test_cached_model_calls_reuse_the_same_event_loop():
    model = LoopRecordingModel()
    invoke_with_hard_timeout(model, [], hard_timeout=1)
    invoke_with_hard_timeout(model, [], hard_timeout=1)
    assert len(set(model.loop_ids)) == 1


def test_backoff_cannot_extend_the_total_budget():
    model = FlakyModel(failures=4)
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="budget=0.03s"):
        invoke_with_hard_timeout(model, [], attempts=4, hard_timeout=0.03)

    assert time.monotonic() - started < 0.25
    assert model.calls == 1
```

- [ ] **Step 4: Run the guard file and verify RED**

Run `pytest -q tests/models/test_guard.py`.

Expected: cancellation, async invocation, validation, and diagnostic assertions FAIL for the current executor implementation.

- [ ] **Step 5: Implement the process-scoped async runner and total deadline**

Replace `src/models/_guard.py` with:

```python
"""Cancellable total-timeout and retry guard for synchronous LLM callers."""
from __future__ import annotations

import atexit
import asyncio
import threading
import time
from typing import Any, Coroutine

_TRANSIENT_KEYWORDS = (
    "connection", "connect", "timeout", "timed out", "read", "eof", "reset",
    "unreachable", "503", "502", "api_connection_error", "rate_limit", "hang",
)
_RUNNER = asyncio.Runner()
_RUNNER_LOCK = threading.Lock()
_RUNNER_CLOSED = False


def _close_runner() -> None:
    global _RUNNER_CLOSED
    with _RUNNER_LOCK:
        if not _RUNNER_CLOSED:
            _RUNNER.close()
            _RUNNER_CLOSED = True


atexit.register(_close_runner)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, ConnectionError):
        return True
    text = str(exc).lower()
    return any(keyword in text for keyword in _TRANSIENT_KEYWORDS)


def _model_identifier(chat_model: Any) -> str:
    identifier = getattr(chat_model, "model_name", None) or getattr(
        chat_model, "model", None
    )
    return str(identifier or chat_model.__class__.__name__)


def _timeout_error(model, hard_timeout, attempt, attempts, elapsed):
    return TimeoutError(
        "LLM invoke exceeded total hard timeout "
        f"(budget={hard_timeout:g}s, elapsed={elapsed:.2f}s, "
        f"attempt={attempt}/{attempts}, model={model})"
    )


async def _invoke_with_total_budget(
    chat_model, messages, *, attempts: int, hard_timeout: float
):
    started = time.monotonic()
    deadline = started + hard_timeout
    model = _model_identifier(chat_model)
    last_exc = None

    for attempt in range(1, attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _timeout_error(
                model, hard_timeout, max(1, attempt - 1), attempts,
                time.monotonic() - started,
            ) from last_exc
        try:
            async with asyncio.timeout(remaining):
                return await chat_model.ainvoke(messages)
        except TimeoutError as exc:
            raise _timeout_error(
                model, hard_timeout, attempt, attempts, time.monotonic() - started
            ) from exc
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_transient(exc):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _timeout_error(
                    model, hard_timeout, attempt, attempts,
                    time.monotonic() - started,
                ) from exc
            wait = min(30.0, float(2 ** (attempt - 1)), remaining)
            elapsed = time.monotonic() - started
            print(
                f"[llm-guard] model={model} attempt={attempt}/{attempts} "
                f"transient={exc.__class__.__name__} elapsed={elapsed:.2f}s "
                f"remaining={remaining:.2f}s retry_in={wait:.2f}s"
            )
            await asyncio.sleep(wait)

    raise AssertionError("unreachable")


def _run_on_guard_loop(coro: Coroutine[Any, Any, Any]):
    with _RUNNER_LOCK:
        if _RUNNER_CLOSED:
            coro.close()
            raise RuntimeError("LLM async runner is closed")
        return _RUNNER.run(coro)


def invoke_with_hard_timeout(
    chat_model, messages, *, attempts: int = 4, hard_timeout: float = 240
):
    """Invoke an async chat model within one cancellable wall-clock budget."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if hard_timeout <= 0:
        raise ValueError("hard_timeout must be greater than 0")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "invoke_with_hard_timeout cannot run inside a running asyncio event loop"
        )
    return _run_on_guard_loop(
        _invoke_with_total_budget(
            chat_model, messages, attempts=attempts, hard_timeout=hard_timeout
        )
    )
```

- [ ] **Step 6: Run guard tests and verify GREEN**

Run `pytest -q tests/models/test_guard.py`.

Expected: all tests PASS without pending-task or event-loop warnings.

- [ ] **Step 7: Commit the guard behavior**

```bash
git add src/models/_guard.py tests/models/test_guard.py
git commit -m "fix: make llm timeout a cancellable total budget"
```

---

### Task 2: Remove provider retry amplification

**Files:**
- Modify: `tests/test_models.py`
- Modify: `src/models/zhipu_model.py:45-54`
- Modify: `src/models/deepseek_model.py:31-39`

**Interfaces:**
- Consumes: Task 1's unchanged synchronous guard call shape.
- Produces: GLM `timeout=240`, `max_retries=0`, `streaming=False`.
- Produces: DeepSeek `timeout=480`, `max_retries=0`, unchanged reasoning settings.

- [ ] **Step 1: Write provider construction tests**

Add these imports and tests to `tests/test_models.py`:

```python
from src.models.deepseek_model import DeepSeekModel
from src.models.zhipu_model import ZhipuModel


@patch("src.models.zhipu_model.ChatOpenAI")
def test_zhipu_client_has_one_bounded_retry_owner(mock_chat_openai, monkeypatch):
    monkeypatch.setenv("ZHIPUAI_API_KEY", "test-key")
    ZhipuModel().get_chat_model()
    kwargs = mock_chat_openai.call_args.kwargs
    assert kwargs["timeout"] == 240
    assert kwargs["max_retries"] == 0
    assert kwargs["streaming"] is False


@patch("src.models.deepseek_model.ChatDeepSeek")
def test_deepseek_client_has_one_bounded_retry_owner(mock_chat_deepseek, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    DeepSeekModel().get_chat_model()
    kwargs = mock_chat_deepseek.call_args.kwargs
    assert kwargs["timeout"] == 480
    assert kwargs["max_retries"] == 0
    assert kwargs["reasoning_effort"] == "high"
    assert kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
```

- [ ] **Step 2: Run provider tests and verify RED**

```bash
pytest -q tests/test_models.py::test_zhipu_client_has_one_bounded_retry_owner tests/test_models.py::test_deepseek_client_has_one_bounded_retry_owner
```

Expected: GLM fails on timeout/retries/streaming; DeepSeek fails on missing timeout/retry arguments.

- [ ] **Step 3: Apply the minimal provider configuration**

Use these GLM arguments in `src/models/zhipu_model.py`:

```python
timeout=240,
temperature=self.temperature,
max_retries=0,
streaming=False,
```

Use these additional DeepSeek arguments in `src/models/deepseek_model.py`:

```python
timeout=480,
max_retries=0,
```

Keep every other argument unchanged.

- [ ] **Step 4: Run focused model tests and verify GREEN**

Run `pytest -q tests/test_models.py tests/models/test_guard.py`.

Expected: all focused tests PASS.

- [ ] **Step 5: Compile and commit provider changes**

```bash
python -m compileall -q src/models
git add src/models/zhipu_model.py src/models/deepseek_model.py tests/test_models.py
git commit -m "fix: remove nested llm provider retries"
```

Expected: compile exits 0 and the commit contains only the three listed files.

---

### Task 3: Verification and review

**Files:**
- Verify only; production changes remain limited to `src/models/`.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: fresh regression, compatibility, static-check, and review evidence.

- [ ] **Step 1: Run the focused regression suite**

Run `pytest -q tests/models/test_guard.py tests/test_models.py`.

Expected: all focused tests PASS.

- [ ] **Step 2: Run the offline suite excluding the accepted baseline errors**

```bash
pytest -q --ignore=tests/integration/test_beauty_account_workflow.py --ignore=tests/integration/test_domain_workflow.py
```

Expected: all collected tests PASS; any new failure blocks completion.

- [ ] **Step 3: Reconfirm the known full-suite baseline**

Run `pytest -q`.

Expected: only the two pre-existing collection errors importing missing `src.editorial_carousel.strategy`; no additional collection error is accepted.

- [ ] **Step 4: Run static verification**

```bash
python -m compileall -q src main.py
git diff --check
git status --short
```

Expected: compile and diff checks exit 0; status contains no unintended files.

- [ ] **Step 5: Review branch scope**

```bash
git diff --stat main...HEAD
git diff main...HEAD -- src/models tests/models tests/test_models.py
```

Expected: no workflow, schema, checkpoint, asset, rendering, publishing, database, output, or user debug-print changes.

- [ ] **Step 6: Run the `code-review` skill**

Review `main...HEAD` for repository standards and approved-spec compliance. Every confirmed high- or medium-severity finding requires a new failing test before its production fix, followed by Steps 1, 2, 4, and 5 again.

- [ ] **Step 7: Record final branch state**

```bash
git status --short
git log --oneline --decorate main..HEAD
```

Expected: clean worktree and the design, plan, and two implementation commits on `fix/llm-timeout-retry-guard`.
