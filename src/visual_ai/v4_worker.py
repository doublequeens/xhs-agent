"""Spawned, one-provider-call worker for the v4 LLM gateway."""

from __future__ import annotations

import multiprocessing
import base64
import json
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

from src.visual_ai.protocols import InvocationRequest, ProviderConfig


@dataclass(frozen=True, slots=True)
class WorkerSuccess:
    response_text: str | None = None
    image_bytes: bytes | None = None
    mime_type: str | None = None
    provider_request_id: str | None = None
    token_usage: dict[str, int] | None = None
    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        if self.response_text is not None and not isinstance(self.response_text, str):
            raise ValueError("response_text must be a string or None")
        if self.image_bytes is not None and not isinstance(self.image_bytes, bytes):
            raise ValueError("image_bytes must be bytes or None")
        if self.image_bytes is not None and not isinstance(self.mime_type, str):
            raise ValueError("mime_type is required for image bytes")
        if self.response_text is None and self.image_bytes is None:
            raise ValueError("success envelope must contain text or image bytes")
        if self.response_text is not None and self.image_bytes is not None:
            raise ValueError("success envelope cannot contain text and image bytes")
        if self.token_usage is not None:
            if any(not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0 for key, value in self.token_usage.items()):
                raise ValueError("token_usage must contain non-negative integer counts")
        for name in ("provider_request_id", "provider", "model"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or len(value) > 256 or any(ord(char) < 0x20 for char in value)):
                raise ValueError(f"{name} must be safe metadata")


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    retryable: bool
    error_class: str
    error_code: str
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be bool")
        for name in ("error_class", "error_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 128 or any(ord(char) < 0x20 for char in value):
                raise ValueError(f"{name} must be a safe short string")
        if self.provider_request_id is not None and (not isinstance(self.provider_request_id, str) or len(self.provider_request_id) > 256 or any(ord(char) < 0x20 for char in self.provider_request_id)):
            raise ValueError("provider_request_id must be safe metadata")

    @classmethod
    def from_exception(cls, exc: BaseException, *, provider_request_id: str | None = None) -> "WorkerFailure":
        from src.visual_ai.v4_gemini import classify_provider_exception

        failure = classify_provider_exception(exc)
        return cls(
            retryable=failure.retryable,
            error_class=failure.error_class,
            error_code=failure.error_code,
            provider_request_id=provider_request_id or failure.provider_request_id,
        )


WorkerEnvelope = WorkerSuccess | WorkerFailure


def serialize_envelope(envelope: WorkerEnvelope) -> bytes:
    """Serialize only the allow-listed envelope fields as canonical JSON."""

    if isinstance(envelope, WorkerSuccess):
        payload: dict[str, Any] = {
            "kind": "success",
            "response_text": envelope.response_text,
            "image_bytes_b64": base64.b64encode(envelope.image_bytes).decode("ascii") if envelope.image_bytes is not None else None,
            "mime_type": envelope.mime_type,
            "provider_request_id": envelope.provider_request_id,
            "token_usage": envelope.token_usage,
            "provider": envelope.provider,
            "model": envelope.model,
        }
    elif isinstance(envelope, WorkerFailure):
        payload = {
            "kind": "failure",
            "retryable": envelope.retryable,
            "error_class": envelope.error_class,
            "error_code": envelope.error_code,
            "provider_request_id": envelope.provider_request_id,
        }
    else:
        raise TypeError("unsupported worker envelope")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def deserialize_envelope(data: bytes) -> WorkerEnvelope:
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid worker envelope") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        raise ValueError("invalid worker envelope")
    if payload["kind"] == "success" and set(payload) == {
        "kind", "response_text", "image_bytes_b64", "mime_type", "provider_request_id", "token_usage", "provider", "model"
    }:
        encoded = payload["image_bytes_b64"]
        if encoded is not None and not isinstance(encoded, str):
            raise ValueError("invalid worker envelope")
        try:
            image_bytes = base64.b64decode(encoded, validate=True) if encoded is not None else None
        except Exception as exc:
            raise ValueError("invalid worker envelope") from exc
        return WorkerSuccess(
            response_text=payload["response_text"],
            image_bytes=image_bytes,
            mime_type=payload["mime_type"],
            provider_request_id=payload["provider_request_id"],
            token_usage=payload["token_usage"],
            provider=payload["provider"],
            model=payload["model"],
        )
    if payload["kind"] == "failure" and set(payload) == {
        "kind", "retryable", "error_class", "error_code", "provider_request_id"
    }:
        return WorkerFailure(
            retryable=payload["retryable"],
            error_class=payload["error_class"],
            error_code=payload["error_code"],
            provider_request_id=payload["provider_request_id"],
        )
    raise ValueError("invalid worker envelope")


class WorkerTimeout(TimeoutError):
    """The parent reached its shared deadline and reaped the child."""


class WorkerCleanupError(RuntimeError):
    """The worker process or IPC handles could not be closed safely."""


def _child_entry(
    child_connection: Connection,
    provider_config: ProviderConfig,
    request: InvocationRequest,
) -> None:
    try:
        from src.visual_ai.v4_gemini import ProviderFailure, execute

        output = execute(provider_config, request)
        if isinstance(output, ProviderFailure):
            envelope: WorkerEnvelope = WorkerFailure(
                retryable=output.retryable,
                error_class=output.error_class,
                error_code=output.error_code,
                provider_request_id=output.provider_request_id,
            )
        elif output.get("kind") == "success":
            envelope = WorkerSuccess(
                response_text=output.get("response_text"),
                image_bytes=output.get("image_bytes"),
                mime_type=output.get("mime_type"),
                provider_request_id=output.get("provider_request_id"),
                token_usage=output.get("token_usage"),
                provider=output.get("provider", provider_config.provider),
                model=output.get("model", provider_config.model),
            )
        else:
            envelope = WorkerFailure(False, "worker", "INVALID_PROVIDER_ENVELOPE")
    except Exception:
        # Never send exception bodies or traceback text over IPC.
        envelope = WorkerFailure(False, "worker", "WORKER_FAILURE")
    try:
        child_connection.send_bytes(serialize_envelope(envelope))
    except Exception:
        pass
    finally:
        try:
            child_connection.close()
        except Exception:
            pass


class V4Worker:
    """One fresh spawned process for each provider attempt."""

    def __init__(self, *, start_method: str = "spawn", cleanup_grace_seconds: float = 0.2) -> None:
        if cleanup_grace_seconds < 0:
            raise ValueError("cleanup_grace_seconds must be non-negative")
        self.start_method = start_method
        self.cleanup_grace_seconds = cleanup_grace_seconds

    def invoke_once(
        self,
        provider_config: ProviderConfig,
        request: InvocationRequest,
        timeout_seconds: float,
    ) -> WorkerEnvelope:
        if timeout_seconds <= 0:
            raise WorkerTimeout("deadline elapsed before worker launch")
        parent_connection: Connection | None = None
        child_connection: Connection | None = None
        process: multiprocessing.Process | None = None
        started = False
        reaped = False
        result: WorkerEnvelope | None = None
        primary_error: BaseException | None = None
        cleanup_errors: list[BaseException] = []
        try:
            context = multiprocessing.get_context(self.start_method)
            parent_connection, child_connection = context.Pipe(duplex=False)
            process = context.Process(
                target=_child_entry,
                args=(child_connection, provider_config, request),
                daemon=False,
            )
            process.start()
            started = True
            self._close_connection(child_connection)
            if not parent_connection.poll(timeout_seconds):
                self._reap(process, timed_out=True)
                reaped = True
                raise WorkerTimeout("worker deadline elapsed")
            try:
                data = parent_connection.recv_bytes()
            except (EOFError, OSError, ValueError) as exc:
                self._reap(process, timed_out=False)
                reaped = True
                raise RuntimeError("worker IPC failed") from exc
            self._reap(process, timed_out=False)
            reaped = True
            result = deserialize_envelope(data)
        except BaseException as exc:
            primary_error = exc
        finally:
            if process is not None and started and not reaped:
                try:
                    self._reap(process, timed_out=isinstance(primary_error, WorkerTimeout))
                    reaped = True
                except BaseException as exc:
                    cleanup_errors.append(exc)
            elif process is not None and not started:
                close = getattr(process, "close", None)
                if close is not None:
                    try:
                        close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
            for connection in (parent_connection, child_connection):
                if connection is not None:
                    try:
                        self._close_connection(connection)
                    except BaseException as exc:
                        cleanup_errors.append(exc)

        if cleanup_errors:
            # A child/pipe cleanup failure is fatal even when the provider
            # operation itself already failed; never retry with live handles.
            raise WorkerCleanupError("worker cleanup failed") from None
        if primary_error is not None:
            if isinstance(primary_error, WorkerTimeout):
                raise primary_error
            if isinstance(primary_error, RuntimeError) and str(primary_error) in {
                "worker IPC failed",
            }:
                raise primary_error
            raise RuntimeError("worker process invocation failed") from None
        if result is None:
            raise RuntimeError("worker process returned no envelope") from None
        return result

    @staticmethod
    def _close_connection(connection: Connection) -> None:
        connection.close()

    def _reap(self, process: multiprocessing.Process, *, timed_out: bool) -> None:
        cleanup_errors: list[BaseException] = []
        if process.is_alive():
            try:
                process.terminate()
            except BaseException as exc:
                # The kill fallback below is still attempted when terminate
                # cannot reach an already-crashed child.
                cleanup_errors.append(exc)
            try:
                process.join(self.cleanup_grace_seconds)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if process.is_alive():
            kill = getattr(process, "kill", None)
            if kill is not None:
                try:
                    kill()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            else:
                cleanup_errors.append(RuntimeError("worker kill is unavailable"))
            try:
                process.join(self.cleanup_grace_seconds)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if process.is_alive():
            # A live child after bounded terminate/kill is a contextual worker
            # failure; do not return while it remains attached to this call.
            raise WorkerCleanupError("worker cleanup exceeded bounded grace") from None
        else:
            try:
                process.join(self.cleanup_grace_seconds)
            except BaseException as exc:
                cleanup_errors.append(exc)
            close = getattr(process, "close", None)
            if close is not None:
                try:
                    close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        if cleanup_errors:
            raise WorkerCleanupError("worker cleanup failed") from None
        if timed_out:
            return


VisualV4Worker = V4Worker
SingleCallV4Worker = V4Worker
worker_main = _child_entry


__all__ = [
    "V4Worker",
    "VisualV4Worker",
    "SingleCallV4Worker",
    "WorkerEnvelope",
    "WorkerFailure",
    "WorkerSuccess",
    "WorkerTimeout",
    "WorkerCleanupError",
    "deserialize_envelope",
    "serialize_envelope",
    "worker_main",
]
