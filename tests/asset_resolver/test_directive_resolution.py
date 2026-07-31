from __future__ import annotations

import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.asset_resolver.providers import ExternalAssetCandidate
from src.schemas.visual_director import AssetDirective
from src.visual_ai.protocols import GeneratedImage, ImageGenerationRequest
from src.visual_design.model_retry import VisualProductionInterrupted


def image_bytes(width: int = 320, height: int = 480) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), (204, 164, 150)).save(output, format="PNG")
    return output.getvalue()


def make_asset_directive(**updates) -> AssetDirective:
    values = {
        "directive_id": "asset-1",
        "page_id": "page-2",
        "role": "skin_example",
        "required": True,
        "preferred_source": "search",
        "fallback_source": "none",
        "query_or_prompt": "realistic irritated facial skin close-up",
        "negative_constraints": ("embedded text", "watermark"),
        "orientation": "portrait",
        "min_width": 300,
        "min_height": 400,
    }
    values.update(updates)
    return AssetDirective(**values)


def candidate(**updates) -> ExternalAssetCandidate:
    values = {
        "provider": "pexels",
        "provider_asset_id": "photo-1",
        "author": "Photographer",
        "source_url": "https://www.pexels.com/photo/photo-1/",
        "source_file_url": "https://images.pexels.com/photos/1/image.jpeg",
        "width": 320,
        "height": 480,
        "role": "skin_example",
        "license": "Pexels License",
        "license_snapshot": "captured Pexels license terms",
        "license_terms_url": "https://www.pexels.com/license/",
        "has_watermark": False,
        "has_logo": False,
        "has_text": False,
        "recognizable_face": False,
        "allowed_for_publishing": True,
        "provider_attribution": (("author", "Photographer"),),
    }
    values.update(updates)
    return ExternalAssetCandidate(**values)


class SearchProvider:
    name = "pexels"

    def __init__(self, results=(), *, raw: bytes | None = None) -> None:
        self.results = list(results)
        self.raw = raw or image_bytes()

    def search(self, directive):
        return list(self.results)

    def record_download(self, selected) -> None:
        return None

    def download(self, selected) -> bytes:
        return self.raw


class AlwaysFailingSearchProvider(SearchProvider):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def search(self, directive):
        raise RuntimeError(self.message)


class FakeGenerationProvider:
    def __init__(self, raw: bytes | None = None) -> None:
        self.raw = raw or image_bytes()
        self.requests: list[ImageGenerationRequest] = []

    def generate(self, request: ImageGenerationRequest, transaction_dir: Path):
        self.requests.append(request)
        transaction_dir.mkdir(parents=True, exist_ok=True)
        path = transaction_dir / "generated.png"
        path.write_bytes(self.raw)
        digest = hashlib.sha256(self.raw).hexdigest()
        return GeneratedImage(
            path=path,
            mime_type="image/png",
            sha256=digest,
            provider="gemini",
            model="gemini-3.1-flash-image",
            prompt_sha256=request.prompt_sha256,
            response_sha256=digest,
            generated_at="2026-07-31T12:00:00+00:00",
        )


class AlwaysSafeChecker:
    def check(self, path: Path, directive: AssetDirective):
        from src.asset_resolver.resolver import AssetSafetyDecision

        return AssetSafetyDecision(approved=True, unwanted_text=False)


class UnwantedTextChecker:
    def check(self, path: Path, directive: AssetDirective):
        from src.asset_resolver.resolver import AssetSafetyDecision

        return AssetSafetyDecision(
            approved=False,
            unwanted_text=True,
            reason="image contains unwanted visible text",
        )


def resolve(tmp_path: Path, directive: AssetDirective, **ports):
    from src.asset_resolver.resolver import resolve_asset_directives

    return resolve_asset_directives(
        directives=(directive,),
        transaction_root=tmp_path,
        run_id="run-42",
        transaction_id="tx-42",
        safety_checker=ports.pop("safety_checker", AlwaysSafeChecker()),
        **ports,
    )


def test_search_failure_uses_generation_only_when_directive_allows_it(
    tmp_path: Path,
) -> None:
    directive = make_asset_directive(fallback_source="generate")
    result = resolve(
        tmp_path,
        directive,
        search_provider=AlwaysFailingSearchProvider("search unavailable"),
        generation_provider=FakeGenerationProvider(),
    )

    item = result.manifest.items[0]
    assert item.source_kind == "generated"
    assert item.directive_id == directive.directive_id
    assert item.security_status == "approved"
    assert item.human_decision == "pending"


