from pathlib import Path

from . import composer
from .composer import compose_prompt, compose_prompt_for_state, serialize_prompt_value

PROMPT_DIR = Path(__file__).resolve().parent

all_prompts = {}
for filepath in PROMPT_DIR.glob("*.txt"):
    prompt_name = filepath.stem.upper()
    all_prompts[prompt_name] = filepath.read_text(encoding="utf-8").strip()

__all__ = [
    "all_prompts",
    "composer",
    "compose_prompt",
    "compose_prompt_for_state",
    "serialize_prompt_value",
]
