from dataclasses import dataclass


@dataclass(frozen=True)
class TrendCollectionSummary:
    status: str
    collected_signals: int = 0
    error_summary: str | None = None
