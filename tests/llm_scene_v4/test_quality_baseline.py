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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_fixture_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    assert not relative.is_absolute()
    assert ".." not in relative.parts
    assert relative.parts
    path = (root / Path(*relative.parts)).resolve()
    assert path.is_relative_to(root.resolve())
    return path


def _assert_sanitized_fixture_json() -> None:
    json_paths = sorted(FIXTURE_ROOT.rglob("*.json"))
    assert json_paths, "fixture JSON files are required"
    text_paths = [Path(__file__), *json_paths]
    payload = "\n".join(path.read_text(encoding="utf-8") for path in text_paths)
    fixture_payload = "\n".join(
        path.read_text(encoding="utf-8") for path in json_paths
    )
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
    assert not re.search(r'(?<![\w:])/(?:[^/\s"]+/)+[^/\s"]+', fixture_payload)
    assert not re.search(r"\b[A-Za-z]:[\\/]", fixture_payload)
    assert not re.search(r"\brun-[A-Za-z0-9]", payload)
    for field in {
        "".join(("proven", "ance")),
        "_".join(("run", "id")),
        "_".join(("api", "key")),
        "".join(("pass", "word")),
        "".join(("sec", "ret")),
    }:
        assert field not in payload.lower()


def _assert_critic(critic: dict[str, Any]) -> None:
    assert set(critic) == CRITIC_FIELDS
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


def _assert_source_contract(
    case_id: str,
    page_ids: list[str],
    critic: dict[str, Any],
    binding: dict[str, str],
) -> None:
    assert set(binding) == {"path", "sha256"}
    assert re.fullmatch(r"[0-9a-f]{64}", binding["sha256"])
    contract_path = _safe_fixture_path(FIXTURE_ROOT, binding["path"])
    assert contract_path.parent == FIXTURE_ROOT / case_id
    assert contract_path.name == "source-contracts.json"
    assert contract_path.is_file()
    assert sha256_path(contract_path) == binding["sha256"]
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
    assert all(set(page) == {"page_id"} for page in contract["pages"])
    assert contract["critic"] == critic
    for field in ("design_plan_sha256", "render_manifest_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", contract[field])


def test_quality_manifest_binds_every_fixture_page() -> None:
    assert MANIFEST_PATH.is_file(), "fixture manifest must exist before it is loaded"
    manifest = load_json(MANIFEST_PATH)
    assert set(manifest) == {"cases"}
    cases = manifest["cases"]
    assert [case["case_id"] for case in cases] == list(EXPECTED_CASES)
    assert {case["case_id"] for case in cases} == set(EXPECTED_CASES)

    all_paths: list[str] = []
    source_bindings: list[str] = []
    for case in cases:
        case_id = case["case_id"]
        expected_count = EXPECTED_PAGE_COUNTS[case_id]
        assert len(case["pages"]) == expected_count
        assert set(case) == {
            "case_id",
            "critic",
            "source_contract",
            "pages",
        }
        _assert_critic(case["critic"])
        source_binding = case["source_contract"]
        assert isinstance(source_binding, dict)
        source_path = _safe_fixture_path(FIXTURE_ROOT, source_binding["path"])
        source_bindings.append(source_path.relative_to(FIXTURE_ROOT).as_posix())
        page_ids = [page["page_id"] for page in case["pages"]]
        assert page_ids == [f"page-{index}" for index in range(1, expected_count + 1)]
        assert len(set(page_ids)) == expected_count

        case_root = FIXTURE_ROOT / case_id
        manifest_paths: list[str] = []
        for index, page in enumerate(case["pages"], start=1):
            assert set(page) == {
                "page_id",
                "label",
                "human_issues",
                "path",
                "sha256",
            }
            assert page["page_id"] == f"page-{index}"
            assert page["label"] == ("positive" if index == 1 else "negative")
            assert isinstance(page["human_issues"], list)
            assert all(issue in ISSUE_CODES for issue in page["human_issues"])
            if index == 1:
                assert page["human_issues"] == []
            else:
                assert page["human_issues"]
            assert page["path"] == f"pages/page-{index}.png"
            assert re.fullmatch(r"[0-9a-f]{64}", page["sha256"])
            path = _safe_fixture_path(case_root, page["path"])
            assert PurePosixPath(page["path"]).parts[0] == "pages"
            assert path.suffix == ".png"
            assert path.is_file()
            assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            assert sha256_path(path) == page["sha256"]
            manifest_paths.append(page["path"])
            all_paths.append(f"{case_id}/{page['path']}")

        assert len(set(manifest_paths)) == expected_count
        actual_paths = sorted(
            path.relative_to(case_root).as_posix()
            for path in (case_root / "pages").glob("*.png")
        )
        assert actual_paths == sorted(manifest_paths)
        _assert_source_contract(case_id, page_ids, case["critic"], source_binding)

    assert len(all_paths) == len(set(all_paths)) == sum(EXPECTED_PAGE_COUNTS.values())
    assert len(source_bindings) == len(set(source_bindings)) == len(EXPECTED_CASES)
    _assert_sanitized_fixture_json()
