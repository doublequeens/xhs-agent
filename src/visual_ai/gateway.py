"""Cancellable, single-retry-layer LLM gateway for visual-production v4."""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import ntpath
import os
import random
import re
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Generic, Mapping, TypeVar
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, ValidationError

from src.visual_ai.protocols import (
    InvocationPolicy,
    InvocationRequest,
    LLMInvocationRequest,
    ProviderConfiguration,
    ProviderConfig,
    V4ProviderConfig,
    VisualInvocationRequest,
)
from src.visual_ai.v4_worker import (
    V4Worker,
    WorkerFailure,
    WorkerSuccess,
    WorkerTimeout,
)
from src.visual_runtime.attempt_ledger import AttemptLedger, AttemptLedgerError


T = TypeVar("T", bound=BaseModel)
_SUPPORTED_IMAGE_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})
_STATUS_CODES = frozenset(
    {
        "SUCCESS",
        "TRANSPORT_RETRYABLE",
        "TRANSPORT_FATAL",
        "HARD_TIMEOUT",
        "INVALID_JSON",
        "SCHEMA_INVALID",
        "CONTENT_CONTRACT_VIOLATION",
    }
)
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "client_secret",
        "credential_id",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "secret_key",
        "password",
        "credential",
        "cookie",
        "cookies",
    }
)
_ATTEMPT_METADATA_KEYS = frozenset(
    {"timestamp", "started_at", "deadline_at", "attempt_number", "retry_count"}
)
_PATH_BEARING_TOKENS = frozenset(
    {
        "path",
        "paths",
        "root",
        "roots",
        "dir",
        "dirs",
        "directory",
        "directories",
        "file",
        "files",
        "local",
        "workspace",
        "cache",
        "location",
    }
)
_INPUT_OUTPUT_TOKENS = frozenset({"input", "inputs", "output", "outputs"})
_KEY_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+")
_IMAGE_VALIDATION_CONTRACT_VERSION = "llm_scene_v4.image_validation_contract.v1"
IMAGE_VALIDATION_CONTRACT_SHA256 = hashlib.sha256(
    _IMAGE_VALIDATION_CONTRACT_VERSION.encode("utf-8")
).hexdigest()


class VisualInvocationError(RuntimeError):
    """Redacted, stable error exposed to v4 callers."""

    def __init__(
        self,
        status: str,
        *,
        error_class: str | None = None,
        error_code: str | None = None,
        attempt_number: int | None = None,
    ) -> None:
        if status not in _STATUS_CODES:
            status = "TRANSPORT_FATAL"
        self.status = status
        self.error_class = _safe_error_class(error_class) if error_class else status
        self.error_code = _safe_error_code(error_code, status) if error_code else status
        self.attempt_number = attempt_number
        suffix = f" ({self.error_class})"
        if attempt_number is not None:
            suffix += f" attempt={attempt_number}"
        # Deliberately no exception body, prompt, response text, path, or key.
        super().__init__(f"{status}{suffix}")


@dataclass(frozen=True, slots=True)
class StructuredInvocationResult(Generic[T]):
    value: T
    attempt_id: str | None
    request_fingerprint: str
    provider_request_id: str | None = None
    token_usage: dict[str, int] | None = None
    validated_contract_sha256: str | None = None
    reused: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedImageResult:
    data: bytes
    mime_type: str
    sha256: str
    provider: str
    model: str
    attempt_id: str | None
    request_fingerprint: str
    provider_request_id: str | None = None
    token_usage: dict[str, int] | None = None
    reused: bool = False

    @property
    def bytes(self) -> bytes:
        return self.data


def _schema_hash(response_model: type[BaseModel]) -> str:
    try:
        schema = response_model.model_json_schema()
        canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except Exception as exc:
        raise ValueError("response model schema is not serializable") from None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _key_tokens(value: str) -> tuple[str, ...]:
    """Split snake/kebab/camel application keys into stable lowercase tokens."""

    tokens: list[str] = []
    for component in re.split(r"[-_\s]+", value):
        tokens.extend(match.group(0).lower() for match in _KEY_TOKEN_RE.finditer(component))
    return tuple(tokens)


def _is_path_bearing_key(value: str) -> bool:
    """Recognize explicit path metadata without classifying bare input/output."""

    tokens = _key_tokens(value)
    if any(token in _PATH_BEARING_TOKENS for token in tokens):
        return True
    return any(token in _INPUT_OUTPUT_TOKENS for token in tokens) and any(
        token in _PATH_BEARING_TOKENS for token in tokens
    )


