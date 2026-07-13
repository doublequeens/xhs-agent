from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


class ContentLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    focus_keyword: str
    topic: str
    topic_id: str
    angle: str
    angle_id: str
    target_group: str
    core_pain: str
    title: str
    cover_copy: str
    first_screen_promise: str
    content: str
    hashtags: list[str]
    storyboards: list[dict]
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def freeze_nested_values(self):
        object.__setattr__(self, "hashtags", _deep_freeze(self.hashtags))
        object.__setattr__(self, "storyboards", _deep_freeze(self.storyboards))
        return self

    @field_serializer("hashtags", "storyboards")
    def serialize_nested_values(self, value):
        return _deep_thaw(value)
