from __future__ import annotations

from typing import Any

import pytest

from src.visual_ai.factory import (
    DEFAULT_VISUAL_MODEL,
    configured_visual_model,
    get_image_generation_provider,
    get_structured_visual_model,
)
from src.visual_ai.gemini import (
    GeminiImageGenerationProvider,
    GeminiStructuredVisualModel,
)


class FakeClient:
    pass


def test_factories_share_the_only_supported_model_without_reading_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_VISUAL_MODEL", raising=False)
    client = FakeClient()

    structured = get_structured_visual_model(client=client)
    image = get_image_generation_provider(client=client)

    assert DEFAULT_VISUAL_MODEL == "gemini-3.1-flash-image"
    assert isinstance(structured, GeminiStructuredVisualModel)
    assert isinstance(image, GeminiImageGenerationProvider)
    assert structured.client is client
    assert image.client is client
    assert structured.model == image.model == DEFAULT_VISUAL_MODEL


def test_configured_visual_model_rejects_model_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_VISUAL_MODEL", "gemini-3.1-pro-preview")

    with pytest.raises(
        ValueError,
        match="GEMINI_VISUAL_MODEL must be gemini-3.1-flash-image",
    ):
        configured_visual_model()


def test_factory_rejects_model_drift_before_reading_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_VISUAL_MODEL", "different-image-model")

    with pytest.raises(
        ValueError,
        match="GEMINI_VISUAL_MODEL must be gemini-3.1-flash-image",
    ):
        get_image_generation_provider()


def test_factory_creates_developer_api_client_with_api_key_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_client(**kwargs: Any) -> FakeClient:
        calls.append(kwargs)
        return FakeClient()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_VISUAL_MODEL", raising=False)
    monkeypatch.setattr("src.visual_ai.factory.genai.Client", fake_client)

    get_structured_visual_model()

    assert calls == [{"api_key": "test-key"}]
