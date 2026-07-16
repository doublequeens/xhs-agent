from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from src.schemas.editorial_templates import TemplateFamily

from .primitives import TemplateRenderer
from .templates import (
    coral_impact,
    deep_teal,
    green_catalog,
    pink_red,
    soft_pink,
    white_quote,
)


TEMPLATE_RENDERERS: Mapping[
    TemplateFamily, TemplateRenderer
] = MappingProxyType(
    {
        "pink_red": pink_red.render_frame,
        "deep_teal": deep_teal.render_frame,
        "soft_pink": soft_pink.render_frame,
        "coral_impact": coral_impact.render_frame,
        "green_catalog": green_catalog.render_frame,
        "white_quote": white_quote.render_frame,
    }
)
