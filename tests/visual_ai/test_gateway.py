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
)
from src.visual_runtime.attempt_ledger import AttemptLedger


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
