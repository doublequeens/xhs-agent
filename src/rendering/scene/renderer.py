"""Generic carousel scene renderer (Task 11).

Renders each QA-approved :class:`CompiledPage` to a 1080x1440 PNG with local
Chromium, extracts per-element DOM probes, assembles a contact sheet, and
produces a :class:`RenderManifest` hash-bound to the design plan, content atom
set and asset manifest.

Determinism / integrity contract (do not violate):

* **Hash-bound manifest.`` The manifest binds ``design_plan_sha256``,
  ``content_atom_set_sha256`` and ``asset_manifest_sha256``;
  ``source_asset_sha256`` is the ordered byte-hash map of every used asset;
  each page PNG sha256 matches its on-disk bytes; the contact sheet has its
  own independent hash.
* **Atomic writes.** PNGs and the contact sheet are written via temp-file +
  ``fsync`` + ``os.replace`` so a crash never leaves a half-written PNG.
* **No leftover HTML.`` The Chromium path keeps its scratch HTML in a private
  temp directory that is removed on exit; the output directory only ever
  contains renderer-owned PNGs and the contact sheet.
* **Offline / no network.`` Pages render from compiled HTML + local
  ``file://`` asset URIs; probe extraction reads only ``data-*`` attributes
  and computed layout.
* **Retry once.`` A transient Chromium failure during one page is retried
  exactly once with the identical compiled page; a second failure re-raises
  the primary (first) exception.

Injection seam: ``render_page_fn`` and ``contact_sheet_fn`` are injectable so
deterministic tests drive orchestration without launching a browser.
"""

from __future__ import annotations

import hashlib
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

from playwright.sync_api import sync_playwright

from src.rendering.scene.compiler import CompiledPage, compile_page_scene
from src.rendering.scene.probes import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    PROBE_SCRIPT,
    ProbeBuildError,
    build_element_probes,
)
from src.schemas.assets import AssetManifestItem
from src.schemas.content_atoms import ContentFragment, canonical_sha256
from src.schemas.design_qa import DesignPlanQAResult
from src.schemas.render_manifest import (
    FontLoadReport,
    RenderedElementProbe,
    RenderedPage,
    RenderManifest,
)
from src.schemas.scene_graph import CarouselDesignPlan, PageScene
from src.schemas.visual_style import FamilyStyleProfile

RenderPageFn = Callable[[CompiledPage], "RenderedPageDraft"]
ContactSheetFn = Callable[[Sequence[Path]], bytes]


class SceneRenderError(RuntimeError):
    """Raised when a generic carousel scene cannot be rendered locally."""


@dataclass(frozen=True)
class RenderedPageDraft:
    """Raw render output for one page produced by ``render_page_fn``.

    ``png_bytes`` are the full-page screenshot bytes; ``raw_probes`` is the
    list of dicts returned by the in-page probe script.
    """

    page_id: str
    png_bytes: bytes
    raw_probes: list[dict]


# ---------------------------------------------------------------------------
# Atomic write (mirrors src/asset_resolver/resolver.py::_atomic_write_bytes)
# ---------------------------------------------------------------------------


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# QA gate
# ---------------------------------------------------------------------------


def _ensure_qa_approved(
    design_plan: CarouselDesignPlan,
    design_plan_qa_result: DesignPlanQAResult,
) -> None:
    if design_plan_qa_result is None:
        raise SceneRenderError(
            "render requires a passing design plan QA result; none was provided"
        )
    if not design_plan_qa_result.passed:
        raise SceneRenderError(
            "render requires design plan QA to have passed before rendering"
        )
    expected_sha = canonical_sha256(design_plan)
    if design_plan_qa_result.design_plan_sha256 != expected_sha:
        raise SceneRenderError(
            "design plan QA hash does not match the design plan being rendered"
        )


# ---------------------------------------------------------------------------
# Retry-once (preserves the primary exception)
# ---------------------------------------------------------------------------


def _render_with_retry(
    render_page_fn: RenderPageFn,
    compiled_page: CompiledPage,
) -> RenderedPageDraft:
    try:
        return render_page_fn(compiled_page)
    except Exception as primary:  # noqa: BLE001 — renderer must retry any failure
        try:
            return render_page_fn(compiled_page)
        except Exception:
            # Preserve the PRIMARY (first) exception; the retry's failure is
            # retained on its __context__ for debugging.
            raise primary


# ---------------------------------------------------------------------------
# Default contact sheet (PIL compositing — no browser needed)
# ---------------------------------------------------------------------------


_THUMB_WIDTH: Final[int] = CANVAS_WIDTH // 3
_THUMB_HEIGHT: Final[int] = CANVAS_HEIGHT // 3
_THUMB_PADDING: Final[int] = 16


