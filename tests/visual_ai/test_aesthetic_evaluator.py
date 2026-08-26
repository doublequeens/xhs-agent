from __future__ import annotations

from dataclasses import dataclass, field
import pytest

from src.schemas.v4.critique import (
    AestheticIssueDraftV4,
    AestheticPageDraftV4,
    AestheticPagePassV4,
    AestheticSetDraftV4,
    AestheticSetPassV4,
)
from src.visual_ai.aesthetic_evaluator import build_aesthetic_request, evaluate_aesthetics


def test_critic_request_omits_revision_round_and_authoring_prompt():
    request = build_aesthetic_request(
        run_id="run-1",
        run_mode="shadow",
        candidate_id="candidate-1",
        revision_id="revision-1",
        page_ids=("page-1",),
        page_roles=("cover",),
        page_duties=("state the skincare promise",),
        image_bytes=(b"png-bytes",),
        image_mime_types=("image/png",),
        pass_kind="page",
    )

    payload = dict(request.payload)
    assert "revision_round" not in payload
    assert "authoring_prompt" not in payload


def test_blind_provider_prompt_contains_allowlisted_page_context_not_hashes_or_paths():
    request = build_aesthetic_request(
        run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1",
        page_ids=("page-1",), page_roles=("cover",), page_duties=("state semantic promise",),
        image_bytes=(b"png-bytes",), image_mime_types=("image/png",), pass_kind="page",
        source_bindings={
            "render_manifest_sha256": "a" * 64, "render_qa_result_sha256": "b" * 64,
            "page_brief_set_sha256": "c" * 64, "semantic_content_model_sha256": "d" * 64,
        },
    )
    assert "prompt" in request.payload
    assert "cover" in request.payload["prompt"]
    assert "state semantic promise" in request.payload["prompt"]
    assert "a" * 64 not in request.payload["prompt"]
    with pytest.raises(ValueError):
        build_aesthetic_request(
            run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1",
            page_ids=("page-1",), page_roles=("/private/tmp",), page_duties=("safe duty",),
            image_bytes=(b"png-bytes",), image_mime_types=("image/png",), pass_kind="page",
        )


@pytest.mark.parametrize("field_name, bad_text", (
    ("role", "assets/layout.json"), ("role", "provider metadata"),
    ("role", "Procfile"),
    ("duty", "C:work.txt"), ("duty", "prompt history"),
    ("duty", "requirements"),
))
def test_aesthetic_request_rejects_path_and_metadata_in_roles_and_duties(field_name, bad_text):
    kwargs = {
        "page_roles": (bad_text,) if field_name == "role" else ("cover",),
        "page_duties": (bad_text,) if field_name == "duty" else ("state the skincare promise",),
    }
    with pytest.raises(ValueError):
        build_aesthetic_request(
            run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1",
            page_ids=("page-1",), image_bytes=(b"png-bytes",), image_mime_types=("image/png",),
            pass_kind="page", **kwargs,
        )


def test_aesthetic_request_keeps_ordinary_role_and_duty_words():
    request = build_aesthetic_request(
        run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1",
        page_ids=("page-1", "page-2"), page_roles=("cover", "steps"),
        page_duties=("introduce the promise", "explain the steps"),
        image_bytes=(b"png", b"png"), image_mime_types=("image/png", "image/png"), pass_kind="page",
    )
    assert tuple(page["role"] for page in request.payload["pages"]) == ("cover", "steps")


@dataclass
class _Gateway:
    calls: list = field(default_factory=list)

    def evaluate_images(self, request, response_model, *args):
        self.calls.append((request, response_model))
        if response_model is AestheticPagePassV4:
            return AestheticPagePassV4(pages=tuple(
                AestheticPageDraftV4(
                    page_id=page_id, hierarchy=90, readability=90, composition=90,
                    whitespace=90, visual_focus=90, asset_integration=90,
                ) for page_id in request.page_ids
            ))
        return AestheticSetPassV4(set_evaluation=AestheticSetDraftV4(
            rhythm=90, repetition=90, family_consistency=90, cover_body_consistency=90,
        ))


def test_evaluator_calls_page_then_set_with_only_blind_payloads():
    gateway = _Gateway()
    page_ids = tuple(f"page-{index}" for index in range(1, 6))

    result = evaluate_aesthetics(
        gateway=gateway, run_id="run-1", run_mode="shadow", candidate_id="candidate-1",
        revision_id="revision-1", page_ids=page_ids, page_roles=("cover",) * 5,
        page_duties=("semantic-duty",) * 5, image_bytes=(b"bytes",) * 5,
        image_mime_types=("image/png",) * 5, render_manifest_sha256="a" * 64,
        render_qa_result_sha256="b" * 64, page_brief_set_sha256="c" * 64,
        semantic_content_model_sha256="d" * 64, authoring_model_identity="author",
        evaluator_model_identity="evaluator",
    )

    assert result.passed is True
    assert [item[0].payload["pass_kind"] for item in gateway.calls] == ["page", "set"]
    assert "page_observations" not in gateway.calls[0][0].payload
    assert tuple(item["page_id"] for item in gateway.calls[1][0].payload["page_observations"]) == page_ids
    for request, _model in gateway.calls:
        rendered = repr(request.payload).lower()
        assert "revision_round" not in rendered
        assert "authoring_prompt" not in rendered
        assert "image_paths" not in request.payload
        assert set(request.payload["source_bindings"]) == {
            "render_manifest_sha256", "render_qa_result_sha256",
            "page_brief_set_sha256", "semantic_content_model_sha256",
        }


