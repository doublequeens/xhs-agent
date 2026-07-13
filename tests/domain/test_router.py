import pytest

from src.domain import DomainProfile
from src.domain.profiles import PROFILES
from src.domain.router import resolve_domain


def test_resolve_domain_explicit_domain_overrides_keyword():
    context = resolve_domain(domain="beauty", focus_keyword="改善睡眠")

    assert context.domain == "beauty"
    assert context.subdomain == "skincare"
    assert context.classification_source == "explicit_domain_default_subdomain"
    assert context.classification_confidence == pytest.approx(0.85)
    assert context.profile_version == "beauty-v1"


def test_resolve_domain_infers_sedentary_habits():
    context = resolve_domain(domain=None, focus_keyword="久坐办公怎么活动")

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "sedentary_habits"
    assert context.classification_source == "inferred"
    assert context.classification_confidence >= 0.8


def test_resolve_domain_infers_sleep_subdomain():
    context = resolve_domain(domain=None, focus_keyword="改善睡眠")

    assert context.domain == "wellness"
    assert context.subdomain == "sleep"
    assert context.classification_source == "inferred"
    assert context.classification_confidence >= 0.8


def test_resolve_domain_defaults_when_keyword_missing():
    context = resolve_domain(domain=None, focus_keyword="完全无关的关键词")

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "daily_habits"
    assert context.classification_source == "default"
    assert context.classification_confidence < 0.65


def test_resolve_domain_rejects_invalid_explicit_domain():
    with pytest.raises(ValueError, match="Unsupported domain: medical"):
        resolve_domain(domain="medical", focus_keyword="睡眠")


def test_resolve_domain_marks_cross_domain_tie_as_low_confidence(monkeypatch):
    beauty = PROFILES["beauty"].model_copy(deep=True)
    hydration = PROFILES["healthy_lifestyle"].model_copy(deep=True)

    beauty.keyword_map["skincare"] = beauty.keyword_map["skincare"] + ("交叉词",)
    hydration.keyword_map["hydration"] = hydration.keyword_map["hydration"] + ("交叉词",)

    monkeypatch.setattr(
        "src.domain.router.PROFILES",
        {
            "beauty": beauty,
            "wellness": PROFILES["wellness"].model_copy(deep=True),
            "healthy_lifestyle": hydration,
        },
    )

    context = resolve_domain(domain=None, focus_keyword="交叉词")

    assert (context.domain, context.subdomain) == ("beauty", "skincare")
    assert context.classification_source == "inferred"
    assert context.classification_confidence < 0.65


def test_resolve_domain_uses_score_based_confidence_for_multi_keyword_match(monkeypatch):
    custom_profile = DomainProfile(
        domain="wellness",
        version="wellness-v1",
        default_subdomain="daily_routine",
        allowed_subdomains=("sleep", "stress_management", "daily_routine", "recovery"),
        keyword_map={
            "sleep": ("睡眠", "早睡"),
            "stress_management": ("压力",),
            "daily_routine": ("作息",),
            "recovery": ("恢复",),
        },
        prohibited_topics=("疾病诊断",),
        prohibited_claims=("保证有效",),
        required_disclaimers=("内容仅作一般生活方式科普",),
        hashtag_seeds=("养生习惯",),
        visual_guidelines=("使用睡眠场景",),
        evidence_domains=("who.int",),
    )

    monkeypatch.setattr(
        "src.domain.router.PROFILES",
        {
            "beauty": PROFILES["beauty"].model_copy(deep=True),
            "wellness": custom_profile,
            "healthy_lifestyle": PROFILES["healthy_lifestyle"].model_copy(deep=True),
        },
    )

    context = resolve_domain(domain=None, focus_keyword="睡眠早睡计划")

    assert context.domain == "wellness"
    assert context.subdomain == "sleep"
    assert context.classification_confidence == pytest.approx(0.85)


def test_explicit_domain_and_subdomain_are_used_directly():
    context = resolve_domain(
        domain="healthy_lifestyle",
        subdomain="exercise",
        focus_keyword="",
    )

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "exercise"
    assert context.classification_source == "explicit"
    assert context.classification_confidence == 1


def test_explicit_domain_rejects_invalid_subdomain():
    with pytest.raises(ValueError, match="Unsupported subdomain"):
        resolve_domain(
            domain="healthy_lifestyle",
            subdomain="skincare",
            focus_keyword="",
        )


def test_bare_subdomain_is_rejected():
    with pytest.raises(ValueError, match="subdomain requires domain"):
        resolve_domain(domain=None, subdomain="daily_habits", focus_keyword="")


def test_explicit_domain_without_subdomain_uses_default_when_non_interactive():
    context = resolve_domain(
        domain="healthy_lifestyle",
        subdomain=None,
        focus_keyword="",
        interactive=False,
    )

    assert context.domain == "healthy_lifestyle"
    assert context.subdomain == "daily_habits"
    assert context.classification_source == "explicit_domain_default_subdomain"
