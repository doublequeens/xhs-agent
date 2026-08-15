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


def require_contract(
    state: Any,
    key: str,
    model_type: type,
    label: str,
    *,
    error_prefix: str = "requires",
) -> Any:
    """Fetch a typed v3 contract from state, validating dict payloads.

    Shared by the visual-chain nodes and the final export; replaces the
    per-node ``_direction_plan``/``_atom_set``/``_manifest``/``_coerce``
    copies. ``model_validate`` reconstructs tuple fields from plain dicts
    that round-tripped through ``model_dump(mode="json")``.
    """
    raw = state.get(key)
    if raw is None:
        raise ValueError(f"{label} {error_prefix} {key}")
    if isinstance(raw, model_type):
        return raw
    return model_type.model_validate(raw)


def required_directive_ids(direction_plan: Any) -> set[str]:
    """IDs of required asset directives on a VisualDirectionPlan (or None)."""
    if direction_plan is None:
        return set()
    directives = get_value(direction_plan, "asset_directives", ()) or ()
    required: set[str] = set()
    for directive in directives:
        if get_value(directive, "required") is True:
            directive_id = get_value(directive, "directive_id")
            if directive_id:
                required.add(str(directive_id))
    return required
