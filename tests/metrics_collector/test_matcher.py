from datetime import datetime, timedelta
from itertools import permutations
from zoneinfo import ZoneInfo

import pytest

from metrics_collector.matcher import (
    ContentMatcher,
    normalize_title,
    time_score,
    title_similarity,
)
from metrics_collector.models import ContentCandidate


TZ = ZoneInfo("Asia/Shanghai")
PUBLISHED_AT = datetime(2026, 7, 5, 12, 0, tzinfo=TZ)


def candidate(
    content_id: str,
    title: str,
    *,
    hours_from_publication: float = 0,
) -> ContentCandidate:
    return ContentCandidate(
        content_id,
        title,
        PUBLISHED_AT + timedelta(hours=hours_from_publication),
    )


def test_normalize_title_removes_punctuation_and_spaces_without_mutation():
    title = "油皮晨间别过度清洁！ 要做减法!"

    assert normalize_title(title) == "油皮晨间别过度清洁要做减法"
    assert title == "油皮晨间别过度清洁！ 要做减法!"


def test_normalize_title_applies_nfkc_and_latin_casefold():
    assert normalize_title(" ＡbＣ-１２！") == "abc12"


def test_title_similarity_uses_normalized_titles():
    assert title_similarity("ＡＢＣ！", "abc") == 1.0


def test_content_matcher_has_configurable_threshold_defaults():
    matcher = ContentMatcher()
    custom = ContentMatcher(
        title_similarity_threshold=0.9,
        combined_score_threshold=0.85,
        winner_margin=0.1,
    )

    assert matcher.title_similarity_threshold == 0.82
    assert matcher.combined_score_threshold == 0.80
    assert matcher.winner_margin == 0.05
    assert custom.title_similarity_threshold == 0.9
    assert custom.combined_score_threshold == 0.85
    assert custom.winner_margin == 0.1


@pytest.mark.parametrize(
    "field",
    [
        "title_similarity_threshold",
        "combined_score_threshold",
        "winner_margin",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.01,
        1.01,
        "0.5",
        True,
    ],
)
def test_content_matcher_rejects_invalid_configuration(field, invalid_value):
    with pytest.raises(ValueError, match=f"^{field} "):
        ContentMatcher(**{field: invalid_value})


def test_content_matcher_accepts_configuration_boundaries():
    matcher = ContentMatcher(
        title_similarity_threshold=0,
        combined_score_threshold=1,
        winner_margin=0,
    )

    assert matcher.title_similarity_threshold == 0
    assert matcher.combined_score_threshold == 1
    assert matcher.winner_margin == 0


def test_unique_exact_normalized_title_matches_with_full_score():
    candidates = [
        candidate("other", "完全不同的标题"),
        candidate("content-1", "油皮晨间别过度清洁 要做减法"),
    ]

    result = ContentMatcher().match(
        "油皮晨间别过度清洁！要做减法!",
        PUBLISHED_AT,
        candidates,
    )

    assert result.status == "matched"
    assert result.content_id == "content-1"
    assert result.score == 1.0
    assert result.candidate_ids == ("content-1",)


def test_small_title_edit_uses_time_as_secondary_signal():
    candidates = [
        candidate("older", "abcdefghiy", hours_from_publication=721),
        candidate("nearer", "abcdefghix", hours_from_publication=1),
    ]

    result = ContentMatcher().match("abcdefghij", PUBLISHED_AT, candidates)

    assert result.status == "matched"
    assert result.content_id == "nearer"
    assert result.score == pytest.approx(0.91)
    assert result.candidate_ids == ("nearer",)


@pytest.mark.parametrize(
    ("exported_title", "candidate_title"),
    [
        (
            "油皮晨间护肤别过度清洁学会做减法",
            "油皮晨间护肤：别过度清洁，要做减法",
        ),
        (
            "油皮晨间护肤别过度清洁要做减法",
            "油皮晨间护肤别过度清洁做好减法",
        ),
    ],
)
def test_realistic_chinese_title_edits_match(
    exported_title,
    candidate_title,
):
    similarity = title_similarity(exported_title, candidate_title)

    result = ContentMatcher().match(
        exported_title,
        PUBLISHED_AT,
        [candidate("content-1", candidate_title)],
    )

    assert similarity >= 0.82
    assert result.status == "matched"
    assert result.content_id == "content-1"


def test_substantial_chinese_title_rewrite_is_unmatched():
    exported_title = "油皮晨间护肤别过度清洁要做减法"
    candidate_title = "油皮早晨正确护肤步骤分享"

    result = ContentMatcher().match(
        exported_title,
        PUBLISHED_AT,
        [candidate("content-1", candidate_title)],
    )

    assert title_similarity(exported_title, candidate_title) < 0.82
    assert result.status == "unmatched"
    assert result.candidate_ids == ()


def test_close_candidates_are_ambiguous_in_deterministic_order():
    candidates = [
        candidate("b", "abcdefghiy", hours_from_publication=48),
        candidate("z", "abcdefghix", hours_from_publication=1),
        candidate("a", "abcdefghiw", hours_from_publication=48),
    ]

    result = ContentMatcher().match("abcdefghij", PUBLISHED_AT, candidates)

    assert result.status == "ambiguous"
    assert result.content_id is None
    assert result.score == pytest.approx(0.91)
    assert result.candidate_ids == ("z", "a", "b")