def test_evaluator_rejects_missing_duplicate_or_reordered_page_observations():
    class BadGateway(_Gateway):
        def evaluate_images(self, request, response_model, *args):
            if response_model is AestheticPagePassV4:
                return AestheticPagePassV4(pages=tuple(
                    AestheticPageDraftV4(
                        page_id="page-1", hierarchy=90, readability=90, composition=90,
                        whitespace=90, visual_focus=90, asset_integration=90,
                    ) for _ in request.page_ids
                ))
            return super().evaluate_images(request, response_model, *args)

    with pytest.raises(ValueError, match="exactly once in order"):
        evaluate_aesthetics(
            gateway=BadGateway(), run_id="run-1", run_mode="shadow", candidate_id="candidate-1",
            revision_id="revision-1", page_ids=tuple(f"page-{i}" for i in range(1, 6)),
            page_roles=("cover",) * 5, page_duties=("semantic-duty",) * 5,
            image_bytes=(b"bytes",) * 5, image_mime_types=("image/png",) * 5,
            render_manifest_sha256="a" * 64, render_qa_result_sha256="b" * 64,
            page_brief_set_sha256="c" * 64, semantic_content_model_sha256="d" * 64,
            authoring_model_identity="author", evaluator_model_identity="critic",
        )


@pytest.mark.parametrize("evidence", ("C:work.txt", "layout.json", "provider metadata"))
def test_evaluator_rejects_bad_pass_one_evidence_before_set_call(evidence):
    class Gateway(_Gateway):
        def evaluate_images(self, request, response_model, *args):
            self.calls.append((request, response_model))
            if response_model is AestheticPagePassV4:
                bad_issue = AestheticIssueDraftV4.model_construct(
                    severity="major", dimension="composition", page_ids=("page-1",), evidence=evidence,
                )
                pages = tuple(AestheticPageDraftV4.model_construct(
                    page_id=page_id, hierarchy=90, readability=90, composition=90,
                    whitespace=90, visual_focus=90, asset_integration=90,
                    issues=(bad_issue,) if page_id == "page-1" else (),
                ) for page_id in request.page_ids)
                self.page_result = AestheticPagePassV4.model_construct(pages=pages)
                return self.page_result
            raise AssertionError("set pass must not run")
    gateway = Gateway()
    with pytest.raises(ValueError):
        evaluate_aesthetics(gateway=gateway, run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1", page_ids=tuple(f"page-{i}" for i in range(1, 6)), page_roles=("cover",) * 5, page_duties=("semantic duty",) * 5, image_bytes=(b"bytes",) * 5, image_mime_types=("image/png",) * 5, render_manifest_sha256="a" * 64, render_qa_result_sha256="b" * 64, page_brief_set_sha256="c" * 64, semantic_content_model_sha256="d" * 64, authoring_model_identity=None, evaluator_model_identity=None)
    assert type(gateway.page_result) is AestheticPagePassV4
    assert gateway.calls[0][1] is AestheticPagePassV4
    assert len(gateway.calls) == 1


def test_v4_gemini_provider_seam_receives_the_blind_prompt(monkeypatch):
    from types import SimpleNamespace
    from src.visual_ai import v4_gemini
    from src.visual_ai.protocols import ProviderConfig

    request = build_aesthetic_request(
        run_id="run-1", run_mode="shadow", candidate_id="candidate-1", revision_id="revision-1",
        page_ids=("page-1",), page_roles=("cover",), page_duties=("state semantic promise",),
        image_bytes=(b"png-bytes",), image_mime_types=("image/png",), pass_kind="page",
    )

    class Models:
        def __init__(self): self.contents = None
        def generate_content(self, **kwargs):
            self.contents = kwargs["contents"]
            return SimpleNamespace(text="{}")
    models = Models()
    monkeypatch.setattr(v4_gemini, "_client", lambda _config: SimpleNamespace(models=models))
    result = v4_gemini._text_call(ProviderConfig(), request)

    assert not isinstance(result, v4_gemini.ProviderFailure)
    assert models.contents[0] == request.payload["prompt"]
    assert "cover" in models.contents[0]
    assert "state semantic promise" in models.contents[0]