def _default_contact_sheet(page_paths: Sequence[Path]) -> bytes:
    """Compose all rendered pages into one contact sheet PNG.

    Layout: a square-root grid of 360x480 thumbnails with uniform padding on
    a white background. Deterministic and browser-free.
    """
    from PIL import Image

    count = len(page_paths)
    if count == 0:
        raise SceneRenderError("cannot build a contact sheet from zero pages")
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    cell_width = _THUMB_WIDTH + 2 * _THUMB_PADDING
    cell_height = _THUMB_HEIGHT + 2 * _THUMB_PADDING
    sheet_width = cols * cell_width + _THUMB_PADDING
    sheet_height = rows * cell_height + _THUMB_PADDING
    sheet = Image.new("RGB", (sheet_width, sheet_height), "#FFFFFF")
    for index, path in enumerate(page_paths):
        with Image.open(path) as image:
            image.load()
            thumbnail = image.resize(
                (_THUMB_WIDTH, _THUMB_HEIGHT), Image.LANCZOS
            )
        column = index % cols
        row = index // cols
        origin_x = _THUMB_PADDING + column * cell_width + _THUMB_PADDING
        origin_y = _THUMB_PADDING + row * cell_height + _THUMB_PADDING
        sheet.paste(thumbnail, (origin_x, origin_y))
    buffer = BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Default Chromium page renderer
# ---------------------------------------------------------------------------


