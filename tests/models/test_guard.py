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
