"""Isolated v4 shadow terminal writer.

Shadow runs end here — never at the production content writer.  The node
exports one non-publish evaluation bundle under the shadow root and records
its manifest in state; it never touches the production publish root, memory,
Chroma, or any network surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.publishing.shadow_artifacts import SHADOW_ROOT, export_v4_shadow_bundle


def shadow_writer_node(
    state: Mapping[str, Any],
    *,
    shadow_root: Path | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    """Write the terminal shadow bundle and stop the run."""

    bundle = export_v4_shadow_bundle(
        state,
        shadow_root=SHADOW_ROOT if shadow_root is None else shadow_root,
        source_run_id=source_run_id,
    )
    return {
        "current_node": "SHADOW_ARTIFACT_WRITER",
        "shadow_bundle_path": str(bundle.bundle_directory),
        "shadow_manifest_v4": bundle.shadow_manifest,
    }


v4_shadow_writer_node = shadow_writer_node


__all__ = [
    "shadow_writer_node",
    "v4_shadow_writer_node",
]
