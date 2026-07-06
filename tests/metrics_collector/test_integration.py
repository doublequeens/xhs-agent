from __future__ import annotations

import os
import socket
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import Workbook
import pytest

from memory.memory_manager import XHSMemoryManager
from memory.models import ContentRecord
from metrics_collector.config import CollectorConfig
from metrics_collector.coordinator import CollectionCoordinator
from metrics_collector.models import NoteIdentity


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "memory" / "schema.sql"
TZ = ZoneInfo("Asia/Shanghai")
COLLECTED_AT = datetime(2026, 7, 6, 23, 0, tzinfo=TZ)
PUBLISHED_AT = datetime(2026, 7, 5, 12, 0, tzinfo=TZ)
POST_ID = "6a49ebd3000000001503fdd0"
DATA_ANALYSIS_URL = (
    "https://creator.xiaohongshu.com/statistics/data-analysis"
)
NOTE_MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager"
OFFICIAL_HEADERS = [
    "笔记标题",
    "首次发布时间",
    "体裁",
    "曝光",
    "观看量",
    "封面点击率",
    "点赞",
    "评论",
    "收藏",
    "涨粉",
    "分享",
    "人均观看时长",
    "弹幕",
]


class RecordingBrowser:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.navigations: list[str] = []
        self.note_detail_visits = 0
        self.export_clicks = 0
        self.closed = False
        self.page = self

    def __enter__(self) -> RecordingBrowser:
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.closed = True
        return False

    def navigate(self, url: str) -> None:
        self.events.append(f"navigate:{url}")
        self.navigations.append(url)

    def record_note_list_read(self) -> None:
        self.events.append("note_list_read")

    def record_note_detail_visit(self) -> None:
        self.events.append("note_detail_visit")
        self.note_detail_visits += 1

    def record_export_click(self) -> None:
        self.events.append("export_click")
        self.export_clicks += 1


class FakeIdentityCollector:
    def __init__(self, identities: list[NoteIdentity]) -> None:
        self.identities = identities
        self.calls = 0

    def __call__(self, page, max_pages, timezone) -> list[NoteIdentity]:
        del max_pages, timezone
        self.calls += 1
        page.record_note_list_read()
        return list(self.identities)


class FakeExporter:
    def __init__(self, workbook_path: Path) -> None:
        self.workbook_path = workbook_path
        self.calls = 0

    def export(self, page: RecordingBrowser) -> Path:
        self.calls += 1
        page.record_export_click()
        return self.workbook_path


def build_official_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["数据说明：以下指标每日更新"])
    sheet.append(OFFICIAL_HEADERS)
    sheet.append(
        [
            "abcdefghix",
            "2026年07月05日12时00分00秒",
            "图文",
            1000,
            200,
            0.2,
            20,
            4,
            8,
            3,
            2,
            "17秒",
            1,
        ]
    )
    sheet.append(
        [
            "abcdefghij",
            "2026年07月05日12时00分00秒",
            "图文",
            500,
            100,
            0.1,
            10,
            2,
            4,
            1,
            1,
            "12秒",
            0,
        ]
    )
    workbook.save(path)
    workbook.close()


def save_published_content(
    manager: XHSMemoryManager,
    content_id: str,
    title: str,
) -> None:
    manager.save_generated_content(
        ContentRecord(
            content_id=content_id,
            topic="integration verification",
            title=title,
            status="published",
            created_at=PUBLISHED_AT.isoformat(),
            published_at=PUBLISHED_AT.isoformat(),
        )
    )


@pytest.fixture
def deny_network(monkeypatch):
    def reject_network(*args, **kwargs):
        del args, kwargs
        raise AssertionError("network access is forbidden in integration test")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    return reject_network


@pytest.fixture
def manager(tmp_path):
    memory_manager = XHSMemoryManager(tmp_path / "memory.db")
    try:
        memory_manager.init_db(SCHEMA_PATH)
        yield memory_manager
    finally:
        memory_manager.close()


