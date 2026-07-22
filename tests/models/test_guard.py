import asyncio
import json
import subprocess
import sys
import threading
import time
import traceback

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


def test_stuck_cancellation_cleanup_is_bounded_and_poisons_runner():
    script = r"""
import asyncio
import importlib.util
import json
import time

guard_spec = importlib.util.spec_from_file_location(
    "standalone_llm_guard", "src/models/_guard.py"
)
guard_module = importlib.util.module_from_spec(guard_spec)
guard_spec.loader.exec_module(guard_module)
invoke_with_hard_timeout = guard_module.invoke_with_hard_timeout


class StuckCancellationModel:
    model_name = "stuck-cancellation"

    def __init__(self):
        self.calls = 0
        self.active = 0
        self.cancelled = False

    async def ainvoke(self, messages):
        self.calls += 1
        self.active += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            await asyncio.Event().wait()
        finally:
            self.active -= 1


class FollowupModel:
    model_name = "must-not-run"

    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return {"ok": True}


stuck = StuckCancellationModel()
started = time.monotonic()
try:
    invoke_with_hard_timeout(stuck, [], hard_timeout=0.03)
except Exception as exc:
    first_error = f"{exc.__class__.__name__}: {exc}"
else:
    first_error = ""
elapsed = time.monotonic() - started

followup = FollowupModel()
try:
    invoke_with_hard_timeout(followup, [], hard_timeout=1)
except Exception as exc:
    second_error = f"{exc.__class__.__name__}: {exc}"
else:
    second_error = ""

print(json.dumps({
    "elapsed": elapsed,
    "first_error": first_error,
    "stuck_calls": stuck.calls,
    "stuck_active": stuck.active,
    "stuck_cancelled": stuck.cancelled,
    "followup_calls": followup.calls,
    "second_error": second_error,
}))
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )
    result = json.loads(completed.stdout.splitlines()[-1])

    assert result["elapsed"] < 0.15
    assert result["first_error"].startswith("TimeoutError: ")
    assert "budget=0.03s" in result["first_error"]
    assert "model=stuck-cancellation" in result["first_error"]
    assert result["stuck_calls"] == 1
    assert result["stuck_active"] == 1
    assert result["stuck_cancelled"] is True
    assert result["followup_calls"] == 0
    assert result["second_error"].startswith("RuntimeError: ")
    assert "runner is unavailable" in result["second_error"]
    assert "restart the process" in result["second_error"]


class BlockingModel:
    model_name = "blocking-model"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    async def ainvoke(self, messages):
        self.started.set()
        await asyncio.to_thread(self.release.wait)
        return {"ok": True}


def test_lock_queue_wait_counts_toward_budget_without_starting_request():
    blocking_model = BlockingModel()
    blocking_errors = []

    def hold_guard_loop():
        try:
            invoke_with_hard_timeout(blocking_model, [], hard_timeout=1)
        except Exception as exc:  # pragma: no cover - diagnostic capture
            blocking_errors.append(exc)

    holder = threading.Thread(target=hold_guard_loop)
    holder.start()
    assert blocking_model.started.wait(timeout=0.25)

    queued_model = FlakyModel(0)
    queued_result = {}
    queued_done = threading.Event()

    def invoke_queued_model():
        started = time.monotonic()
        try:
            invoke_with_hard_timeout(queued_model, [], hard_timeout=0.03)
        except Exception as exc:
            queued_result["exception"] = exc
        finally:
            queued_result["elapsed"] = time.monotonic() - started
            queued_done.set()

    queued = threading.Thread(target=invoke_queued_model)
    queued.start()
    completed_within_budget_window = queued_done.wait(timeout=0.15)

    blocking_model.release.set()
    holder.join(timeout=0.5)
    queued.join(timeout=0.5)

    assert completed_within_budget_window is True
    assert isinstance(queued_result.get("exception"), TimeoutError)
    assert queued_result["elapsed"] < 0.15
    assert queued_model.calls == 0
    assert blocking_errors == []


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


def test_provider_timeout_retries_sequentially_within_total_budget(
    monkeypatch, capsys
):
    async def no_backoff(_seconds):
        return None

    monkeypatch.setattr("src.models._guard.asyncio.sleep", no_backoff)
    model = FlakyModel(1, lambda: TimeoutError("secret provider response"))

    assert invoke_with_hard_timeout(
        model, [], attempts=2, hard_timeout=1
    ) == {"ok": True}
    assert model.calls == 2
    assert model.max_active == 1

    output = capsys.readouterr().out
    assert "transient=TimeoutError" in output
    assert "secret provider response" not in output


def test_exhausted_provider_timeouts_raise_redacted_guard_timeout(monkeypatch):
    async def no_backoff(_seconds):
        return None

    monkeypatch.setattr("src.models._guard.asyncio.sleep", no_backoff)
    model = FlakyModel(4, lambda: TimeoutError("secret provider body"))

    with pytest.raises(TimeoutError) as caught:
        invoke_with_hard_timeout(model, [], attempts=3, hard_timeout=1)

    rendered = "".join(traceback.format_exception(caught.value))
    assert model.calls == 3
    assert model.max_active == 1
    assert "budget=1s" in rendered
    assert "elapsed=" in rendered
    assert "attempt=3/3" in rendered
    assert "model=flaky-model" in rendered
    assert "secret provider body" not in rendered


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
