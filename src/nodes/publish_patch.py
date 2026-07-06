from __future__ import annotations


STORYBOARD_VISIBLE_FIELDS = ("frame_title", "on_image_copy", "narration")
ASSEMBLER_AUTHORITATIVE_FIELDS = {
    "title",
    "content",
    "topic_id",
    "topic",
    "angle_id",
    "angle",
    "target_group",
    "core_pain",
    "cover_copy",
    "hashtags",
    "storyboards",
    "domain",
    "profile_version",
    "subdomain",
    "content_intent",
    "risk_level",
    "risk_flags",
}


def merge_publish_package(
    base: dict,
    patch: dict,
    *,
    replace_storyboards: bool = False,
) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if key == "storyboards" and replace_storyboards:
            merged[key] = value
        elif key == "storyboards" and isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = merge_storyboards(merged[key], value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_publish_package(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_storyboards(base: list, patch: list) -> list:
    merged = list(base)
    index_by_frame_id = {
        frame.get("frame_id"): index
        for index, frame in enumerate(merged)
        if isinstance(frame, dict) and frame.get("frame_id")
    }

    for patch_index, patch_frame in enumerate(patch):
        frame_id = patch_frame.get("frame_id") if isinstance(patch_frame, dict) else None
        if frame_id:
            target_index = index_by_frame_id.get(frame_id)
        else:
            target_index = patch_index if patch_index < len(merged) else None

        if target_index is None:
            if frame_id:
                index_by_frame_id[frame_id] = len(merged)
            merged.append(patch_frame)
        elif isinstance(merged[target_index], dict) and isinstance(patch_frame, dict):
            merged[target_index] = merge_publish_package(merged[target_index], patch_frame)
        else:
            merged[target_index] = patch_frame

    return merged


def extract_storyboard_visible_text(storyboards) -> list[dict]:
    visible_text = []
    for frame in list(storyboards or []):
        if not isinstance(frame, dict):
            continue
        visible_text.append(
            {
                "frame_id": frame.get("frame_id"),
                **{
                    field_name: str(frame.get(field_name) or "")
                    for field_name in STORYBOARD_VISIBLE_FIELDS
                },
            }
        )
    return visible_text


def storyboard_patch_without_visible_text(publish_patch: dict) -> dict:
    storyboards = publish_patch.get("storyboards")
    if not isinstance(storyboards, list):
        return {}

    stripped_storyboards = []
    for frame in storyboards:
        if not isinstance(frame, dict):
            stripped_storyboards.append(frame)
            continue
        stripped_storyboards.append(
            {
                key: value
                for key, value in frame.items()
                if key not in STORYBOARD_VISIBLE_FIELDS
            }
        )
    return {"storyboards": stripped_storyboards}


def publish_patch_for_assembler(publish_patch: dict) -> dict:
    return {
        key: value
        for key, value in publish_patch.items()
        if key not in ASSEMBLER_AUTHORITATIVE_FIELDS
    }
