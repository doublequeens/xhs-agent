from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from pydantic import BaseModel

from src.schemas.v4.runtime import AttemptStarted
from src.visual_ai.gateway import (
    IMAGE_VALIDATION_CONTRACT_SHA256,
    InvocationPolicy,
    InvocationRequest,
    ProviderConfig,
    VisualInvocationError,
    VisualLLMGateway,
    request_fingerprint,
)
from src.visual_ai.v4_worker import (
    WorkerFailure,
    WorkerSuccess,
    WorkerTimeout,
)
from src.visual_runtime.attempt_ledger import AttemptLedger, ReusableResult


class Answer(BaseModel):
    value: str


def make_request(*, operation_kind: str = "structured_request", payload: dict[str, Any] | None = None) -> InvocationRequest:
    return InvocationRequest(
        run_id="run-1",
        run_mode="production",
        candidate_id="candidate-1",
        revision_id="revision-1",
        parent_revision_id=None,
        node="visual_director",
        page_ids=("page-1",),
        operation_kind=operation_kind,
        payload=payload or {"prompt": "Return JSON with value ok."},
    )


def make_gateway(tmp_path: Path, *, worker: Any, **kwargs: Any) -> tuple[VisualLLMGateway, AttemptLedger]:
    root = tmp_path / "results"
    ledger = AttemptLedger(tmp_path / "attempts.sqlite", result_root=root)
    gateway = VisualLLMGateway(
        worker=worker,
        ledger=ledger,
        provider_config=ProviderConfig(provider="fake", model="fake-model", api_key="secret-key"),
        **kwargs,
    )
    return gateway, ledger


class QueueWorker:
    def __init__(self, *responses: WorkerSuccess | WorkerFailure) -> None:
        self.responses = list(responses)
        self.calls: list[Any] = []

    def invoke_once(self, provider_config: ProviderConfig, request: InvocationRequest, timeout_seconds: float) -> WorkerSuccess | WorkerFailure:
        self.calls.append((provider_config, request, timeout_seconds))
        if not self.responses:
            raise AssertionError("worker queue exhausted")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class BlockedWorker:
    def __init__(self) -> None:
        self.terminated = False
        self.calls = 0

    def invoke_once(self, provider_config: ProviderConfig, request: InvocationRequest, timeout_seconds: float) -> WorkerSuccess:
        self.calls += 1
        self.terminated = True
        from src.visual_ai.v4_worker import WorkerTimeout

        raise WorkerTimeout("blocked worker")

    def terminate(self) -> None:
        self.terminated = True


def success(text: str = '{"value":"ok"}') -> WorkerSuccess:
    return WorkerSuccess(response_text=text, provider_request_id="provider-1", token_usage={"total": 2}, provider="fake", model="fake-model")


def test_gateway_terminates_blocked_worker(tmp_path: Path) -> None:
    worker = BlockedWorker()
    gateway, ledger = make_gateway(tmp_path, worker=worker)

    with pytest.raises(VisualInvocationError, match="HARD_TIMEOUT"):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=0.05, max_attempts=1))

    assert worker.terminated is True
    assert ledger.latest() is not None
    assert ledger.latest().status == "HARD_TIMEOUT"
    ledger.close()


def test_schema_repair_consumes_a_visible_attempt(tmp_path: Path) -> None:
    worker = QueueWorker(success('{"value": 1}'), success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)

    result = gateway.invoke_structured(
        make_request(),
        Answer,
        InvocationPolicy(deadline_seconds=2, max_attempts=3, max_schema_repairs=1),
    )

    assert result.value == "ok"
    assert ledger.consumed_attempts("run-1", "candidate-1") == 2
    assert [event.status for event in ledger.events() if hasattr(event, "status")] == [
        "SCHEMA_INVALID",
        "SUCCESS",
    ]
    assert worker.calls[1][1].payload["repair"] is True
    ledger.close()


