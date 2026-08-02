"""Editorial-carousel checkpoint migration seam.

The fixed-template visual production path (planner, selector, blueprints,
renderer) was removed in Task 17. This package now exists only to host
``legacy.py`` (the sole old-checkpoint migration boundary) and
``publish_profile.py`` (the publish-profile helper consumed by the v3 path).
"""

__all__: list[str] = []
