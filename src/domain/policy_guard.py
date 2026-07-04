from __future__ import annotations

import re
import unicodedata
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
        re.compile(
            r"(指标.{0,24}?说明(?=.{0,8}?(身体|健康|疾病|异常|结果|状况|问题))"
            r"|化验.{0,24}?代表(?=.{0,8}?(身体|健康|疾病|异常|结果|状况|问题)))"
        ),
        "Avoid interpreting medical indicators or lab test results.",
    ),
    (
        "supplement_dosage",
        re.compile(r"(每天[^\n。！？]{0,24}?毫克|每日[^\n。！？]{0,24}?粒)"),
        "Avoid supplement dosage instructions.",
    ),
    (
        "guaranteed_outcome",
        re.compile(r"(保证(?=百分百|立即见效|有效|改善|治愈|根治|恢复|解决|缓解|好转)|一定会|百分百|永久|立即见效)"),
        "Avoid guaranteed or immediate outcome claims.",
    ),
)

_STRIP_CHARS: Final[set[str]] = {"·", "•", "‧", "・", "･"}
_SENTENCE_BREAKS: Final[set[str]] = {"\n", "\r", ".", "。", "!", "！", "?", "？"}


def normalize_policy_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    normalized = unicodedata.normalize("NFKC", text)
    compact_chars = []
    for char in normalized:
        if char in _SENTENCE_BREAKS:
            compact_chars.append("\n")
            continue
        category = unicodedata.category(char)
        if category.startswith(("P", "Z")) or char in _STRIP_CHARS:
            continue
        compact_chars.append(char)
    return "".join(compact_chars)


def find_policy_violations(text: str) -> list[PolicyIssue]:
    normalized_text = normalize_policy_text(text)
    if not normalized_text:
        return []

    issues: list[PolicyIssue] = []
    for rule_id, pattern, message in _RULE_SPECS:
        match = pattern.search(normalized_text)
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
