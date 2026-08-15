

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator

from .visual_style import Sha256


class ContentLock(BaseModel):
    """Immutable locked publish content for the ``llm_scene_v3`` path.

    The lock binds the canonical visible source copy (title, body, hashtags,
    first-screen promise and the textual brief fields) plus the
    ``content_atom_set_sha256`` of the atom set that feeds the dynamic visual
    chain. The locked fields and ``content_atom_set_sha256`` together feed
    ``canonical_sha256``. Storyboard-based locking was retired with the old
    fixed-card renderer; visible carousel text now derives from the content
    atom set, so the atom-set hash is the structural binding.
    """

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
    hashtags: tuple[str, ...]
    content_atom_set_sha256: Sha256
    canonical_sha256: Sha256

    @model_validator(mode="after")
    def freeze_nested_values(self):
        # ``hashtags`` arrives coerced to a tuple by pydantic (tuple[str, ...]);
        # freeze it again so a mutated nested structure can never survive.
        object.__setattr__(self, "hashtags", tuple(self.hashtags))
        return self

    @field_serializer("hashtags")
    def serialize_hashtags(self, value):
        # JSON consumers (publish copy, rescue prompt, audit) expect a list.
        return list(value)
