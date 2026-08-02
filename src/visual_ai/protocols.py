from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


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
