from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rendering.editorial.design_system import ASSET_ROOT
from src.schemas import (
    AssetManifest,
    CarouselPayload,
    ContentLock,
    RenderManifest,
    VisualPlan,
)
from src.schemas.content_contract import ContentContract


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
_TEMPLATE_PATH = (
    Path(__file__).resolve().parent
    / "templates"
    / "codex_image_regeneration_prompt.txt"
)
_REFERENCE_MANIFEST_PATH = ASSET_ROOT / "references" / "manifest.json"


@dataclass(frozen=True)
class PublishArtifacts:
    package_directory: Path
    publish_copy_path: Path
    rescue_prompt_path: Path
    audit_json_path: Path
    rendered_image_paths: tuple[Path, ...]
    content_lock: ContentLock


def canonical_content_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_package_dict(package: dict) -> dict:
    if not isinstance(package, dict):
        raise TypeError("publish package must be a dict")
    return package


def _require_locked_value(package: dict, field: str) -> Any:
    if field not in package:
        raise ValueError(f"publish package is missing locked field: {field}")
    value = package[field]
    if field == "focus_keyword":
        if not isinstance(value, str):
            raise ValueError("locked field focus_keyword must be a string")
        return value
    if field == "hashtags":
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError("locked field hashtags must be a list of strings")
        return list(value)
    if not isinstance(value, str) or not value:
        raise ValueError(f"locked field {field} must be a non-empty string")
    return value


def _content_payload(package: dict) -> dict:
    package = _require_package_dict(package)
    if "content_contract" not in package:
        raise ValueError("publish package is missing locked content_contract")
    contract = ContentContract.model_validate(package["content_contract"])
    if "storyboards" not in package:
        raise ValueError("publish package is missing locked field: storyboards")
    storyboard = CarouselPayload.model_validate(
        {"storyboards": package["storyboards"]}
    )

    payload = {
        field: _require_locked_value(package, field)
        for field in LOCK_FIELDS
        if field not in {"first_screen_promise", "storyboards"}
    }
    payload["first_screen_promise"] = contract.first_screen_promise
    payload["storyboards"] = storyboard.model_dump(mode="json")["storyboards"]
    return {field: payload[field] for field in LOCK_FIELDS}


def build_content_lock(package: dict) -> ContentLock:
    payload = _content_payload(package)
    canonical_sha256 = hashlib.sha256(canonical_content_bytes(payload)).hexdigest()
    return ContentLock.model_validate(
        {**payload, "canonical_sha256": canonical_sha256}
    )


def build_publish_copy(package: dict) -> str:
    package = _require_package_dict(package)
    title = _require_locked_value(package, "title")
    content = _require_locked_value(package, "content")
    hashtags = _require_locked_value(package, "hashtags")
    return f"{title}\n\n{content}\n\n{' '.join(hashtags)}\n"


def _package_directory(package: dict) -> Path:
    raw_paths = package.get("rendered_image_paths")
    if isinstance(raw_paths, list) and raw_paths:
        try:
            return Path(raw_paths[0]).resolve().parent.parent
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(f"rendered image path cannot be resolved: {exc}") from exc
    raw_directory = package.get("package_directory")
    if raw_directory is not None:
        return Path(raw_directory).resolve()
    return Path.cwd().resolve()


def _lock_payload(lock: ContentLock) -> dict:
    serialized = lock.model_dump(mode="json")
    return {field: serialized[field] for field in LOCK_FIELDS}


def _frame_text_table(lock: ContentLock) -> str:
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
            f"{index}. frame_id={frame['frame_id']} role={frame['role']} "
            f"layout={frame['layout']} visible_text="
            + json.dumps(
                visible,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return "\n".join(rows)


def build_codex_rescue_prompt(
    package: dict,
    lock: ContentLock,
    reference_paths: Sequence[Path | str],
) -> str:
    package = _require_package_dict(package)
    if len(reference_paths) != 3:
        raise ValueError("rescue prompt requires exactly three reference-only anchors")
    expected_lock = build_content_lock(package)
    if lock != expected_lock:
        raise ValueError("ContentLock does not match the current publish package")

    package_directory = _package_directory(package)
    title = _require_locked_value(package, "title")
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        content_lock_json=canonical_content_bytes(_lock_payload(lock)).decode(
            "utf-8"
        ),
        content_lock_sha256=lock.canonical_sha256,
        frame_text_table=_frame_text_table(lock),
        package_directory=package_directory,
        audit_json_path=package_directory / f"{title}.json",
        current_images_directory=package_directory / "images",
        style_reference_paths="\n".join(
            f"- {Path(path)}" for path in reference_paths
        ),
    )


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


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


