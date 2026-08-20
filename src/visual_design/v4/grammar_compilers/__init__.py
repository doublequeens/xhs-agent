"""Deterministic v4 grammar solver registry.

The registry is keyed only by the approved grammar ID.  Family selection is
passed as canonical tokens to each solver; no solver branches on a family ID.
"""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

from src.schemas.scene_graph import SceneElement
from src.visual_design.v4.compiler import CompilerContextV4

from .comparison_grid import solve_comparison_grid
from .editorial_hero import solve_editorial_hero
from .step_flow import solve_step_flow

GrammarSolverV4 = Callable[[CompilerContextV4], tuple[SceneElement, ...]]
GRAMMAR_COMPILERS = MappingProxyType(
    {
        "editorial_hero": solve_editorial_hero,
        "comparison_grid": solve_comparison_grid,
        "step_flow": solve_step_flow,
    }
)


def get_grammar_compiler(grammar_id: str) -> GrammarSolverV4:
    try:
        return GRAMMAR_COMPILERS[grammar_id]
    except KeyError as exc:
        raise ValueError(f"v4 grammar solver is not implemented: {grammar_id}") from exc


__all__ = [
    "GRAMMAR_COMPILERS",
    "GrammarSolverV4",
    "get_grammar_compiler",
    "solve_comparison_grid",
    "solve_editorial_hero",
    "solve_step_flow",
]
