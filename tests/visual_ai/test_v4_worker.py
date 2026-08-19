from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.visual_ai.gateway import InvocationRequest, ProviderConfig
from src.visual_ai.v4_gemini import classify_provider_exception
from src.visual_ai.v4_worker import (
    V4Worker,
    WorkerFailure,
    WorkerSuccess,
    WorkerTimeout,
    deserialize_envelope,
    serialize_envelope,
)


def make_request(*, payload: dict[str, Any] | None = None) -> InvocationRequest:
    return InvocationRequest(
        run_id="run-1", run_mode="production", candidate_id="candidate-1", revision_id="revision-1",
        node="node", page_ids=("page-1",), operation_kind="structured_request",
        payload=payload or {"prompt": "hello"},
    )


def test_worker_envelopes_are_serializable_and_sanitized() -> None:
    success = WorkerSuccess(response_text='{"value":"ok"}', provider_request_id="request-1", token_usage={"total": 3}, provider="gemini", model="model")
    restored = deserialize_envelope(serialize_envelope(success))
    assert restored == success
    assert "traceback" not in serialize_envelope(success).decode().lower()

    failure = WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE", provider_request_id="request-2")
    assert deserialize_envelope(serialize_envelope(failure)) == failure


def test_worker_failure_never_contains_provider_body_or_traceback() -> None:
    failure = WorkerFailure.from_exception(ConnectionError("provider body SECRET"), provider_request_id="p")
    encoded = serialize_envelope(failure).decode()
    assert "SECRET" not in encoded
    assert "traceback" not in encoded.lower()
    assert failure.retryable is True


@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_provider_transport_codes_are_retryable(code: int) -> None:
    error = type("ApiError", (Exception,), {"code": code})("secret body")
    assert classify_provider_exception(error).retryable is True


def test_provider_client_error_is_fatal_without_nested_retry() -> None:
    error = type("ApiError", (Exception,), {"code": 400})("secret body")
    classified = classify_provider_exception(error)
    assert classified.retryable is False
    assert classified.error_code == "BAD_REQUEST"


def _record_pid(request: InvocationRequest) -> None:
    raw_path = request.payload.get("pid_path")
    if isinstance(raw_path, str):
        Path(raw_path).write_text(str(os.getpid()), encoding="ascii")


def _blocked_child(connection, _provider_config, request) -> None:
    _record_pid(request)
    time.sleep(5)


def _success_child(connection, _provider_config, _request) -> None:
    connection.send_bytes(
        serialize_envelope(
            WorkerSuccess(
                response_text='{"value":"ok"}', provider="fake", model="fake"
            )
        )
    )
    connection.close()


def _closed_child(connection, _provider_config, _request) -> None:
    connection.close()


def _ignore_term_child(connection, _provider_config, request) -> None:
    _record_pid(request)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(5)


def _wait_for_pid(path: Path) -> int:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="ascii"))
        except (FileNotFoundError, ValueError):
            time.sleep(0.01)
    raise AssertionError("child did not publish its pid")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_spawned_blocked_child_is_gone_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _blocked_child)
    pid_path = tmp_path / "blocked-child.pid"
    started = time.monotonic()
    with pytest.raises(WorkerTimeout):
        V4Worker(cleanup_grace_seconds=0.05).invoke_once(
                ProviderConfig(api_key="secret"),
                make_request(payload={"prompt": "hello", "pid_path": str(pid_path)}),
            1.0,
        )
    pid = _wait_for_pid(pid_path)
    assert time.monotonic() - started < 3
    assert not _pid_exists(pid)


def test_spawned_sigterm_ignored_child_uses_bounded_kill_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _ignore_term_child)
    pid_path = tmp_path / "kill-child.pid"
    started = time.monotonic()
    with pytest.raises(WorkerTimeout):
        V4Worker(cleanup_grace_seconds=0.05).invoke_once(
                ProviderConfig(api_key="secret"),
                make_request(payload={"prompt": "hello", "pid_path": str(pid_path)}),
            1.0,
        )
    pid = _wait_for_pid(pid_path)
    assert time.monotonic() - started < 3
    assert not _pid_exists(pid)


