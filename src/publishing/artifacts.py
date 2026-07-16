from __future__ import annotations

import copy
import errno
import fcntl
import hashlib
import io
import json
import os
import stat
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from PIL import Image, UnidentifiedImageError
from langgraph.types import StateSnapshot

from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas import (
    AssetManifest,
    CarouselPayload,
    ContentLock,
    RenderManifest,
    VisualPlan,
)
from src.schemas.carousel_qa import CarouselQAResult
from src.schemas.content_contract import ContentContract
from src.schemas.render_qa import RenderQAResult
from src.nodes.node_q_01_final_policy_guard import validate_final_policy
from src.editorial_carousel.legacy import (
    EDITORIAL_WORKFLOW_VERSION_KEY,
    LEGACY_EDITORIAL_CHECKPOINT_KEY,
    MODERN_EDITORIAL_V2,
)


LOCK_FIELDS = (
    "focus_keyword",
    "topic",
    "topic_id",
    "angle",
    "angle_id",
    "target_group",
    "core_pain",
    "title",
    "cover_copy",
    "first_screen_promise",
    "content",
    "hashtags",
    "storyboards",
)

PUBLISH_COPY_FILENAME = "publish-copy.txt"
RESCUE_PROMPT_FILENAME = "codex-image-regeneration-prompt.txt"
LEGACY_IMAGE_PROMPT_FILENAME = "Storyboard_images_generator_prompt.txt"
PACKAGE_LOCK_FILENAME = ".publish-artifacts.lock"
PACKAGE_VERSION_FILENAME = ".publish-artifacts.version"
PACKAGE_VERSION = 1
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "templates"
    / "codex_image_regeneration_prompt.txt"
)
_REFERENCE_MANIFEST_PATH = ASSET_ROOT / "references" / "manifest.json"
_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


class _FrozenList(tuple):
    pass


class ArtifactRollbackError(RuntimeError):
    def __init__(self, recovery_paths: Sequence[Path]):
        self.recovery_paths = tuple(recovery_paths)
        super().__init__(
            "artifact rollback restore failed; recovery backups preserved: "
            + ", ".join(str(path) for path in self.recovery_paths)
        )


class ArtifactCleanupError(RuntimeError):
    committed = True

    def __init__(self, recovery_paths: Sequence[Path]):
        self.recovery_paths = tuple(recovery_paths)
        super().__init__(
            "artifact export committed but cleanup failed; recovery files preserved: "
            + ", ".join(str(path) for path in self.recovery_paths)
        )


@dataclass(frozen=True)
class PublishArtifacts:
    package_directory: Path
    publish_copy_path: Path
    rescue_prompt_path: Path
    audit_json_path: Path
    rendered_image_paths: tuple[Path, ...]
    content_lock: ContentLock
    artifact_generation: int
    publish_attestation: "PublishAttestation"


@dataclass(frozen=True)
class PublishAttestation:
    publish_package_sha256: str
    visual_plan_sha256: str
    asset_manifest_sha256: str
    render_manifest_sha256: str
    carousel_qa_sha256: str
    render_qa_sha256: str
    content_lock_sha256: str
    rendered_artifact_sha256: tuple[tuple[str, str], ...]
    canonical_sha256: str


def canonical_content_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenList(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _freeze_package_snapshot(package: dict) -> Mapping[str, Any]:
    if not isinstance(package, dict):
        raise TypeError("publish package must be a dict")
    detached = copy.deepcopy(package)
    serialized = _json_value(detached)
    if not isinstance(serialized, dict):
        raise TypeError("publish package must serialize to a dict")
    return _deep_freeze(serialized)


def _require_locked_value(package: Mapping[str, Any], field: str) -> Any:
    if field not in package:
        raise ValueError(f"publish package is missing locked field: {field}")
    value = package[field]
    if field == "focus_keyword":
        if not isinstance(value, str):
            raise ValueError("locked field focus_keyword must be a string")
        return value
    if field == "hashtags":
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError("locked field hashtags must be a list of strings")
        return list(value)
    if not isinstance(value, str) or not value:
        raise ValueError(f"locked field {field} must be a non-empty string")
    return value


def _content_payload(package: Mapping[str, Any]) -> dict:
    if "content_contract" not in package:
        raise ValueError("publish package is missing locked content_contract")
    contract = ContentContract.model_validate(_deep_thaw(package["content_contract"]))
    if "storyboards" not in package:
        raise ValueError("publish package is missing locked field: storyboards")
    storyboard = CarouselPayload.model_validate(
        {"storyboards": _deep_thaw(package["storyboards"])}
    )

    payload = {
        field: _require_locked_value(package, field)
        for field in LOCK_FIELDS
        if field not in {"first_screen_promise", "storyboards"}
    }
    payload["first_screen_promise"] = contract.first_screen_promise
    payload["storyboards"] = storyboard.model_dump(mode="json")["storyboards"]
    return {field: payload[field] for field in LOCK_FIELDS}


def _build_content_lock(package: Mapping[str, Any]) -> ContentLock:
    payload = _content_payload(package)
    canonical_sha256 = hashlib.sha256(canonical_content_bytes(payload)).hexdigest()
    return ContentLock.model_validate(
        {**payload, "canonical_sha256": canonical_sha256}
    )


def build_content_lock(package: dict) -> ContentLock:
    return _build_content_lock(_freeze_package_snapshot(package))


def _build_publish_copy(package: Mapping[str, Any]) -> str:
    title = _require_locked_value(package, "title")
    content = _require_locked_value(package, "content")
    hashtags = _require_locked_value(package, "hashtags")
    return f"{title}\n\n{content}\n\n{' '.join(hashtags)}\n"


def build_publish_copy(package: dict) -> str:
    return _build_publish_copy(_freeze_package_snapshot(package))


def _lexical_absolute(raw_path: Any, *, label: str) -> Path:
    if not isinstance(raw_path, (str, os.PathLike)):
        raise ValueError(f"{label} must be a filesystem path")
    try:
        return Path(os.path.abspath(os.fspath(raw_path)))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} cannot be resolved: {exc}") from exc