def test_hard_timeout_retries_within_shared_deadline(tmp_path: Path) -> None:
    worker = QueueWorker(WorkerTimeout("blocked"), success())
    gateway, ledger = make_gateway(tmp_path, worker=worker, sleep=lambda _seconds: None)

    result = gateway.invoke_structured(
        make_request(), Answer, InvocationPolicy(deadline_seconds=2, max_attempts=2)
    )

    assert result.value == "ok"
    assert len(worker.calls) == 2
    assert [event.status for event in ledger.events() if hasattr(event, "status")] == [
        "HARD_TIMEOUT",
        "SUCCESS",
    ]
    ledger.close()


def test_transient_transport_retries_once_per_worker_attempt(tmp_path: Path) -> None:
    worker = QueueWorker(
        WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE", provider_request_id="p-1"),
        success(),
    )
    sleeps: list[float] = []
    gateway, ledger = make_gateway(tmp_path, worker=worker, sleep=sleeps.append, jitter=lambda _attempt: 0.0)

    result = gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2, max_attempts=2))

    assert result.value == "ok"
    assert len(worker.calls) == 2
    assert ledger.consumed_attempts("run-1", "candidate-1") == 2
    assert sleeps and sleeps[0] >= 0
    ledger.close()


def test_deadline_is_shared_by_backoff_and_worker_attempts(tmp_path: Path) -> None:
    worker = QueueWorker(
        WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE"),
        success(),
    )
    observed: list[float] = []

    def sleep(seconds: float) -> None:
        observed.append(seconds)
        time.sleep(0.1)

    gateway, ledger = make_gateway(tmp_path, worker=worker, sleep=sleep, jitter=lambda _attempt: 0.0)
    with pytest.raises(VisualInvocationError, match="TRANSPORT_RETRYABLE"):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=0.04, max_attempts=2))
    assert len(worker.calls) == 1
    assert ledger.consumed_attempts("run-1", "candidate-1") == 1
    ledger.close()


def test_transport_retry_ceiling_and_candidate_ceiling(tmp_path: Path) -> None:
    worker = QueueWorker(
        WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE"),
        WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE"),
        WorkerFailure(retryable=True, error_class="transport", error_code="UNAVAILABLE"),
    )
    gateway, ledger = make_gateway(tmp_path, worker=worker, sleep=lambda _seconds: None)
    with pytest.raises(VisualInvocationError, match="TRANSPORT_RETRYABLE"):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2, max_attempts=2))
    assert ledger.consumed_attempts("run-1", "candidate-1") == 2

    ledger.close()


def test_invalid_policy_is_rejected_before_attempt_started(tmp_path: Path) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    with pytest.raises(ValueError):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=0, max_attempts=1))
    assert ledger.events() == []
    ledger.close()


def test_candidate_budget_is_not_reset_on_resume(tmp_path: Path) -> None:
    worker = QueueWorker(*[success() for _ in range(3)])
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    for index in range(14):
        started = ledger.start(
            AttemptStarted(
                run_id="run-1", workflow_version="llm_scene_v4", run_mode="production",
                candidate_id="candidate-1", revision_id="revision-1", node="node",
                page_ids=("page-1",), operation_kind="structured_request", attempt_number=index + 1,
                request_fingerprint=f"{index + 1:064x}", started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                deadline_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            )
        )
        ledger.finish(started.attempt_id, status="TRANSPORT_FATAL")
    with pytest.raises(VisualInvocationError, match="budget"):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))
    assert len(worker.calls) == 0
    ledger.close()


def test_fingerprint_excludes_secret_paths_and_attempt_metadata(tmp_path: Path) -> None:
    request = make_request(payload={"prompt": "safe", "absolute_path": str(tmp_path / "secret"), "api_key": "secret-key"})
    first = request_fingerprint(request, ProviderConfig(provider="fake", model="model-a", api_key="secret-key"), Answer)
    second = request_fingerprint(request, ProviderConfig(provider="fake", model="model-a", api_key="different"), Answer)
    assert first == second
    assert "secret-key" not in repr(request)
    assert "secret-key" not in repr(ProviderConfig(provider="fake", model="model-a", api_key="secret-key"))


