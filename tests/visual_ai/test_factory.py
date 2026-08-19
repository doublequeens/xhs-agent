from __future__ import annotations

from typing import Any

import pytest

from src.visual_ai.factory import (
    DEFAULT_VISUAL_MODEL,
    configured_visual_model,
    get_image_generation_provider,
    get_structured_visual_model,
    get_v4_visual_llm_gateway,
)
from src.visual_ai.protocols import ProviderConfig
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


def test_v4_factory_is_lazy_and_does_not_construct_a_parent_google_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_VISUAL_MODEL", raising=False)
    calls: list[dict[str, Any]] = []

    def forbidden_client(**kwargs: Any) -> FakeClient:
        calls.append(kwargs)
        raise AssertionError("v4 factory must construct its client in the worker")

    monkeypatch.setattr("src.visual_ai.factory.genai.Client", forbidden_client)
    gateway = get_v4_visual_llm_gateway(
        ledger_path=tmp_path / "attempts.sqlite",
        result_root=tmp_path / "results",
    )

    assert gateway.provider_config.model == DEFAULT_VISUAL_MODEL
    assert calls == []


def test_default_v4_factory_requires_api_key_before_creating_run_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        get_v4_visual_llm_gateway(
            ledger_path=tmp_path / "attempts.sqlite",
            result_root=tmp_path / "results",
        )
    assert not (tmp_path / "attempts.sqlite").exists()


def test_v4_factory_accepts_explicit_fake_provider_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gateway = get_v4_visual_llm_gateway(
        provider_config=ProviderConfig(provider="fake", model="fake-model"),
        ledger_path=tmp_path / "attempts.sqlite",
        result_root=tmp_path / "results",
    )
    assert gateway.provider_config.provider == "fake"
    assert gateway.provider_config.api_key == ""