def _canonical_absolute(raw_path: Any, *, label: str) -> Path:
    lexical = _lexical_absolute(raw_path, label=label)
    raw = Path(os.fspath(raw_path))
    if not raw.is_absolute() or raw != lexical:
        raise ValueError(f"{label} must be a canonical absolute path")
    if Path(os.path.realpath(raw)) != lexical:
        raise ValueError(f"{label} must not contain symlinked path components")
    return lexical


def _package_directory(package: Mapping[str, Any]) -> Path:
    raw_paths = package.get("rendered_image_paths")
    if isinstance(raw_paths, (list, tuple)) and raw_paths:
        return _canonical_absolute(
            raw_paths[0], label="rendered image path"
        ).parent.parent
    raw_directory = package.get("package_directory")
    if raw_directory is not None:
        return _lexical_absolute(raw_directory, label="package directory")
    return Path.cwd().absolute()


def _lock_payload(lock: ContentLock) -> dict:
    serialized = lock.model_dump(mode="json")
    return {field: serialized[field] for field in LOCK_FIELDS}


def _frame_text_table(
    lock: ContentLock,
    template_family: str,
) -> str:
    frames = lock.model_dump(mode="json")["storyboards"]
    rows: list[str] = []
    for index, frame in enumerate(frames, start=1):
        visible = {
            "headline": frame["headline"],
            "kicker": frame.get("kicker"),
            "content_blocks": frame.get("content_blocks", []),
            "emphasis": frame.get("emphasis", []),
            "footer": frame.get("footer"),
        }
        rows.append(
            f"{index}. template_family={template_family} "
            f"frame_id={frame['frame_id']} role={frame['role']} "
            f"page_archetype={frame['page_archetype']} "
            f"density={frame.get('content_density_hint', 'auto')} "
            "visible_text="
            + json.dumps(
                visible,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(rows)


def _build_codex_rescue_prompt(
    package: Mapping[str, Any],
    lock: ContentLock,
    reference_paths: Sequence[Path | str],
) -> str:
    if len(reference_paths) != 3:
        raise ValueError("rescue prompt requires exactly three reference-only anchors")
    expected_lock = _build_content_lock(package)
    if lock != expected_lock:
        raise ValueError("ContentLock does not match the current publish package")

    package_directory = _package_directory(package)
    title = _validate_title_component(_require_locked_value(package, "title"))
    rendered_references: list[str] = []
    for path in reference_paths:
        raw_path = os.fspath(path)
        if any(character in raw_path for character in ("\r", "\n", "\x00")):
            raise ValueError("rescue reference paths must not contain CR, LF, or NUL")
        rendered_references.append(f"- {Path(raw_path)}")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    visual_plan = package.get("visual_plan")
    template_family = (
        str(visual_plan.get("template_family") or "")
        if isinstance(visual_plan, Mapping)
        else ""
    )
    return template.format(
        content_lock_json=canonical_content_bytes(_lock_payload(lock)).decode("utf-8"),
        content_lock_sha256=lock.canonical_sha256,
        frame_text_table=_frame_text_table(lock, template_family),
        package_directory=package_directory,
        audit_json_path=package_directory / f"{title}.json",
        current_images_directory=package_directory / "images",
        style_reference_paths="\n".join(rendered_references),
    )


def build_codex_rescue_prompt(
    package: dict,
    lock: ContentLock,
    reference_paths: Sequence[Path | str],
) -> str:
    return _build_codex_rescue_prompt(
        _freeze_package_snapshot(package), lock, reference_paths
    )


def _approved_reference_paths() -> tuple[Path, Path, Path]:
    try:
        manifest = json.loads(_REFERENCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"reference-only manifest could not be loaded: {exc}") from exc
    entries = manifest.get("assets")
    if not isinstance(entries, list) or len(entries) != 3:
        raise ValueError("reference-only manifest must contain exactly three anchors")

    paths: list[Path] = []
    reference_root = _REFERENCE_MANIFEST_PATH.parent.resolve()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("usage") != "reference_only":
            raise ValueError("all rescue anchors must be reference_only")
        path = (reference_root / str(entry.get("path", ""))).resolve()
        if not path.is_relative_to(reference_root) or not path.is_file():
            raise ValueError("reference-only anchor path is invalid")
        expected_sha256 = entry.get("sha256")
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError("reference-only anchor sha256 does not match file bytes")
        paths.append(path)
    return paths[0], paths[1], paths[2]


def _validate_manifest_snapshot(
    package: Mapping[str, Any],
) -> tuple[VisualPlan, AssetManifest, RenderManifest]:
    visual_plan = VisualPlan.model_validate(_deep_thaw(package.get("visual_plan")))
    asset_manifest = AssetManifest.model_validate(
        _deep_thaw(package.get("asset_manifest"))
    )
    if any(item.status == "pending_external" for item in asset_manifest.items):
        raise ValueError("publish authorization rejects pending assets")
    render_manifest = RenderManifest.model_validate(
        _deep_thaw(package.get("render_manifest"))
    )

    package_flag = package.get("focus_keyword_cli_present")
    if type(package_flag) is not bool:
        raise ValueError("focus_keyword_cli_present must be an authoritative bool")
    focus_keyword = _require_locked_value(package, "focus_keyword")
    if package_flag and not focus_keyword.strip():
        raise ValueError("explicit CLI focus_keyword cannot be empty")
    if not package_flag and focus_keyword == "":
        pass

    return visual_plan, asset_manifest, render_manifest


def validate_publishability(package: dict) -> None:
    """Validate low-level package shape; this does not authorize final export."""
    _validate_manifest_snapshot(_freeze_package_snapshot(package))


def _completed_state_snapshot(completed_state: Any) -> tuple[dict, Mapping[str, Any]]:
    if type(completed_state) is not StateSnapshot:
        raise TypeError("final export requires a real langgraph.types.StateSnapshot")
    if type(completed_state.next) is not tuple or completed_state.next != ():
        raise ValueError("final export requires terminal StateSnapshot next to be ()")
    values = completed_state.values
    if not isinstance(values, Mapping):
        raise TypeError("final export requires completed_state.values")
    if values.get(EDITORIAL_WORKFLOW_VERSION_KEY) != MODERN_EDITORIAL_V2:
        raise ValueError("final export requires editorial_workflow_version == modern_v2")
    if values.get(LEGACY_EDITORIAL_CHECKPOINT_KEY) is not False:
        raise ValueError("final export rejects legacy or hybrid editorial checkpoints")

    detached = _json_value(copy.deepcopy(dict(values)))
    if not isinstance(detached, dict) or not isinstance(detached.get("publish_package"), dict):
        raise ValueError("completed state requires publish_package")
    package = detached["publish_package"]
    for field in ("visual_plan", "asset_manifest", "render_manifest"):
        if field not in detached:
            raise ValueError(f"completed state requires {field}")
        package[field] = detached[field]
    package.pop("publish_authorization", None)
    package.pop("publish_attestation", None)
    package.pop("expected_artifact_generation", None)
    if type(detached.get("focus_keyword_cli_present")) is not bool:
        raise ValueError("completed state requires authoritative focus_keyword_cli_present")
    package["focus_keyword_cli_present"] = detached["focus_keyword_cli_present"]
    if detached.get("focus_keyword") != package.get("focus_keyword"):
        raise ValueError("completed state focus_keyword binding changed")
    if detached.get("review_status") != "approved":
        raise ValueError("completed state requires approved review")
    carousel_qa = CarouselQAResult.model_validate(detached.get("carousel_qa_result"))
    render_qa = RenderQAResult.model_validate(detached.get("render_qa_result"))
    if not carousel_qa.passed or carousel_qa.issues:
        raise ValueError("completed state requires passed Carousel QA")
    if not render_qa.passed or render_qa.issues:
        raise ValueError("completed state requires passed Render QA")
    issues = validate_final_policy(detached)
    if issues:
        raise ValueError(
            "completed state failed recomputed Final Guard: "
            + json.dumps(issues, ensure_ascii=False, sort_keys=True)
        )
    return detached, _freeze_package_snapshot(package)


def _validate_title_component(title: str) -> str:
    if title.startswith(".") or "/" in title or "\\" in title:
        raise ValueError("publish title must be one safe filename component")
    if any(unicodedata.category(character).startswith("C") for character in title):
        raise ValueError("publish title must not contain control characters")
    return title


def _read_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _decode_png(data: bytes, *, label: str, required_size: tuple[int, int] | None) -> None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"{label} must decode as PNG")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if required_size is not None and image.size != required_size:
                raise ValueError(f"{label} must be 1080 x 1440")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"{label} failed full PNG decode") from exc


