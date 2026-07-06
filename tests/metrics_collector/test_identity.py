import ast
import inspect
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import metrics_collector.identity as identity_module
from metrics_collector.identity import (
    IdentityCollectionError,
    collect_note_identities,
    extract_note_identities,
)
from metrics_collector.models import NoteIdentity


TZ = ZoneInfo("Asia/Shanghai")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "metrics_collector"


class _NoteManagerParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.controls = []
        self._card = None
        self._field = None
        self._control = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if "note-card" in classes:
            self._card = {
                "impression": attributes.get("data-impression"),
                "title": None,
                "time": None,
            }
            self.cards.append(self._card)
        elif self._card is not None and "note-card__title" in classes:
            self._field = "title"
            self._card[self._field] = ""
        elif self._card is not None and "note-card__time" in classes:
            self._field = "time"
            self._card[self._field] = ""

        if "d-pagination-page" in classes:
            self._control = {
                "className": attributes.get("class", ""),
                "dataPage": attributes.get("data-page"),
                "ariaCurrent": attributes.get("aria-current"),
                "ariaDisabled": attributes.get("aria-disabled"),
                "disabled": "disabled" in attributes,
                "text": "",
            }
            self.controls.append(self._control)

    def handle_data(self, data):
        if self._card is not None and self._field is not None:
            self._card[self._field] += data
        if self._control is not None:
            self._control["text"] += data

    def handle_endtag(self, tag):
        if self._field is not None and tag == "span":
            self._card[self._field] = self._card[self._field].strip()
            self._field = None
        if self._control is not None and tag == "button":
            self._control["text"] = self._control["text"].strip()
            self._control = None
        if self._card is not None and tag == "div" and self._field is None:
            self._card = None


def _parse_fixture(name):
    parser = _NoteManagerParser()
    parser.feed((FIXTURES / name).read_text(encoding="utf-8"))
    return {"cards": parser.cards, "controls": parser.controls}


class FakeLocator:
    def __init__(
        self,
        page,
        selector,
        *,
        container_index=None,
        control_index=None,
    ):
        self.page = page
        self.selector = selector
        self.container_index = container_index
        self.control_index = control_index

    def evaluate_all(self, expression):
        self.page.evaluate_all_calls.append((self.selector, expression))
        current = self.page.pages[self.page.page_index]
        if self.selector == ".note-card":
            return [dict(card) for card in current["cards"]]
        if self.selector == ".d-pagination":
            return [
                {
                    "containerIndex": 0,
                    "controls": [
                        {**control, "controlIndex": index}
                        for index, control in enumerate(current["controls"])
                    ],
                    "firstCardImpression": (
                        current["cards"][0]["impression"]
                        if current["cards"]
                        else None
                    ),
                }
            ]
        raise AssertionError(f"unexpected evaluate_all selector: {self.selector}")

    def nth(self, index):
        if self.selector == ".d-pagination":
            return FakeLocator(
                self.page,
                self.selector,
                container_index=index,
            )
        if self.selector == ".d-pagination-page":
            return FakeLocator(
                self.page,
                self.selector,
                container_index=self.container_index,
                control_index=index,
            )
        raise AssertionError(f"unexpected nth selector: {self.selector}")

    def locator(self, selector):
        assert self.selector == ".d-pagination"
        assert selector == ".d-pagination-page"
        return FakeLocator(
            self.page,
            selector,
            container_index=self.container_index,
        )

    def click(self):
        assert self.selector == ".d-pagination-page"
        self.page.click_calls.append(
            (self.container_index, self.control_index)
        )
        controls = self.page.pages[self.page.page_index]["controls"]
        control = controls[self.control_index]
        if control["disabled"] or control["ariaDisabled"] == "true":
            raise AssertionError("disabled pagination control was clicked")
        self.page.page_index = int(control["dataPage"]) - 1
        self.page.visited_pages.append(self.page.page_index + 1)


