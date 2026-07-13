import json
import warnings
from pathlib import Path
from typing import Any, Mapping

from src.domain import get_domain_profile
from src.domain.models import DomainProfile

PROMPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = PROMPTS_DIR / "base"
FRAGMENTS_DIR = PROMPTS_DIR / "fragments"

TASK_FILES = {
    "trend_scout": "trend_scout.txt",
    "angle_strategist": "angle_strategist.txt",
    "novelty_guard": "novelty_guard.txt",
    "virality_scorer": "virality_scorer.txt",
    "outline_architect": "outline_architect.txt",
    "draft_writer": "draft_writer.txt",
    "title_lab": "title_lab.txt",
    "title_ranker": "title_ranker.txt",
    "r1_reflector": "r1_reflector.txt",
    "r2_compliance": "r2_compliance.txt",
    "decision_engine": "decision_engine.txt",
    "hashtag_seo": "hashtag_seo.txt",
    "assembler": "assembler.txt",
    "storyboards_generator": "storyboards_generator.txt",
    "storyboards_generator_legacy": "storyboards_generator_legacy.txt",
    "topic_ideator": "topic_ideator.txt",
}


def _read_prompt_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path.read_text(encoding="utf-8").strip()


def _serialize_profile(profile: DomainProfile) -> str:
    return json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)


def _get_value(payload: Any, key: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(key)
    return getattr(payload, key, None)


def _normalize_payload(payload: Any) -> Any:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    elif hasattr(payload, "__dict__"):
        payload = vars(payload)

    if isinstance(payload, Mapping):
        return {key: _normalize_payload(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_normalize_payload(item) for item in payload]
    return payload


def serialize_prompt_value(payload: Any) -> str:
    return json.dumps(_normalize_payload(payload), ensure_ascii=False, indent=2, sort_keys=True)


def _compose_prompt(
    task: str,
    profile: DomainProfile,
    creator_profile: Any | None = None,
) -> str:
    try:
        base_filename = TASK_FILES[task]
    except KeyError as exc:
        raise ValueError(f"Unknown prompt task: {task}") from exc

    sections = [
        _read_prompt_file(BASE_DIR / base_filename),
        _read_prompt_file(FRAGMENTS_DIR / "safety_common.txt"),
    ]
    if creator_profile is not None:
        sections.extend(
            [
                _read_prompt_file(FRAGMENTS_DIR / "creator_profile.txt"),
                "【Creator Profile】\n" + serialize_prompt_value(creator_profile),
            ]
        )
    sections.extend(
        [
            _read_prompt_file(FRAGMENTS_DIR / f"{profile.domain}.txt"),
            "【Domain Profile】\n" + _serialize_profile(profile),
        ]
    )
    return "\n\n".join(sections)


def compose_prompt(task: str, profile: DomainProfile) -> str:
    return _compose_prompt(task, profile)


def compose_prompt_for_state(
    task: str,
    state: Mapping[str, Any],
    *,
    allow_legacy_beauty_fallback: bool = True,
) -> str:
    """Compose a task prompt from state.

    Legacy checkpoints may not have `domain_context`; in that case we can
    explicitly fall back to the beauty profile. Once `domain_context` exists,
    modern validation is strict: malformed or version-mismatched values raise.
    """
    domain_context = state.get("domain_context")

    if domain_context is None:
        if allow_legacy_beauty_fallback:
            warnings.warn(
                f"{task} is falling back to beauty-v1 for a legacy checkpoint without domain_context.",
                UserWarning,
                stacklevel=2,
            )
            return compose_prompt(task, get_domain_profile("beauty"))
        raise ValueError(
            f"{task} requires state.domain_context with both domain and profile_version."
        )

    domain = _get_value(domain_context, "domain")
    profile_version = _get_value(domain_context, "profile_version")
    if not domain or not profile_version:
        raise ValueError(
            f"{task} requires state.domain_context with both domain and profile_version."
        )

    profile = get_domain_profile(domain, version=profile_version)
    creator_profile = state.get("creator_profile")
    if creator_profile is None:
        return compose_prompt(task, profile)

    return _compose_prompt(task, profile, creator_profile)