@pytest.mark.parametrize("method_name", ["connect", "connect_ex"])
def test_network_guard_blocks_low_level_socket_methods(
    deny_network,
    method_name,
):
    del deny_network
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        missing_socket = f"/tmp/xhs-agent-{os.getpid()}-{id(client)}.sock"
        with pytest.raises(
            AssertionError,
            match="network access is forbidden",
        ):
            getattr(client, method_name)(missing_socket)


def test_collects_metrics_end_to_end_without_network(
    tmp_path,
    deny_network,
    manager,
):
    del deny_network
    save_published_content(manager, "content-1", "abcdefghix")
    save_published_content(manager, "content-2", "abcdefghiy")

    workbook_path = tmp_path / "official-note-metrics.xlsx"
    build_official_workbook(workbook_path)
    fake_browser = RecordingBrowser()
    identity_collector = FakeIdentityCollector(
        [
            NoteIdentity(
                post_id=POST_ID,
                title="abcdefghix",
                published_at=PUBLISHED_AT,
            )
        ]
    )
    config = replace(
        CollectorConfig.default(home=tmp_path),
        db_path=manager.db_path,
        schema_path=SCHEMA_PATH,
        download_dir=tmp_path / "downloads",
        diagnostics_dir=tmp_path / "diagnostics",
    )
    exporter = FakeExporter(workbook_path)
    # Real DOM adapters are covered by test_identity.py and test_exporter.py.
    coordinator = CollectionCoordinator(
        config=config,
        manager=manager,
        browser_factory=lambda: fake_browser,
        identity_collector=identity_collector,
        exporter=exporter,
    )

    summary = coordinator.collect(now=COLLECTED_AT)

    assert summary.status == "partial_success"
    assert summary.updated_rows == 1
    assert summary.ambiguous_rows == 1
    assert summary.exported_rows == 2
    assert summary.skipped_rows == 1
    assert summary.matched_post_ids == 1
    assert fake_browser.navigations == [
        DATA_ANALYSIS_URL,
        NOTE_MANAGER_URL,
        DATA_ANALYSIS_URL,
    ]
    assert fake_browser.events == [
        f"navigate:{DATA_ANALYSIS_URL}",
        f"navigate:{NOTE_MANAGER_URL}",
        "note_list_read",
        f"navigate:{DATA_ANALYSIS_URL}",
        "export_click",
    ]
    assert fake_browser.note_detail_visits == 0
    assert fake_browser.export_clicks == 1
    assert fake_browser.closed
    assert identity_collector.calls == 1
    assert exporter.calls == 1

    content_1 = manager.get_content_by_id("content-1")
    assert content_1 is not None
    assert content_1["post_id"] == POST_ID
    assert content_1["url"] == (
        "https://www.xiaohongshu.com/explore/"
        "6a49ebd3000000001503fdd0"
    )
    metrics = manager.get_metrics("content-1")
    assert metrics is not None
    assert metrics["impressions"] == 1000
    assert metrics["views"] == 200
    assert metrics["avg_watch_time_seconds"] == 17
    history = manager.get_metrics_history("content-1")
    assert len(history) == 1
    assert history[0]["collected_date"] == "2026-07-06"
    assert history[0]["source"] == "creator_center_note_export_v1"

    content_2 = manager.get_content_by_id("content-2")
    assert content_2 is not None
    assert content_2["post_id"] is None
    assert content_2["url"] is None
    assert manager.get_metrics("content-2") is None
    assert manager.get_metrics_history("content-2") == []

    collection_run = manager.connect().execute(
        """
        SELECT *
        FROM metrics_collection_runs
        WHERE execution_date = ?
        """,
        (COLLECTED_AT.date().isoformat(),),
    ).fetchone()
    assert collection_run is not None
    assert collection_run["status"] == "partial_success"
    assert collection_run["completed_at"] is not None
    assert collection_run["exported_rows"] == 2
    assert collection_run["updated_rows"] == 1
    assert collection_run["ambiguous_rows"] == 1
    assert collection_run["matched_post_ids"] == 1
    assert not workbook_path.exists()
