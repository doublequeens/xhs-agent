import pytest
from pydantic import ValidationError

from src.evidence import (
    EvidenceBrief,
    EvidenceItem,
    classify_source_type,
    is_allowlisted_source_url,
)


def test_evidence_models_require_http_source_urls():
    brief = EvidenceBrief(
        topic_id="tp_001",
        items=[
            EvidenceItem(
                claim="保持规律睡眠时间有助于睡眠卫生。",
                summary="成年人保持规律睡眠时间有助于睡眠卫生。这只是搜索摘要片段，仍需逐条核验。",
                source_title="Sleep hygiene basics",
                source_url="https://www.who.int/news-room/fact-sheets/detail/sleep",
                source_type="public_health",
                provenance_type="search_snippet",
                verified=False,
            )
        ],
        unsupported_claims=["主题“睡眠改善”的完整结论仍需逐条核验"],
    )

    assert brief.topic_id == "tp_001"
    assert brief.items[0].source_url.host == "www.who.int"
    assert brief.items[0].provenance_type == "search_snippet"
    assert brief.items[0].verified is False

    with pytest.raises(ValidationError):
        EvidenceItem(
            claim="睡眠改善",
            summary="summary",
            source_title="bad",
            source_url="notaurl",
            source_type="public_health",
        )


@pytest.mark.parametrize(
    ("url", "allowed_domains", "expected"),
    [
        ("https://who.int/news", ("who.int",), True),
        ("http://www.cdc.gov/sleep", ("cdc.gov",), True),
        ("https://subdomain.nhs.uk/guide", ("nhs.uk",), True),
        ("https://who.int.evil.com/news", ("who.int",), False),
        ("https://evilwho.int/news", ("who.int",), False),
        ("https://who.int@evil.com/news", ("who.int",), False),
        ("https://redirector.example/?next=https://who.int/news", ("who.int",), False),
        ("ftp://who.int/news", ("who.int",), False),
    ],
)
def test_allowlist_matches_only_exact_domains_and_subdomains(url, allowed_domains, expected):
    assert is_allowlisted_source_url(url, allowed_domains) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.who.int/news", "public_health"),
        ("https://www.harvard.edu/research", "academic"),
        ("https://www.mayoclinic.org/healthy-lifestyle", "professional"),
    ],
)
def test_source_type_classification_is_deterministic(url, expected):
    assert classify_source_type(url) == expected
