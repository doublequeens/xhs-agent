import pytest

from src.schemas import AgentState


def test_commuting_beauty_profile_allows_only_two_beauty_subdomains():
    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("beauty", "skincare")
    COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("beauty", "makeup_basics")

    with pytest.raises(ValueError, match="outside creator profile scope"):
        COMMUTING_BEAUTY_WOMEN_V1.assert_domain_scope("wellness", "sleep")


def test_commuting_beauty_profile_is_frozen():
    from pydantic import ValidationError

    from src.creator_profile import COMMUTING_BEAUTY_WOMEN_V1

    with pytest.raises(ValidationError):
        COMMUTING_BEAUTY_WOMEN_V1.audience = "another audience"


def test_profile_and_carousel_qa_are_optional_agent_state_keys():
    assert {"creator_profile", "carousel_qa_result"} <= AgentState.__optional_keys__