def test_search_result_binds_page_and_directive(tmp_path: Path) -> None:
    directive = make_asset_directive()
    result = resolve(
        tmp_path,
        directive,
        search_provider=SearchProvider([candidate()]),
        generation_provider=None,
    )

    item = result.manifest.items[0]
    assert (item.directive_id, item.page_id) == (
        directive.directive_id,
        directive.page_id,
    )
    assert item.source_kind == "search"
    assert item.run_id == "run-42"
    assert item.transaction_id == "tx-42"


def test_generation_records_internal_provenance(tmp_path: Path) -> None:
    directive = make_asset_directive(
        preferred_source="generate",
        fallback_source="none",
    )
    result = resolve(
        tmp_path,
        directive,
        search_provider=None,
        generation_provider=FakeGenerationProvider(),
    )

    provenance = result.manifest.items[0].internal_provenance
    assert provenance["provider"] == "gemini"
    assert provenance["model"] == "gemini-3.1-flash-image"
    assert len(provenance["prompt_sha256"]) == 64
    assert len(provenance["response_sha256"]) == 64
    assert "AI 生成示意图" not in result.manifest.items[0].model_dump_json()


def test_optional_failure_returns_unresolved_optional(tmp_path: Path) -> None:
    directive = make_asset_directive(required=False)
    result = resolve(
        tmp_path,
        directive,
        search_provider=AlwaysFailingSearchProvider("offline"),
        generation_provider=None,
    )

    assert result.manifest.items == ()
    assert result.unresolved_optional_assets[0].directive_id == directive.directive_id
    assert result.unresolved_optional_assets[0].reason == "offline"


def test_required_failure_keeps_recovery_evidence(tmp_path: Path) -> None:
    directive = make_asset_directive()

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        resolve(
            tmp_path,
            directive,
            search_provider=AlwaysFailingSearchProvider("offline"),
            generation_provider=None,
        )

    assert exc_info.value.stage == "asset_resolver"
    assert exc_info.value.errors == ("offline",)
    journal = tmp_path / "tx-42" / "recovery.json"
    assert journal.is_file()
    assert '"status":"interrupted"' in journal.read_text(encoding="utf-8")


def test_no_follow_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_bytes())

    class EscapingGenerationProvider(FakeGenerationProvider):
        def generate(self, request, transaction_dir):
            transaction_dir.mkdir(parents=True, exist_ok=True)
            path = transaction_dir / "generated.png"
            path.symlink_to(outside)
            digest = hashlib.sha256(outside.read_bytes()).hexdigest()
            return GeneratedImage(
                path=path,
                mime_type="image/png",
                sha256=digest,
                provider="gemini",
                model="gemini-3.1-flash-image",
                prompt_sha256=request.prompt_sha256,
                response_sha256=digest,
                generated_at="2026-07-31T12:00:00+00:00",
            )

    directive = make_asset_directive(
        preferred_source="generate",
        fallback_source="none",
    )
    with pytest.raises(VisualProductionInterrupted, match="asset_resolver"):
        resolve(
            tmp_path,
            directive,
            search_provider=None,
            generation_provider=EscapingGenerationProvider(),
        )


def test_unlicensed_asset_is_rejected(tmp_path: Path) -> None:
    directive = make_asset_directive()
    unlicensed = replace(candidate(), license="")

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        resolve(
            tmp_path,
            directive,
            search_provider=SearchProvider([unlicensed]),
            generation_provider=None,
        )

    assert any("license" in error for error in exc_info.value.errors)


def test_unwanted_image_text_is_rejected(tmp_path: Path) -> None:
    directive = make_asset_directive()

    with pytest.raises(VisualProductionInterrupted) as exc_info:
        resolve(
            tmp_path,
            directive,
            search_provider=SearchProvider([candidate()]),
            generation_provider=None,
            safety_checker=UnwantedTextChecker(),
        )

    assert any("unwanted visible text" in error for error in exc_info.value.errors)


def test_required_failure_preserves_primary_error_when_journal_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """M4 regression: a journal-write failure must not mask the primary errors."""
    from src.asset_resolver import resolver as resolver_module

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(resolver_module, "_persist_recovery_journal", boom)

    directive = make_asset_directive()
    with pytest.raises(VisualProductionInterrupted) as exc_info:
        resolve(
            tmp_path,
            directive,
            search_provider=AlwaysFailingSearchProvider("offline"),
            generation_provider=None,
        )

    assert exc_info.value.stage == "asset_resolver"
    assert exc_info.value.errors == ("offline",)
    assert isinstance(exc_info.value.__cause__, OSError)
