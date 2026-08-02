"""Bounded validation-repair loop for structured visual model responses."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.visual_ai import StructuredVisualModel


T = TypeVar("T", bound=BaseModel)


class VisualProductionInterrupted(RuntimeError):
    """A checkpoint-safe visual-stage failure with all repair evidence."""

    resumable = True

    def __init__(
        self,
        *,
        stage: str,
        errors: Sequence[str],
        raw_outputs: Sequence[str],
    ) -> None:
        self.stage = stage
        self.errors = tuple(errors)
        self.raw_outputs = tuple(raw_outputs)
        super().__init__(
            f"{stage} failed validation after {len(self.errors)} attempts"
        )

    def checkpoint_payload(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "errors": list(self.errors),
            "raw_outputs": list(self.raw_outputs),
            "resumable": self.resumable,
        }


def repair_prompt(prompt: str, errors: Sequence[str]) -> str:
    if not errors:
        return prompt
    feedback = "\n".join(
        f"- Attempt {index}: {error}"
        for index, error in enumerate(errors, start=1)
    )
    return (
        f"{prompt}\n\n"
        "【Validation repair required】\n"
        "Your earlier response failed the following deterministic checks:\n"
        f"{feedback}\n"
        "Return a complete corrected JSON object. Preserve every immutable "
        "source character and change only the invalid planning fields."
    )


def _repairable_error_message(exc: ValueError) -> str:
    message = str(exc)
    cause = exc.__cause__
    if isinstance(cause, (ValidationError, ValueError)):
        cause_message = str(cause)
        if cause_message and cause_message != message:
            return f"{message}\nCaused by: {cause_message}"
    return message


def _record_repairable_failure(
    exc: ValueError,
    *,
    errors: list[str],
    raw_outputs: list[str],
) -> None:
    errors.append(_repairable_error_message(exc))
    raw_response = getattr(exc, "raw_response", None)
    if isinstance(raw_response, str):
        raw_outputs.append(raw_response)


def generate_validated(
    model: StructuredVisualModel,
    *,
    prompt: str,
    response_model: type[T],
    image_paths: Sequence[Path],
    validate: Callable[[T], BaseModel | None],
    max_attempts: int = 3,
) -> T:
    """Generate and validate with no more than three model attempts.

    The ``validate`` callback may either return ``None`` (the candidate itself is
    the accepted result) or return a transformed candidate (e.g. a draft that the
    caller derives into the final contract object). Returning a non-``None``
    value lets a caller accept a model output whose wire shape differs from the
    durable contract while still routing it through the same repair loop.
    """
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")

    errors: list[str] = []
    raw_outputs: list[str] = []
    for _attempt in range(1, max_attempts + 1):
        try:
            candidate = model.generate_json(
                prompt=repair_prompt(prompt, errors),
                response_model=response_model,
                image_paths=image_paths,
            )
        except (ValidationError, ValueError) as exc:
            _record_repairable_failure(
                exc,
                errors=errors,
                raw_outputs=raw_outputs,
            )
            continue

        raw_outputs.append(candidate.model_dump_json())
        try:
            validated = validate(candidate)
            return validated if validated is not None else candidate
        except (ValidationError, ValueError) as exc:
            _record_repairable_failure(
                exc,
                errors=errors,
                raw_outputs=raw_outputs,
            )
    raise VisualProductionInterrupted(
        stage="visual_director",
        errors=errors,
        raw_outputs=raw_outputs,
    )
