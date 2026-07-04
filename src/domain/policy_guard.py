from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel


class PolicyIssue(BaseModel):
    rule_id: str
    matched_text: str
    message: str
    location: str | None = None


_SENTENCE_SPAN: Final[str] = r"[^\n。！？]{0,24}"
_RULE_SPECS: Final[tuple[tuple[str, re.Pattern[str], str], ...]] = (
    (
        "medical_treatment",
        re.compile(r"(治疗|治愈|根治|替代药物)"),
        "Avoid medical treatment or cure claims.",
    ),
    (
        "medication_advice",
        re.compile(r"(服用[^\n。！？]{0,24}?药|停药|处方药)"),
        "Avoid medication-taking, stopping, or prescription-drug advice.",
    ),
    (
        "test_interpretation",
        re.compile(r"(指标[^\n。！？]{0,24}?说明|化验[^\n。！？]{0,24}?代表)"),
        "Avoid interpreting medical indicators or lab test results.",
    ),
    (
        "supplement_dosage",
        re.compile(r"(每天[^\n。！？]{0,24}?毫克|每日[^\n。！？]{0,24}?粒)"),
        "Avoid supplement dosage instructions.",
    ),
    (
        "guaranteed_outcome",
        re.compile(r"(保证|一定会|百分百|永久|立即见效)"),
        "Avoid guaranteed or immediate outcome claims.",
    ),
)


def find_policy_violations(text: str) -> list[PolicyIssue]:
    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    if not text.strip():
        return []

    issues: list[PolicyIssue] = []
    for rule_id, pattern, message in _RULE_SPECS:
        match = pattern.search(text)
        if match is None:
            continue
        issues.append(
            PolicyIssue(
                rule_id=rule_id,
                matched_text=match.group(0),
                message=message,
            )
        )

    return issues
