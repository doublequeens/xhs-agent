"""Architecture guard: the obsolete fixed-template visual production path is gone.

Task 17 deletes the pre-``llm_scene_v3`` visual execution path. This guard
fails on any surviving obsolete import, graph node, or forbidden compat
symbol so the old path cannot be partially restored.
"""

from __future__ import annotations

import ast
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from src.graph import create_graph


FORBIDDEN_GRAPH_NODES = {
    "visual_strategy_planner",
    "storyboard_generator",
    "carousel_qa",
    "editorial_carousel_renderer",
}


def scan_python_imports(root: Path) -> set[str]:
    imports: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_production_graph_contains_no_obsolete_visual_nodes():
    graph = create_graph(checkpointer=InMemorySaver()).get_graph()
    assert FORBIDDEN_GRAPH_NODES.isdisjoint(graph.nodes)


def test_source_has_no_obsolete_visual_imports():
    forbidden = (
        "src.schemas.visual_plan",
        "src.schemas.storyboard",
        "src.schemas.carousel_qa",
        "src.rendering.editorial",
        "src.editorial_carousel.planner",
        "src.editorial_carousel.selector",
    )
    assert scan_python_imports(Path("src")).isdisjoint(forbidden)


def test_production_source_contains_no_obsolete_compat_symbols():
    """No surviving compat shim, feature flag, or deleted schema symbol.

    ``src/editorial_carousel/legacy.py`` is the SOLE checkpoint-migration seam
    (kept by Task 17): it must name the retired artifacts (``modern_v2``
    version marker, ``visual_plan``/``storyboards`` keys) to read and strip
    them from old checkpoints, so it is excluded from this active-code scan.
    """
    forbidden_symbols = (
        "modern_v2",
        "force_pass",
        "CarouselPayload",
        "ResolvedVariant",
        "recommended_frame_count",
    )
    offenders: dict[str, list[str]] = {}
    for path in Path("src").rglob("*.py"):
        if path.name == "legacy.py" and "editorial_carousel" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden_symbols if token in text]
        if hits:
            offenders[str(path)] = hits
    assert not offenders, f"obsolete compat symbols remain in production source: {offenders}"
