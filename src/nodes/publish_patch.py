from __future__ import annotations


STORYBOARD_VISIBLE_FIELDS = ("kicker", "headline", "footer")
STORYBOARD_VISIBLE_LIST_FIELDS = ("emphasis",)
CONTENT_BLOCK_VISIBLE_FIELDS = ("heading", "body")
TITLE_MAX_LENGTH = 20
ASSEMBLER_AUTHORITATIVE_FIELDS = {
    "focus_keyword",
    "focus_keyword_cli_present",
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


def enforce_title_length(title, max_length: int = TITLE_MAX_LENGTH) -> str:
    return str(title or "")[:max_length]


def enforce_publish_package_title_length(publish_package: dict) -> dict:
    if "title" not in publish_package:
        return publish_package
    normalized = dict(publish_package)
    normalized["title"] = enforce_title_length(normalized.get("title"))
    return normalized


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
        text_blocks = {
            field_name: str(frame.get(field_name) or "")
            for field_name in STORYBOARD_VISIBLE_FIELDS
            if field_name in frame
        }
        for field_name in STORYBOARD_VISIBLE_LIST_FIELDS:
            for index, value in enumerate(frame.get(field_name) or []):
                text_blocks[f"{field_name}[{index}]"] = str(value or "")
        for block_index, block in enumerate(frame.get("content_blocks") or []):
            if not isinstance(block, dict):
                continue
            for field_name in CONTENT_BLOCK_VISIBLE_FIELDS:
                if field_name in block:
                    text_blocks[f"content_blocks[{block_index}].{field_name}"] = str(
                        block.get(field_name) or ""
                    )
            for item_index, item in enumerate(block.get("items") or []):
                text_blocks[
                    f"content_blocks[{block_index}].items[{item_index}]"
                ] = str(item or "")
        visible_text.append({
            "frame_id": str(frame.get("frame_id") or ""),
            "role": str(frame.get("role") or ""),
            "layout": str(frame.get("layout") or ""),
            "text_blocks": text_blocks,
        })
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
        stripped_frame = {
            key: value
            for key, value in frame.items()
            if key not in (
                *STORYBOARD_VISIBLE_FIELDS,
                *STORYBOARD_VISIBLE_LIST_FIELDS,
                "content_blocks",
            )
        }
        if isinstance(frame.get("content_blocks"), list):
            stripped_frame["content_blocks"] = [
                {
                    key: value
                    for key, value in block.items()
                    if key not in (*CONTENT_BLOCK_VISIBLE_FIELDS, "items")
                }
                if isinstance(block, dict)
                else block
                for block in frame["content_blocks"]
            ]
        stripped_storyboards.append(stripped_frame)
    return {"storyboards": stripped_storyboards}


def merge_storyboard_visible_text(prior_visible_text, revised_visible_text) -> list[dict]:
    """Keep prior atoms while applying only known frame-ID-addressed revisions.

    Empty frame IDs are ignored because they cannot be safely bound to a card;
    non-empty IDs must exist in the prior snapshot and otherwise fail loudly.
    """
    prior = [
        frame.model_dump() if hasattr(frame, "model_dump") else dict(frame)
        for frame in list(prior_visible_text or [])
        if isinstance(frame, dict) or hasattr(frame, "model_dump")
    ]
    merged = [
        {
            **frame,
            "text_blocks": dict(frame.get("text_blocks") or {}),
        }
        for frame in prior
    ]
    index_by_frame_id = {
        frame.get("frame_id"): index
        for index, frame in enumerate(merged)
        if frame.get("frame_id")
    }
    for revised_frame in list(revised_visible_text or []):
        if hasattr(revised_frame, "model_dump"):
            revised_frame = revised_frame.model_dump()
        if not isinstance(revised_frame, dict):
            continue
        frame_id = revised_frame.get("frame_id")
        if not frame_id:
            continue
        target_index = index_by_frame_id.get(frame_id)
        if target_index is None:
            raise ValueError(
                f"unknown frame_id in storyboard visible-text merge: {frame_id}"
            )
        target = merged[target_index]
        target["text_blocks"].update(
            dict(revised_frame.get("text_blocks") or {})
        )
    return merged


def apply_storyboard_visible_text_patch(storyboards, visible_text) -> list:
    patched = [dict(frame) if isinstance(frame, dict) else frame for frame in list(storyboards or [])]
    index_by_frame_id = {
        frame.get("frame_id"): index
        for index, frame in enumerate(patched)
        if isinstance(frame, dict) and frame.get("frame_id")
    }
    for visible_frame in list(visible_text or []):
        if hasattr(visible_frame, "model_dump"):
            visible_frame = visible_frame.model_dump()
        if not isinstance(visible_frame, dict):
            continue
        frame_id = visible_frame.get("frame_id")
        if not frame_id:
            continue
        target_index = index_by_frame_id.get(frame_id)
        if target_index is None:
            raise ValueError(f"unknown frame_id in storyboard visible-text patch: {frame_id}")
        if not isinstance(patched[target_index], dict):
            continue
        frame = patched[target_index]
        for location, value in dict(visible_frame.get("text_blocks") or {}).items():
            if location in STORYBOARD_VISIBLE_FIELDS:
                frame[location] = value
                continue
            if "[" not in location:
                continue
            root, remainder = location.split("[", 1)
            index_text, _, child_field = remainder.partition("]")
            if not index_text.isdigit():
                continue
            item_index = int(index_text)
            if root == "content_blocks" and child_field.startswith("."):
                blocks = [
                    dict(item) if isinstance(item, dict) else item
                    for item in list(frame.get(root) or [])
                ]
                if item_index >= len(blocks) or not isinstance(blocks[item_index], dict):
                    continue
                block_location = child_field[1:]
                if block_location in CONTENT_BLOCK_VISIBLE_FIELDS:
                    blocks[item_index][block_location] = value
                    frame[root] = blocks
                    continue
                if block_location.startswith("items[") and block_location.endswith("]"):
                    nested_index_text = block_location[len("items["):-1]
                    if not nested_index_text.isdigit():
                        continue
                    nested_index = int(nested_index_text)
                    items = list(blocks[item_index].get("items") or [])
                    if nested_index < len(items):
                        items[nested_index] = value
                        blocks[item_index]["items"] = items
                        frame[root] = blocks
                continue
            if root in STORYBOARD_VISIBLE_LIST_FIELDS:
                items = list(frame.get(root) or [])
                if item_index < len(items):
                    items[item_index] = value
                    frame[root] = items
    return patched


def publish_patch_for_assembler(publish_patch: dict) -> dict:
    return {
        key: value
        for key, value in publish_patch.items()
        if key not in ASSEMBLER_AUTHORITATIVE_FIELDS
    }
