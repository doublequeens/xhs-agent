"""Deterministic tests for the generic scene renderer (Task 11).

These tests NEVER launch Chromium. They drive
:func:`render_carousel_scenes` with a stub ``render_page_fn`` that returns
canned PNG bytes + raw probe dicts, so orchestration (ordering, hashing,
manifest binding, retry, contact sheet, atomic writes) is verified without a
browser. The real-Chromium path is covered by ``test_chromium_smoke.py``.
"""

from __future__ import annotations

import hashlib
import re
import struct
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from src.rendering.scene.compiler import CompiledPage
from src.rendering.scene.probes import PROBE_SCRIPT, V4_PROBE_SCRIPT
from src.rendering.scene.renderer import (
    RenderedPageDraft,
    SceneRenderError,
    _ChromiumPageRenderer,
    render_carousel_scenes,
)
from src.schemas.assets import AssetManifest, AssetManifestItem
from src.schemas.content_atoms import (
    ContentAtom,
    ContentAtomSet,
    ContentFragment,
    canonical_sha256,
    sha256_text,
)
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.scene_graph import (
    Box,
    CarouselDesignPlan,
    ImageElement,
    PageScene,
    TextElement,
    TextStyle,
)
from src.schemas.visual_director import (
    AssetDirective,
    PageDirection,
    VisualDirectionPlan,
)
from src.schemas.visual_style import FamilyStyleProfile


def test_chromium_renderer_keeps_v3_probe_default_and_accepts_v4_seam():
    default = _ChromiumPageRenderer()
    strict = _ChromiumPageRenderer(probe_script=V4_PROBE_SCRIPT)

    assert default._probe_script == PROBE_SCRIPT
    assert strict._probe_script == V4_PROBE_SCRIPT


# ---------------------------------------------------------------------------
# Fixture builders (mirror the Task 7-10 contracts)
# ---------------------------------------------------------------------------


def _atom_set(page_count: int = 5) -> ContentAtomSet:
    texts = [f"第{index}页的核心内容。" for index in range(1, page_count + 1)]
    atoms = tuple(
        ContentAtom(
            atom_id=f"atom-{index}",
            text=text,
            role="paragraph",
            sha256=sha256_text(text),
        )
        for index, text in enumerate(texts, start=1)
    )
    return ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )


def _fragments(atom_set: ContentAtomSet) -> tuple[ContentFragment, ...]:
    return tuple(
        ContentFragment(
            fragment_id=f"fragment-{index}",
            source_atom_id=atom.atom_id,
            start=0,
            end=len(atom.text),
            text=atom.text,
        )
        for index, atom in enumerate(atom_set.atoms, start=1)
    )


def _direction_plan(
    atom_set: ContentAtomSet,
    *,
    image_on_page: int | None = None,
) -> VisualDirectionPlan:
    fragments = _fragments(atom_set)
    directive = (
        AssetDirective(
            directive_id="directive-image",
            page_id=f"page-{image_on_page}",
            role="skin_example",
            required=True,
            preferred_source="search",
            fallback_source="none",
            query_or_prompt="realistic skin close-up",
            negative_constraints=("no embedded text",),
            orientation="portrait",
            min_width=1080,
            min_height=1440,
        )
        if image_on_page is not None
        else None
    )
    return VisualDirectionPlan(
        template_family="pink_red",
        page_count=len(atom_set.atoms),
        content_atom_set_sha256=atom_set.canonical_sha256,
        art_direction="护肤编辑方向",
        palette=("#F4A7BF",),
        typography_direction={"display": "醒目", "body": "清晰"},
        motifs=("red underlines",),
        content_fragments=fragments,
        page_sequence=tuple(
            PageDirection(
                page_id=f"page-{index}",
                sequence=index,
                purpose=f"解释第{index}个重点",
                visual_job=f"job-{index}",
                fragment_ids=(f"fragment-{index}",),
                asset_directive_ids=(
                    ("directive-image",) if directive and index == image_on_page else ()
                ),
            )
            for index in range(1, len(atom_set.atoms) + 1)
        ),
        asset_directives=(directive,) if directive else (),
    )


def _style_profile() -> FamilyStyleProfile:
    return FamilyStyleProfile(
        family="pink_red",
        reference_image_paths=(
            "assets/visual/beauty-editorial-v1/active/textures/serum-drops.svg",
        ),
        palette=("#F4A7BF", "#1A1A1A", "#FFFFFF"),
        font_roles={
            "display": "Test Display",
            "heading": "Test Heading",
            "body": "Test Body",
            "caption": "Test Caption",
        },
        composition_principles=("hierarchy", "whitespace"),
        whitespace_range=(0.2, 0.6),
        density_range=(0.3, 0.8),
        allowed_motifs=("underline",),
        prohibited_patterns=("clutter",),
    )


