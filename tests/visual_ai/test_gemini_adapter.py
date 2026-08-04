from __future__ import annotations

import base64
import hashlib
import io
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image
from pydantic import BaseModel, ValidationError

from src.visual_ai import gemini as gemini_module
from src.visual_ai.gemini import (
    GeminiImageGenerationProvider,
    GeminiStructuredVisualModel,
    ImageGenerationResponseError,
    StructuredVisualResponseError,
)
from src.visual_ai.protocols import ImageGenerationRequest


MODEL = "gemini-3.1-flash-image"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class VisualAnswer(BaseModel):
    title: str
    score: int


class FakeModels:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, *responses: Any) -> None:
        self.models = FakeModels(list(responses))


def text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(parts=[types.Part(text=text)])
            )
        ]
    )


def image_response(data: bytes, mime_type: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    parts=[types.Part.from_bytes(data=data, mime_type=mime_type)]
                )
            )
        ]
    )


def interaction_output(data: bytes, mime_type: str) -> SimpleNamespace:
    """An interactions.create output_image shape (.data base64, .mime_type)."""
    return SimpleNamespace(
        data=base64.b64encode(data).decode("ascii"),
        mime_type=mime_type,
    )


class FakeInteractions:
    def __init__(self, output_image: SimpleNamespace) -> None:
        self._output_image = output_image
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_image=self._output_image)


class FakeInteractionsClient:
    def __init__(self, output_image: SimpleNamespace) -> None:
        self.interactions = FakeInteractions(output_image)


