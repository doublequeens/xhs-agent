from __future__ import annotations

import os
from typing import Any

from google import genai

from src.visual_ai.gemini import (
    GEMINI_VISUAL_MODEL,
    GeminiImageGenerationProvider,
    GeminiStructuredVisualModel,
)
from src.visual_ai.protocols import (
    ImageGenerationProvider,
    InvocationPolicy,
    ProviderConfig,
    StructuredVisualModel,
)
from src.visual_runtime.attempt_ledger import AttemptLedger


DEFAULT_VISUAL_MODEL = GEMINI_VISUAL_MODEL


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


def get_v4_visual_llm_gateway(
    *,
    ledger: AttemptLedger | None = None,
    ledger_path: str | os.PathLike[str] | None = None,
    result_root: str | os.PathLike[str] | None = None,
    provider_config: ProviderConfig | None = None,
    worker: Any | None = None,
    default_policy: InvocationPolicy | None = None,
):
    """Construct the v4 gateway without creating a Google client in parent."""

    # The default Gemini path must fail before creating a ledger/run state when
    # its required secret is absent.  An explicitly injected non-Gemini config
    # is a supported seam for offline tests and local providers.
    if provider_config is None:
        model = configured_visual_model()
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required for the default v4 Gemini factory")
        config = ProviderConfig(provider="gemini", model=model, api_key=api_key)
    else:
        config = provider_config
        if config.provider == "gemini":
            model = configured_visual_model()
            if not config.api_key:
                raise ValueError("GEMINI_API_KEY is required for an injected Gemini config")
            if config.model != model:
                raise ValueError(f"v4 provider model must be {model}")
    if ledger is None:
        from pathlib import Path

        path = ledger_path or Path("data") / "agent_runs.sqlite"
        root = result_root or Path("data") / "visual_v4_results"
        ledger = AttemptLedger(path, result_root=root)
    elif result_root is not None and ledger.result_root is None:
        raise ValueError("result_root must be configured on the supplied ledger")
    from src.visual_ai.gateway import VisualLLMGateway

    gateway = VisualLLMGateway(
        worker=worker,
        ledger=ledger,
        provider_config=config,
        default_policy=default_policy,
    )
    return gateway


get_v4_gateway = get_v4_visual_llm_gateway
get_visual_llm_gateway_v4 = get_v4_visual_llm_gateway
get_v4_visual_gateway = get_v4_visual_llm_gateway
get_v4_llm_gateway = get_v4_visual_llm_gateway
get_visual_gateway_v4 = get_v4_visual_llm_gateway
