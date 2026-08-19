from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "llm_scene_v4"
MANIFEST_PATH = FIXTURE_ROOT / "quality_manifest.json"
EXPECTED_CASES = ("beauty-20260805", "beauty-20260806")
EXPECTED_PAGE_COUNTS = {"beauty-20260805": 10, "beauty-20260806": 9}
ISSUE_CODES = {
    "weak_hierarchy",
    "poor_information_design",
    "excessive_empty_space",
    "unbalanced_composition",
    "inconsistent_scale",
    "weak_visual_anchor",
    "repetitive_layout",
    "awkward_spacing",
    "content_visual_mismatch",
    "low_legibility",
}
SCORE_FIELDS = {
    "overall",
    "hierarchy",
    "legibility",
    "composition",
    "family_consistency",
    "page_variation",
    "page_rhythm",
    "color",
    "spacing",
    "image_relevance",
}
CRITIC_FIELDS = SCORE_FIELDS | {
    "contains_images",
    "passed",
    "revision_round",
    "issues",
}
EXPECTED_CRITIC = {
    "beauty-20260805": {
        "contains_images": True,
        "overall": 92,
        "hierarchy": 95,
        "legibility": 98,
        "composition": 90,
        "family_consistency": 95,
        "page_variation": 90,
        "page_rhythm": 95,
        "color": 95,
        "spacing": 92,
        "image_relevance": 98,
        "passed": True,
        "revision_round": 2,
        "issues": [],
    },
    "beauty-20260806": {
        "contains_images": True,
        "overall": 91,
        "hierarchy": 90,
        "legibility": 93,
        "composition": 92,
        "family_consistency": 89,
        "page_variation": 95,
        "page_rhythm": 90,
        "color": 95,
        "spacing": 88,
        "image_relevance": 92,
        "passed": True,
        "revision_round": 0,
        "issues": [],
    },
}
EXPECTED_PAGE_ISSUES = {
    "beauty-20260805": {
        "page-1": [],
        "page-2": ["excessive_empty_space", "weak_hierarchy"],
        "page-3": ["excessive_empty_space", "poor_information_design"],
        "page-4": ["excessive_empty_space", "weak_visual_anchor"],
        "page-5": ["inconsistent_scale", "unbalanced_composition"],
        "page-6": ["inconsistent_scale", "unbalanced_composition"],
        "page-7": ["excessive_empty_space", "repetitive_layout"],
        "page-8": ["excessive_empty_space", "poor_information_design"],
        "page-9": ["excessive_empty_space", "weak_visual_anchor"],
        "page-10": [
            "excessive_empty_space",
            "weak_visual_anchor",
            "poor_information_design",
        ],
    },
    "beauty-20260806": {
        "page-1": [],
        "page-2": ["excessive_empty_space", "weak_hierarchy"],
        "page-3": ["excessive_empty_space", "weak_visual_anchor"],
        "page-4": ["excessive_empty_space", "unbalanced_composition"],
        "page-5": ["inconsistent_scale", "awkward_spacing"],
        "page-6": ["inconsistent_scale", "awkward_spacing"],
        "page-7": ["content_visual_mismatch", "poor_information_design"],
        "page-8": ["repetitive_layout", "awkward_spacing"],
        "page-9": ["excessive_empty_space", "weak_visual_anchor"],
    },
}
EXPECTED_CONTRACT_HASHES = {
    "beauty-20260805": {
        "design_plan_sha256": "4ab13594701c6e1f611b99f8ef81a3297e17d291cb49af4d9dcb4fc6a02aa24b",
        "render_manifest_sha256": "fec63ec455697ea5971456dcd51347d9cb24f1e5b5ace498df6e70fe55a7b2cd",
    },
    "beauty-20260806": {
        "design_plan_sha256": "cd11db0d309abee8f66a1a09915f09f0ff54b3ac7a4cb2cb1cfed145a2b1d2c3",
        "render_manifest_sha256": "d4c58a197437ffce7da6ad5c15ca8388568017e9d8ccd251a44b6558bdb48e7e",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_fixture_path(case_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    assert relative.parts and relative.parts[0] == "pages"
    path = (case_root / Path(*relative.parts)).resolve()
    assert path.is_relative_to(case_root.resolve())
    return path


def _assert_sanitized_fixture_json() -> None:
    json_paths = sorted(FIXTURE_ROOT.rglob("*.json"))
    assert json_paths, "fixture JSON files are required"
    payload = "\n".join(path.read_text(encoding="utf-8") for path in json_paths)
    forbidden_paths = {
        "/".join(("outputs", "publish")),
        "/".join(("outputs", "render_runs")),
        "/".join(("", "Users", "")),
    }
    for token in forbidden_paths:
        assert token not in payload
    assert not re.search(r"\bhttps?://", payload, flags=re.IGNORECASE)
    assert not re.search(r"\b20\d{6}-beauty-", payload)
    assert not re.search(r"/(?:Users|private|tmp|home)/", payload)
    assert not re.search(r'(?<![\w:])/(?:[^/\s"]+/)+[^/\s"]+', payload)
    assert not re.search(r"\b[A-Za-z]:[\\/]", payload)
    assert not re.search(r"\brun-[A-Za-z0-9]", payload)
    for field in {
        "".join(("proven", "ance")),
        "_".join(("run", "id")),
        "_".join(("api", "key")),
        "".join(("pass", "word")),
        "".join(("sec", "ret")),
    }:
        assert field not in payload.lower()


def _assert_source_contract(case_id: str, page_ids: list[str]) -> None:
    contract_path = FIXTURE_ROOT / case_id / "source-contracts.json"
    assert contract_path.is_file()
    contract = load_json(contract_path)
    assert set(contract) == {
        "case_id",
        "critic",
        "pages",
        "design_plan_sha256",
        "render_manifest_sha256",
    }
    assert contract["case_id"] == case_id
    assert [page["page_id"] for page in contract["pages"]] == page_ids
    assert all(set(page) == {"page_id", "human_issues"} for page in contract["pages"])
    for page in contract["pages"]:
        issues = page["human_issues"]
        assert isinstance(issues, list)
        assert issues == EXPECTED_PAGE_ISSUES[case_id][page["page_id"]]
        assert all(issue in ISSUE_CODES for issue in issues)
    critic = contract["critic"]
    assert set(critic) == CRITIC_FIELDS
    assert critic == EXPECTED_CRITIC[case_id]
    assert isinstance(critic["passed"], bool)
    assert isinstance(critic["contains_images"], bool)
    assert 0 <= critic["revision_round"] <= 2
    assert isinstance(critic["issues"], list)
    for field in SCORE_FIELDS - {"image_relevance"}:
        assert isinstance(critic[field], int)
        assert 0 <= critic[field] <= 100
    assert (
        isinstance(critic["image_relevance"], int)
        or critic["image_relevance"] == "not_applicable"
    )
    for field in ("design_plan_sha256", "render_manifest_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", contract[field])
        assert contract[field] == EXPECTED_CONTRACT_HASHES[case_id][field]


def test_quality_manifest_binds_every_fixture_page() -> None:
    assert MANIFEST_PATH.is_file(), "fixture manifest must exist before it is loaded"
    manifest = load_json(MANIFEST_PATH)
    assert set(manifest) == {"cases"}
    cases = manifest["cases"]
    assert [case["case_id"] for case in cases] == list(EXPECTED_CASES)
    assert {case["case_id"] for case in cases} == set(EXPECTED_CASES)

    all_paths: list[str] = []
    for case in cases:
        case_id = case["case_id"]
        expected_count = EXPECTED_PAGE_COUNTS[case_id]
        assert len(case["pages"]) == expected_count
        assert set(case) == {"case_id", "pages"}
        page_ids = [page["page_id"] for page in case["pages"]]
        assert page_ids == [f"page-{index}" for index in range(1, expected_count + 1)]
        assert len(set(page_ids)) == expected_count
        assert case["pages"][0]["label"] == "positive"
        assert all(page["label"] == "negative" for page in case["pages"][1:])

        case_root = FIXTURE_ROOT / case_id
        manifest_paths: list[str] = []
        for index, page in enumerate(case["pages"], start=1):
            assert set(page) == {"page_id", "label", "path", "sha256"}
            assert page["page_id"] == f"page-{index}"
            assert page["path"] == f"pages/page-{index}.png"
            assert re.fullmatch(r"[0-9a-f]{64}", page["sha256"])
            path = _safe_fixture_path(case_root, page["path"])
            assert path.suffix == ".png"
            assert path.is_file()
            assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            assert sha256_path(path) == page["sha256"]
            manifest_paths.append(page["path"])
            all_paths.append(f"{case_id}/{page['path']}")
            if index == 1:
                assert page.get("human_issues", []) == []

        assert len(set(manifest_paths)) == expected_count
        actual_paths = sorted(
            path.relative_to(case_root).as_posix()
            for path in (case_root / "pages").glob("*.png")
        )
        assert actual_paths == sorted(manifest_paths)
        _assert_source_contract(case_id, page_ids)

        source_pages = load_json(case_root / "source-contracts.json")["pages"]
        for index, source_page in enumerate(source_pages):
            if index == 0:
                assert source_page["human_issues"] == []
            else:
                assert source_page["human_issues"]

    assert len(all_paths) == len(set(all_paths)) == sum(EXPECTED_PAGE_COUNTS.values())
    _assert_sanitized_fixture_json()
