"""Shared LangGraph checkpoint serializer configuration.

``src/graph.py`` (the production v3 graph) and the graph-free v4 review CLI
must read and write SQLite checkpoints through the same trusted-schema
allowlist. The factory lives in this small module so local-only tooling can
configure the serializer without importing the graph module and its
node/model/browser import graph.
"""

from __future__ import annotations

from pydantic import BaseModel


def trusted_schema_classes() -> list[type[BaseModel]]:
    """Pydantic models defined in our own packages that may round-trip
    through the SQLite checkpoint.

    LangGraph's checkpoint serializer encodes every custom pydantic class stored
    in state as a typed ``(module, class, data)`` blob. On read-back it warns for
    any type not on its built-in safe list — once per node, every run — because
    the whole state is deserialized at the start of each node. Registering these
    classes via ``allowed_msgpack_modules`` silences the warning while keeping
    the objects intact (no business-code changes).

    We enumerate ``BaseModel`` subclasses under ``src.`` / ``memory.`` rather
    than hand-listing them, so new schema classes are covered automatically.
    Which subclasses exist depends on the modules already imported:
    importing ``src.schemas`` (``AgentState``) covers everything the persisted
    state can hold; review tooling imports the review schema modules directly.
    """

    def _all_subclasses(cls: type):
        for sub in cls.__subclasses__():
            yield sub
            yield from _all_subclasses(sub)

    trusted: list[type[BaseModel]] = []
    seen: set[type] = set()
    for cls in _all_subclasses(BaseModel):
        module = getattr(cls, "__module__", "") or ""
        if module.startswith(("src.", "memory.")) and cls not in seen:
            seen.add(cls)
            trusted.append(cls)
    return trusted


def checkpoint_serializer():
    """Build one serializer with the shared trusted-schema configuration."""

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(allowed_msgpack_modules=trusted_schema_classes())
