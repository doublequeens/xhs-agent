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


def generate_validated(
    model: StructuredVisualModel,
    *,
    prompt: str,
    response_model: type[T],
    image_paths: Sequence[Path],
    validate: Callable[[T], None],
    max_attempts: int = 3,
) -> T:
    """Generate and validate with no more than three model attempts."""
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")

    errors: list[str] = []
    raw_outputs: list[str] = []
    for _attempt in range(1, max_attempts + 1):
        candidate = model.generate_json(
            prompt=repair_prompt(prompt, errors),
            response_model=response_model,
            image_paths=image_paths,
        )
        raw_outputs.append(candidate.model_dump_json())
        try:
            validate(candidate)
            return candidate
        except (ValidationError, ValueError) as exc:
            errors.append(str(exc))
    raise VisualProductionInterrupted(
        stage="visual_director",
        errors=errors,
        raw_outputs=raw_outputs,
    )