def _asset_item(asset_path: Path, *, payload: bytes) -> AssetManifestItem:
    return AssetManifestItem(
        asset_id="asset-image",
        directive_id="directive-image",
        page_id="page-1",
        source_kind="catalog",
        provider="catalog",
        license="project-owned",
        local_path=str(asset_path),
        width=1080,
        height=1440,
        sha256=hashlib.sha256(payload).hexdigest(),
        subject_focal_point=(0.5, 0.5),
        crop_guidance="centered",
        security_status="approved",
        human_decision="pending",
        run_id="run-1",
        transaction_id="tx-1",
        internal_provenance={"provider": "catalog"},
    )


def _design_plan(
    direction_plan: VisualDirectionPlan,
    atom_set: ContentAtomSet,
    manifest_items: Mapping[str, AssetManifestItem],
    *,
    page_count: int | None = None,
) -> CarouselDesignPlan:
    pages: list[PageScene] = []
    count = page_count or len(direction_plan.page_sequence)
    for index, direction_page in enumerate(direction_plan.page_sequence):
        if index >= count:
            break
        elements: list = [
            TextElement(
                element_id=f"text-{direction_page.page_id}",
                layer=1,
                box=Box(x=80, y=120, width=920, height=160),
                content_ref=direction_page.fragment_ids[0],
                style=TextStyle(
                    font_role="heading",
                    font_size=48,
                    line_height=1.3,
                    color="#1A1A1A",
                    align="left",
                    weight=700,
                ),
            )
        ]
        asset = next(
            (
                item
                for item in manifest_items.values()
                if item.page_id == direction_page.page_id
            ),
            None,
        )
        if asset is not None:
            elements.append(
                ImageElement(
                    element_id=f"image-{direction_page.page_id}",
                    layer=0,
                    box=Box(x=80, y=400, width=920, height=720),
                    asset_ref=asset.asset_id,
                    fit="cover",
                    focal_point=(0.5, 0.5),
                    corner_radius=0,
                )
            )
        pages.append(
            PageScene(
                page_id=direction_page.page_id,
                sequence=direction_page.sequence,
                background="#FFFFFF",
                elements=tuple(elements),
            )
        )
    return CarouselDesignPlan(
        direction_plan_sha256=canonical_sha256(direction_plan),
        content_atom_set_sha256=atom_set.canonical_sha256,
        asset_manifest_sha256=canonical_sha256(
            AssetManifest(items=tuple(manifest_items.values()))
        ),
        revision=0,
        pages=tuple(pages),
    )


def _passing_qa(design_plan: CarouselDesignPlan) -> DesignPlanQAResult:
    return DesignPlanQAResult(
        passed=True,
        issues=(),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=True,
        family_attestation=True,
        asset_binding_attestation=True,
    )


def _failing_qa(design_plan: CarouselDesignPlan) -> DesignPlanQAResult:
    return DesignPlanQAResult(
        passed=False,
        issues=(
            {
                "rule": "coverage",
                "message": "missing atom",
                "repair_instruction": "add element",
                "atom_id": "atom-1",
            },
        ),
        design_plan_sha256=canonical_sha256(design_plan),
        content_coverage_attestation=False,
        family_attestation=True,
        asset_binding_attestation=True,
    )


# ---------------------------------------------------------------------------
# Fake render injection seam (no browser)
# ---------------------------------------------------------------------------

_ELEMENT_RE = re.compile(
    r'data-element-id="([^"]+)"(?:[^>]*?data-content-ref="([^"]*)")?'
    r'(?:[^>]*?data-asset-ref="([^"]*)")?'
)


def _universal_raw_probe(element_id: str, content_ref: str | None, asset_ref: str | None) -> dict:
    return {
        "element_id": element_id,
        "content_ref": content_ref,
        "asset_ref": asset_ref,
        "x": 80.0,
        "y": 120.0,
        "width": 920.0,
        "height": 400.0,
        "scroll_width": 900,
        "scroll_height": 380,
        "client_width": 920,
        "client_height": 400,
        "font_family": '"Test Heading", sans-serif',
        "font_size": 48.0,
        "line_height": 62.4,
        "color": "rgb(26, 26, 26)",
        "background_color": "rgb(255, 255, 255)",
        "natural_width": 1080 if asset_ref else None,
        "natural_height": 1440 if asset_ref else None,
        "rendered_image_width": 920.0 if asset_ref else None,
        "rendered_image_height": 720.0 if asset_ref else None,
    }


