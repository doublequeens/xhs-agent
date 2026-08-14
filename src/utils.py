"""Small shared helpers used across nodes, prompts and publishing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_value(payload: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a dict-like payload or an object attribute.

    Supersedes the per-module ``_get_value``/``_value`` copies; tolerates
    ``None`` payloads and treats dicts and Mappings alike.
    """
    if payload is None:
        return default
    if isinstance(payload, Mapping):
        return payload.get(key, default)
    return getattr(payload, key, default)


# Local-name aliases so the former per-module ``_get_value``/``_value``
# call sites keep working without a mass rename.
_get_value = get_value
_value = get_value