def test_candidate_order_permutations_produce_identical_result():
    candidates = [
        candidate("b", "abcdefghiy", hours_from_publication=48),
        candidate("z", "abcdefghix", hours_from_publication=1),
        candidate("a", "abcdefghiw", hours_from_publication=48),
    ]

    results = {
        ContentMatcher().match("abcdefghij", PUBLISHED_AT, list(order))
        for order in permutations(candidates)
    }

    assert len(results) == 1
    result = results.pop()
    assert result.status == "ambiguous"
    assert result.candidate_ids == ("z", "a", "b")


def test_below_title_threshold_is_unmatched():
    result = ContentMatcher().match(
        "abcdefghi",
        PUBLISHED_AT,
        [candidate("content-1", "abcdefgxy")],
    )

    assert result.status == "unmatched"
    assert result.content_id is None
    assert result.score is None
    assert result.candidate_ids == ()


def test_exact_title_similarity_threshold_is_accepted():
    exported_title = "a" * 41 + "b" * 9
    candidate_title = "a" * 41 + "c" * 9

    result = ContentMatcher().match(
        exported_title,
        PUBLISHED_AT,
        [candidate("content-1", candidate_title)],
    )

    assert title_similarity(exported_title, candidate_title) == 0.82
    assert result.status == "matched"
    assert result.content_id == "content-1"


def test_exact_combined_score_threshold_is_accepted():
    result = ContentMatcher().match(
        "abcdefghijkl",
        PUBLISHED_AT,
        [candidate("content-1", "abcdefghijxy", hours_from_publication=100)],
    )

    assert result.status == "matched"
    assert result.content_id == "content-1"
    assert result.score == 0.80


def test_below_combined_threshold_is_unmatched():
    result = ContentMatcher().match(
        "abcdefghijkl",
        PUBLISHED_AT,
        [candidate("content-1", "abcdefghijxy", hours_from_publication=721)],
    )

    assert result.status == "unmatched"
    assert result.candidate_ids == ()


def test_multiple_exact_titles_are_disambiguated_by_time():
    candidates = [
        candidate("old", "Exact title!", hours_from_publication=721),
        candidate("near", "exact title", hours_from_publication=1),
    ]

    result = ContentMatcher().match("ＥＸＡＣＴ TITLE", PUBLISHED_AT, candidates)

    assert result.status == "matched"
    assert result.content_id == "near"
    assert result.score == 1.0
    assert result.candidate_ids == ("near",)


def test_multiple_exact_titles_with_same_time_score_are_ambiguous():
    candidates = [
        candidate("z-id", "Same title", hours_from_publication=1),
        candidate("a-id", "same-title", hours_from_publication=20),
    ]

    result = ContentMatcher().match("ＳＡＭＥ TITLE", PUBLISHED_AT, candidates)

    assert result.status == "ambiguous"
    assert result.content_id is None
    assert result.score == 1.0
    assert result.candidate_ids == ("a-id", "z-id")


def test_winner_margin_accepts_exact_boundary():
    candidates = [
        candidate("old", "Exact title", hours_from_publication=721),
        candidate("winner", "exact-title", hours_from_publication=100),
    ]

    result = ContentMatcher().match("Exact title", PUBLISHED_AT, candidates)

    assert result.status == "matched"
    assert result.content_id == "winner"
    assert result.score == pytest.approx(0.95)


def test_empty_normalized_title_is_unmatched():
    result = ContentMatcher().match(
        "！ -- ",
        PUBLISHED_AT,
        [candidate("content-1", "Valid title")],
    )

    assert result.status == "unmatched"
    assert result.content_id is None
    assert result.score is None
    assert result.candidate_ids == ()


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (0, 1.0),
        (24, 1.0),
        (24.01, 0.8),
        (72, 0.8),
        (72.01, 0.5),
        (168, 0.5),
        (168.01, 0.2),
        (720, 0.2),
        (720.01, 0.0),
        (-24, 1.0),
    ],
)
def test_time_score_boundaries(hours, expected):
    assert time_score(PUBLISHED_AT, PUBLISHED_AT + timedelta(hours=hours)) == expected


def test_time_score_uses_real_elapsed_time_across_spring_forward():
    new_york = ZoneInfo("America/New_York")
    before = datetime(2026, 3, 7, 3, 0, tzinfo=new_york)
    after = datetime(2026, 3, 8, 3, 30, tzinfo=new_york)

    assert time_score(before, after) == 1.0


def test_time_score_uses_real_elapsed_time_across_fall_back():
    new_york = ZoneInfo("America/New_York")
    before = datetime(2026, 10, 31, 2, 0, tzinfo=new_york)
    after = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)

    assert time_score(before, after) == 0.8


def test_time_score_supports_two_naive_datetimes():
    before = datetime(2026, 7, 5, 12, 0)
    after = datetime(2026, 7, 6, 13, 0)

    assert time_score(before, after) == 0.8


def test_time_score_rejects_mixed_aware_and_naive_datetimes():
    naive = PUBLISHED_AT.replace(tzinfo=None)

    with pytest.raises(
        ValueError,
        match="^datetimes must both be timezone-aware or both naive$",
    ):
        time_score(PUBLISHED_AT, naive)


def test_match_rejects_mixed_datetimes_even_for_unique_exact_title():
    naive = PUBLISHED_AT.replace(tzinfo=None)
    candidates = [ContentCandidate("content-1", "Exact title", naive)]

    with pytest.raises(
        ValueError,
        match="^datetimes must both be timezone-aware or both naive$",
    ):
        ContentMatcher().match("Exact title", PUBLISHED_AT, candidates)
