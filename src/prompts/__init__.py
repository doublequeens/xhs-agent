from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

all_prompts = {}
for filepath in PROMPT_DIR.glob("*.txt"):
    prompt_name = filepath.stem.upper()
    all_prompts[prompt_name] = filepath.read_text(encoding="utf-8").strip()
