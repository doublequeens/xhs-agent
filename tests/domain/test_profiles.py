import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.domain import ContentPolicy, DomainContext
from src.domain.registry import build_content_policy, get_domain_profile


def test_get_domain_profile_returns_expected_domain_profiles():
    cases = [
        (
            "beauty",
            "skincare",
            ("skincare", "haircare", "bodycare", "makeup_basics"),
        ),
        (
            "wellness",
            "daily_routine",
            ("sleep", "stress_management", "daily_routine", "recovery"),
        ),
        (
            "healthy_lifestyle",
            "daily_habits",
            (
                "nutrition_basics",
                "exercise",
                "hydration",
                "sedentary_habits",
                "daily_habits",
            ),
        ),
    ]

    for domain, expected_default, expected_subdomains in cases:
        profile = get_domain_profile(domain)
        assert profile.domain == domain
        assert profile.version
        assert profile.default_subdomain == expected_default
        assert profile.allowed_subdomains == expected_subdomains
        assert profile.prohibited_topics
        assert profile.evidence_domains


def test_get_domain_profile_rejects_unknown_domain():
    with pytest.raises(ValueError, match="Unsupported domain"):
        get_domain_profile("medical")


def test_get_domain_profile_rejects_unsupported_version():
    with pytest.raises(ValueError, match="Unsupported profile version"):
        get_domain_profile("beauty", version="beauty-v999")


def test_build_content_policy_is_serializable():
    cases = [
        ("beauty", False),
        ("wellness", True),
        ("healthy_lifestyle", True),
    ]

    for domain, expected_require_evidence_brief in cases:
        profile = get_domain_profile(domain)
        policy = build_content_policy(profile)
        assert json.loads(json.dumps(policy.model_dump()))
        assert isinstance(policy.allowed_topics, list)
        assert isinstance(policy.prohibited_topics, list)
        assert isinstance(policy.prohibited_claims, list)
        assert isinstance(policy.required_disclaimers, list)
        assert policy.require_evidence_brief is expected_require_evidence_brief
        assert policy.require_human_review is True


def test_domain_context_accepts_confidence_field_and_bounds():
    context = DomainContext(
        domain="beauty",
        subdomain="skincare",
        classification_source="explicit",
        classification_confidence=0.5,
        profile_version="beauty-v1",
        risk_level="low",
    )

    assert context.classification_confidence == 0.5


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_domain_context_rejects_out_of_bounds_confidence(confidence):
    with pytest.raises(ValueError):
        DomainContext(
            domain="beauty",
            subdomain="skincare",
            classification_source="explicit",
            classification_confidence=confidence,
            profile_version="beauty-v1",
            risk_level="low",
        )
