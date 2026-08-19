"""Single-call Gemini adapter used only inside v4 worker processes.

The v3 adapters intentionally retain their historical retry behavior.  This
module is a separate boundary: every function below performs at most one SDK
call and returns a small, serializable result or failure description.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import mimetypes
from dataclasses import dataclass
from typing import Any

from PIL import Image

from src.visual_ai.protocols import InvocationRequest, ProviderConfig


_TRANSIENT_CODES = frozenset({408, 429, 500, 502, 503, 504})
_SUPPORTED_MIME = frozenset({"image/png", "image/jpeg", "image/webp"})


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    retryable: bool
    error_class: str
    error_code: str
    provider_request_id: str | None = None


def _safe_request_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256:
        return None
    # Request IDs are diagnostic metadata only.  Do not permit multiline or
    # control text to enter ledger events.
    if any(ord(character) < 0x20 for character in value):
        return None
    return value


def _status_code(exc: BaseException) -> int | None:
    for candidate in (getattr(exc, "code", None), getattr(exc, "status_code", None)):
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def classify_provider_exception(exc: BaseException) -> ProviderFailure:
    """Convert an SDK/network exception to a stable, redacted classification."""

    code = _status_code(exc)
    name = type(exc).__name__.lower()
    retryable = code in _TRANSIENT_CODES or isinstance(exc, (TimeoutError, ConnectionError))
    if retryable:
        error_code = {
            408: "REQUEST_TIMEOUT",
            429: "RATE_LIMITED",
            500: "SERVER_ERROR",
            502: "BAD_GATEWAY",
            503: "UNAVAILABLE",
            504: "GATEWAY_TIMEOUT",
        }.get(code, "TRANSPORT_RETRYABLE")
        return ProviderFailure(True, "transport", error_code)
    if code is not None and 400 <= code < 500:
        return ProviderFailure(False, "request", "BAD_REQUEST")
    if "auth" in name or "permission" in name:
        return ProviderFailure(False, "provider", "AUTHENTICATION_FAILED")
    return ProviderFailure(False, "provider", "PROVIDER_FAILURE")


def _client(config: ProviderConfig) -> Any:
    # Import and client construction happen in the child process, never in the
    # parent-side v4 factory.
    from google import genai

    kwargs: dict[str, Any] = {}
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.endpoint:
        # The SDK currently accepts http_options for custom endpoints.  Keep
        # this optional and avoid exposing the endpoint in request content.
        try:
            from google.genai import types

            kwargs["http_options"] = types.HttpOptions(base_url=config.endpoint)
        except (AttributeError, TypeError):
            pass
    return genai.Client(**kwargs)


def _response_request_id(response: Any) -> str | None:
    for name in ("response_id", "request_id", "id"):
        value = _safe_request_id(getattr(response, name, None))
        if value:
            return value
    return None


def _token_usage(response: Any) -> dict[str, int] | None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    result: dict[str, int] = {}
    for output_name, source_name in (
        ("prompt", "prompt_token_count"),
        ("candidates", "candidates_token_count"),
        ("total", "total_token_count"),
    ):
        value = getattr(usage, source_name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[output_name] = value
    return result or None


def _typed_image_part(data: bytes, mime_type: str) -> Any:
    from google.genai import types

    return types.Part.from_bytes(data=data, mime_type=mime_type)


def _image_inputs(request: InvocationRequest) -> list[Any]:
    values: list[Any] = []
    mime_types = request.payload.get("image_mime_types", ())
    if not isinstance(mime_types, (list, tuple)):
        mime_types = ()
    for index, data in enumerate(request.image_inputs):
        mime_type = mime_types[index] if index < len(mime_types) else mimetypes.guess_type(f"image-{index}.png")[0]
        if not isinstance(mime_type, str) or mime_type not in _SUPPORTED_MIME:
            mime_type = "image/png"
        values.append(_typed_image_part(data, mime_type))
    return values


def _text_call(config: ProviderConfig, request: InvocationRequest) -> tuple[str, str | None, dict[str, int] | None] | ProviderFailure:
    try:
        from google.genai import types

        client = _client(config)
        prompt = request.payload.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return ProviderFailure(False, "request", "MISSING_PROMPT")
        schema = request.payload.get("repair_schema") or request.payload.get("response_schema")
        if schema is not None:
            try:
                prompt = prompt + "\nJSON schema:\n" + json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError):
                return ProviderFailure(False, "request", "INVALID_SCHEMA_GUIDANCE")
        contents: list[Any] = [prompt, *_image_inputs(request)]
        sdk_config = types.GenerateContentConfig(response_modalities=["TEXT"])
        # Exactly one provider call in this child attempt.
        response = client.models.generate_content(
            model=config.model,
            contents=contents,
            config=sdk_config,
        )
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            return ProviderFailure(False, "provider", "EMPTY_TEXT", _response_request_id(response))
        return text, _response_request_id(response), _token_usage(response)
    except Exception as exc:
        failure = classify_provider_exception(exc)
        return ProviderFailure(
            failure.retryable,
            failure.error_class,
            failure.error_code,
            failure.provider_request_id,
        )


def _image_call(config: ProviderConfig, request: InvocationRequest) -> tuple[bytes, str, str | None, dict[str, int] | None] | ProviderFailure:
    try:
        from google.genai import types

        client = _client(config)
        prompt = request.payload.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            return ProviderFailure(False, "request", "MISSING_PROMPT")
        width = request.payload.get("width", 1080)
        height = request.payload.get("height", 1440)
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            return ProviderFailure(False, "request", "INVALID_DIMENSIONS")
        # Aspect-ratio selection is intentionally local to this one call; no
        # v3 image provider or retrying adapter is imported here.
        from math import gcd

        ratio = f"{width // gcd(width, height)}:{height // gcd(width, height)}"
        sdk_config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=ratio, image_size="1K"),
        )
        response = client.models.generate_content(
            model=config.model,
            contents=[prompt],
            config=sdk_config,
        )
        outputs: list[tuple[bytes, str]] = []
        for candidate in getattr(response, "candidates", None) or ():
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or ():
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None) if inline is not None else None
                mime_type = getattr(inline, "mime_type", None) if inline is not None else None
                if isinstance(data, bytes) and isinstance(mime_type, str):
                    outputs.append((data, mime_type.lower()))
        if len(outputs) != 1:
            return ProviderFailure(False, "provider", "INVALID_IMAGE_OUTPUT", _response_request_id(response))
        data, mime_type = outputs[0]
        return data, mime_type, _response_request_id(response), _token_usage(response)
    except Exception as exc:
        failure = classify_provider_exception(exc)
        return ProviderFailure(
            failure.retryable,
            failure.error_class,
            failure.error_code,
            failure.provider_request_id,
        )


def execute(config: ProviderConfig, request: InvocationRequest) -> dict[str, Any] | ProviderFailure:
    """Perform exactly one provider operation and return a serializable value."""

    operation = request.operation_kind
    if operation in {"image_generation", "generate_image"}:
        result = _image_call(config, request)
        if isinstance(result, ProviderFailure):
            return result
        data, mime_type, provider_request_id, token_usage = result
        return {
            "kind": "success",
            "image_bytes": data,
            "mime_type": mime_type,
            "provider_request_id": provider_request_id,
            "token_usage": token_usage,
            "provider": config.provider,
            "model": config.model,
        }
    result = _text_call(config, request)
    if isinstance(result, ProviderFailure):
        return result
    text, provider_request_id, token_usage = result
    return {
        "kind": "success",
        "response_text": text,
        "provider_request_id": provider_request_id,
        "token_usage": token_usage,
        "provider": config.provider,
        "model": config.model,
    }


__all__ = ["ProviderFailure", "classify_provider_exception", "execute"]
