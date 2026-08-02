from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import tempfile
import time
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import Any, Sequence

from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image
from pydantic import ValidationError

from src.visual_ai.protocols import (
    GeneratedImage,
    ImageGenerationRequest,
    T,
)


_IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_PIL_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_SUPPORTED_ASPECT_RATIOS = frozenset(
    {"1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"}
)
GEMINI_VISUAL_MODEL = "gemini-3.1-flash-image"

# Transient API failures (overload, rate-limit, gateway) that are safe to
# retry with backoff. ``genai_errors.APIError`` (and its ``ServerError``
# subclass) carry a ``.code``; we also accept built-in network/timeout errors.
_TRANSIENT_ERROR_CODES = frozenset({429, 500, 502, 503, 504})
_MAX_API_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.5
# Indirection so tests can disable real sleeping.
_retry_sleep = time.sleep


def _is_transient_error(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in _TRANSIENT_ERROR_CODES:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _backoff_delay_seconds(attempt: int) -> float:
    return min(_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), 8.0)


class StructuredVisualResponseError(ValueError):
    def __init__(self, message: str, *, raw_response: str) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class ImageGenerationResponseError(ValueError):
    pass


def _validated_model(model: str) -> str:
    if model != GEMINI_VISUAL_MODEL:
        raise ValueError(f"model must be {GEMINI_VISUAL_MODEL}")
    return model


def _top_level_json_objects(raw_response: str) -> list[str]:
    objects: list[str] = []
    start: int | None = None
    depth = 0
    array_depth = 0
    in_string = False
    escaped = False

    for index, character in enumerate(raw_response):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "[" and depth == 0:
            array_depth += 1
        elif character == "]" and depth == 0 and array_depth:
            array_depth -= 1
        elif character == "{":
            if depth == 0 and array_depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(raw_response[start : index + 1])
                start = None

    return objects


def _extract_one_json_object(raw_response: str) -> dict[str, Any]:
    candidates = _top_level_json_objects(raw_response)
    if len(candidates) != 1:
        raise StructuredVisualResponseError(
            "Gemini response must contain exactly one JSON object",
            raw_response=raw_response,
        )
    try:
        value = json.loads(candidates[0])
    except json.JSONDecodeError as error:
        raise StructuredVisualResponseError(
            "Gemini response did not contain valid JSON",
            raw_response=raw_response,
        ) from error
    if not isinstance(value, dict):
        raise StructuredVisualResponseError(
            "Gemini response JSON must be an object",
            raw_response=raw_response,
        )
    return value


def _image_part(path: Path) -> types.Part:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in _IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported local image MIME type: {mime_type or 'unknown'}")
    return types.Part.from_bytes(data=path.read_bytes(), mime_type=mime_type)


def _response_text(response: Any) -> str:
    try:
        text = response.text
    except (AttributeError, ValueError) as error:
        raise StructuredVisualResponseError(
            "Gemini response did not contain text output",
            raw_response="",
        ) from error
    if not isinstance(text, str) or not text.strip():
        raise StructuredVisualResponseError(
            "Gemini response did not contain text output",
            raw_response=text if isinstance(text, str) else "",
        )
    return text


class GeminiStructuredVisualModel:
    def __init__(self, *, client: Any, model: str) -> None:
        self.client = client
        self.model = _validated_model(model)

    def generate_json(
        self,
        prompt: str,
        response_model: type[T],
        image_paths: Sequence[Path] = (),
    ) -> T:
        contents: list[str | types.Part] = [prompt]
        contents.extend(_image_part(Path(path)) for path in image_paths)
        # NOTE: the Gemini Developer API rejects response_schema for models
        # whose JSON schema carries additionalProperties (StrictModel uses
        # extra="forbid"), so we do not pass response_schema here. The prompt
        # carries the exact output shape, and the response is re-validated
        # against response_model below.
        config = types.GenerateContentConfig(response_modalities=["TEXT"])
        response = self._generate_content_with_retry(
            model=self.model,
            contents=contents,
            config=config,
        )
        raw_response = _response_text(response)
        payload = _extract_one_json_object(raw_response)
        try:
            return response_model.model_validate(payload)
        except ValidationError as error:
            raise StructuredVisualResponseError(
                "Gemini response failed schema validation",
                raw_response=raw_response,
            ) from error

    def _generate_content_with_retry(
        self, *, model: str, contents: Any, config: Any
    ) -> Any:
        """Call generate_content, retrying transient overload/rate-limit errors."""
        for attempt in range(1, _MAX_API_ATTEMPTS + 1):
            try:
                return self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except Exception as exc:
                if attempt < _MAX_API_ATTEMPTS and _is_transient_error(exc):
                    _retry_sleep(_backoff_delay_seconds(attempt))
                    continue
                raise
        # Unreachable: the loop either returns or re-raises on the last attempt.
        raise RuntimeError("generate_content retry loop exited unexpectedly")


