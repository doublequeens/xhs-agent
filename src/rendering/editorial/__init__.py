"""Project-local beauty editorial carousel rendering."""

from typing import Any

from .layouts import TEMPLATE_RENDERERS

__all__ = [
    "EditorialCarouselRenderError",
    "TEMPLATE_RENDERERS",
    "render_carousel",
]


def __getattr__(name: str) -> Any:
    if name in {"EditorialCarouselRenderError", "render_carousel"}:
        from .renderer import (
            EditorialCarouselRenderError,
            render_carousel,
        )

        return {
            "EditorialCarouselRenderError": EditorialCarouselRenderError,
            "render_carousel": render_carousel,
        }[name]
    raise AttributeError(name)
