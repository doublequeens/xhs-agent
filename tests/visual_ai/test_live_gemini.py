from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from src.visual_ai.factory import (
    get_image_generation_provider,
    get_structured_visual_model,
)
from src.visual_ai.protocols import ImageGenerationRequest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_VISUAL_AI_TESTS") != "1"
    or not os.getenv("GEMINI_API_KEY"),
    reason="set RUN_LIVE_VISUAL_AI_TESTS=1 and GEMINI_API_KEY to call Gemini",
)


class LiveStructuredAnswer(BaseModel):
    ok: bool


def test_live_structured_visual_response() -> None:
    result = get_structured_visual_model().generate_json(
        'Return exactly one JSON object: {"ok": true}',
        LiveStructuredAnswer,
    )

    assert result.ok is True


def test_live_image_generation_returns_valid_image_bytes(tmp_path: Path) -> None:
    prompt = "A single ivory serum drop on a clean neutral background."
    request = ImageGenerationRequest(
        prompt=prompt,
        negative_constraints=("text", "logo", "watermark"),
        width=512,
        height=512,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )

    generated = get_image_generation_provider().generate(request, tmp_path)

    assert generated.mime_type.startswith("image/")
    assert generated.path.parent == tmp_path.resolve()
    assert generated.path.read_bytes()
