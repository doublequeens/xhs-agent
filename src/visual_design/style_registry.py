"""Validated reference DNA for the six approved visual families."""

from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import get_args

from src.schemas.visual_style import FamilyStyleProfile, TemplateFamily


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STYLE_MANIFEST = REPOSITORY_ROOT / "assets" / "visual-families" / "manifest.json"
_REFERENCE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
_TUPLE_FIELDS = (
    "reference_image_paths",
    "palette",
    "composition_principles",
    "whitespace_range",
    "density_range",
    "allowed_motifs",
    "prohibited_patterns",
)


def _resolve_reference_paths(profile: FamilyStyleProfile) -> FamilyStyleProfile:
    resolved_paths: list[str] = []
    for raw_path in profile.reference_image_paths:
        candidate = Path(raw_path)
        if candidate.is_absolute() or candidate.suffix.lower() not in _REFERENCE_IMAGE_SUFFIXES:
            raise ValueError("reference image path must be a relative PNG or JPEG")
        resolved = (REPOSITORY_ROOT / candidate).resolve()
        try:
            resolved.relative_to(REPOSITORY_ROOT)
        except ValueError as exc:
            raise ValueError("reference image path must stay beneath repository root") from exc
        if not resolved.is_file():
            raise ValueError(f"reference image path does not exist: {raw_path}")
        resolved_paths.append(str(resolved))
    return profile.model_copy(update={"reference_image_paths": tuple(resolved_paths)})


def _profile_from_json(item: object) -> FamilyStyleProfile:
    """Convert JSON arrays only where the strict schema requires tuples."""
    if not isinstance(item, dict):
        return FamilyStyleProfile.model_validate(item)
    normalized = dict(item)
    for field_name in _TUPLE_FIELDS:
        if field_name in normalized and isinstance(normalized[field_name], list):
            normalized[field_name] = tuple(normalized[field_name])
    return FamilyStyleProfile.model_validate(normalized)


def load_style_registry(
    path: Path = DEFAULT_STYLE_MANIFEST,
) -> MappingProxyType[TemplateFamily, FamilyStyleProfile]:
    """Load all approved family profiles, resolving sample images safely."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = [_profile_from_json(item) for item in payload["families"]]
    registry = {profile.family: _resolve_reference_paths(profile) for profile in profiles}
    if set(registry) != set(get_args(TemplateFamily)) or len(profiles) != len(registry):
        raise ValueError("style registry must define exactly the six approved families")
    return MappingProxyType(registry)