def _request_aspect_ratio(request: ImageGenerationRequest) -> str:
    if request.width <= 0 or request.height <= 0:
        raise ValueError("image dimensions must be positive")
    divisor = gcd(request.width, request.height)
    ratio = f"{request.width // divisor}:{request.height // divisor}"
    if ratio not in _SUPPORTED_ASPECT_RATIOS:
        raise ValueError(f"unsupported Gemini image aspect ratio: {ratio}")
    return ratio


def _request_image_size(request: ImageGenerationRequest) -> str:
    longest_edge = max(request.width, request.height)
    if longest_edge <= 1024:
        return "1K"
    if longest_edge <= 2048:
        return "2K"
    if longest_edge <= 4096:
        return "4K"
    raise ValueError("Gemini image dimensions cannot exceed 4K")


def _generation_prompt(request: ImageGenerationRequest) -> str:
    if not request.negative_constraints:
        return request.prompt
    constraints = "\n".join(f"- {item}" for item in request.negative_constraints)
    return f"{request.prompt}\n\nNegative constraints:\n{constraints}"


def _image_outputs(response: Any) -> list[tuple[bytes, str]]:
    outputs: list[tuple[bytes, str]] = []
    for candidate in getattr(response, "candidates", None) or ():
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or ():
            inline_data = getattr(part, "inline_data", None)
            if inline_data is None:
                continue
            data = getattr(inline_data, "data", None)
            mime_type = getattr(inline_data, "mime_type", None)
            if isinstance(data, bytes) and isinstance(mime_type, str):
                outputs.append((data, mime_type.lower()))
    return outputs


def _valid_image_bytes(data: bytes, mime_type: str) -> bool:
    expected_format = _PIL_FORMATS.get(mime_type)
    if not data or expected_format is None:
        return False
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected_format:
                return False
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != expected_format:
                return False
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return False
    if mime_type == "image/jpeg" and not data.endswith(b"\xff\xd9"):
        return False
    if mime_type == "image/png" and not data.endswith(
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    ):
        return False
    if mime_type == "image/webp":
        if len(data) < 12 or int.from_bytes(data[4:8], "little") + 8 != len(data):
            return False
    return True


def _validated_image_output(response: Any) -> tuple[bytes, str]:
    outputs = _image_outputs(response)
    if len(outputs) != 1:
        raise ImageGenerationResponseError(
            "Gemini response must contain exactly one image output"
        )
    data, mime_type = outputs[0]
    if mime_type not in _IMAGE_EXTENSIONS or not _valid_image_bytes(data, mime_type):
        raise ImageGenerationResponseError(
            "Gemini response contained invalid image MIME type or bytes"
        )
    return data, mime_type


def _write_generated_image(
    data: bytes,
    mime_type: str,
    transaction_dir: Path,
    response_sha256: str,
) -> Path:
    root = transaction_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"generated-{response_sha256}{_IMAGE_EXTENSIONS[mime_type]}"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=root,
            prefix=".generated-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return destination


class GeminiImageGenerationProvider:
    def __init__(self, *, client: Any, model: str) -> None:
        self.client = client
        self.model = _validated_model(model)

    def generate(
        self,
        request: ImageGenerationRequest,
        transaction_dir: Path,
    ) -> GeneratedImage:
        expected_prompt_sha256 = hashlib.sha256(
            request.prompt.encode("utf-8")
        ).hexdigest()
        if request.prompt_sha256 != expected_prompt_sha256:
            raise ValueError("prompt_sha256 does not match prompt")
        response = self.client.models.generate_content(
            model=self.model,
            contents=[_generation_prompt(request)],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=_request_aspect_ratio(request),
                    image_size=_request_image_size(request),
                ),
            ),
        )
        data, mime_type = _validated_image_output(response)
        response_sha256 = hashlib.sha256(data).hexdigest()
        path = _write_generated_image(
            data,
            mime_type,
            Path(transaction_dir),
            response_sha256,
        )
        return GeneratedImage(
            path=path,
            mime_type=mime_type,
            sha256=response_sha256,
            provider="gemini",
            model=self.model,
            prompt_sha256=request.prompt_sha256,
            response_sha256=response_sha256,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