def test_fingerprint_excludes_endpoint_local_roots_and_redacts_endpoint_parts(
    tmp_path: Path,
) -> None:
    request_one = make_request(
        payload={"prompt": "safe", "nested": {"path": str(tmp_path / "one")}}
    )
    request_two = make_request(
        payload={"prompt": "safe", "nested": {"path": str(tmp_path / "two")}}
    )
    config_one = ProviderConfig(
        provider="fake",
        model="model-a",
        endpoint="https://user:secret@example.test/v1?token=private",
    )
    config_two = ProviderConfig(
        provider="fake",
        model="model-a",
        endpoint="https://other:changed@example.test/v2?token=different",
    )

    assert request_fingerprint(request_one, config_one, Answer) == request_fingerprint(
        request_two, config_two, Answer
    )
    assert "secret" not in repr(config_one)
    assert "private" not in repr(config_one)
    assert "secret" not in repr(config_one.sanitized())
    assert "private" not in repr(config_one.sanitized())


def test_request_secret_fields_are_rejected_before_attempt_started(tmp_path: Path) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    request = make_request(payload={"prompt": "safe", "nested": {"token": "secret"}})

    with pytest.raises(ValueError, match="secret field"):
        gateway.invoke_structured(request, Answer, InvocationPolicy(deadline_seconds=2))

    assert ledger.events() == []
    ledger.close()


def test_fingerprint_binds_image_bytes_and_excludes_local_attempt_metadata(
    tmp_path: Path,
) -> None:
    image = b"image-bytes"
    first = make_request(
        operation_kind="image_evaluation",
        payload={
            "prompt": "inspect",
            "nested": {"arbitrary_local": str(tmp_path / "first")},
            "attempt_number": 1,
            "timestamp": "2026-08-20T00:00:00Z",
            "image_mime_types": ("image/png",),
        },
    ).with_payload(
        {
            "prompt": "inspect",
            "nested": {"arbitrary_local": str(tmp_path / "first")},
            "attempt_number": 1,
            "timestamp": "2026-08-20T00:00:00Z",
            "image_mime_types": ("image/png",),
        },
        image_inputs=(image,),
    )
    second = first.with_payload(
        {
            "prompt": "inspect",
            "nested": {"arbitrary_local": str(tmp_path / "second")},
            "attempt_number": 99,
            "timestamp": "2026-08-21T00:00:00Z",
            "image_mime_types": ("image/png",),
        },
        image_inputs=(image,),
    )
    config = ProviderConfig(provider="fake", model="model-a")
    assert request_fingerprint(first, config, Answer) == request_fingerprint(second, config, Answer)

    changed = second.with_payload(dict(second.payload), image_inputs=(b"different",))
    assert request_fingerprint(first, config, Answer) != request_fingerprint(changed, config, Answer)


