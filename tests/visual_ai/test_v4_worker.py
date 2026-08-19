from __future__ import annotations

from typing import Any

import pytest

from src.visual_ai.gateway import InvocationRequest, ProviderConfig
from src.visual_ai.v4_gemini import classify_provider_exception
from src.visual_ai.v4_worker import (
    WorkerFailure,
    WorkerSuccess,
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