def _blank_png_bytes() -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (1080, 1440), "#FFFFFF").save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class _ScriptedRenderer:
    fail_first: int = 0  # number of pages whose first attempt fails, then succeed
    always_fail: bool = False
    calls: list[CompiledPage] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = [] if self.calls is None else self.calls
        self._attempt_counts: dict[str, int] = {}

    def __call__(self, compiled_page: CompiledPage) -> RenderedPageDraft:
        self.calls.append(compiled_page)
        page_id = compiled_page.page_id
        attempts = self._attempt_counts.get(page_id, 0) + 1
        self._attempt_counts[page_id] = attempts
        if self.always_fail:
            raise RuntimeError("transient chromium failure")
        if self.fail_first and attempts <= self.fail_first:
            raise RuntimeError("transient chromium failure")
        raw_probes = []
        seen_ids = set()
        for match in _ELEMENT_RE.finditer(compiled_page.html):
            element_id = match.group(1)
            if element_id in seen_ids:
                continue
            seen_ids.add(element_id)
            content_ref = match.group(2) or None
            asset_ref = match.group(3) or None
            raw_probes.append(_universal_raw_probe(element_id, content_ref, asset_ref))
        return RenderedPageDraft(
            page_id=page_id,
            png_bytes=_blank_png_bytes(),
            raw_probes=raw_probes,
        )


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", header[16:24])


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _build_plan(page_count: int, *, image: bool, tmp_path: Path):
    atom_set = _atom_set(page_count=page_count)
    direction = _direction_plan(atom_set, image_on_page=1 if image else None)
    items: dict[str, AssetManifestItem] = {}
    if image:
        payload = b"\x89PNG\r\n\x1a\nasset-bytes"
        asset_path = tmp_path / "asset.png"
        asset_path.write_bytes(payload)
        item = _asset_item(asset_path, payload=payload)
        items[item.asset_id] = item
    design_plan = _design_plan(direction, atom_set, items, page_count=page_count)
    fragments = {frag.fragment_id: frag for frag in direction.content_fragments}
    assets = {item.asset_id: item for item in items.values()}
    return atom_set, direction, design_plan, fragments, assets


@pytest.mark.parametrize("page_count", [5, 12, 18])
def test_renders_each_page_count_with_exact_order_and_png_dimensions(tmp_path, page_count):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        page_count, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    fake = _ScriptedRenderer()

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=fake,
    )

    assert [page.sequence for page in manifest.pages] == list(range(1, page_count + 1))
    assert [page.page_id for page in manifest.pages] == [
        f"page-{index}" for index in range(1, page_count + 1)
    ]
    for rendered in manifest.pages:
        path = Path(rendered.path)
        assert path.is_file()
        assert _png_dimensions(path) == (1080, 1440)
        assert rendered.width == 1080
        assert rendered.height == 1440
        assert rendered.sha256 == _file_sha(path)
    assert len(fake.calls) == page_count


def test_every_planned_element_produces_one_probe(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=True, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    fake = _ScriptedRenderer()

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=fake,
    )

    page_one = manifest.pages[0]
    page_one_ids = [probe.element_id for probe in page_one.element_probes]
    assert page_one_ids == ["image-page-1", "text-page-1"]
    # every probe is hash-bound: image carries rendered-asset hash, text carries
    # a rasterized-text hash.
    image_probe = next(p for p in page_one.element_probes if p.kind == "image")
    text_probe = next(p for p in page_one.element_probes if p.kind == "text")
    assert image_probe.rendered_asset_sha256 == assets["asset-image"].sha256
    assert text_probe.rasterized_text_sha256 == sha256_text(
        fragments["fragment-1"].text
    )


def test_manifest_binds_every_source_hash(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=True, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=_ScriptedRenderer(),
    )

    assert manifest.design_plan_sha256 == canonical_sha256(design_plan)
    assert manifest.content_atom_set_sha256 == atom_set.canonical_sha256
    assert manifest.asset_manifest_sha256 == canonical_sha256(
        AssetManifest(items=tuple(assets.values()))
    )
    # source_asset_sha256 is the ordered map of every used asset, byte-bound.
    assert manifest.source_asset_sha256 == {
        "asset-image": hashlib.sha256(
            Path(assets["asset-image"].local_path).read_bytes()
        ).hexdigest()
    }


