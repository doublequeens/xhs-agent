from typing import Literal

from pydantic import BaseModel, ConfigDict


class CreatorProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str
    audience: str
    default_domain: Literal["beauty"]
    default_subdomain: Literal["skincare"]
    allowed_domains: tuple[str, ...]
    allowed_subdomains: tuple[str, ...]
    primary_situations: tuple[str, ...]
    excluded_themes: tuple[str, ...]
    visual_modes: tuple[
        Literal["text_card", "text_plus_real_proof", "comparison_table"], ...
    ]

    def assert_domain_scope(self, domain: str, subdomain: str) -> None:
        if domain not in self.allowed_domains or subdomain not in self.allowed_subdomains:
            raise ValueError(
                f"{domain}/{subdomain} is outside creator profile scope: {self.profile_id}"
            )


COMMUTING_BEAUTY_WOMEN_V1 = CreatorProfile(
    profile_id="commuting_beauty_women_v1",
    audience="23–35 岁、通勤、有基础护肤和底妆需求的女性",
    default_domain="beauty",
    default_subdomain="skincare",
    allowed_domains=("beauty",),
    allowed_subdomains=("skincare", "makeup_basics"),
    primary_situations=(
        "early commute",
        "sunscreen",
        "air-conditioned office",
        "seasonal changes",
        "makeup preparation",
        "midday touch-up",
        "after-work plans",
    ),
    excluded_themes=(
        "sleep",
        "stress",
        "exercise",
        "nutrition",
        "supplements",
        "generic healthy lifestyle",
        "disease-like skincare claims",
    ),
    visual_modes=("text_card", "text_plus_real_proof", "comparison_table"),
)