class FakePage:
    def __init__(self, pages):
        self.pages = pages
        self.page_index = 0
        self.visited_pages = [1]
        self.locator_calls = []
        self.evaluate_all_calls = []
        self.click_calls = []
        self.wait_calls = []

    def locator(self, selector):
        self.locator_calls.append(selector)
        return FakeLocator(self, selector)

    def wait_for_function(self, expression, arg=None, timeout=None):
        self.wait_calls.append((expression, arg, timeout))
        current = self.pages[self.page_index]
        active_page = next(
            (
                control["dataPage"]
                for control in current["controls"]
                if control["ariaCurrent"] == "page"
                or "active" in control["className"].split()
            ),
            None,
        )
        first_impression = (
            current["cards"][0]["impression"]
            if current["cards"]
            else None
        )
        assert (
            active_page != arg["activePage"]
            or first_impression != arg["firstCardImpression"]
        )
        return True


@pytest.fixture
def fixture_pages():
    return [
        _parse_fixture("note_manager_page_1.html"),
        _parse_fixture("note_manager_page_2.html"),
    ]


@pytest.fixture
def ready_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        identity_module,
        "assert_creator_center_ready",
        lambda page: calls.append(page.page_index + 1),
    )
    return calls


def test_extract_note_identities_uses_one_bulk_card_boundary(fixture_pages):
    page = FakePage(fixture_pages[:1])

    identities = extract_note_identities(page, TZ)

    assert identities == [
        NoteIdentity(
            post_id="6a49ebd3000000001503fdd0",
            title="工位摸鱼放松法：5个隐蔽动作缓解久坐僵硬",
            published_at=datetime(2026, 7, 5, 13, 29, tzinfo=TZ),
        ),
        NoteIdentity(
            post_id="6a49ebd3000000001503fdd1",
            title="下班后十分钟拉伸记录",
            published_at=datetime(2026, 7, 4, 18, 5, tzinfo=TZ),
        ),
    ]
    assert page.locator_calls == [".note-card"]
    assert len(page.evaluate_all_calls) == 1
    assert page.click_calls == []


@pytest.mark.parametrize(
    ("card", "context"),
    [
        (
            {"impression": "{bad", "title": "title", "time": "2026-07-05 13:29"},
            "data-impression",
        ),
        (
            {"impression": "{}", "title": "title", "time": "2026-07-05 13:29"},
            "noteId",
        ),
        (
            {
                "impression": (
                    '{"noteTarget":{"value":{"noteId":"ABCDEF0123456789ABCDEF01"}}}'
                ),
                "title": "title",
                "time": "2026-07-05 13:29",
            },
            "post_id",
        ),
        (
            {
                "impression": (
                    '{"noteTarget":{"value":{"noteId":'
                    '"6a49ebd3000000001503fdd0"}}}'
                ),
                "title": "   ",
                "time": "2026-07-05 13:29",
            },
            "title",
        ),
        (
            {
                "impression": (
                    '{"noteTarget":{"value":{"noteId":'
                    '"6a49ebd3000000001503fdd0"}}}'
                ),
                "title": "title",
                "time": "2026-7-5 13:29",
            },
            "time",
        ),
    ],
)
def test_extract_rejects_malformed_cards_with_index(card, context):
    page = FakePage([{"cards": [card], "controls": []}])

    with pytest.raises(
        IdentityCollectionError,
        match=rf"card 0.*{context}",
    ):
        extract_note_identities(page, TZ)


def test_extract_dedupes_identical_cards(fixture_pages):
    card = fixture_pages[0]["cards"][0]
    page = FakePage([{"cards": [card, card], "controls": []}])

    identities = extract_note_identities(page, TZ)

    assert identities == [
        NoteIdentity(
            post_id="6a49ebd3000000001503fdd0",
            title="工位摸鱼放松法：5个隐蔽动作缓解久坐僵硬",
            published_at=datetime(2026, 7, 5, 13, 29, tzinfo=TZ),
        )
    ]


def test_extract_rejects_conflicting_duplicate(fixture_pages):
    original = fixture_pages[0]["cards"][0]
    conflict = {**original, "title": "different title"}
    page = FakePage([{"cards": [original, conflict], "controls": []}])

    with pytest.raises(
        IdentityCollectionError,
        match="card 1.*conflicting duplicate",
    ):
        extract_note_identities(page, TZ)


