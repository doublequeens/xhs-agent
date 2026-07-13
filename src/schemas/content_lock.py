from pydantic import BaseModel, ConfigDict, Field


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