def test_terminate_then_kill_fallback_is_bounded() -> None:
    import src.visual_ai.v4_worker as worker_module

    class ProcessThatNeedsKill:
        def __init__(self) -> None:
            self.alive = True
            self.terminated = False
            self.killed = False
            self.closed = False

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True
            self.alive = False

        def join(self, _timeout: float) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    process = ProcessThatNeedsKill()
    started = time.monotonic()
    V4Worker(cleanup_grace_seconds=0.01)._reap(process, timed_out=True)  # type: ignore[arg-type]
    assert time.monotonic() - started < 1
    assert process.terminated is True
    assert process.killed is True
    assert process.closed is True


def test_normal_child_ipc_and_process_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _success_child)
    result = V4Worker(cleanup_grace_seconds=0.05).invoke_once(
        ProviderConfig(provider="fake", model="fake"), make_request(), 1
    )
    assert isinstance(result, WorkerSuccess)
    assert result.response_text == '{"value":"ok"}'


def test_spawned_child_ipc_eof_is_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _closed_child)
    with pytest.raises(RuntimeError, match="worker IPC failed"):
        V4Worker(cleanup_grace_seconds=0.05).invoke_once(
            ProviderConfig(provider="fake", model="fake"), make_request(), 1
        )


def test_process_construction_failure_closes_allocated_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.visual_ai.v4_worker as worker_module

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeContext:
        def __init__(self) -> None:
            self.connections: tuple[FakeConnection, FakeConnection] | None = None

        def Pipe(self, *, duplex: bool) -> tuple[FakeConnection, FakeConnection]:
            assert duplex is False
            self.connections = (FakeConnection(), FakeConnection())
            return self.connections

        def Process(self, **_kwargs: Any) -> Any:
            raise RuntimeError("process constructor body SECRET")

    context = FakeContext()
    monkeypatch.setattr(worker_module.multiprocessing, "get_context", lambda _name: context)
    with pytest.raises(RuntimeError, match="worker process invocation failed"):
        V4Worker(start_method="spawn").invoke_once(
            ProviderConfig(provider="fake", model="fake"), make_request(), 1
        )
    assert context.connections is not None
    assert all(connection.closed for connection in context.connections)


def test_partial_process_start_is_reaped_and_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _blocked_child)
    context = worker_module.multiprocessing.get_context("spawn")
    holder: dict[str, Any] = {}

    class PartialStartProcess:
        def __init__(self, **kwargs: Any) -> None:
            self.inner = context.Process(**kwargs)
            self.closed = False
            self.started_pid: int | None = None

        @property
        def pid(self) -> int | None:
            return self.started_pid

        @property
        def _popen(self) -> Any:
            return self.inner._popen

        def start(self) -> None:
            self.inner.start()
            self.started_pid = self.inner.pid
            raise RuntimeError("partial process start body SECRET")

        def is_alive(self) -> bool:
            return self.inner.is_alive()

        def terminate(self) -> None:
            self.inner.terminate()

        def kill(self) -> None:
            self.inner.kill()

        def join(self, timeout: float) -> None:
            self.inner.join(timeout)

        def close(self) -> None:
            self.closed = True
            self.inner.close()

    def process_factory(**kwargs: Any) -> PartialStartProcess:
        process = PartialStartProcess(**kwargs)
        holder["process"] = process
        return process

    with pytest.raises(RuntimeError, match="worker process invocation failed"):
        V4Worker(
            cleanup_grace_seconds=0.05,
            process_factory=process_factory,
        ).invoke_once(
            ProviderConfig(provider="fake", model="fake"),
            make_request(),
            1,
        )

    process = holder["process"]
    pid = process.pid
    assert isinstance(pid, int) and pid > 0
    assert not _pid_exists(pid)
    assert process.closed is True


def test_v4_adapter_makes_one_sdk_call_per_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.visual_ai.v4_gemini as adapter

    class Models:
        def __init__(self) -> None:
            self.calls = 0

        def generate_content(self, **_kwargs: Any) -> Any:
            self.calls += 1
            return SimpleNamespace(text='{"value":"ok"}')

    models = Models()
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda _config: SimpleNamespace(models=models),
    )
    result = adapter.execute(
        ProviderConfig(provider="fake", model="fake"),
        make_request(),
    )

    assert result["kind"] == "success"
    assert models.calls == 1