@pytest.mark.parametrize("max_pages", [0, -1, 4, True, 1.5])
def test_collect_rejects_invalid_page_bounds(max_pages, fixture_pages):
    page = FakePage(fixture_pages)

    with pytest.raises(ValueError, match="max_pages must be an integer from 1 to 3"):
        collect_note_identities(page, max_pages, TZ)

    assert page.evaluate_all_calls == []
    assert page.click_calls == []


def test_collect_stops_at_page_limit(fixture_pages, ready_calls):
    page = FakePage(fixture_pages)

    identities = collect_note_identities(page, max_pages=1, timezone=TZ)

    assert [identity.post_id for identity in identities] == [
        "6a49ebd3000000001503fdd0",
        "6a49ebd3000000001503fdd1",
    ]
    assert page.visited_pages == [1]
    assert page.click_calls == []
    assert ready_calls == []


def test_collect_two_pages_dedupes_in_deterministic_order(
    fixture_pages,
    ready_calls,
):
    page = FakePage(fixture_pages)

    identities = collect_note_identities(page, max_pages=3, timezone=TZ)

    assert [identity.post_id for identity in identities] == [
        "6a49ebd3000000001503fdd0",
        "6a49ebd3000000001503fdd1",
        "6a49ebd3000000001503fdd2",
    ]
    assert page.visited_pages == [1, 2]
    assert page.click_calls == [(0, 1)]
    assert ready_calls == [2]
    assert page.locator_calls.count(".note-card") == 2


def test_collect_stops_for_disabled_next_control(fixture_pages, ready_calls):
    page = FakePage(fixture_pages)

    collect_note_identities(page, max_pages=3, timezone=TZ)

    assert page.visited_pages == [1, 2]
    assert page.click_calls == [(0, 1)]


def test_collect_stops_when_next_control_is_absent(fixture_pages, ready_calls):
    first_page = fixture_pages[0]
    first_page["controls"] = first_page["controls"][:1]
    page = FakePage([first_page])

    collect_note_identities(page, max_pages=3, timezone=TZ)

    assert page.visited_pages == [1]
    assert page.click_calls == []
    assert page.wait_calls == []


def test_collect_calls_early_stop_after_each_page(fixture_pages, ready_calls):
    page = FakePage(fixture_pages)
    observed = []

    identities = collect_note_identities(
        page,
        max_pages=3,
        timezone=TZ,
        stop_when=lambda current: observed.append(current) or True,
    )

    assert observed == [tuple(identities)]
    assert page.click_calls == []
    assert page.wait_calls == []


def test_collect_waits_for_concrete_transition_with_bounded_timeout(
    fixture_pages,
    ready_calls,
):
    page = FakePage(fixture_pages)

    collect_note_identities(page, max_pages=2, timezone=TZ)

    assert len(page.wait_calls) == 1
    _, previous_state, timeout = page.wait_calls[0]
    assert previous_state["activePage"] == "1"
    assert previous_state["firstCardImpression"].endswith(
        '"6a49ebd3000000001503fdd0"}}}'
    )
    assert timeout is not None
    assert 0 < timeout <= 10_000


def test_collect_rejects_conflicting_duplicate_across_pages(
    fixture_pages,
    ready_calls,
):
    fixture_pages[1]["cards"][0]["title"] = "conflicting title"
    page = FakePage(fixture_pages)

    with pytest.raises(
        IdentityCollectionError,
        match="page 2.*conflicting duplicate",
    ):
        collect_note_identities(page, max_pages=2, timezone=TZ)

    assert page.click_calls == [(0, 1)]


def test_identity_source_forbids_navigation_and_nonpagination_clicks():
    source = inspect.getsource(identity_module)

    assert "/explore/" not in source
    assert ".note-card__media" not in source
    assert ".note-detail" not in source
    assert ".goto(" not in source
    assert "control.textContent" not in source

    tree = ast.parse(source)
    click_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "click"
    ]
    assert len(click_calls) == 1
    assert isinstance(click_calls[0].func.value, ast.Name)
    assert click_calls[0].func.value.id == "next_control"