def _write_sibling_temp(destination: Path, payload: bytes) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_artifacts(payloads: Mapping[Path, bytes]) -> None:
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for destination, payload in payloads.items():
            staged[destination] = _write_sibling_temp(destination, payload)

        for destination, temp_path in staged.items():
            if destination.exists():
                descriptor, raw_backup = tempfile.mkstemp(
                    prefix=f".{destination.name}.",
                    suffix=".backup",
                    dir=destination.parent,
                )
                os.close(descriptor)
                backup = Path(raw_backup)
                backup.unlink()
                os.replace(destination, backup)
                backups[destination] = backup
            os.replace(temp_path, destination)
            committed.append(destination)
        _fsync_directory(next(iter(payloads)).parent)
    except BaseException:
        for temp_path in staged.values():
            temp_path.unlink(missing_ok=True)
        for destination in reversed(tuple(payloads)):
            if destination in committed:
                destination.unlink(missing_ok=True)
            backup = backups.get(destination)
            if backup is not None and backup.exists():
                try:
                    os.replace(backup, destination)
                except OSError:
                    pass
        for backup in backups.values():
            backup.unlink(missing_ok=True)
        raise
    else:
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def export_publish_package(package: dict) -> PublishArtifacts:
    package = _require_package_dict(package)
    lock = build_content_lock(package)
    visual_plan = VisualPlan.model_validate(package.get("visual_plan"))
    asset_manifest = AssetManifest.model_validate(package.get("asset_manifest"))
    render_manifest = RenderManifest.model_validate(package.get("render_manifest"))
    package_directory = _package_directory(package)
    if not package_directory.is_dir():
        raise ValueError("publish package directory does not exist")

    title = _require_locked_value(package, "title")
    audit_json_path = (package_directory / f"{title}.json").resolve()
    if not audit_json_path.is_relative_to(package_directory):
        raise ValueError("publish audit path must remain inside the package directory")
    rendered_image_paths = tuple(
        Path(path).resolve() for path in package.get("rendered_image_paths", [])
    )
    if not rendered_image_paths:
        raise ValueError("publish package requires rendered_image_paths")

    rescue_prompt = build_codex_rescue_prompt(
        package,
        lock,
        _approved_reference_paths(),
    )
    audit = _json_value(package)
    audit["content_lock"] = lock.model_dump(mode="json")
    audit["visual_plan"] = visual_plan.model_dump(mode="json")
    audit["asset_manifest"] = asset_manifest.model_dump(mode="json")
    audit["render_manifest"] = render_manifest.model_dump(mode="json")
    try:
        audit["rendered_image_paths"] = [
            path.relative_to(package_directory).as_posix()
            for path in rendered_image_paths
        ]
    except ValueError as exc:
        raise ValueError(
            "rendered image paths must remain inside the package directory"
        ) from exc

    publish_copy_path = package_directory / PUBLISH_COPY_FILENAME
    rescue_prompt_path = package_directory / RESCUE_PROMPT_FILENAME
    payloads = {
        publish_copy_path: build_publish_copy(package).encode("utf-8"),
        rescue_prompt_path: rescue_prompt.encode("utf-8"),
        audit_json_path: (
            json.dumps(
                audit,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8"),
    }
    _atomic_replace_artifacts(payloads)

    legacy_prompt_path = package_directory / LEGACY_IMAGE_PROMPT_FILENAME
    try:
        legacy_prompt_path.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError(
            "obsolete image prompt could not be removed from package"
        ) from exc

    return PublishArtifacts(
        package_directory=package_directory,
        publish_copy_path=publish_copy_path,
        rescue_prompt_path=rescue_prompt_path,
        audit_json_path=audit_json_path,
        rendered_image_paths=rendered_image_paths,
        content_lock=lock,
    )
