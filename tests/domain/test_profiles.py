import json
import re

import pytest

from src.domain import DomainContext, DomainProfile, build_content_policy, get_domain_profile


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


def test_get_domain_profile_returns_deep_copy():
    first = get_domain_profile("beauty")
    first.keyword_map["skincare"] = ("mutated",)

    second = get_domain_profile("beauty")

    assert second.keyword_map["skincare"] == ("护肤", "防晒", "保湿", "清洁", "抗老")
    assert second is not first


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


def test_domain_profile_invariants_for_built_profiles():
    version_pattern = re.compile(r"^[a-z0-9-]+-v[1-9][0-9]*$")

    for domain in ("beauty", "wellness", "healthy_lifestyle"):
        profile = get_domain_profile(domain)
        assert profile.version
        assert version_pattern.fullmatch(profile.version)
        assert profile.allowed_subdomains
        assert profile.prohibited_topics
        assert profile.prohibited_claims
        assert profile.required_disclaimers
        assert profile.hashtag_seeds
        assert profile.visual_guidelines
        assert profile.evidence_domains
        assert profile.default_subdomain in profile.allowed_subdomains
        for subdomain, keywords in profile.keyword_map.items():
            assert subdomain in profile.allowed_subdomains
            assert keywords


def test_domain_profile_rejects_invalid_shape():
    with pytest.raises(ValueError, match="DomainProfile invariant check failed"):
        DomainProfile(
            domain="beauty",
            version="beauty-v1",
            default_subdomain="skincare",
            allowed_subdomains=("skincare",),
            keyword_map={"invalid": ("护肤",)},
            prohibited_topics=("疾病诊断",),
            prohibited_claims=("保证有效",),
            required_disclaimers=("免责声明",),
            hashtag_seeds=("美容",),
            visual_guidelines=("真实场景",),
            evidence_domains=("who.int",),
        )


def test_domain_profile_rejects_empty_keyword_map():
    with pytest.raises(ValueError, match="DomainProfile invariant check failed"):
        DomainProfile(
            domain="beauty",
            version="beauty-v1",
            default_subdomain="skincare",
            allowed_subdomains=("skincare",),
            keyword_map={},
            prohibited_topics=("疾病诊断",),
            prohibited_claims=("保证有效",),
            required_disclaimers=("免责声明",),
            hashtag_seeds=("美容",),
            visual_guidelines=("真实场景",),
            evidence_domains=("who.int",),
        )


def test_domain_profile_rejects_missing_subdomain_mapping():
    with pytest.raises(ValueError, match="DomainProfile invariant check failed"):
        DomainProfile(
            domain="beauty",
            version="beauty-v1",
            default_subdomain="skincare",
            allowed_subdomains=("skincare", "haircare"),
            keyword_map={"skincare": ("护肤",)},
            prohibited_topics=("疾病诊断",),
            prohibited_claims=("保证有效",),
            required_disclaimers=("免责声明",),
            hashtag_seeds=("美容",),
            visual_guidelines=("真实场景",),
            evidence_domains=("who.int",),
        )


@pytest.mark.parametrize(
    "domain, version",
    [
        ("beauty", "wellness-v1"),
        ("wellness", "healthy-lifestyle-v1"),
        ("healthy_lifestyle", "beauty-v1"),
    ],
)
def test_domain_profile_rejects_cross_domain_version(domain, version):
    with pytest.raises(ValueError, match="DomainProfile invariant check failed"):
        DomainProfile(
            domain=domain,
            version=version,
            default_subdomain="skincare" if domain == "beauty" else "daily_routine",
            allowed_subdomains=("skincare",) if domain == "beauty" else ("daily_routine",),
            keyword_map={"skincare" if domain == "beauty" else "daily_routine": ("x",)},
            prohibited_topics=("疾病诊断",),
            prohibited_claims=("保证有效",),
            required_disclaimers=("免责声明",),
            hashtag_seeds=("美容",),
            visual_guidelines=("真实场景",),
            evidence_domains=("who.int",),
        )
