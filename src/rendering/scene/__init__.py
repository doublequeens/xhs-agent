"""Generic scene-to-HTML compiler package.

The single public entry point is :func:`compile_page_scene`, which turns one
:class:`~src.schemas.scene_graph.PageScene` into self-contained HTML using a
single generic code path over the five primitives (``text``, ``image``,
``shape``, ``line``, ``icon``). All six template families share this path.
"""

from __future__ import annotations

from .compiler import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CompiledPage,
    MissingContentRefError,
    SceneAssetError,
    SceneCompilationError,
    compile_element,
    compile_page_scene,
)
from .fonts import (
    GENERIC_FALLBACK,
    MissingFontRoleError,
    format_font_family,
    resolve_font_stack,
)

__all__ = [
    "CANVAS_HEIGHT",
    "CANVAS_WIDTH",
    "CompiledPage",
    "GENERIC_FALLBACK",
    "MissingContentRefError",
    "MissingFontRoleError",
    "SceneAssetError",
    "SceneCompilationError",
    "compile_element",
    "compile_page_scene",
    "format_font_family",
    "resolve_font_stack",
]