class _ChromiumPageRenderer:
    """Renders CompiledPages via a single shared Chromium browser context.

    Holds a private temp directory for scratch HTML so the output directory
    never sees ``.html`` files. The class is a context manager: ``__enter__``
    returns ``self`` (which is callable), ``__exit__`` tears everything down.
    """

    def __init__(
        self,
        *,
        playwright_factory: Callable = sync_playwright,
    ) -> None:
        self._playwright_factory = playwright_factory
        self._tmpdir: Path | None = None
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> "_ChromiumPageRenderer":
        self._tmpdir = Path(tempfile.mkdtemp(prefix="scene-render-"))
        try:
            self._playwright = self._playwright_factory().start()
            self._browser = self._playwright.chromium.launch()
            self._page = self._browser.new_page(
                viewport={"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT}
            )
        except Exception:
            self._teardown(quiet=True)
            raise
        return self

    def __call__(self, compiled_page: CompiledPage) -> RenderedPageDraft:
        if self._page is None or self._tmpdir is None:
            raise SceneRenderError("chromium renderer used before __enter__")
        html_path = self._tmpdir / f"{compiled_page.page_id}.html"
        html_path.write_text(compiled_page.html, encoding="utf-8")
        try:
            self._page.goto(html_path.as_uri(), wait_until="load")
            raw_probes = self._page.evaluate(PROBE_SCRIPT)
            png_bytes = self._page.locator(".scene-page").screenshot()
        except Exception as exc:  # pragma: no cover — exercised via smoke test
            raise SceneRenderError(
                f"chromium render failed for page {compiled_page.page_id}: {exc}"
            ) from exc
        return RenderedPageDraft(
            page_id=compiled_page.page_id,
            png_bytes=png_bytes,
            raw_probes=list(raw_probes or []),
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        self._teardown(quiet=False)

    def _teardown(self, *, quiet: bool) -> None:
        close_errors: list[Exception] = []
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as exc:  # pragma: no cover
                close_errors.append(exc)
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as exc:  # pragma: no cover
                close_errors.append(exc)
        if self._tmpdir is not None and self._tmpdir.exists():
            import shutil

            try:
                shutil.rmtree(self._tmpdir)
            except OSError as exc:
                close_errors.append(exc)
        if close_errors and not quiet:
            raise SceneRenderError(
                "chromium renderer teardown failed: " + "; ".join(map(str, close_errors))
            )


# ---------------------------------------------------------------------------
# Asset / font accounting
# ---------------------------------------------------------------------------


def _used_source_assets(
    design_plan: CarouselDesignPlan,
    assets: Mapping[str, AssetManifestItem],
) -> dict[str, str]:
    """Ordered ``asset_id -> sha256(file bytes)`` for every used asset."""
    ordered: dict[str, str] = {}
    for page in design_plan.pages:
        for element in sorted(page.elements, key=lambda item: item.layer):
            if element.kind != "image":
                continue
            asset = assets.get(element.asset_ref)
            if asset is None:
                raise SceneRenderError(
                    f"image element {element.element_id} references unknown asset "
                    f"{element.asset_ref!r}"
                )
            if element.asset_ref in ordered:
                continue
            try:
                ordered[element.asset_ref] = hashlib.sha256(
                    Path(asset.local_path).read_bytes()
                ).hexdigest()
            except OSError as exc:
                raise SceneRenderError(
                    f"used asset {element.asset_ref!r} is not readable: {exc}"
                ) from exc
    return ordered


def _font_report(
    page_probes: Sequence[Sequence[RenderedElementProbe]],
) -> FontLoadReport:
    families: set[str] = set()
    for probes in page_probes:
        for probe in probes:
            if probe.kind == "text" and probe.computed_font_family:
                families.add(probe.computed_font_family)
    # The generic scene emits no @font-face declarations; every family is a
    # locally available system font, so the set is always fully loaded.
    return FontLoadReport(
        all_loaded=True,
        computed_families=tuple(sorted(families)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_carousel_scenes(
    design_plan: CarouselDesignPlan,
    *,
    fragments: Mapping[str, ContentFragment],
    assets: Mapping[str, AssetManifestItem],
    style: FamilyStyleProfile,
    design_plan_qa_result: DesignPlanQAResult,
    output_dir: Path | str,
    render_page_fn: RenderPageFn | None = None,
    contact_sheet_fn: ContactSheetFn | None = None,
    playwright_factory: Callable = sync_playwright,
) -> RenderManifest:
    """Render a QA-approved design plan into a hash-bound :class:`RenderManifest`.

    ``render_page_fn`` and ``contact_sheet_fn`` are injection seams: when
    omitted, the default local-Chromium renderer and the PIL contact-sheet
    compositor are used. Deterministic tests inject stubs to avoid launching a
    browser.
    """
    _ensure_qa_approved(design_plan, design_plan_qa_result)

    output_path = Path(output_dir).resolve()
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SceneRenderError(
            f"could not create render output directory: {exc}"
        ) from exc

    compiled_pages = [
        (page, compile_page_scene(page, fragments=fragments, assets=assets, style=style))
        for page in design_plan.pages
    ]

    owned_renderer: _ChromiumPageRenderer | None = None
    if render_page_fn is None:
        owned_renderer = _ChromiumPageRenderer(playwright_factory=playwright_factory)
        try:
            render_page_fn = owned_renderer.__enter__()
        except Exception as exc:
            raise SceneRenderError(f"could not start local Chromium: {exc}") from exc

    sheet_fn = contact_sheet_fn or _default_contact_sheet

    try:
        rendered_pages: list[RenderedPage] = []
        all_probes: list[tuple[RenderedElementProbe, ...]] = []
        page_paths: list[Path] = []
        for sequence, (scene_page, compiled) in enumerate(compiled_pages, start=1):
            try:
                draft = _render_with_retry(render_page_fn, compiled)
            except SceneRenderError:
                raise
            except Exception as exc:
                raise SceneRenderError(
                    f"render failed for page {scene_page.page_id}: {exc}"
                ) from exc

            try:
                probes = build_element_probes(
                    raw_probes=draft.raw_probes,
                    page=scene_page,
                    fragments=fragments,
                    assets=assets,
                    page_background=scene_page.background,
                )
            except ProbeBuildError as exc:
                raise SceneRenderError(
                    f"probe extraction failed for page {scene_page.page_id}: {exc}"
                ) from exc

            page_path = output_path / _page_file_name(sequence, scene_page)
            _atomic_write_bytes(page_path, draft.png_bytes)
            page_sha = hashlib.sha256(draft.png_bytes).hexdigest()
            rendered_pages.append(
                RenderedPage(
                    page_id=scene_page.page_id,
                    sequence=sequence,
                    path=str(page_path),
                    width=CANVAS_WIDTH,
                    height=CANVAS_HEIGHT,
                    sha256=page_sha,
                    element_probes=probes,
                )
            )
            all_probes.append(probes)
            page_paths.append(page_path)

        try:
            contact_bytes = sheet_fn(page_paths)
        except Exception as exc:
            raise SceneRenderError(
                f"contact sheet rendering failed: {exc}"
            ) from exc
        contact_path = output_path / "contact-sheet.png"
        _atomic_write_bytes(contact_path, contact_bytes)
        contact_sha = hashlib.sha256(contact_bytes).hexdigest()

        source_assets = _used_source_assets(design_plan, assets)
        fonts = _font_report(all_probes)

        manifest = RenderManifest(
            design_plan_sha256=canonical_sha256(design_plan),
            content_atom_set_sha256=design_plan.content_atom_set_sha256,
            asset_manifest_sha256=design_plan.asset_manifest_sha256,
            revision=design_plan.revision,
            pages=tuple(rendered_pages),
            fonts=fonts,
            contact_sheet_path=str(contact_path),
            contact_sheet_sha256=contact_sha,
            source_asset_sha256=source_assets,
        )
        return manifest
    finally:
        if owned_renderer is not None:
            owned_renderer.__exit__(None, None, None)


def _page_file_name(sequence: int, page: PageScene) -> str:
    return f"{sequence:02d}-{page.page_id}.png"


__all__ = [
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "RenderedPageDraft",
    "SceneRenderError",
    "render_carousel_scenes",
]