def test_reusable_structured_result_is_revalidated_without_new_attempt(tmp_path: Path) -> None:
    worker = QueueWorker(success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    request = make_request()
    first = gateway.invoke_structured(request, Answer, InvocationPolicy(deadline_seconds=2))
    assert first.value == "ok"
    consumed = ledger.consumed_attempts("run-1", "candidate-1")

    second = gateway.invoke_structured(request, Answer, InvocationPolicy(deadline_seconds=2))
    assert second.value == "ok"
    assert ledger.consumed_attempts("run-1", "candidate-1") == consumed
    assert len(worker.calls) == 1
    ledger.close()


@pytest.mark.parametrize("validated_contract_sha256", [None, "0" * 64])
def test_structured_reuse_requires_schema_contract_and_canonical_bytes(
    tmp_path: Path,
    validated_contract_sha256: str | None,
) -> None:
    worker = QueueWorker(success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    request = make_request()
    fingerprint = request_fingerprint(
        request.with_payload({**request.payload, "response_schema": Answer.model_json_schema()}),
        gateway.provider_config,
        Answer,
    )
    content = b'{ "value": "ok" }'
    result_ref = "reuse.json"
    result_root = ledger.result_root
    assert result_root is not None
    result_root.mkdir(parents=True, exist_ok=True)
    (result_root / result_ref).write_bytes(content)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        ledger,
        "reusable_result",
        lambda _fingerprint: ReusableResult(
            attempt_id="old",
            request_fingerprint=fingerprint,
            result_ref=result_ref,
            result_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
            validated_contract_sha256=validated_contract_sha256,
        ),
    )
    try:
        result = gateway.invoke_structured(request, Answer, InvocationPolicy(deadline_seconds=2))
    finally:
        monkeypatch.undo()

    assert result.value == "ok"
    assert len(worker.calls) == 1
    ledger.close()


def test_structured_success_records_schema_validation_contract_hash(
    tmp_path: Path,
) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    latest = ledger.latest()
    assert latest is not None
    assert latest.validated_contract_sha256 == hashlib.sha256(
        __import__("json").dumps(
            Answer.model_json_schema(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    assert latest.validated_contract_sha256 != latest.sanitized_result_sha256
    ledger.close()


def test_image_generation_validates_and_persists_immutable_bytes(tmp_path: Path) -> None:
    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(image_buffer, format="PNG")
    worker = QueueWorker(WorkerSuccess(image_bytes=image_buffer.getvalue(), mime_type="image/png", provider_request_id="p", token_usage={"total": 1}, provider="fake", model="fake-model"))
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    result = gateway.generate_image(make_request(operation_kind="image_generation", payload={"prompt": "red", "width": 2, "height": 2}), InvocationPolicy(deadline_seconds=2))
    assert result.mime_type == "image/png"
    assert result.data.startswith(b"\x89PNG")
    assert result.sha256 == hashlib.sha256(result.data).hexdigest()
    assert ledger.latest().status == "SUCCESS"
    assert ledger.latest().validated_contract_sha256 == IMAGE_VALIDATION_CONTRACT_SHA256
    reused = gateway.generate_image(
        make_request(
            operation_kind="image_generation",
            payload={"prompt": "red", "width": 2, "height": 2},
        ),
        InvocationPolicy(deadline_seconds=2),
    )
    assert reused.reused is True
    assert reused.data == result.data
    assert len(worker.calls) == 1
    ledger.close()


def test_missing_evaluate_image_fails_before_attempt(tmp_path: Path) -> None:
    worker = QueueWorker(success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    request = make_request(operation_kind="image_evaluation", payload={"prompt": "inspect", "image_paths": [str(tmp_path / "missing.png")]})
    with pytest.raises(VisualInvocationError, match="input"):
        gateway.evaluate_images(request, Answer, InvocationPolicy(deadline_seconds=2))
    assert ledger.events() == []
    assert not worker.calls
    ledger.close()


def test_direct_evaluate_image_bytes_are_validated_before_attempt(tmp_path: Path) -> None:
    worker = QueueWorker(success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    request = make_request(
        operation_kind="image_evaluation",
        payload={"prompt": "inspect", "image_mime_types": ("image/png",)},
    ).with_payload(
        {"prompt": "inspect", "image_mime_types": ("image/png",)},
        image_inputs=(b"not-an-image",),
    )

    with pytest.raises(VisualInvocationError, match="input"):
        gateway.evaluate_images(request, Answer, InvocationPolicy(deadline_seconds=2))

    assert ledger.events() == []
    assert not worker.calls
    ledger.close()


@pytest.mark.parametrize("symlink_name", ["v4", "structured"])
def test_result_store_rejects_symlinked_result_directory_without_outside_write(
    tmp_path: Path,
    symlink_name: str,
) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    root = ledger.result_root
    assert root is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True, exist_ok=True)
    if symlink_name == "v4":
        (root / "v4").symlink_to(outside, target_is_directory=True)
    else:
        (root / "v4").mkdir(parents=True, exist_ok=True)
        (root / "v4" / symlink_name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(VisualInvocationError, match="result_store"):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert list(outside.iterdir()) == []
    assert ledger.latest() is not None
    assert ledger.latest().status == "TRANSPORT_FATAL"
    ledger.close()


def test_attempt_order_is_start_worker_persist_finish(tmp_path: Path) -> None:
    events: list[str] = []
    worker = QueueWorker(success())
    gateway, ledger = make_gateway(tmp_path, worker=worker)
    original_persist = gateway._persist_result

    def persist(kind: str, attempt_id: str, data: bytes) -> tuple[str, str]:
        assert ledger.latest() is not None and ledger.latest().status == "RUNNING"
        events.append("persist")
        result = original_persist(kind, attempt_id, data)
        assert ledger.latest() is not None and ledger.latest().status == "RUNNING"
        return result

    original_invoke = worker.invoke_once

    def invoke(*args: Any, **kwargs: Any) -> Any:
        assert ledger.latest() is not None and ledger.latest().status == "RUNNING"
        events.append("worker")
        return original_invoke(*args, **kwargs)

    worker.invoke_once = invoke  # type: ignore[method-assign]
    gateway._persist_result = persist  # type: ignore[method-assign]
    gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert events == ["worker", "persist"]
    assert ledger.latest() is not None and ledger.latest().status == "SUCCESS"
    ledger.close()


def test_process_start_failure_finishes_started_attempt_without_secret_leak(tmp_path: Path) -> None:
    class FailingWorker:
        def invoke_once(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("process start body SECRET")

    gateway, ledger = make_gateway(tmp_path, worker=FailingWorker())
    with pytest.raises(VisualInvocationError, match="TRANSPORT_FATAL") as error_info:
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert "SECRET" not in str(error_info.value)
    assert ledger.latest() is not None and ledger.latest().status == "TRANSPORT_FATAL"
    ledger.close()


def test_result_store_failure_finishes_started_attempt_without_secret_leak(tmp_path: Path) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))

    def fail_persist(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("result body SECRET")

    gateway._persist_result = fail_persist  # type: ignore[method-assign]
    with pytest.raises(VisualInvocationError, match="result_store") as error_info:
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert "SECRET" not in str(error_info.value)
    assert ledger.latest() is not None and ledger.latest().status == "TRANSPORT_FATAL"
    ledger.close()


def test_crash_leaves_open_attempt_for_reconciliation(tmp_path: Path) -> None:
    class CrashingWorker:
        def invoke_once(self, *_args: Any, **_kwargs: Any) -> Any:
            raise KeyboardInterrupt("provider traceback SECRET")

    gateway, ledger = make_gateway(tmp_path, worker=CrashingWorker())
    with pytest.raises(KeyboardInterrupt):
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert ledger.latest() is not None and ledger.latest().status == "RUNNING"
    ledger.close()


def test_success_finish_failure_is_reconciled_without_duplicate_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    original_finish = ledger.finish
    calls = 0

    def fail_once(attempt_id: str, **kwargs: Any) -> Any:
        nonlocal calls
        if kwargs.get("status") == "SUCCESS" and calls == 0:
            calls += 1
            raise RuntimeError("ambiguous finish provider body SECRET")
        calls += 1
        return original_finish(attempt_id, **kwargs)

    monkeypatch.setattr(ledger, "finish", fail_once)
    result = gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert result.value == "ok"
    assert calls == 2
    latest = ledger.latest()
    assert latest is not None and latest.status == "SUCCESS"
    assert len([event for event in ledger.events() if type(event).__name__ == "AttemptFinished"]) == 1
    ledger.close()


def test_ambiguous_finish_state_keeps_reconciliation_evidence_without_double_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, ledger = make_gateway(tmp_path, worker=QueueWorker(success()))
    calls = 0

    def fail_finish(_attempt_id: str, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("finish body SECRET")

    monkeypatch.setattr(ledger, "finish", fail_finish)
    monkeypatch.setattr(ledger, "projection", lambda _attempt_id: (_ for _ in ()).throw(RuntimeError("ledger unavailable")))
    with pytest.raises(VisualInvocationError, match="ledger") as error_info:
        gateway.invoke_structured(make_request(), Answer, InvocationPolicy(deadline_seconds=2))

    assert calls == 1
    assert "SECRET" not in str(error_info.value)
    monkeypatch.undo()
    latest = ledger.latest()
    assert latest is not None and latest.status == "RUNNING"
    assert list((ledger.result_root / "v4" / "structured").iterdir())  # type: ignore[operator]
    ledger.close()
