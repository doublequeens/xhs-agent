"""Canonical nodes for the isolated v4 content and revision boundaries."""

from .content import (
    content_atomizer_node,
    content_lock_builder_node,
    invalidate_visible_copy_artifacts,
    project_visible_copy,
)
from .revision import revision_node, v4_revision_node
from .critic import aesthetic_critic_node, route_after_aesthetic_critic, v4_aesthetic_critic_node

__all__ = [
    "content_atomizer_node",
    "content_lock_builder_node",
    "invalidate_visible_copy_artifacts",
    "project_visible_copy",
    "revision_node",
    "v4_revision_node",
    "aesthetic_critic_node",
    "route_after_aesthetic_critic",
    "v4_aesthetic_critic_node",
    "human_review_node",
    "route_after_human_review_v4",
    "v4_human_review_node",
]


def __getattr__(name: str):
    """Load the review node lazily to keep review/workspace imports acyclic."""

    if name in {"human_review_node", "route_after_human_review_v4", "v4_human_review_node"}:
        from .human_review import (
            human_review_node,
            route_after_human_review_v4,
            v4_human_review_node,
        )

        return {
            "human_review_node": human_review_node,
            "route_after_human_review_v4": route_after_human_review_v4,
            "v4_human_review_node": v4_human_review_node,
        }[name]
    raise AttributeError(name)
