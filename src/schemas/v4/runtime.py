"""Strict, immutable contracts for visual Attempt Ledger events.

The ledger deliberately stores event payloads rather than mutable attempt rows.
These models are the schema boundary used both when appending and when replaying
payloads read back from SQLite.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


AttemptTerminalStatus: TypeAlias = Literal[
    "SUCCESS",
    "TRANSPORT_RETRYABLE",
    "TRANSPORT_FATAL",
    "HARD_TIMEOUT",
    "INVALID_JSON",
    "SCHEMA_INVALID",
    "CONTENT_CONTRACT_VIOLATION",
]
AttemptStatus: TypeAlias = Literal[
    "RUNNING",
    "SUCCESS",
    "TRANSPORT_RETRYABLE",
    "TRANSPORT_FATAL",
    "HARD_TIMEOUT",
    "INVALID_JSON",
    "SCHEMA_INVALID",
    "CONTENT_CONTRACT_VIOLATION",
    "UNKNOWN_AFTER_CRASH",
]

ATTEMPT_TERMINAL_STATUSES = (
    "SUCCESS",
    "TRANSPORT_RETRYABLE",
    "TRANSPORT_FATAL",
    "HARD_TIMEOUT",
    "INVALID_JSON",
    "SCHEMA_INVALID",
    "CONTENT_CONTRACT_VIOLATION",
)
ATTEMPT_STATUSES = ("RUNNING", *ATTEMPT_TERMINAL_STATUSES, "UNKNOWN_AFTER_CRASH")

Sha256 = str


def _validate_sha256(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase sha256")
    return value


def _validate_timezone(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _validate_result_ref(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or "\\" in value:
        raise ValueError("sanitized_result_ref must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("sanitized_result_ref must stay within result_root")
    if not path.parts or all(part in {"", "."} for part in path.parts):
        raise ValueError("sanitized_result_ref must name a file")
    return PurePosixPath(*[part for part in path.parts if part not in {"", "."}]).as_posix()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _validate_token_usage(
    value: dict[StrictStr, StrictInt] | None,
) -> dict[StrictStr, StrictInt] | None:
    if value is None:
        return None
    if not value:
        raise ValueError("token_usage must contain at least one count")
    if any(not key.strip() for key in value):
        raise ValueError("token_usage keys must be non-empty")
    if any(count < 0 for count in value.values()):
        raise ValueError("token_usage counts must be non-negative")
    return value


class AttemptStarted(StrictModel):
    """The immutable identity and deadline committed before a provider call."""

    attempt_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    run_id: str = Field(min_length=1)
    workflow_version: Literal["llm_scene_v4"]
    run_mode: Literal["production", "shadow"]
    candidate_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    parent_revision_id: str | None = None
    node: str = Field(min_length=1)
    page_ids: tuple[str, ...] = Field(min_length=1)
    operation_kind: str = Field(min_length=1)
    attempt_number: int = Field(gt=0)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    started_at: datetime
    deadline_at: datetime
    sequence: int | None = Field(default=None, gt=0)

    @field_validator("request_fingerprint")
    @classmethod
    def validate_request_fingerprint(cls, value: str) -> str:
        return _validate_sha256(value, field_name="request_fingerprint") or value

    @field_validator("started_at", "deadline_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info) -> datetime:
        return _validate_timezone(value, field_name=info.field_name)

    @field_validator("page_ids")
    @classmethod
    def validate_page_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not page_id for page_id in value):
            raise ValueError("page_ids must contain non-empty IDs")
        if len(set(value)) != len(value):
            raise ValueError("page_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_deadline(self) -> "AttemptStarted":
        if self.deadline_at < self.started_at:
            raise ValueError("deadline_at must not precede started_at")
        return self


class AttemptFinished(StrictModel):
    """One terminal result appended after provider output is persisted."""

    attempt_id: str = Field(min_length=1)
    completed_at: datetime
    status: AttemptTerminalStatus
    error_class: str | None = None
    provider_request_id: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: dict[StrictStr, StrictInt] | None = None
    sanitized_result_ref: str | None = None
    sanitized_result_sha256: str | None = None
    validated_contract_sha256: str | None = None
    sequence: int | None = Field(default=None, gt=0)

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, value: datetime) -> datetime:
        return _validate_timezone(value, field_name="completed_at")

    @field_validator("sanitized_result_ref")
    @classmethod
    def validate_sanitized_result_ref(cls, value: str | None) -> str | None:
        return _validate_result_ref(value)

    @field_validator("sanitized_result_sha256", "validated_contract_sha256")
    @classmethod
    def validate_hashes(cls, value: str | None, info) -> str | None:
        return _validate_sha256(value, field_name=info.field_name)

    @field_validator("token_usage")
    @classmethod
    def validate_token_usage(cls, value):
        return _validate_token_usage(value)

    @model_validator(mode="after")
    def validate_result_pair(self) -> "AttemptFinished":
        if (self.sanitized_result_ref is None) != (
            self.sanitized_result_sha256 is None
        ):
            raise ValueError(
                "sanitized_result_ref and sanitized_result_sha256 must be paired"
            )
        return self

    @property
    def result_ref(self) -> str | None:
        """Compatibility convenience for callers using the shorter result name."""

        return self.sanitized_result_ref

    @property
    def result_sha256(self) -> str | None:
        """Compatibility convenience for callers using the shorter result name."""

        return self.sanitized_result_sha256


class AttemptReconciled(StrictModel):
    """Terminal event emitted for an attempt left open across a crash."""

    attempt_id: str = Field(min_length=1)
    reconciled_at: datetime
    status: Literal["UNKNOWN_AFTER_CRASH"] = "UNKNOWN_AFTER_CRASH"
    evidence: str | dict[str, Any] = "open attempt during recovery"
    sequence: int | None = Field(default=None, gt=0)

    @field_validator("reconciled_at")
    @classmethod
    def validate_reconciled_at(cls, value: datetime) -> datetime:
        return _validate_timezone(value, field_name="reconciled_at")


class AttemptProjection(StrictModel):
    """Replay projection of one start plus at most one terminal event."""

    attempt_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    workflow_version: Literal["llm_scene_v4"]
    run_mode: Literal["production", "shadow"]
    candidate_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    parent_revision_id: str | None = None
    node: str = Field(min_length=1)
    page_ids: tuple[str, ...] = Field(min_length=1)
    operation_kind: str = Field(min_length=1)
    attempt_number: int = Field(gt=0)
    request_fingerprint: str = Field(min_length=64, max_length=64)
    started_at: datetime
    deadline_at: datetime
    status: AttemptStatus
    completed_at: datetime | None = None
    error_class: str | None = None
    provider_request_id: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    token_usage: dict[StrictStr, StrictInt] | None = None
    sanitized_result_ref: str | None = None
    sanitized_result_sha256: str | None = None
    validated_contract_sha256: str | None = None
    reconciled_at: datetime | None = None
    evidence: str | dict[str, Any] | None = None
    start_sequence: int = Field(gt=0)
    terminal_sequence: int | None = Field(default=None, gt=0)

    @field_validator("request_fingerprint")
    @classmethod
    def validate_request_fingerprint(cls, value: str) -> str:
        return _validate_sha256(value, field_name="request_fingerprint") or value

    @field_validator("started_at", "deadline_at", "completed_at", "reconciled_at")
    @classmethod
    def validate_projection_timestamps(cls, value: datetime | None, info):
        if value is None:
            return None
        return _validate_timezone(value, field_name=info.field_name)

    @field_validator("sanitized_result_ref")
    @classmethod
    def validate_projection_result_ref(cls, value: str | None) -> str | None:
        return _validate_result_ref(value)

    @field_validator("sanitized_result_sha256", "validated_contract_sha256")
    @classmethod
    def validate_projection_hashes(cls, value: str | None, info) -> str | None:
        return _validate_sha256(value, field_name=info.field_name)

    @field_validator("token_usage")
    @classmethod
    def validate_token_usage(cls, value):
        return _validate_token_usage(value)

    @model_validator(mode="after")
    def validate_projection_result_pair(self) -> "AttemptProjection":
        if (self.sanitized_result_ref is None) != (
            self.sanitized_result_sha256 is None
        ):
            raise ValueError(
                "sanitized_result_ref and sanitized_result_sha256 must be paired"
            )
        return self


def canonical_json(value: BaseModel | dict[str, Any]) -> str:
    """Serialize an event payload using the ledger's canonical JSON rules."""

    payload = value.model_dump(mode="python") if isinstance(value, BaseModel) else value

    def encode_datetime(item: Any) -> str:
        if isinstance(item, datetime):
            serialized = item.isoformat()
            return serialized[:-6] + "Z" if serialized.endswith("+00:00") else serialized
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=encode_datetime,
    )


__all__ = [
    "ATTEMPT_STATUSES",
    "ATTEMPT_TERMINAL_STATUSES",
    "AttemptFinished",
    "AttemptProjection",
    "AttemptReconciled",
    "AttemptStarted",
    "AttemptStatus",
    "AttemptTerminalStatus",
    "canonical_json",
]
