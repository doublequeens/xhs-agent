from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class _FrozenDict(dict[str, Any]):
    """Pickle-friendly immutable mapping used by serializable requests."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("request payload is frozen")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __reduce__(self):
        return (_FrozenDict, (dict(self),))


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenDict({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _clean_page_ids(value: Sequence[str]) -> tuple[str, ...]:
    result = tuple(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise ValueError("page_ids must contain at least one non-empty string")
    if len(set(result)) != len(result):
        raise ValueError("page_ids must be unique")
    return result


@dataclass(frozen=True, slots=True, repr=False)
class ProviderConfig:
    """Serializable provider settings passed across the v4 worker boundary.

    ``api_key`` is deliberately excluded from representation and comparison.
    The parent may hold the secret long enough to pass it to a spawned worker,
    but it is never part of a request fingerprint or a ledger payload.
    """

    provider: str = "gemini"
    model: str = "gemini-3.1-flash-image"
    api_key: str = field(default="", repr=False, compare=False)
    endpoint: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider must be a non-empty string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be a non-empty string")
        if self.endpoint is not None and not isinstance(self.endpoint, str):
            raise ValueError("endpoint must be a string or None")
        if not isinstance(self.api_key, str):
            raise ValueError("api_key must be a string")

    def __repr__(self) -> str:
        endpoint = f", endpoint={self.endpoint!r}" if self.endpoint else ""
        return f"ProviderConfig(provider={self.provider!r}, model={self.model!r}{endpoint})"

    def sanitized(self) -> dict[str, str]:
        values = {"provider": self.provider, "model": self.model}
        if self.endpoint:
            values["endpoint"] = self.endpoint
        return values


@dataclass(frozen=True, slots=True, repr=False)
class InvocationRequest:
    """The complete, serializable identity and content of one v4 request."""

    run_id: str
    run_mode: Literal["production", "shadow"]
    candidate_id: str
    revision_id: str
    node: str
    page_ids: tuple[str, ...]
    operation_kind: str
    payload: Mapping[str, Any]
    parent_revision_id: str | None = None
    image_inputs: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "candidate_id",
            "revision_id",
            "node",
            "operation_kind",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.run_mode not in ("production", "shadow"):
            raise ValueError("run_mode must be production or shadow")
        object.__setattr__(self, "page_ids", _clean_page_ids(self.page_ids))
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        object.__setattr__(self, "payload", _deep_freeze(self.payload))
        if self.parent_revision_id is not None and not isinstance(self.parent_revision_id, str):
            raise ValueError("parent_revision_id must be a string or None")
        images = tuple(self.image_inputs)
        if any(not isinstance(item, bytes) for item in images):
            raise ValueError("image_inputs must contain bytes")
        object.__setattr__(self, "image_inputs", images)
        # Fail before an AttemptStarted event if content cannot cross a worker
        # boundary.  The gateway performs a stronger canonicalization check.
        try:
            json.dumps(self._json_safe_payload(), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must contain serializable values") from exc

    def __repr__(self) -> str:
        return (
            "InvocationRequest("
            f"run_id={self.run_id!r}, run_mode={self.run_mode!r}, "
            f"candidate_id={self.candidate_id!r}, revision_id={self.revision_id!r}, "
            f"node={self.node!r}, page_ids={self.page_ids!r}, "
            f"operation_kind={self.operation_kind!r}, payload=<redacted>, "
            f"image_inputs={len(self.image_inputs)})"
        )

    def _json_safe_payload(self) -> Any:
        def convert(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, bytes):
                return {"__bytes_sha256__": __import__("hashlib").sha256(value).hexdigest()}
            if isinstance(value, Mapping):
                return {str(key): convert(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [convert(item) for item in value]
            return value

        return convert(self.payload)

    def with_payload(self, payload: Mapping[str, Any], *, image_inputs: tuple[bytes, ...] | None = None) -> "InvocationRequest":
        return InvocationRequest(
            run_id=self.run_id,
            run_mode=self.run_mode,
            candidate_id=self.candidate_id,
            revision_id=self.revision_id,
            parent_revision_id=self.parent_revision_id,
            node=self.node,
            page_ids=self.page_ids,
            operation_kind=self.operation_kind,
            payload=payload,
            image_inputs=self.image_inputs if image_inputs is None else image_inputs,
        )


@dataclass(frozen=True, slots=True)
class InvocationPolicy:
    """One invocation-wide deadline and explicitly visible retry budgets."""

    deadline_seconds: float
    max_attempts: int = 3
    max_schema_repairs: int = 1
    candidate_attempt_ceiling: int = 14
    candidate_max_attempts: int | None = None
    candidate_budget: int | None = None
    backoff_base_seconds: float = 0.05
    backoff_max_seconds: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.deadline_seconds, bool) or not isinstance(self.deadline_seconds, (int, float)) or not math.isfinite(self.deadline_seconds) or self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        for name in ("max_attempts", "max_schema_repairs", "candidate_attempt_ceiling"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                if name == "max_schema_repairs" and value == 0:
                    continue
                raise ValueError(f"{name} must be a positive integer")
        aliases = [value for value in (self.candidate_max_attempts, self.candidate_budget) if value is not None]
        if aliases:
            if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in aliases):
                raise ValueError("candidate budget aliases must be positive integers")
            if len(set(aliases)) != 1:
                raise ValueError("candidate budget aliases must agree")
            object.__setattr__(self, "candidate_attempt_ceiling", aliases[0])
        if not isinstance(self.backoff_base_seconds, (int, float)) or not isinstance(self.backoff_max_seconds, (int, float)) or not math.isfinite(self.backoff_base_seconds) or not math.isfinite(self.backoff_max_seconds) or self.backoff_base_seconds < 0 or self.backoff_max_seconds < 0:
            raise ValueError("backoff values must be non-negative")
        if self.backoff_max_seconds < self.backoff_base_seconds:
            raise ValueError("backoff_max_seconds must be at least backoff_base_seconds")


# Explicit aliases make the boundary easy to discover without coupling
# callers to one spelling used by an individual node.
VisualInvocationRequest = InvocationRequest
V4ProviderConfig = ProviderConfig
ProviderConfiguration = ProviderConfig
LLMInvocationRequest = InvocationRequest
VisualInvocationPolicy = InvocationPolicy


@dataclass(frozen=True, slots=True)
class ImageGenerationRequest:
    prompt: str
    negative_constraints: tuple[str, ...]
    width: int
    height: int
    prompt_sha256: str


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    path: Path
    mime_type: str
    sha256: str
    provider: str
    model: str
    prompt_sha256: str = ""
    response_sha256: str = ""
    generated_at: str = ""

    @property
    def internal_provenance(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_sha256": self.prompt_sha256,
            "response_sha256": self.response_sha256,
            "generated_at": self.generated_at,
        }


class StructuredVisualModel(Protocol):
    def generate_json(
        self,
        prompt: str,
        response_model: type[T],
        image_paths: Sequence[Path] = (),
    ) -> T: ...


class ImageGenerationProvider(Protocol):
    def generate(
        self,
        request: ImageGenerationRequest,
        transaction_dir: Path,
    ) -> GeneratedImage: ...
