import json
import re
from datetime import datetime, tzinfo
from typing import Any, Callable

from metrics_collector.browser import assert_creator_center_ready
from metrics_collector.models import NoteIdentity


_POST_ID_PATTERN = re.compile(r"[0-9a-f]{24}")
_PUBLISHED_AT_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
_TRANSITION_TIMEOUT_MS = 5_000

_CARD_DATA_SCRIPT = """
(cards) => cards.map((card) => ({
    impression: card.getAttribute('data-impression'),
    title: card.querySelector('.note-card__title')?.textContent?.trim() ?? null,
    time: card.querySelector('.note-card__time')?.textContent?.trim() ?? null
}))
"""

_PAGINATION_STATE_SCRIPT = """
(containers) => containers.flatMap((container, containerIndex) => {
    const style = window.getComputedStyle(container);
    const visible = container.getClientRects().length > 0
        && style.display !== 'none'
        && style.visibility !== 'hidden';
    if (!visible) {
        return [];
    }
    const controls = Array.from(
        container.querySelectorAll('.d-pagination-page')
    ).map((control, controlIndex) => {
        const controlStyle = window.getComputedStyle(control);
        return {
            controlIndex,
            className: control.className || '',
            dataPage: control.getAttribute('data-page'),
            ariaCurrent: control.getAttribute('aria-current'),
            ariaDisabled: control.getAttribute('aria-disabled'),
            disabled: Boolean(control.disabled),
            visible: control.getClientRects().length > 0
                && controlStyle.display !== 'none'
                && controlStyle.visibility !== 'hidden'
        };
    });
    return [{
        containerIndex,
        controls,
        firstCardImpression: document.querySelector('.note-card')
            ?.getAttribute('data-impression') ?? null
    }];
})
"""

_LIST_TRANSITION_SCRIPT = """
(previous) => {
    const firstCardImpression = document.querySelector('.note-card')
        ?.getAttribute('data-impression') ?? null;
    const container = document.querySelectorAll('.d-pagination')[
        previous.containerIndex
    ];
    if (!container) {
        return false;
    }
    const style = window.getComputedStyle(container);
    if (
        container.getClientRects().length === 0
        || style.display === 'none'
        || style.visibility === 'hidden'
    ) {
        return false;
    }
    return firstCardImpression !== null
        && firstCardImpression !== previous.firstCardImpression;
}
"""


class IdentityCollectionError(RuntimeError):
    pass


def extract_note_identities(page: Any, timezone: tzinfo) -> list[NoteIdentity]:
    timezone = _validate_timezone(timezone)
    try:
        raw_cards = page.locator(".note-card").evaluate_all(_CARD_DATA_SCRIPT)
    except Exception as error:
        raise IdentityCollectionError("note-card extraction failed") from error

    if not isinstance(raw_cards, list):
        raise IdentityCollectionError("note-card extraction returned invalid data")

    identities: list[NoteIdentity] = []
    identities_by_id: dict[str, NoteIdentity] = {}
    for card_index, raw_card in enumerate(raw_cards):
        identity = _parse_card(raw_card, card_index, timezone)
        existing = identities_by_id.get(identity.post_id)
        if existing is None:
            identities_by_id[identity.post_id] = identity
            identities.append(identity)
        elif existing != identity:
            raise IdentityCollectionError(
                f"card {card_index} has conflicting duplicate post_id "
                f"{identity.post_id}"
            )
    return identities


def collect_note_identities(
    page: Any,
    max_pages: int,
    timezone: tzinfo,
    stop_when: Callable[[tuple[NoteIdentity, ...]], bool] | None = None,
) -> list[NoteIdentity]:
    timezone = _validate_timezone(timezone)
    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or not 1 <= max_pages <= 3
    ):
        raise ValueError("max_pages must be an integer from 1 to 3")

    identities: list[NoteIdentity] = []
    identities_by_id: dict[str, NoteIdentity] = {}
    for page_number in range(1, max_pages + 1):
        try:
            page_identities = extract_note_identities(page, timezone)
        except IdentityCollectionError as error:
            raise IdentityCollectionError(f"page {page_number}: {error}") from error

        for identity in page_identities:
            existing = identities_by_id.get(identity.post_id)
            if existing is None:
                identities_by_id[identity.post_id] = identity
                identities.append(identity)
            elif existing != identity:
                raise IdentityCollectionError(
                    f"page {page_number} has conflicting duplicate post_id "
                    f"{identity.post_id}"
                )

        if stop_when is not None and stop_when(tuple(identities)):
            break
        if page_number == max_pages:
            break

        next_page = _find_next_page_control(page)
        if next_page is None:
            break
        next_control, previous_state = next_page
        try:
            next_control.click()
        except Exception as error:
            raise IdentityCollectionError(
                f"page {page_number} pagination click failed"
            ) from error
        try:
            page.wait_for_function(
                _LIST_TRANSITION_SCRIPT,
                previous_state,
                timeout=_TRANSITION_TIMEOUT_MS,
            )
        except Exception as error:
            raise IdentityCollectionError(
                f"page {page_number} pagination transition timed out"
            ) from error
        assert_creator_center_ready(page)

    return identities


