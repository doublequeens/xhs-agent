"""RED tests for the strict v4 revision node boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.nodes.v4.revision import revision_node


def test_revision_node_rejects_duck_typed_failed_result() -> None:
    """Would fail if a caller could bypass exact Q0-Q3 model validation."""
    with pytest.raises(ValueError):
        revision_node(
            {
                "render_qa_result_v4": SimpleNamespace(
                    passed=False,
                    issues=(SimpleNamespace(code="RENDER_OVERFLOW"),),
                ),
                "candidate_id": "candidate-a",
                "revision_history_v4": (),
            }
        )


def test_revision_node_rejects_caller_forged_operations() -> None:
    """Would fail if node routing accepted an externally supplied request."""
    with pytest.raises(ValueError):
        revision_node(
            {
                "revision_request_v4": {"permitted_operations": ("REPAGINATE",)},
                "candidate_id": "candidate-a",
                "revision_history_v4": (),
            }
        )
