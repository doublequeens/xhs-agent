import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from metrics_collector.models import ContentCandidate, MatchResult


_DATETIME_AWARENESS_ERROR = (
    "datetimes must both be timezone-aware or both naive"
)


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(
        None,
        normalize_title(left),
        normalize_title(right),
    ).ratio()


def time_score(left: datetime, right: datetime) -> float:
    if _is_aware(left) != _is_aware(right):
        raise ValueError(_DATETIME_AWARENESS_ERROR)

    hours = abs((left - right).total_seconds()) / 3600
    if hours <= 24:
        return 1.0
    if hours <= 72:
        return 0.8
    if hours <= 168:
        return 0.5
    if hours <= 720:
        return 0.2
    return 0.0


def _is_aware(value: datetime) -> bool:
    return value.utcoffset() is not None


@dataclass(frozen=True)
class _ScoredCandidate:
    candidate: ContentCandidate
    score: float


@dataclass(frozen=True)
class ContentMatcher:
    title_similarity_threshold: float = 0.82
    combined_score_threshold: float = 0.80
    winner_margin: float = 0.05

    def match(
        self,
        title: str,
        published_at: datetime,
        candidates: list[ContentCandidate],
    ) -> MatchResult:
        normalized_title = normalize_title(title)
        if not normalized_title:
            return MatchResult("unmatched", None, None, ())

        for candidate in candidates:
            if _is_aware(published_at) != _is_aware(candidate.reference_time):
                raise ValueError(_DATETIME_AWARENESS_ERROR)

        exact_candidates = [
            candidate
            for candidate in candidates
            if normalize_title(candidate.title) == normalized_title
        ]
        if len(exact_candidates) == 1:
            content_id = exact_candidates[0].content_id
            return MatchResult("matched", content_id, 1.0, (content_id,))
        if exact_candidates:
            scored = [
                _ScoredCandidate(
                    candidate,
                    0.90 + 0.10 * time_score(
                        published_at,
                        candidate.reference_time,
                    ),
                )
                for candidate in exact_candidates
            ]
            return self._select(scored)

        scored = []
        for candidate in candidates:
            similarity = title_similarity(title, candidate.title)
            if similarity < self.title_similarity_threshold:
                continue
            combined_score = (
                0.90 * similarity
                + 0.10 * time_score(
                    published_at,
                    candidate.reference_time,
                )
            )
            scored.append(_ScoredCandidate(candidate, combined_score))

        return self._select(scored)

    def _select(self, scored: list[_ScoredCandidate]) -> MatchResult:
        ranked = sorted(
            scored,
            key=lambda item: (-item.score, item.candidate.content_id),
        )
        if not ranked or ranked[0].score < self.combined_score_threshold:
            return MatchResult("unmatched", None, None, ())

        winner = ranked[0]
        if len(ranked) == 1 or self._has_winning_margin(
            winner.score,
            ranked[1].score,
        ):
            content_id = winner.candidate.content_id
            return MatchResult(
                "matched",
                content_id,
                winner.score,
                (content_id,),
            )

        return MatchResult(
            "ambiguous",
            None,
            winner.score,
            tuple(item.candidate.content_id for item in ranked),
        )

    def _has_winning_margin(
        self,
        winner_score: float,
        second_score: float,
    ) -> bool:
        difference = winner_score - second_score
        return difference > self.winner_margin or math.isclose(
            difference,
            self.winner_margin,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
