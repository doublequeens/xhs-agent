from __future__ import annotations

import time
import signal
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


def make_request() -> InvocationRequest:
    return InvocationRequest(
        run_id="run-1", run_mode="production", candidate_id="candidate-1", revision_id="revision-1",
        node="node", page_ids=("page-1",), operation_kind="structured_request", payload={"prompt": "hello"},
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


def _blocked_child(connection, _provider_config, _request) -> None:
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


def _ignore_term_child(connection, _provider_config, _request) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(5)


def test_spawned_blocked_child_is_gone_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _blocked_child)
    started = time.monotonic()
    with pytest.raises(WorkerTimeout):
        V4Worker(start_method="fork", cleanup_grace_seconds=0.05).invoke_once(
            ProviderConfig(api_key="secret"), make_request(), 0.05
        )
    assert time.monotonic() - started < 1


def test_spawned_sigterm_ignored_child_uses_bounded_kill_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _ignore_term_child)
    started = time.monotonic()
    with pytest.raises(WorkerTimeout):
        V4Worker(start_method="fork", cleanup_grace_seconds=0.05).invoke_once(
            ProviderConfig(api_key="secret"), make_request(), 0.05
        )
    assert time.monotonic() - started < 1


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
    result = V4Worker(start_method="fork", cleanup_grace_seconds=0.05).invoke_once(
        ProviderConfig(provider="fake", model="fake"), make_request(), 1
    )
    assert isinstance(result, WorkerSuccess)
    assert result.response_text == '{"value":"ok"}'


def test_spawned_child_ipc_eof_is_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.visual_ai.v4_worker as worker_module

    monkeypatch.setattr(worker_module, "_child_entry", _closed_child)
    with pytest.raises(RuntimeError, match="worker IPC failed"):
        V4Worker(start_method="fork", cleanup_grace_seconds=0.05).invoke_once(
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