def _parse_card(
    raw_card: Any,
    card_index: int,
    timezone: tzinfo,
) -> NoteIdentity:
    if not isinstance(raw_card, dict):
        raise IdentityCollectionError(f"card {card_index} has invalid card data")

    impression = raw_card.get("impression")
    if not isinstance(impression, str) or not impression.strip():
        raise IdentityCollectionError(
            f"card {card_index} is missing data-impression"
        )
    try:
        payload = json.loads(impression)
    except (json.JSONDecodeError, TypeError) as error:
        raise IdentityCollectionError(
            f"card {card_index} has invalid data-impression JSON"
        ) from error
    try:
        post_id = payload["noteTarget"]["value"]["noteId"]
    except (KeyError, TypeError) as error:
        raise IdentityCollectionError(
            f"card {card_index} is missing noteId"
        ) from error
    if (
        not isinstance(post_id, str)
        or _POST_ID_PATTERN.fullmatch(post_id) is None
    ):
        raise IdentityCollectionError(f"card {card_index} has invalid post_id")

    title = raw_card.get("title")
    if not isinstance(title, str) or not title.strip():
        raise IdentityCollectionError(f"card {card_index} has invalid title")
    title = title.strip()

    published_at_text = raw_card.get("time")
    if (
        not isinstance(published_at_text, str)
        or _PUBLISHED_AT_PATTERN.fullmatch(published_at_text) is None
    ):
        raise IdentityCollectionError(f"card {card_index} has invalid time")
    try:
        published_at = datetime.strptime(
            published_at_text,
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=timezone)
    except ValueError as error:
        raise IdentityCollectionError(
            f"card {card_index} has invalid time"
        ) from error

    return NoteIdentity(
        post_id=post_id,
        title=title,
        published_at=published_at,
    )


def _validate_timezone(value: Any) -> tzinfo:
    if not isinstance(value, tzinfo):
        raise ValueError("timezone must produce aware datetimes")
    try:
        offset = datetime(2000, 1, 1, tzinfo=value).utcoffset()
    except Exception as error:
        raise ValueError("timezone must produce aware datetimes") from error
    if offset is None:
        raise ValueError("timezone must produce aware datetimes")
    return value


def _find_next_page_control(
    page: Any,
) -> tuple[Any, dict[str, str | int | None]] | None:
    try:
        containers = page.locator(".d-pagination").evaluate_all(
            _PAGINATION_STATE_SCRIPT
        )
    except Exception as error:
        raise IdentityCollectionError("pagination inspection failed") from error
    if not isinstance(containers, list):
        raise IdentityCollectionError("pagination inspection returned invalid data")

    if len(containers) > 1:
        raise IdentityCollectionError(
            "multiple visible note pagination containers"
        )
    if not containers:
        return None

    candidate = _pagination_candidate(containers[0])
    if candidate is None:
        return None

    container_index, controls, active_page, first_impression = candidate
    selection = _select_next_control(controls, active_page)
    if selection is None:
        return None
    control_index = selection
    next_control = (
        page.locator(".d-pagination")
        .nth(container_index)
        .locator(".d-pagination-page")
        .nth(control_index)
    )
    return (
        next_control,
        {
            "containerIndex": container_index,
            "activePage": str(active_page),
            "firstCardImpression": first_impression,
        },
    )


def _pagination_candidate(
    container: Any,
) -> tuple[int, list[Any], int, str | None] | None:
    if not isinstance(container, dict):
        raise IdentityCollectionError("pagination container data is invalid")
    controls = container.get("controls")
    container_index = container.get("containerIndex")
    if not isinstance(controls, list) or not isinstance(container_index, int):
        raise IdentityCollectionError("pagination container data is invalid")

    active_page: int | None = None
    for control in controls:
        if not isinstance(control, dict):
            raise IdentityCollectionError("pagination control data is invalid")
        classes = str(control.get("className", "")).split()
        is_active = (
            control.get("ariaCurrent") in {"page", "true"}
            or control.get("dataActive") == "true"
            or "active" in classes
        )
        if is_active:
            active_page = _control_page_number(control)
            break
    if active_page is None:
        return None
    first_impression = container.get("firstCardImpression")
    if first_impression is not None and not isinstance(first_impression, str):
        raise IdentityCollectionError("pagination container data is invalid")
    return container_index, controls, active_page, first_impression


def _select_next_control(
    controls: list[Any],
    active_page: int,
) -> int | None:
    for control in controls:
        if not isinstance(control, dict):
            raise IdentityCollectionError("pagination control data is invalid")
        if not control.get("visible", True):
            continue
        if _control_page_number(control) != active_page + 1:
            continue
        if (
            control.get("disabled") is True
            or control.get("ariaDisabled") == "true"
            or "disabled" in str(control.get("className", "")).split()
        ):
            return None
        control_index = control.get("controlIndex")
        if not isinstance(control_index, int):
            raise IdentityCollectionError("pagination control data is invalid")
        return control_index
    return None


def _control_page_number(control: dict[str, Any]) -> int | None:
    value = control.get("dataPage")
    if not isinstance(value, str) or not value.isdigit():
        return None
    page_number = int(value)
    return page_number if page_number > 0 else None