class _ResultStoreError(RuntimeError):
    """Sanitized result-store failure retaining primary/cleanup facts."""

    def __init__(
        self,
        *,
        primary_code: str | None = None,
        cleanup_codes: tuple[str, ...] = (),
    ) -> None:
        self.primary_code = primary_code
        self.cleanup_codes = tuple(cleanup_codes)
        self.has_primary_failure = primary_code is not None
        self.has_cleanup_failure = bool(self.cleanup_codes)
        if self.has_primary_failure and self.has_cleanup_failure:
            self.public_code = "RESULT_STORE_PRIMARY_AND_CLEANUP"
        elif self.has_primary_failure:
            self.public_code = "RESULT_STORE_PRIMARY"
        else:
            self.public_code = "RESULT_STORE_CLEANUP"
        super().__init__(self.public_code)

    def with_cleanup(self, cleanup_codes: list[str]) -> "_ResultStoreError":
        if not cleanup_codes:
            return self
        return _ResultStoreError(
            primary_code=self.primary_code,
            cleanup_codes=self.cleanup_codes + tuple(cleanup_codes),
        )


def _safe_fingerprint_value(
    value: Any,
    *,
    key: str | None = None,
    path_context: bool = False,
) -> Any:
    if key is not None and key.lower().replace("-", "_") in _SECRET_KEYS:
        return "<redacted>"
    if isinstance(value, Path):
        if value.is_absolute():
            # Absolute local roots are never fingerprint material.
            return "<local-path>"
        # Relative paths are content identity and use a platform-independent
        # representation without consulting the current working directory.
        return value.as_posix()
    if isinstance(value, bytes):
        return {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key_text = str(raw_key)
            normalized_key = key_text.lower().replace("-", "_")
            if normalized_key in _SECRET_KEYS:
                continue
            if normalized_key in _ATTEMPT_METADATA_KEYS:
                continue
            result[key_text] = _safe_fingerprint_value(
                item,
                key=key_text,
                path_context=path_context or _is_path_bearing_key(key_text),
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _safe_fingerprint_value(item, key=key, path_context=path_context)
            for item in value
        ]
    if isinstance(value, str):
        # A local path can occur under an arbitrary application-specific key;
        # only path-bearing metadata keys may opt into path normalization.
        # ``ntpath`` covers Windows paths when fingerprints are produced on
        # another OS.  Slash-prefixed prompt/content text remains semantic
        # request data.
        if path_context and (
            os.path.isabs(value) or ntpath.isabs(value)
        ):
            return "<local-path>"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _find_secret_field(value: Any) -> str | None:
    """Find a secret-bearing request key without inspecting its value."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key_text = str(raw_key)
            if key_text.lower().replace("-", "_") in _SECRET_KEYS:
                return key_text
            found = _find_secret_field(item)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_secret_field(item)
            if found is not None:
                return found
    return None


def response_model_schema_hash(response_model: type[BaseModel]) -> str:
    return _schema_hash(response_model)


def request_fingerprint(
    request: InvocationRequest,
    provider_config: ProviderConfig,
    response_model: type[BaseModel] | None = None,
    *,
    schema_issue_codes: tuple[str, ...] = (),
    original_fingerprint: str | None = None,
) -> str:
    """Compute the canonical, credential-free identity of a request."""

    content = {
        "provider": provider_config.provider,
        "model": provider_config.model,
        "operation_kind": request.operation_kind,
        "payload": _safe_fingerprint_value(request.payload),
        "image_inputs": [
            {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for data in request.image_inputs
        ],
    }
    if response_model is not None:
        content["response_schema_sha256"] = _schema_hash(response_model)
    if schema_issue_codes:
        content["schema_repair"] = {
            "original_request_fingerprint": original_fingerprint or request_fingerprint(request, provider_config, response_model),
            "issue_codes": sorted({str(code) for code in schema_issue_codes}),
        }
    return hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()


def _strip_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) < 3 or not lines[-1].strip() == "```":
        return value
    if lines[0].strip() not in {"```", "```json"}:
        return value
    return "\n".join(lines[1:-1]).strip()


@dataclass(frozen=True, slots=True)
class _ParseFailure:
    status: str
    issue_code: str


def _strict_parse(text: str, response_model: type[T]) -> T | _ParseFailure:
    if not isinstance(text, str) or not text.strip():
        return _ParseFailure("INVALID_JSON", "empty_response")
    candidate = _strip_fence(text)
    try:
        def reject_constant(_value: str) -> Any:
            raise ValueError("non-standard JSON constant")

        def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        payload = json.loads(
            candidate,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return _ParseFailure("INVALID_JSON", "invalid_json")
    try:
        return response_model.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        return _ParseFailure("SCHEMA_INVALID", "schema_validation")


def _valid_image_bytes(data: bytes, mime_type: str) -> bool:
    if not isinstance(data, bytes) or not data or mime_type not in _SUPPORTED_IMAGE_MIME:
        return False
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[mime_type]
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected:
                return False
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected:
                return False
            image.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False
    return True


def _safe_token_usage(value: Mapping[str, Any] | None) -> dict[str, int] | None:
    if value is None:
        return None
    result: dict[str, int] = {}
    for key, count in value.items():
        if isinstance(key, str) and isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            result[key] = count
    return result or None


def _safe_provider_request_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(ord(char) < 0x20 for char in value):
        return None
    return value


def _safe_error_class(value: Any) -> str:
    if not isinstance(value, str):
        return "worker"
    value = value.strip().lower()
    allowed = {"transport", "provider", "request", "worker", "input", "result_store", "candidate_budget", "ledger"}
    if value in allowed:
        return value
    return "worker"


def _safe_error_code(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        return fallback
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in value):
        return fallback
    return value


def _safe_model_metadata(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        return fallback
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/-" for character in value):
        return fallback
    return value


class VisualLLMGateway:
    """Parent-side budget, process, retry, parsing, and result-store owner."""

    def __init__(
        self,
        *,
        worker: Any | None = None,
        ledger: AttemptLedger,
        provider_config: ProviderConfig,
        default_policy: InvocationPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[int], float] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(ledger, AttemptLedger):
            raise TypeError("ledger must be an AttemptLedger")
        if not isinstance(provider_config, ProviderConfig):
            provider_config = ProviderConfig(**dict(provider_config))  # type: ignore[arg-type]
        self.worker = worker if worker is not None else V4Worker()
        self.ledger = ledger
        self.provider_config = provider_config
        self.default_policy = default_policy or InvocationPolicy(deadline_seconds=90.0)
        self.sleep = sleep
        self.jitter = jitter or (lambda _attempt: random.random())
        self.monotonic = monotonic
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def invoke_structured(
        self,
        request: InvocationRequest,
        response_model: type[T],
        policy: InvocationPolicy | None = None,
    ) -> T:
        self._validate_request(request)
        if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
            raise TypeError("response_model must be a Pydantic BaseModel class")
        effective_policy = self._policy(policy)
        schema_sha256 = _schema_hash(response_model)
        payload = dict(request.payload)
        payload.setdefault("response_schema", response_model.model_json_schema())
        normalized_request = request.with_payload(payload)
        fingerprint = request_fingerprint(normalized_request, self.provider_config, response_model)

        reusable = self.ledger.reusable_result(fingerprint)
        if reusable is not None:
            if reusable.validated_contract_sha256 == schema_sha256:
                try:
                    value = self._value_from_bytes(reusable.content, response_model)
                except (VisualInvocationError, ValueError, TypeError):
                    value = None
                if value is not None:
                    return value

        def parse(envelope: WorkerSuccess) -> tuple[T, bytes] | _ParseFailure:
            if envelope.response_text is None:
                return _ParseFailure("INVALID_JSON", "missing_text")
            parsed = _strict_parse(envelope.response_text, response_model)
            if isinstance(parsed, _ParseFailure):
                return parsed
            try:
                output = _canonical_model_bytes(parsed)
            except (TypeError, ValueError):
                return _ParseFailure("SCHEMA_INVALID", "serialization_failure")
            return parsed, output

        result = self._run_attempts(
            normalized_request,
            fingerprint=fingerprint,
            response_model=response_model,
            policy=effective_policy,
            parse_success=parse,
            result_kind="structured",
            schema_sha256=schema_sha256,
        )
        assert isinstance(result, StructuredInvocationResult)
        return result.value

    def generate_image(
        self,
        request: InvocationRequest,
        policy: InvocationPolicy | None = None,
    ) -> GeneratedImageResult:
        self._validate_request(request)
        effective_policy = self._policy(policy)
        fingerprint = request_fingerprint(request, self.provider_config)
        reusable = self.ledger.reusable_result(fingerprint)
        if reusable is not None:
            mime_type = _mime_from_ref(reusable.result_ref)
            if (
                reusable.validated_contract_sha256 == IMAGE_VALIDATION_CONTRACT_SHA256
                and mime_type
                and hashlib.sha256(reusable.content).hexdigest() == reusable.result_sha256
                and _valid_image_bytes(reusable.content, mime_type)
            ):
                return GeneratedImageResult(
                    data=reusable.content,
                    mime_type=mime_type,
                    sha256=hashlib.sha256(reusable.content).hexdigest(),
                    provider=self.provider_config.provider,
                    model=self.provider_config.model,
                    attempt_id=reusable.attempt_id,
                    request_fingerprint=fingerprint,
                    reused=True,
                )

        def parse(envelope: WorkerSuccess) -> tuple[GeneratedImageResult, bytes] | _ParseFailure:
            if envelope.image_bytes is None or not envelope.mime_type or not _valid_image_bytes(envelope.image_bytes, envelope.mime_type):
                return _ParseFailure("CONTENT_CONTRACT_VIOLATION", "invalid_image")
            data = bytes(envelope.image_bytes)
            return GeneratedImageResult(
                data=data,
                mime_type=envelope.mime_type,
                sha256=hashlib.sha256(data).hexdigest(),
                provider=_safe_model_metadata(envelope.provider, self.provider_config.provider),
                model=_safe_model_metadata(envelope.model, self.provider_config.model),
                attempt_id=None,
                request_fingerprint=fingerprint,
                provider_request_id=_safe_provider_request_id(envelope.provider_request_id),
                token_usage=_safe_token_usage(envelope.token_usage),
            ), data

        result = self._run_attempts(
            request,
            fingerprint=fingerprint,
            response_model=None,
            policy=effective_policy,
            parse_success=parse,
            result_kind="image",
            schema_sha256=IMAGE_VALIDATION_CONTRACT_SHA256,
        )
        assert isinstance(result, GeneratedImageResult)
        return result

    def evaluate_images(
        self,
        request: InvocationRequest,
        response_model: type[T],
        policy: InvocationPolicy | None = None,
    ) -> T:
        self._validate_request(request)
        normalized = self._load_image_inputs(request)
        return self.invoke_structured(normalized, response_model, policy)

    def invoke(
        self,
        request: InvocationRequest,
        response_model: type[T] | None = None,
        policy: InvocationPolicy | None = None,
    ) -> Any:
        if response_model is None:
            raise TypeError("v4 structured invocation requires response_model")
        return self.invoke_structured(request, response_model, policy)

    def _policy(self, policy: InvocationPolicy | None) -> InvocationPolicy:
        if policy is None:
            return self.default_policy
        if not isinstance(policy, InvocationPolicy):
            policy = InvocationPolicy(**dict(policy))  # type: ignore[arg-type]
        return policy

    @staticmethod
    def _validate_request(request: InvocationRequest) -> None:
        if not isinstance(request, InvocationRequest):
            raise TypeError("request must be an InvocationRequest")
        secret_field = _find_secret_field(request.payload)
        if secret_field is not None:
            raise ValueError(f"request payload contains secret field {secret_field!r}")

    def _load_image_inputs(self, request: InvocationRequest) -> InvocationRequest:
        self._validate_request(request)
        paths = request.payload.get("image_paths", ())
        if paths is None:
            paths = ()
        if not isinstance(paths, (list, tuple)):
            raise VisualInvocationError("TRANSPORT_FATAL", error_class="input")
        if not paths:
            if not request.image_inputs:
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="input")
            raw_mime_types = request.payload.get("image_mime_types", ())
            if not isinstance(raw_mime_types, (list, tuple)) or len(raw_mime_types) != len(request.image_inputs):
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="input")
            for data, mime_type in zip(request.image_inputs, raw_mime_types, strict=True):
                if not isinstance(mime_type, str) or not _valid_image_bytes(data, mime_type):
                    raise VisualInvocationError("CONTENT_CONTRACT_VIOLATION", error_class="input") from None
            return request
        if request.image_inputs:
            # Do not silently discard a second source of bytes.  Callers must
            # choose either path-backed inputs or direct bytes so every input
            # is validated and fingerprinted exactly once.
            raise VisualInvocationError("TRANSPORT_FATAL", error_class="input")
        contents: list[bytes] = []
        mime_types: list[str] = []
        for raw_path in paths:
            path = Path(raw_path)
            try:
                if not path.is_file() or path.is_symlink():
                    raise OSError("missing image input")
                data = path.read_bytes()
            except (OSError, ValueError):
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="input") from None
            mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
            if not _valid_image_bytes(data, mime_type):
                raise VisualInvocationError("CONTENT_CONTRACT_VIOLATION", error_class="input") from None
            contents.append(data)
            mime_types.append(mime_type)
        payload = dict(request.payload)
        payload.pop("image_paths", None)
        payload["image_mime_types"] = tuple(mime_types)
        return request.with_payload(payload, image_inputs=tuple(contents))

    def _run_attempts(
        self,
        request: InvocationRequest,
        *,
        fingerprint: str,
        response_model: type[BaseModel] | None,
        policy: InvocationPolicy,
        parse_success: Callable[[WorkerSuccess], tuple[Any, bytes] | _ParseFailure],
        result_kind: str,
        schema_sha256: str | None,
    ) -> Any:
        invocation_start = self.monotonic()
        deadline_mono = invocation_start + policy.deadline_seconds
        started_wall = self.wall_clock()
        if started_wall.tzinfo is None or started_wall.utcoffset() is None:
            raise ValueError("wall_clock must return timezone-aware datetime")
        deadline_wall = started_wall + timedelta(seconds=policy.deadline_seconds)
        attempts = 0
        schema_repairs = 0
        current_request = request
        current_fingerprint = fingerprint
        last_error: VisualInvocationError | None = None

        while attempts < policy.max_attempts:
            remaining = deadline_mono - self.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise VisualInvocationError("HARD_TIMEOUT")
            try:
                consumed = self.ledger.consumed_attempts(request.run_id, request.candidate_id)
            except AttemptLedgerError:
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="ledger") from None
            if consumed >= policy.candidate_attempt_ceiling:
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="candidate_budget") from None
            attempts += 1
            attempt_number = consumed + 1
            started_at = self.wall_clock()
            try:
                started = self.ledger.start(
                    {
                        "run_id": request.run_id,
                        "workflow_version": "llm_scene_v4",
                        "run_mode": request.run_mode,
                        "candidate_id": request.candidate_id,
                        "revision_id": request.revision_id,
                        "parent_revision_id": request.parent_revision_id,
                        "node": request.node,
                        "page_ids": request.page_ids,
                        "operation_kind": request.operation_kind,
                        "attempt_number": attempt_number,
                        "request_fingerprint": current_fingerprint,
                        "started_at": started_at,
                        "deadline_at": deadline_wall,
                    }
                )
            except Exception:
                raise VisualInvocationError("TRANSPORT_FATAL", error_class="ledger", attempt_number=attempt_number) from None

            attempt_started_mono = self.monotonic()
            terminal_status: str | None = None
            provider_request_id: str | None = None
            token_usage: dict[str, int] | None = None
            try:
                try:
                    worker_remaining = max(0.0, deadline_mono - self.monotonic())
                    envelope = self._invoke_worker(current_request, worker_remaining)
                except WorkerTimeout:
                    terminal_status = "HARD_TIMEOUT"
                    last_error = VisualInvocationError(terminal_status, attempt_number=attempt_number)
                except Exception:
                    terminal_status = "TRANSPORT_FATAL"
                    last_error = VisualInvocationError(terminal_status, error_class="worker", attempt_number=attempt_number)
                if terminal_status is None:
                    if isinstance(envelope, WorkerFailure):
                        provider_request_id = _safe_provider_request_id(envelope.provider_request_id)
                        terminal_status = "TRANSPORT_RETRYABLE" if envelope.retryable else "TRANSPORT_FATAL"
                        last_error = VisualInvocationError(
                            terminal_status,
                            error_class=_safe_error_class(envelope.error_class),
                            error_code=_safe_error_code(envelope.error_code, terminal_status),
                            attempt_number=attempt_number,
                        )
                    elif not isinstance(envelope, WorkerSuccess):
                        terminal_status = "TRANSPORT_FATAL"
                        last_error = VisualInvocationError(terminal_status, error_class="worker", attempt_number=attempt_number)
                    else:
                        provider_request_id = _safe_provider_request_id(envelope.provider_request_id)
                        token_usage = _safe_token_usage(envelope.token_usage)
                        parsed = parse_success(envelope)
                        if isinstance(parsed, _ParseFailure):
                            terminal_status = parsed.status
                            last_error = VisualInvocationError(terminal_status, error_class=parsed.issue_code, attempt_number=attempt_number)
                        else:
                            value, result_bytes = parsed
                            try:
                                result_ref, result_sha = self._persist_result(result_kind, started.attempt_id, result_bytes)
                            except Exception as exc:
                                terminal_status = "TRANSPORT_FATAL"
                                last_error = VisualInvocationError(
                                    terminal_status,
                                    error_class="result_store",
                                    error_code=(
                                        exc.public_code
                                        if isinstance(exc, _ResultStoreError)
                                        else None
                                    ),
                                    attempt_number=attempt_number,
                                )
                            else:
                                # Persistence and the terminal ledger append
                                # are deliberately separate.  If the append
                                # acknowledgement is ambiguous, the helper
                                # inspects the durable projection before making
                                # one bounded, state-appropriate retry.
                                self._finish_success_with_reconciliation(
                                    started.attempt_id,
                                    attempt_number=attempt_number,
                                    provider_request_id=provider_request_id,
                                    latency_ms=max(0.0, (self.monotonic() - attempt_started_mono) * 1000),
                                    token_usage=token_usage,
                                    sanitized_result_ref=result_ref,
                                    sanitized_result_sha256=result_sha,
                                    validated_contract_sha256=schema_sha256,
                                )
                                if isinstance(value, GeneratedImageResult):
                                    value = GeneratedImageResult(
                                        data=value.data,
                                        mime_type=value.mime_type,
                                        sha256=value.sha256,
                                        provider=_safe_model_metadata(value.provider, self.provider_config.provider),
                                        model=_safe_model_metadata(value.model, self.provider_config.model),
                                        attempt_id=started.attempt_id,
                                        request_fingerprint=fingerprint,
                                        provider_request_id=_safe_provider_request_id(value.provider_request_id),
                                        token_usage=value.token_usage,
                                        reused=False,
                                    )
                                else:
                                    value = StructuredInvocationResult(
                                        value=value,
                                        attempt_id=started.attempt_id,
                                        request_fingerprint=fingerprint,
                                        provider_request_id=provider_request_id,
                                        token_usage=token_usage,
                                        reused=False,
                                    )
                                return value
            finally:
                if terminal_status is not None:
                    self._finish_terminal_with_reconciliation(
                        started.attempt_id,
                        attempt_number=attempt_number,
                        status=terminal_status,
                        error_class=(last_error.error_class if last_error is not None else terminal_status),
                        provider_request_id=provider_request_id,
                        latency_ms=max(0.0, (self.monotonic() - attempt_started_mono) * 1000),
                        token_usage=token_usage,
                    )

            if last_error is None:
                last_error = VisualInvocationError("TRANSPORT_FATAL", attempt_number=attempt_number)
            if terminal_status in {"INVALID_JSON", "SCHEMA_INVALID"} and schema_repairs < policy.max_schema_repairs and attempts < policy.max_attempts:
                remaining = deadline_mono - self.monotonic()
                if remaining <= 0:
                    raise last_error
                schema_repairs += 1
                issue_code = last_error.error_class
                repair_payload = dict(request.payload)
                original_prompt = repair_payload.get("prompt", "")
                if not isinstance(original_prompt, str):
                    original_prompt = ""
                repair_payload["prompt"] = original_prompt + "\nReturn only JSON matching the supplied schema."
                repair_payload["repair"] = True
                repair_payload["repair_schema_sha256"] = schema_sha256
                repair_payload["repair_guidance"] = "strict_json_and_schema"
                repair_payload["repair_schema"] = response_model.model_json_schema() if response_model is not None else {}
                current_request = request.with_payload(repair_payload, image_inputs=request.image_inputs)
                current_fingerprint = request_fingerprint(
                    current_request,
                    self.provider_config,
                    response_model,
                    schema_issue_codes=(issue_code,),
                    original_fingerprint=fingerprint,
                )
                continue
            if terminal_status in {"TRANSPORT_RETRYABLE", "HARD_TIMEOUT"} and attempts < policy.max_attempts:
                remaining = deadline_mono - self.monotonic()
                if remaining <= 0:
                    raise last_error
                delay = min(
                    remaining,
                    policy.backoff_max_seconds,
                    policy.backoff_base_seconds * (2 ** max(0, attempts - 1)) + max(0.0, self.jitter(attempts)),
                )
                if delay > 0:
                    self.sleep(delay)
                if self.monotonic() >= deadline_mono:
                    raise last_error
                current_request = request
                current_fingerprint = fingerprint
                continue
            raise last_error
        if last_error is not None:
            raise last_error
        raise VisualInvocationError("TRANSPORT_FATAL")

    def _finish_success_with_reconciliation(
        self,
        attempt_id: str,
        *,
        attempt_number: int,
        provider_request_id: str | None,
        latency_ms: float,
        token_usage: dict[str, int] | None,
        sanitized_result_ref: str,
        sanitized_result_sha256: str,
        validated_contract_sha256: str | None,
    ) -> None:
        """Append one SUCCESS terminal, resolving an ambiguous append safely.

        SQLite append acknowledgement can be lost after the durable insert.  A
        projection check distinguishes that case from an open attempt.  Only
        an observed open attempt is eligible for one bounded retry; if the
        state cannot be read, the attempt remains available to the ledger's
        recovery/reconciliation path and a redacted ledger error is raised.
        """

        finish_kwargs = {
            "status": "SUCCESS",
            "provider_request_id": provider_request_id,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
            "sanitized_result_ref": sanitized_result_ref,
            "sanitized_result_sha256": sanitized_result_sha256,
            "validated_contract_sha256": validated_contract_sha256,
        }
        self._finish_terminal_with_reconciliation(
            attempt_id,
            attempt_number=attempt_number,
            **finish_kwargs,
        )

    def _finish_terminal_with_reconciliation(
        self,
        attempt_id: str,
        *,
        attempt_number: int,
        status: str,
        **finish_kwargs: Any,
    ) -> None:
        """Append one terminal event, retrying only an observed open state."""

        finish_kwargs = {"status": status, **finish_kwargs}
        try:
            self.ledger.finish(attempt_id, **finish_kwargs)
            return
        except Exception:
            projection = self._safe_projection(attempt_id, attempt_number)
            if projection.status == status:
                return
            if projection.status != "RUNNING":
                raise VisualInvocationError(
                    "TRANSPORT_FATAL", error_class="ledger", attempt_number=attempt_number
                ) from None

        try:
            self.ledger.finish(attempt_id, **finish_kwargs)
            return
        except Exception:
            projection = self._safe_projection(attempt_id, attempt_number)
            if projection.status == status:
                return
            # Keep the open attempt and persisted artifact for explicit
            # reconciliation.  A blind third append could create a duplicate
            # terminal if the second failure was also post-commit.
            raise VisualInvocationError(
                "TRANSPORT_FATAL", error_class="ledger", attempt_number=attempt_number
            ) from None

    def _safe_projection(self, attempt_id: str, attempt_number: int) -> Any:
        try:
            return self.ledger.projection(attempt_id)
        except Exception:
            raise VisualInvocationError(
                "TRANSPORT_FATAL", error_class="ledger", attempt_number=attempt_number
            ) from None

    def _invoke_worker(self, request: InvocationRequest, timeout_seconds: float) -> WorkerSuccess | WorkerFailure:
        worker = self.worker
        method = getattr(worker, "invoke_once", None)
        if method is None:
            method = getattr(worker, "invoke", None)
        if method is None and callable(worker):
            method = worker
        if method is None:
            raise RuntimeError("worker does not implement invoke_once")
        result = method(self.provider_config, request, timeout_seconds)
        if isinstance(result, (WorkerSuccess, WorkerFailure)):
            return result
        raise RuntimeError("worker returned an invalid envelope")

    def _persist_result(self, kind: str, attempt_id: str, data: bytes) -> tuple[str, str]:
        root = self.ledger.result_root
        if root is None:
            raise RuntimeError("result_root is required")
        if not isinstance(data, bytes):
            raise TypeError("result bytes required")
        if kind not in {"structured", "image"}:
            raise ValueError("unsupported result kind")
        suffix = ".json" if kind == "structured" else _extension_for_mime(data)
        relative = Path("v4") / kind / f"{attempt_id}{suffix}"
        digest = hashlib.sha256(data).hexdigest()
        owned_fds: dict[int, str] = {}
        kind_fd: int | None = None
        temporary_name: str | None = None
        primary_error: _ResultStoreError | None = None
        cleanup_errors: list[str] = []
        try:
            # The final root component is opened without following a symlink;
            # child directories are then resolved only through directory file
            # descriptors.  This keeps v4/kind containment intact even when a
            # pre-existing path component is hostile.
            root_fd = self._open_result_root(root)
            owned_fds[root_fd] = "result-root"
            v4_fd = self._open_result_directory(root_fd, "v4")
            owned_fds[v4_fd] = "result-v4"
            kind_fd = self._open_result_directory(v4_fd, kind)
            owned_fds[kind_fd] = f"result-{kind}"

            temporary_name = f".result-{uuid4().hex}.tmp"
            temp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._no_follow_flag() | self._close_on_exec_flag()
            temp_fd = os.open(temporary_name, temp_flags, 0o600, dir_fd=kind_fd)
            owned_fds[temp_fd] = "result-temporary"
            write_failed = False
            close_errors: list[str] = []
            try:
                offset = 0
                while offset < len(data):
                    written = os.write(temp_fd, data[offset:])
                    if written <= 0:
                        raise OSError("result write made no progress")
                    offset += written
                os.fsync(temp_fd)
            except BaseException:
                write_failed = True
            finally:
                close_errors = self._close_owned_fd(owned_fds, temp_fd)
            if write_failed or close_errors:
                raise _ResultStoreError(
                    primary_code="temporary_write" if write_failed else None,
                    cleanup_codes=tuple(close_errors),
                ) from None

            os.replace(
                temporary_name,
                f"{attempt_id}{suffix}",
                src_dir_fd=kind_fd,
                dst_dir_fd=kind_fd,
            )
            temporary_name = None
            # Sync the containing directory and its parents so the rename is
            # durable before the ledger SUCCESS event is appended.
            os.fsync(kind_fd)
            os.fsync(v4_fd)
            os.fsync(root_fd)
        except _ResultStoreError as exc:
            primary_error = exc
        except BaseException:
            primary_error = _ResultStoreError(primary_code="operation")
        finally:
            if temporary_name is not None and kind_fd is not None:
                try:
                    os.unlink(temporary_name, dir_fd=kind_fd)
                except FileNotFoundError:
                    pass
                except BaseException:
                    cleanup_errors.append("result-temporary-unlink")
            for descriptor in tuple(owned_fds):
                cleanup_errors.extend(self._close_owned_fd(owned_fds, descriptor))
        if primary_error is not None:
            raise primary_error.with_cleanup(cleanup_errors) from None
        if cleanup_errors:
            raise _ResultStoreError(cleanup_codes=tuple(cleanup_errors)) from None
        return relative.as_posix(), digest

    @staticmethod
    def _no_follow_flag() -> int:
        return int(getattr(os, "O_NOFOLLOW", 0))

    @staticmethod
    def _close_on_exec_flag() -> int:
        return int(getattr(os, "O_CLOEXEC", 0))

    @classmethod
    def _directory_open_flags(cls) -> int:
        return os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0)) | cls._no_follow_flag() | cls._close_on_exec_flag()

    @classmethod
    def _close_owned_fd(cls, owned_fds: dict[int, str], descriptor: int) -> list[str]:
        """Release ownership before one best-effort close, never retrying an fd."""

        label = owned_fds.pop(descriptor, "result-fd")
        try:
            os.close(descriptor)
        except BaseException:
            # A failed close may have released and reused the numeric fd in
            # another thread.  Ownership is gone and the number is never
            # inspected or touched again by this cleanup path.
            return [f"{label}.close"]
        return []

    @classmethod
    def _cleanup_owned_fds(cls, owned_fds: dict[int, str]) -> list[str]:
        errors: list[str] = []
        for descriptor in tuple(owned_fds):
            errors.extend(cls._close_owned_fd(owned_fds, descriptor))
        return errors

    @classmethod
    def _open_result_root(cls, root: Path) -> int:
        """Create/open an absolute root by descriptor-relative components."""

        absolute = Path(os.path.abspath(os.fspath(root)))
        components = absolute.parts
        if not components or components[0] != os.sep:
            raise _ResultStoreError(primary_code="root_absolute") from None
        owned_fds: dict[int, str] = {}
        try:
            descriptor = os.open(os.sep, cls._directory_open_flags())
            owned_fds[descriptor] = "result-root-parent"
            for component in components[1:]:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                next_descriptor = os.open(
                    component,
                    cls._directory_open_flags(),
                    dir_fd=descriptor,
                )
                owned_fds[next_descriptor] = "result-root-component"
                close_errors = cls._close_owned_fd(owned_fds, descriptor)
                if close_errors:
                    raise _ResultStoreError(
                        primary_code="root_descriptor_close",
                        cleanup_codes=tuple(close_errors),
                    ) from None
                descriptor = next_descriptor
            owned_fds.pop(descriptor, None)
            return descriptor
        except _ResultStoreError as exc:
            cleanup_errors = cls._cleanup_owned_fds(owned_fds)
            raise exc.with_cleanup(cleanup_errors) from None
        except BaseException:
            cleanup_errors = cls._cleanup_owned_fds(owned_fds)
            raise _ResultStoreError(
                primary_code="root_open",
                cleanup_codes=tuple(cleanup_errors),
            ) from None

    @classmethod
    def _open_result_directory(cls, parent_fd: int, name: str) -> int:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except BaseException:
            raise _ResultStoreError(primary_code="directory_create") from None
        try:
            descriptor = os.open(name, cls._directory_open_flags(), dir_fd=parent_fd)
        except BaseException:
            raise _ResultStoreError(primary_code="directory_open") from None
        owned_fds = {descriptor: "result-directory"}
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise _ResultStoreError(primary_code="directory_validation") from None
            owned_fds.pop(descriptor, None)
            return descriptor
        except _ResultStoreError as exc:
            cleanup_errors = cls._cleanup_owned_fds(owned_fds)
            raise exc.with_cleanup(cleanup_errors) from None
        except BaseException:
            cleanup_errors = cls._cleanup_owned_fds(owned_fds)
            raise _ResultStoreError(
                primary_code="directory_validation",
                cleanup_codes=tuple(cleanup_errors),
            ) from None

    @staticmethod
    def _value_from_bytes(data: bytes, response_model: type[T]) -> T:
        try:
            parsed = _strict_parse(data.decode("utf-8"), response_model)
            if isinstance(parsed, _ParseFailure):
                raise ValueError(parsed.issue_code)
            canonical = _canonical_model_bytes(parsed)
            if canonical != data:
                raise ValueError("non-canonical result bytes")
            return parsed
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise VisualInvocationError("SCHEMA_INVALID", error_class="reuse_validation") from None


def _canonical_model_bytes(model: BaseModel) -> bytes:
    return _canonical(model.model_dump(mode="json")).encode("utf-8")


def _mime_from_ref(reference: str) -> str | None:
    mime_type, _ = mimetypes.guess_type(reference)
    return mime_type if mime_type in _SUPPORTED_IMAGE_MIME else None


def _extension_for_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


__all__ = [
    "GeneratedImageResult",
    "InvocationPolicy",
    "InvocationRequest",
    "LLMInvocationRequest",
    "ProviderConfiguration",
    "ProviderConfig",
    "StructuredInvocationResult",
    "V4ProviderConfig",
    "VisualInvocationError",
    "VisualInvocationRequest",
    "VisualLLMGateway",
    "request_fingerprint",
    "response_model_schema_hash",
]
