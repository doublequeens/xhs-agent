from collections.abc import Iterator, Mapping
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent


class _LazyPromptMapping(Mapping[str, str]):
    def __init__(self, prompt_dir: Path):
        self._paths = {
            filepath.stem.upper(): filepath
            for filepath in sorted(prompt_dir.glob("*.txt"))
        }
        self._cache: dict[str, str] = {}

    def __getitem__(self, key: str) -> str:
        try:
            filepath = self._paths[key]
        except KeyError as exc:
            raise KeyError(key) from exc

        if key not in self._cache:
            self._cache[key] = filepath.read_text(encoding="utf-8").strip()
        return self._cache[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __len__(self) -> int:
        return len(self._paths)


all_prompts = _LazyPromptMapping(PROMPT_DIR)