def make_request(prompt: str = "Create a clean serum texture photograph.") -> ImageGenerationRequest:
    return ImageGenerationRequest(
        prompt=prompt,
        negative_constraints=("text", "logo"),
        width=1080,
        height=1440,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def raster_bytes(image_format: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color=(214, 205, 196)).save(
        buffer,
        format=image_format,
    )
    return buffer.getvalue()


@pytest.mark.parametrize(
    "adapter_type",
    [GeminiStructuredVisualModel, GeminiImageGenerationProvider],
)
def test_direct_adapter_constructors_reject_model_drift(
    adapter_type: type,
) -> None:
    with pytest.raises(
        ValueError,
        match="model must be gemini-3.1-flash-image",
    ):
        adapter_type(client=FakeClient(), model="different-image-model")


def test_structured_model_sends_local_images_as_typed_byte_parts(
    tmp_path: Path,
) -> None:
    png_path = tmp_path / "reference.png"
    jpeg_path = tmp_path / "render.jpg"
    png_path.write_bytes(PNG_BYTES)
    jpeg_path.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    client = FakeClient(text_response('Preface\n```json\n{"title":"Calm","score":9}\n```'))

    result = GeminiStructuredVisualModel(client=client, model=MODEL).generate_json(
        "Inspect these references.",
        VisualAnswer,
        (png_path, jpeg_path),
    )

    assert result == VisualAnswer(title="Calm", score=9)
    call = client.models.calls[0]
    assert call["model"] == MODEL
    assert call["contents"][0] == "Inspect these references."
    image_parts = call["contents"][1:]
    assert [
        (part.inline_data.data, part.inline_data.mime_type) for part in image_parts
    ] == [
        (PNG_BYTES, "image/png"),
        (b"\xff\xd8\xff\xe0jpeg", "image/jpeg"),
    ]
    config = call["config"]
    assert config.response_modalities == ["TEXT"]
    assert config.response_schema is None


def test_structured_model_picks_largest_json_object_when_multiple() -> None:
    """When the model emits the plan plus trailing braces/prose, the extractor
    takes the largest top-level JSON object rather than failing."""
    raw = (
        '{"title":"first","score":1}\n'
        '{"title":"the-actual-plan","score":99}\n'
    )
    adapter = GeminiStructuredVisualModel(
        client=FakeClient(text_response(raw)),
        model=MODEL,
    )

    result = adapter.generate_json("Choose.", VisualAnswer)

    assert result.title == "the-actual-plan"
    assert result.score == 99


def test_structured_model_rejects_non_object_json() -> None:
    raw = '[{"title":"wrapped","score":1}]'
    adapter = GeminiStructuredVisualModel(
        client=FakeClient(text_response(raw)),
        model=MODEL,
    )

    with pytest.raises(StructuredVisualResponseError):
        adapter.generate_json("Choose.", VisualAnswer)


def test_struct_model_repairs_slightly_invalid_json() -> None:
    """LLMs sometimes emit slightly invalid JSON (missing commas, unbalanced
    braces) on large outputs; the extractor falls back to json_repair."""
    # Missing comma after "Calm" -> normally invalid JSON.
    raw = '```json\n{"title":"Calm" "score":9}\n```'
    adapter = GeminiStructuredVisualModel(
        client=FakeClient(text_response(raw)),
        model=MODEL,
    )

    result = adapter.generate_json("Score.", VisualAnswer)

    assert result.title == "Calm"
    assert result.score == 9


def test_structured_model_exposes_raw_response_when_schema_validation_fails() -> None:
    raw_response = '{"title":"Calm","score":"not-an-integer"}'
    adapter = GeminiStructuredVisualModel(
        client=FakeClient(text_response(raw_response)),
        model=MODEL,
    )

    with pytest.raises(StructuredVisualResponseError) as exc_info:
        adapter.generate_json("Score.", VisualAnswer)

    assert exc_info.value.raw_response == raw_response
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_generation_writes_validated_bytes_and_records_internal_provenance(
    tmp_path: Path,
) -> None:
    request = make_request()
    transaction_dir = tmp_path / "transaction"
    client = FakeClient(image_response(PNG_BYTES, "image/png"))

    generated = GeminiImageGenerationProvider(
        client=client,
        model=MODEL,
    ).generate(request, transaction_dir)

    response_sha256 = hashlib.sha256(PNG_BYTES).hexdigest()
    assert generated.path.parent == transaction_dir.resolve()
    assert generated.path.read_bytes() == PNG_BYTES
    assert generated.mime_type == "image/png"
    assert generated.sha256 == response_sha256
    assert generated.provider == "gemini"
    assert generated.model == MODEL
    assert generated.prompt_sha256 == request.prompt_sha256
    assert generated.response_sha256 == response_sha256
    datetime.fromisoformat(generated.generated_at)
    assert generated.internal_provenance == {
        "provider": "gemini",
        "model": MODEL,
        "prompt_sha256": request.prompt_sha256,
        "response_sha256": response_sha256,
        "generated_at": generated.generated_at,
    }

    call = client.models.calls[0]
    assert call["model"] == MODEL
    submitted_prompt = call["contents"][0]
    assert request.prompt in submitted_prompt
    assert all(constraint in submitted_prompt for constraint in request.negative_constraints)
    assert "AI-generated" not in submitted_prompt
    assert "示意图" not in submitted_prompt
    assert "disclaimer" not in submitted_prompt.lower()
    config = call["config"]
    assert config.response_modalities == ["IMAGE"]
    assert config.image_config.aspect_ratio == "3:4"
    assert config.image_config.image_size == "1K"
    assert set(generated.internal_provenance) == {
        "provider",
        "model",
        "prompt_sha256",
        "response_sha256",
        "generated_at",
    }


@pytest.mark.parametrize(
    ("data", "mime_type"),
    [
        (b"", "image/png"),
        (b"not-a-png", "image/png"),
        (PNG_BYTES[:16], "image/png"),
        (PNG_BYTES, "text/plain"),
    ],
)
def test_generation_rejects_invalid_image_output_before_writing(
    tmp_path: Path,
    data: bytes,
    mime_type: str,
) -> None:
    transaction_dir = tmp_path / "transaction"
    adapter = GeminiImageGenerationProvider(
        client=FakeClient(image_response(data, mime_type)),
        model=MODEL,
    )

    with pytest.raises(ImageGenerationResponseError):
        adapter.generate(make_request(), transaction_dir)

    assert not transaction_dir.exists() or list(transaction_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("image_format", "mime_type", "removed_bytes"),
    [
        pytest.param("JPEG", "image/jpeg", 1, id="jpeg-minus-1"),
        pytest.param("JPEG", "image/jpeg", 10, id="jpeg-minus-10"),
        pytest.param("JPEG", "image/jpeg", 21, id="jpeg-minus-21"),
        pytest.param("PNG", "image/png", 1, id="png-minus-1"),
        pytest.param("WEBP", "image/webp", 1, id="webp-minus-1"),
    ],
)
def test_generation_rejects_truncated_raster_before_writing(
    tmp_path: Path,
    image_format: str,
    mime_type: str,
    removed_bytes: int,
) -> None:
    complete = raster_bytes(image_format)
    truncated = complete[:-removed_bytes]
    transaction_dir = tmp_path / "transaction"
    adapter = GeminiImageGenerationProvider(
        client=FakeInteractionsClient(interaction_output(truncated, mime_type)),
        model=MODEL,
    )

    with pytest.raises(ImageGenerationResponseError):
        adapter.generate(make_request(), transaction_dir)

    assert not transaction_dir.exists() or list(transaction_dir.iterdir()) == []


class TransientFailingModels:
    """Fake models that raise a transient error for the first ``fail_times``
    calls, then return ``response``. Records the call count."""

    def __init__(self, response: Any, *, fail_times: int, error: Exception) -> None:
        self._response = response
        self._fail_times = fail_times
        self._error = error
        self.calls = 0

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return self._response


class _FakeClientWithModels:
    def __init__(self, models: Any) -> None:
        self.models = models


def _server_error(code: int) -> genai_errors.ServerError:
    return genai_errors.ServerError(
        code,
        {"error": {"code": code, "message": "transient", "status": "UNAVAILABLE"}},
        None,
    )


def test_structured_model_retries_transient_503_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(gemini_module, "_retry_sleep", lambda _seconds: None)
    models = TransientFailingModels(
        text_response('{"title":"Calm","score":9}'),
        fail_times=2,
        error=_server_error(503),
    )
    client = _FakeClientWithModels(models)

    result = GeminiStructuredVisualModel(client=client, model=MODEL).generate_json(
        "Score.", VisualAnswer
    )

    assert result == VisualAnswer(title="Calm", score=9)
    assert models.calls == 3  # 2 transient failures + 1 success


def test_structured_model_raises_after_exhausting_transient_retries(monkeypatch) -> None:
    monkeypatch.setattr(gemini_module, "_retry_sleep", lambda _seconds: None)
    models = TransientFailingModels(
        text_response('{"title":"Calm","score":9}'),
        fail_times=99,  # always fails
        error=_server_error(503),
    )
    client = _FakeClientWithModels(models)

    with pytest.raises(genai_errors.ServerError):
        GeminiStructuredVisualModel(client=client, model=MODEL).generate_json(
            "Score.", VisualAnswer
        )

    assert models.calls == gemini_module._MAX_API_ATTEMPTS  # retried up to the budget


def test_structured_model_does_not_retry_non_transient_error(monkeypatch) -> None:
    monkeypatch.setattr(gemini_module, "_retry_sleep", lambda _seconds: None)
    # 400 is a client error, not transient -> no retry.
    models = TransientFailingModels(
        text_response('{"title":"Calm","score":9}'),
        fail_times=99,
        error=_server_error(400),
    )
    client = _FakeClientWithModels(models)

    with pytest.raises(genai_errors.ServerError):
        GeminiStructuredVisualModel(client=client, model=MODEL).generate_json(
            "Score.", VisualAnswer
        )

    assert models.calls == 1  # raised immediately, no retry