def test_contact_sheet_includes_all_pages_and_has_own_hash(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=_ScriptedRenderer(),
    )

    sheet = Path(manifest.contact_sheet_path)
    assert sheet.is_file()
    assert manifest.contact_sheet_sha256 == _file_sha(sheet)
    # the sheet is a real PNG and non-empty
    assert _png_dimensions(sheet)[0] > 0


def test_no_html_files_left_in_output_dir(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)

    render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=_ScriptedRenderer(),
    )

    assert not list(tmp_path.glob("*.html"))


def test_renderer_rejects_failed_design_plan_qa(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _failing_qa(design_plan)
    output_dir = tmp_path / "render"

    with pytest.raises(SceneRenderError, match="design plan QA"):
        render_carousel_scenes(
            design_plan,
            fragments=fragments,
            assets=assets,
            style=_style_profile(),
            design_plan_qa_result=qa,
            output_dir=output_dir,
            render_page_fn=_ScriptedRenderer(),
        )

    # Nothing is rendered when the gate rejects the plan.
    assert not list(output_dir.glob("*.png"))


def test_renderer_rejects_qa_hash_that_does_not_match_plan(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    poisoned = qa.model_copy(update={"design_plan_sha256": "0" * 64})

    with pytest.raises(SceneRenderError, match="hash"):
        render_carousel_scenes(
            design_plan,
            fragments=fragments,
            assets=assets,
            style=_style_profile(),
            design_plan_qa_result=poisoned,
            output_dir=tmp_path,
            render_page_fn=_ScriptedRenderer(),
        )


def test_transient_failure_retries_identical_plan_once_then_raises(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    fake = _ScriptedRenderer(always_fail=True)

    with pytest.raises(Exception, match="transient chromium failure"):
        render_carousel_scenes(
            design_plan,
            fragments=fragments,
            assets=assets,
            style=_style_profile(),
            design_plan_qa_result=qa,
            output_dir=tmp_path,
            render_page_fn=fake,
        )

    # The first page was retried exactly once with the identical compiled page.
    assert fake.calls[0].page_id == "page-1"
    assert fake.calls[1].page_id == "page-1"
    assert fake.calls[0].html == fake.calls[1].html
    # No partial PNG should be published after the raise.
    assert not list(tmp_path.glob("*.png"))


def test_transient_failure_then_success_renders_full_carousel(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    # First attempt of the first page fails; the retry succeeds and the rest
    # render normally.
    fake = _ScriptedRenderer(fail_first=1)

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=fake,
    )

    assert len(manifest.pages) == 5
    # page-1 was attempted twice; every other page once.
    page_one_calls = [call for call in fake.calls if call.page_id == "page-1"]
    assert len(page_one_calls) == 2


def test_custom_contact_sheet_fn_is_used(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    sentinel = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d49444154789c63000100000005000100"
        "0d0a2db40000000049454e44ae426082"
    )  # a real 1x1 PNG

    def custom_sheet(page_paths: Sequence[Path]) -> bytes:
        assert len(page_paths) == 5
        return sentinel

    manifest = render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        render_page_fn=_ScriptedRenderer(),
        contact_sheet_fn=custom_sheet,
    )

    assert Path(manifest.contact_sheet_path).read_bytes() == sentinel
    assert manifest.contact_sheet_sha256 == hashlib.sha256(sentinel).hexdigest()


# ---------------------------------------------------------------------------
# I1: a cleanup/teardown failure must never mask a PRIMARY render error or
# lose a successfully-built manifest. These tests drive the REAL
# _ChromiumPageRenderer context-manager protocol (no real Chromium) with a
# browser whose close() raises, so the inherited _teardown/__exit__ path is
# exercised deterministically.
# ---------------------------------------------------------------------------


class _CloseFailingBrowser:
    """Stand-in browser whose close() always fails, to force a teardown error."""

    def close(self) -> None:
        raise RuntimeError("browser.close exploded")


class _OwnedRendererNoChromium(_ChromiumPageRenderer):
    """Owned renderer that skips real Chromium but keeps the real teardown path.

    ``__enter__`` stands up a private temp dir (so rmtree succeeds) and a
    browser whose close() raises; ``_playwright`` stays None so the inherited
    ``_teardown`` collects exactly one close error. ``__call__`` delegates to a
    class-level scripted renderer so each test can drive the failed-render and
    successful-render paths. The inherited ``__exit__``/``_teardown`` (the fix
    under test) decide whether to mask, note, or record the close error.
    """

    created: list["_OwnedRendererNoChromium"] = []
    scripted: _ScriptedRenderer  # set per-test before rendering

    def __init__(self, *, playwright_factory) -> None:  # noqa: ANN001
        super().__init__(playwright_factory=playwright_factory)
        type(self).created.append(self)

    def __enter__(self) -> "_OwnedRendererNoChromium":
        self._tmpdir = Path(tempfile.mkdtemp(prefix="test-scene-cleanup-"))
        self._browser = _CloseFailingBrowser()
        return self

    def __call__(self, compiled_page: CompiledPage) -> RenderedPageDraft:
        return type(self).scripted(compiled_page)


def _render_with_owned_renderer(monkeypatch, tmp_path, *, scripted: _ScriptedRenderer):
    _OwnedRendererNoChromium.created = []
    _OwnedRendererNoChromium.scripted = scripted
    monkeypatch.setattr(
        "src.rendering.scene.renderer._ChromiumPageRenderer",
        _OwnedRendererNoChromium,
    )
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=False, tmp_path=tmp_path
    )
    qa = _passing_qa(design_plan)
    return render_carousel_scenes(
        design_plan,
        fragments=fragments,
        assets=assets,
        style=_style_profile(),
        design_plan_qa_result=qa,
        output_dir=tmp_path,
        # render_page_fn omitted -> render_carousel_scenes owns a renderer and
        # drives its context-manager protocol (the path the I1 fix hardens).
    )


def test_cleanup_failure_during_failed_render_surfaces_primary_error(monkeypatch, tmp_path):
    # The render itself fails (transient chromium failure that does not recover
    # within the single retry). The teardown path ALSO fails (browser.close).
    # The PRIMARY render error must be what surfaces; the teardown failure must
    # be attached as a note rather than masking the primary (AGENTS.md).
    with pytest.raises(SceneRenderError) as exc_info:
        _render_with_owned_renderer(
            monkeypatch, tmp_path, scripted=_ScriptedRenderer(always_fail=True)
        )

    primary = exc_info.value
    # The surfaced exception is the PRIMARY render failure, not the teardown.
    assert "transient chromium failure" in str(primary)
    assert "render failed" in str(primary)
    assert "teardown failed" not in str(primary)
    # The teardown failure is preserved as a note on the primary exception
    # (recorded, not masking).
    notes = getattr(primary, "__notes__", [])
    assert any("teardown" in note.lower() and "browser.close" in note for note in notes)


def test_cleanup_failure_during_successful_render_returns_manifest(monkeypatch, tmp_path):
    # The render succeeds. The teardown path then fails (browser.close). The
    # successfully-built manifest must still be RETURNED (not lost), and the
    # cleanup failure must be recorded rather than aborting the return.
    manifest = _render_with_owned_renderer(
        monkeypatch, tmp_path, scripted=_ScriptedRenderer()
    )

    # The manifest is returned intact even though cleanup raised.
    assert [page.sequence for page in manifest.pages] == [1, 2, 3, 4, 5]
    for rendered in manifest.pages:
        assert Path(rendered.path).is_file()
    # The cleanup failure was recorded (not silently swallowed, not masking).
    owned = _OwnedRendererNoChromium.created[0]
    recorded = getattr(owned, "_last_teardown_error", None)
    assert recorded is not None
    assert "browser.close" in str(recorded)


# ---------------------------------------------------------------------------
# I2: asset_manifest_sha256 must be recomputed from the supplied assets and
# cross-checked against the design plan, symmetric with design_plan_sha256.
# ---------------------------------------------------------------------------


def test_renderer_rejects_plan_whose_asset_manifest_hash_disagrees_with_assets(tmp_path):
    atom_set, direction, design_plan, fragments, assets = _build_plan(
        5, image=True, tmp_path=tmp_path
    )
    # Poison the plan's asset_manifest_sha256 so it disagrees with the supplied
    # assets, then rebuild a passing QA against the tampered plan so the QA gate
    # does not fire first (we want the renderer's own asset-hash check to fire).
    poisoned_plan = design_plan.model_copy(update={"asset_manifest_sha256": "0" * 64})
    qa = _passing_qa(poisoned_plan)

    with pytest.raises(SceneRenderError, match="asset_manifest_sha256"):
        render_carousel_scenes(
            poisoned_plan,
            fragments=fragments,
            assets=assets,
            style=_style_profile(),
            design_plan_qa_result=qa,
            output_dir=tmp_path,
            render_page_fn=_ScriptedRenderer(),
        )
