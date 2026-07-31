from __future__ import annotations

import os
from typing import Any

from google import genai

from src.visual_ai.gemini import (
    GeminiImageGenerationProvider,
    GeminiStructuredVisualModel,
)
from src.visual_ai.protocols import (
    ImageGenerationProvider,
    StructuredVisualModel,
)


DEFAULT_VISUAL_MODEL = "gemini-3.1-flash-image"


def configured_visual_model() -> str:
    model = os.environ.get("GEMINI_VISUAL_MODEL", DEFAULT_VISUAL_MODEL)
    if model != DEFAULT_VISUAL_MODEL:
        raise ValueError("GEMINI_VISUAL_MODEL must be gemini-3.1-flash-image")
    return model


def _developer_api_client() -> Any:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def get_structured_visual_model(
    *,
    client: Any | None = None,
) -> StructuredVisualModel:
    model = configured_visual_model()
    return GeminiStructuredVisualModel(
        client=client if client is not None else _developer_api_client(),
        model=model,
    )


def get_image_generation_provider(
    *,
    client: Any | None = None,
) -> ImageGenerationProvider:
    model = configured_visual_model()
    return GeminiImageGenerationProvider(
        client=client if client is not None else _developer_api_client(),
        model=model,
    )
