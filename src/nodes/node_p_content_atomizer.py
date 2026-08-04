import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Literal

from src.schemas import (
    AgentState,
    ContentAtom,
    ContentAtomSet,
    canonical_sha256,
    sha256_text,
)


AtomRole = Literal[
    "title",
    "cover",
    "heading",
    "paragraph",
    "list_item",
    "step",
    "quote",
]

_BLOCK_MARKERS: tuple[tuple[AtomRole, re.Pattern[str]], ...] = (
    ("heading", re.compile(r"^[ \t]*#{1,6}[ \t]+(.*)$")),
    ("step", re.compile(r"^[ \t]*\d+[.)][ \t]+(.*)$")),
    ("list_item", re.compile(r"^[ \t]*[-+*][ \t]+(.*)$")),
    ("quote", re.compile(r"^[ \t]*>[ \t]?(.*)$")),
)

_THEMATIC_BREAK = re.compile(
    r"^[ \t]*(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$"
)


def _is_markdown_table_separator(line: str) -> bool:
    """True for a structural markdown table separator row (e.g. ``|------|``,
    ``| :--- | ---: |``).

    A separator row is table syntax, not visible copy. If it became a content
    atom, the fragment-coverage rule would force the carousel to render the raw
    ``|---|---|`` markup as visible text, so the atomizer must skip it the same
    way it skips thematic breaks.
    """
    stripped = line.strip()
    if "|" not in stripped or stripped.count("-") < 3:
        return False
    return all(char in "|:-\t " for char in stripped)

_INLINE_MARKERS = (
    re.compile(r"(?<!\\)\*\*(?=\S)(.+?)(?<=\S)\*\*"),
    re.compile(r"(?<!\\)__(?=\S)(.+?)(?<=\S)__"),
    re.compile(r"(?<!\\)~~(?=\S)(.+?)(?<=\S)~~"),
    re.compile(r"(?<![\\*])\*(?=\S)(.+?)(?<=\S)\*(?!\*)"),
    re.compile(r"(?<![\\_\w])_(?=\S)(.+?)(?<=\S)_(?![_\w])"),
)

_FORBIDDEN_VISIBLE_COPY = (
    re.compile(
        r"(?:本|此|该)?(?:图|图片|图像|内容|素材|页面|本文)\s*"
        r"(?:由|使用|采用|系|为)\s*"
        r"(?:AI|人工智能)\s*(?:技术\s*)?(?:辅助|参与)?\s*"
        r"(?:生成|绘制|创作|制作)",
        re.IGNORECASE,
    ),
    re.compile(
        r"^[ \t（(【\[]*(?:AI|人工智能)\s*(?:技术\s*)?"
        r"(?:辅助|参与)?\s*(?:生成|绘制|创作|制作)(?:的)?"
        r"(?:内容|图像|图片|示意图|素材)?"
        r"[ \t）)】\]。！!：:]*$",
        re.IGNORECASE,
    ),
    re.compile(r"示意图"),
    re.compile(r"免责声明"),
    re.compile(r"仅供参考"),
    re.compile(
        r"(?:本文|本内容|以上内容|相关内容)?\s*"
        r"(?:不能|无法|不可)\s*(?:替代|代替)\s*"
        r"(?:专业)?(?:医生|医师|医疗|诊断|治疗)?(?:的)?"
        r"(?:建议|诊疗|诊断|治疗)"
    ),
    re.compile(
        r"(?:本文|本内容|以上内容|相关内容)?\s*"
        r"不(?:作为|构成)(?:任何)?\s*"
        r"(?:医疗|医学|诊疗|诊断|治疗|用药)(?:建议|依据|指导)"
    ),
    re.compile(
        r"(?:本文|本内容|以上内容|相关内容|内容)?仅"
        r"(?:作|供|用于)(?:一般)?(?:科普|参考|信息分享)"
    ),
)


def _required_visible_field(package: Mapping[str, object], field: str) -> str:
    value = package.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"publish_package.{field} must be a non-empty string")
    return value


def _strip_inline_markdown(text: str) -> str:
    for pattern in _INLINE_MARKERS:
        while True:
            updated, replacements = pattern.subn(r"\1", text)
            text = updated
            if replacements == 0:
                break
    return text


def find_forbidden_visible_system_copy(
    *,
    title: str,
    cover_copy: str,
    content: str,
) -> list[str]:
    issues: list[str] = []
    for field, value in (
        ("title", title),
        ("cover_copy", cover_copy),
        ("content", content),
    ):
        for line in value.splitlines() or [value]:
            visible_line = _strip_inline_markdown(line)
            if any(
                pattern.search(visible_line)
                for pattern in _FORBIDDEN_VISIBLE_COPY
            ):
                issues.append(
                    f"{field} 包含禁止的页面可见系统说明或免责声明，"
                    f"请在 R2 移除：{line}"
                )
    return issues


def _parse_content_line(line: str) -> tuple[AtomRole, str]:
    for role, pattern in _BLOCK_MARKERS:
        match = pattern.fullmatch(line)
        if match is not None:
            return role, match.group(1)
    return "paragraph", line


def build_content_atoms(
    *,
    title: str,
    cover_copy: str,
    content: str,
) -> tuple[ContentAtom, ...]:
    counters: defaultdict[AtomRole, int] = defaultdict(int)
    atoms: list[ContentAtom] = []

    def append_atom(role: AtomRole, text: str) -> None:
        if not text:
            return
        counters[role] += 1
        atoms.append(
            ContentAtom(
                atom_id=f"{role}-{counters[role]:03d}",
                text=text,
                role=role,
                sha256=sha256_text(text),
            )
        )

    append_atom("title", _strip_inline_markdown(title))
    append_atom("cover", _strip_inline_markdown(cover_copy))
    for line in content.splitlines():
        if not line.strip():
            continue
        if _THEMATIC_BREAK.fullmatch(line):
            continue
        if _is_markdown_table_separator(line):
            continue
        role, text = _parse_content_line(line)
        append_atom(role, _strip_inline_markdown(text))
    return tuple(atoms)


def content_atomizer_node(state: AgentState) -> dict:
    package = state.get("publish_package")
    if not isinstance(package, Mapping):
        raise ValueError("content_atomizer requires publish_package")

    title = _required_visible_field(package, "title")
    cover_copy = _required_visible_field(package, "cover_copy")
    content = _required_visible_field(package, "content")
    issues = find_forbidden_visible_system_copy(
        title=title,
        cover_copy=cover_copy,
        content=content,
    )
    if issues:
        return {
            "content_atom_set": None,
            "content_atomization_route": "r2_compliance",
            "content_atomization_issues": issues,
            "current_node": "CONTENT_ATOMIZER",
        }

    atoms = build_content_atoms(
        title=title,
        cover_copy=cover_copy,
        content=content,
    )
    atom_set = ContentAtomSet(
        atoms=atoms,
        canonical_sha256=canonical_sha256(
            [atom.model_dump(mode="json") for atom in atoms]
        ),
    )
    return {
        "content_atom_set": atom_set,
        "content_atomization_route": "visual_director",
        "content_atomization_issues": [],
        "current_node": "CONTENT_ATOMIZER",
    }