def _open_regular_snapshot(
    directory_fd: int,
    name: str,
    *,
    label: str,
) -> tuple[tuple[int, int], bytes]:
    try:
        descriptor = os.open(name, os.O_RDONLY | _OPEN_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(f"{label} must not be a symlink") from exc
        raise ValueError(f"{label} cannot be opened") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if metadata.st_nlink != 1:
            raise ValueError(f"{label} must not be a hardlink")
        data = _read_all(descriptor)
        after = os.fstat(descriptor)
        try:
            named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValueError(f"{label} changed during snapshot") from exc
        before_binding = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        after_binding = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_binding != after_binding or (
            named.st_dev,
            named.st_ino,
        ) != (metadata.st_dev, metadata.st_ino):
            raise ValueError(f"{label} changed during snapshot")
        return (metadata.st_dev, metadata.st_ino), data
    finally:
        os.close(descriptor)


def _validate_rendered_snapshots(
    package: Mapping[str, Any],
    package_directory: Path,
    package_fd: int,
    render_manifest: RenderManifest,
) -> tuple[Path, ...]:
    raw_paths = package.get("rendered_image_paths")
    if not isinstance(raw_paths, (list, tuple)) or len(raw_paths) != len(
        render_manifest.pages
    ):
        raise ValueError(
            "publish_package rendered_image_paths must match the 5-7 RenderManifest pages"
        )
    image_directory = package_directory / "images"
    try:
        image_fd = os.open(
            "images",
            os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW,
            dir_fd=package_fd,
        )
    except OSError as exc:
        raise ValueError("package images directory must be canonical and non-symlink") from exc
    image_directory_metadata = os.fstat(image_fd)

    identities: set[tuple[int, int]] = set()
    rendered_paths: list[Path] = []
    page_hashes: list[str] = []
    listed_names: set[str] = set()
    try:
        for index, (raw_path, page) in enumerate(
            zip(raw_paths, render_manifest.pages, strict=True), start=1
        ):
            image_path = _canonical_absolute(
                raw_path, label=f"rendered image path {index}"
            )
            manifest_path = _canonical_absolute(
                page.path, label=f"RenderManifest page path {index}"
            )
            if image_path != manifest_path:
                raise ValueError("rendered_image_paths must preserve RenderManifest order")
            if image_path.parent != image_directory:
                raise ValueError("rendered image paths must stay in package images")
            expected_name = "01-cover.png" if index == 1 else None
            if expected_name is not None and image_path.name != expected_name:
                raise ValueError("RenderManifest page paths must start with 01-cover.png")
            if index > 1 and not image_path.name.startswith(f"{index:02d}-"):
                raise ValueError("RenderManifest page paths must use ordered NN-role names")
            if image_path.suffix.lower() != ".png":
                raise ValueError("rendered image paths must be PNG files")
            identity, data = _open_regular_snapshot(
                image_fd, image_path.name, label=f"rendered page {index}"
            )
            if identity in identities:
                raise ValueError("rendered pages must have distinct canonical inodes")
            identities.add(identity)
            actual_hash = hashlib.sha256(data).hexdigest()
            if actual_hash != page.sha256:
                raise ValueError(f"rendered page {index} sha256 changed after RenderManifest")
            _decode_png(
                data,
                label=f"rendered page {index}",
                required_size=(1080, 1440),
            )
            page_hashes.append(actual_hash)
            listed_names.add(image_path.name)
            rendered_paths.append(image_path)

        contact_path = _canonical_absolute(
            render_manifest.contact_sheet_path, label="contact sheet path"
        )
        if contact_path.parent != image_directory or contact_path.name != "contact-sheet.png":
            raise ValueError(
                "RenderManifest contact sheet must use images/contact-sheet.png"
            )
        contact_identity, contact_data = _open_regular_snapshot(
            image_fd, contact_path.name, label="contact sheet"
        )
        if contact_identity in identities:
            raise ValueError("contact sheet must be distinct from every page inode")
        actual_contact_hash = hashlib.sha256(contact_data).hexdigest()
        if actual_contact_hash != render_manifest.contact_sheet_sha256:
            raise ValueError("contact sheet sha256 changed after RenderManifest")
        _decode_png(contact_data, label="contact sheet", required_size=None)
        if list(render_manifest.contact_sheet_page_sha256) != page_hashes:
            raise ValueError("contact sheet page hashes must match current page bytes")
        listed_names.add(contact_path.name)
        actual_png_names = {
            name for name in os.listdir(image_fd) if name.lower().endswith(".png")
        }
        if actual_png_names != listed_names:
            raise ValueError(
                "package images directory contains an unlisted PNG or is missing a manifest PNG"
            )
        current_image_directory = os.stat(
            "images", dir_fd=package_fd, follow_symlinks=False
        )
        if (
            current_image_directory.st_dev,
            current_image_directory.st_ino,
        ) != (
            image_directory_metadata.st_dev,
            image_directory_metadata.st_ino,
        ):
            raise ValueError("package images directory changed during snapshot")
    finally:
        os.close(image_fd)
    return tuple(rendered_paths)


@dataclass(frozen=True)
class _ExportLock:
    package_fd: int
    parent_fd: int
    package_directory: Path
    parent_identity: tuple[int, int]
    package_identity: tuple[int, int]
    lock_fd: int
    lock_name: str
    lock_identity: tuple[int, int]

    def verify(self) -> None:
        try:
            parent = os.stat(
                self.package_directory.parent,
                follow_symlinks=False,
            )
            package = os.stat(
                self.package_directory.name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
            lock = os.stat(
                self.lock_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise ValueError("publish package or lock binding changed") from exc
        if (
            not stat.S_ISDIR(parent.st_mode)
            or (parent.st_dev, parent.st_ino) != self.parent_identity
        ):
            raise ValueError("publish package parent binding changed")
        if (
            not stat.S_ISDIR(package.st_mode)
            or (package.st_dev, package.st_ino) != self.package_identity
        ):
            raise ValueError("publish package directory binding changed")
        if (
            not stat.S_ISREG(lock.st_mode)
            or lock.st_nlink != 1
            or (lock.st_dev, lock.st_ino) != self.lock_identity
        ):
            raise ValueError("publish package lock binding changed")
        opened_lock = os.fstat(self.lock_fd)
        if (
            not stat.S_ISREG(opened_lock.st_mode)
            or opened_lock.st_nlink != 1
            or (opened_lock.st_dev, opened_lock.st_ino) != self.lock_identity
        ):
            raise ValueError("publish package lock binding changed")


@contextmanager
def _package_export_lock(package_directory: Path):
    parent_directory = package_directory.parent
    try:
        parent_fd = os.open(
            parent_directory,
            os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW,
        )
    except OSError as exc:
        raise ValueError("publish package parent must be canonical and non-symlink") from exc
    package_fd: int | None = None
    lock_fd: int | None = None
    lock_name = f".{package_directory.name}.publish-artifacts.lock"
    try:
        package_fd = os.open(
            package_directory.name,
            os.O_RDONLY | _OPEN_DIRECTORY | _OPEN_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        os.close(parent_fd)
        raise ValueError("publish package directory must be canonical and non-symlink") from exc
    opened_package = os.fstat(package_fd)
    try:
        named_package = os.stat(
            package_directory.name, dir_fd=parent_fd, follow_symlinks=False
        )
    except OSError as exc:
        os.close(package_fd)
        os.close(parent_fd)
        raise ValueError("publish package directory binding changed") from exc
    if (opened_package.st_dev, opened_package.st_ino) != (
        named_package.st_dev,
        named_package.st_ino,
    ):
        os.close(package_fd)
        os.close(parent_fd)
        raise ValueError("publish package directory binding changed")
    try:
        try:
            try:
                lock_fd = os.open(
                    lock_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                lock_fd = os.open(
                    lock_name,
                    os.O_RDWR | _OPEN_NOFOLLOW,
                    dir_fd=parent_fd,
                )
        except OSError as exc:
            raise ValueError("publish package lock must be a canonical regular file") from exc
        metadata = os.fstat(lock_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("publish package lock must be a canonical regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        current = os.stat(
            lock_name, dir_fd=parent_fd, follow_symlinks=False
        )
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("publish package lock changed while acquiring flock")
        export_lock = _ExportLock(
            package_fd=package_fd,
            parent_fd=parent_fd,
            package_directory=package_directory,
            parent_identity=(os.fstat(parent_fd).st_dev, os.fstat(parent_fd).st_ino),
            package_identity=(opened_package.st_dev, opened_package.st_ino),
            lock_fd=lock_fd,
            lock_name=lock_name,
            lock_identity=(metadata.st_dev, metadata.st_ino),
        )
        export_lock.verify()
        # This lock coordinates cooperating exporters and detects observed pathname
        # replacement. A same-uid non-cooperating process can still mutate files
        # after the final verification; Unix advisory locks cannot prevent that.
        yield export_lock
        export_lock.verify()
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        if package_fd is not None:
            os.close(package_fd)
        os.close(parent_fd)


def _secure_existing_file_bytes(package_fd: int, name: str) -> bytes | None:
    try:
        identity, data = _open_regular_snapshot(
            package_fd, name, label=f"package support file {name}"
        )
    except ValueError as exc:
        try:
            os.stat(name, dir_fd=package_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        raise exc
    del identity
    return data


def _read_package_version(package_fd: int) -> dict | None:
    data = _secure_existing_file_bytes(package_fd, PACKAGE_VERSION_FILENAME)
    if data is None:
        return None
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("publish artifact version file is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("version") != PACKAGE_VERSION
        or type(value.get("artifact_generation")) is not int
        or value["artifact_generation"] < 1
        or not isinstance(value.get("audit_filename"), str)
    ):
        raise ValueError("publish artifact version file is invalid")
    return value


def _existing_audit_json_names(package_fd: int) -> set[str]:
    names = {
        name
        for name in os.listdir(package_fd)
        if name.endswith(".json") and not name.startswith(".")
    }
    for name in names:
        metadata = os.stat(name, dir_fd=package_fd, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("existing publish audit must be a canonical regular file")
    return names


def _stage_bytes(
    package_fd: int, package_directory: Path, destination_name: str, payload: bytes
) -> Path:
    temp_name = f".{destination_name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW,
        0o600,
        dir_fd=package_fd,
    )
    temp_path = package_directory / temp_name
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
    except BaseException:
        try:
            os.unlink(temp_name, dir_fd=package_fd)
        except OSError:
            pass
        raise
    return temp_path


def _fsync_directory_fd(package_fd: int) -> None:
    os.fsync(package_fd)


def _replace_at(
    package_fd: int,
    source: Path,
    destination: Path,
    *,
    verify: Callable[[], None] | None = None,
) -> None:
    if verify is not None:
        verify()
    os.replace(
        source.name,
        destination.name,
        src_dir_fd=package_fd,
        dst_dir_fd=package_fd,
    )


def _unlink_at(
    package_fd: int,
    path: Path,
    *,
    verify: Callable[[], None] | None = None,
) -> None:
    if verify is not None:
        verify()
    os.unlink(path.name, dir_fd=package_fd)
    if verify is not None:
        verify()


def _exists_at(package_fd: int, path: Path) -> bool:
    try:
        metadata = os.stat(path.name, dir_fd=package_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"existing support artifact is not canonical: {path.name}")
    return True


def _transactional_replace_artifacts(
    package_fd: int,
    package_directory: Path,
    payloads: Mapping[Path, bytes],
    *,
    delete_paths: Sequence[Path],
    verify: Callable[[], None] | None = None,
) -> None:
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    backup_payloads: dict[Path, bytes] = {}
    committed: set[Path] = set()

    def rollback(original_error: BaseException) -> None:
        recovery_paths: list[Path] = []
        for destination in reversed((*payloads.keys(), *delete_paths)):
            backup = backups.get(destination)
            if backup is not None:
                try:
                    if _exists_at(package_fd, backup):
                        _replace_at(package_fd, backup, destination)
                    else:
                        recovery_temp = _stage_bytes(
                            package_fd,
                            package_directory,
                            destination.name,
                            backup_payloads[destination],
                        )
                        _replace_at(package_fd, recovery_temp, destination)
                except (KeyError, OSError, ValueError):
                    recovery_paths.append(backup)
                    if destination in committed:
                        try:
                            _unlink_at(package_fd, destination)
                        except FileNotFoundError:
                            pass
                        except OSError:
                            recovery_paths.append(destination)
            elif destination in committed:
                try:
                    _unlink_at(package_fd, destination)
                except OSError:
                    recovery_paths.append(destination)
        for destination, temp_path in staged.items():
            if destination in committed:
                continue
            try:
                _unlink_at(package_fd, temp_path)
            except OSError:
                recovery_paths.append(temp_path)
        try:
            _fsync_directory_fd(package_fd)
        except OSError:
            recovery_paths.append(package_directory)
        if recovery_paths:
            raise ArtifactRollbackError(recovery_paths) from original_error
        raise original_error

    try:
        for destination, payload in payloads.items():
            if verify is not None:
                verify()
            staged[destination] = _stage_bytes(
                package_fd, package_directory, destination.name, payload
            )

        for destination in (*payloads.keys(), *delete_paths):
            if verify is not None:
                verify()
            if _exists_at(package_fd, destination):
                existing_payload = _secure_existing_file_bytes(
                    package_fd, destination.name
                )
                if existing_payload is None:
                    raise ValueError("existing support artifact disappeared")
                backup_payloads[destination] = existing_payload
                backup = package_directory / (
                    f".{destination.name}.{uuid.uuid4().hex}.backup"
                )
                _replace_at(package_fd, destination, backup, verify=verify)
                backups[destination] = backup

        for destination, temp_path in staged.items():
            _replace_at(package_fd, temp_path, destination, verify=verify)
            committed.add(destination)
        if verify is not None:
            verify()
        _fsync_directory_fd(package_fd)
        if verify is not None:
            verify()
            # Keep all backups until the final pathname/input preflight passes.
            # A binding failure here still enters the rollback block below.
            verify()
    except BaseException as original_error:
        rollback(original_error)

    cleanup_failures: list[Path] = []
    try:
        for backup in backups.values():
            try:
                _unlink_at(package_fd, backup, verify=verify)
            except OSError:
                cleanup_failures.append(backup)
        try:
            _fsync_directory_fd(package_fd)
        except OSError:
            cleanup_failures.append(package_directory)
        if verify is not None:
            verify()
    except ValueError as binding_error:
        rollback(binding_error)
    if cleanup_failures:
        raise ArtifactCleanupError(cleanup_failures)


def _relative_package_path(value: Any, package_directory: Path) -> Any:
    if not isinstance(value, str):
        return value
    path = _lexical_absolute(value, label="audit package path")
    try:
        return path.relative_to(package_directory).as_posix()
    except ValueError:
        return value


def _portable_audit(
    package: Mapping[str, Any], package_directory: Path
) -> dict[str, Any]:
    audit = _deep_thaw(package)
    audit["rendered_image_paths"] = [
        _relative_package_path(path, package_directory)
        for path in audit.get("rendered_image_paths", [])
    ]
    render_manifest = audit.get("render_manifest") or {}
    for page in render_manifest.get("pages", []):
        page["path"] = _relative_package_path(page.get("path"), package_directory)
    render_manifest["contact_sheet_path"] = _relative_package_path(
        render_manifest.get("contact_sheet_path"), package_directory
    )
    for item in (audit.get("asset_manifest") or {}).get("items", []):
        for field in ("path", "metadata_path", "license_snapshot"):
            if item.get(field):
                item[field] = _relative_package_path(item[field], package_directory)
    return audit


def _verify_committed_payloads(
    package_fd: int,
    payloads: Mapping[Path, bytes],
) -> None:
    for path, expected in payloads.items():
        actual = _secure_existing_file_bytes(package_fd, path.name)
        if actual != expected:
            raise ValueError(f"committed support artifact changed: {path.name}")


def _verify_deleted_paths_absent(
    package_fd: int,
    delete_paths: Sequence[Path],
) -> None:
    for path in delete_paths:
        try:
            os.stat(path.name, dir_fd=package_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise ValueError(f"legacy delete path was recreated: {path.name}")


def current_artifact_generation(package: dict) -> int:
    snapshot = _freeze_package_snapshot(package)
    package_directory = _package_directory(snapshot)
    with _package_export_lock(package_directory) as export_lock:
        export_lock.verify()
        current_version = _read_package_version(export_lock.package_fd)
        return current_version["artifact_generation"] if current_version else 0


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_content_bytes(_json_value(value))).hexdigest()


def _build_publish_attestation(
    snapshot: Mapping[str, Any],
    completed_values: Mapping[str, Any],
    lock: ContentLock,
    render_manifest: RenderManifest,
    publish_copy: bytes,
    rescue_prompt: bytes,
) -> PublishAttestation:
    rendered_digests = tuple(
        (Path(page.path).name, page.sha256) for page in render_manifest.pages
    ) + ((Path(render_manifest.contact_sheet_path).name, render_manifest.contact_sheet_sha256),)
    payload = {
        "publish_package_sha256": _sha256_json(_deep_thaw(snapshot)),
        "visual_plan_sha256": _sha256_json(completed_values["visual_plan"]),
        "asset_manifest_sha256": _sha256_json(completed_values["asset_manifest"]),
        "render_manifest_sha256": _sha256_json(completed_values["render_manifest"]),
        "carousel_qa_sha256": _sha256_json(completed_values["carousel_qa_result"]),
        "render_qa_sha256": _sha256_json(completed_values["render_qa_result"]),
        "content_lock_sha256": lock.canonical_sha256,
        "rendered_artifact_sha256": rendered_digests
        + (
            (PUBLISH_COPY_FILENAME, hashlib.sha256(publish_copy).hexdigest()),
            (RESCUE_PROMPT_FILENAME, hashlib.sha256(rescue_prompt).hexdigest()),
        ),
    }
    return PublishAttestation(
        **payload,
        canonical_sha256=_sha256_json(payload),
    )


def _export_publish_package_snapshot(
    snapshot: Mapping[str, Any],
    completed_values: Mapping[str, Any],
    *,
    expected_generation: int | None = None,
) -> PublishArtifacts:
    visual_plan, asset_manifest, render_manifest = _validate_manifest_snapshot(snapshot)
    package_directory = _package_directory(snapshot)
    title = _validate_title_component(_require_locked_value(snapshot, "title"))
    if expected_generation is not None and (
        type(expected_generation) is not int or expected_generation < 0
    ):
        raise ValueError("expected_generation must be a non-negative int")

    with _package_export_lock(package_directory) as export_lock:
        package_fd = export_lock.package_fd
        export_lock.verify()
        current_version = _read_package_version(package_fd)
        current_generation = (
            current_version["artifact_generation"] if current_version else 0
        )
        if expected_generation is not None and expected_generation != current_generation:
            raise ValueError(
                "publish artifact generation compare-and-swap failed: "
                f"expected {expected_generation}, found {current_generation}"
            )
        audit_filename = f"{title}.json"
        if current_version and current_version["audit_filename"] != audit_filename:
            raise ValueError("title-changing re-export is not allowed")
        existing_audits = _existing_audit_json_names(package_fd)
        if existing_audits - {audit_filename}:
            raise ValueError("a different title audit already exists in the package")
        if current_version and existing_audits != {audit_filename}:
            raise ValueError("versioned publish package is missing its sole audit JSON")

        def verify_export_inputs() -> None:
            export_lock.verify()
            _validate_rendered_snapshots(
                snapshot,
                package_directory,
                package_fd,
                render_manifest,
            )

        rendered_image_paths = _validate_rendered_snapshots(
            snapshot, package_directory, package_fd, render_manifest
        )
        lock = _build_content_lock(snapshot)
        rescue_prompt = _build_codex_rescue_prompt(
            snapshot,
            lock,
            _approved_reference_paths(),
        )
        publish_copy = _build_publish_copy(snapshot).encode("utf-8")
        rescue_prompt_bytes = rescue_prompt.encode("utf-8")
        publish_attestation = _build_publish_attestation(
            snapshot,
            completed_values,
            lock,
            render_manifest,
            publish_copy,
            rescue_prompt_bytes,
        )
        next_generation = current_generation + 1
        audit = _portable_audit(snapshot, package_directory)
        audit["content_lock"] = lock.model_dump(mode="json")
        audit["visual_plan"] = visual_plan.model_dump(mode="json")
        audit["asset_manifest"] = _portable_audit(
            {"asset_manifest": asset_manifest.model_dump(mode="json")},
            package_directory,
        )["asset_manifest"]
        audit["render_manifest"] = _portable_audit(
            {"render_manifest": render_manifest.model_dump(mode="json")},
            package_directory,
        )["render_manifest"]
        audit["artifact_generation"] = next_generation
        audit["publish_attestation"] = asdict(publish_attestation)
        audit["review_status"] = completed_values["review_status"]
        audit["carousel_qa_result"] = _json_value(completed_values["carousel_qa_result"])
        audit["render_qa_result"] = _json_value(completed_values["render_qa_result"])
        audit["final_policy_issues"] = []

        publish_copy_path = package_directory / PUBLISH_COPY_FILENAME
        rescue_prompt_path = package_directory / RESCUE_PROMPT_FILENAME
        audit_json_path = package_directory / audit_filename
        version_path = package_directory / PACKAGE_VERSION_FILENAME
        version_payload = {
            "version": PACKAGE_VERSION,
            "artifact_generation": next_generation,
            "audit_filename": audit_filename,
            "content_lock_sha256": lock.canonical_sha256,
        }
        payloads = {
            publish_copy_path: publish_copy,
            rescue_prompt_path: rescue_prompt_bytes,
            audit_json_path: (
                json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8"),
            version_path: (
                json.dumps(
                    version_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        }
        delete_paths = (package_directory / LEGACY_IMAGE_PROMPT_FILENAME,)
        _transactional_replace_artifacts(
            package_fd,
            package_directory,
            payloads,
            delete_paths=delete_paths,
            verify=verify_export_inputs,
        )
        verify_export_inputs()
        _verify_committed_payloads(package_fd, payloads)
        _verify_deleted_paths_absent(package_fd, delete_paths)

    return PublishArtifacts(
        package_directory=package_directory,
        publish_copy_path=publish_copy_path,
        rescue_prompt_path=rescue_prompt_path,
        audit_json_path=audit_json_path,
        rendered_image_paths=rendered_image_paths,
        content_lock=lock,
        artifact_generation=next_generation,
        publish_attestation=publish_attestation,
    )


def _export_verified_state_snapshot(completed_state: StateSnapshot) -> PublishArtifacts:
    """Export only a frozen terminal graph state after recomputing Final Guard."""
    completed_values, snapshot = _completed_state_snapshot(completed_state)
    return _export_publish_package_snapshot(snapshot, completed_values)


def export_publish_package(completed_state: StateSnapshot) -> PublishArtifacts:
    """Public final exporter; accepts only a real modern terminal StateSnapshot."""
    return _export_verified_state_snapshot(completed_state)
