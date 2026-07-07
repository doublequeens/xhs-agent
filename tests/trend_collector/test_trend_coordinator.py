from pathlib import Path
from zoneinfo import ZoneInfo

from trend_collector.config import TrendCollectorConfig
from trend_collector.coordinator import TrendCollectionCoordinator
from trend_collector.models import TrendCollectionSummary


class FakePage:
    def __init__(self, html):
        self._html = html

    def content(self):
        return self._html


class FakeBrowserSession:
    html = ""
    opened = False

    def __init__(self, config):
        self.page = FakePage(self.html)

    def __enter__(self):
        type(self).opened = True
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def navigate(self, url):
        self.url = url


class FakeManager:
    success_exists = False
    records = []
    signals = []

    def __init__(self, path):
        self.path = path

    def init_db(self, schema_path):
        pass

    def has_successful_trend_collection(self, collection_date):
        return self.success_exists

    def record_trend_collection_run(self, summary):
        self.records.append(summary)

    def upsert_trend_signals(self, signals):
        self.signals.extend(signals)


def _config(tmp_path, **overrides):
    values = {
        "db_path": tmp_path / "memory.db",
        "schema_path": Path("memory/schema.sql"),
        "profile_dir": tmp_path / "profile",
        "timezone": ZoneInfo("Asia/Shanghai"),
        "creator_center_url": "https://creator.xiaohongshu.com/",
        "max_items_per_block": 20,
        "target_domain": "healthy_lifestyle",
        "target_subdomain": "hydration",
    }
    values.update(overrides)
    return TrendCollectorConfig(**values)


def test_collect_fails_closed_when_creator_center_structure_unknown(
    monkeypatch,
    tmp_path,
):
    FakeBrowserSession.html = "<main><p>no trend cards</p></main>"
    FakeBrowserSession.opened = False
    FakeManager.success_exists = False
    FakeManager.records = []
    FakeManager.signals = []
    monkeypatch.setattr("trend_collector.coordinator.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("trend_collector.coordinator.XHSMemoryManager", FakeManager)

    summary = TrendCollectionCoordinator(_config(tmp_path)).collect()

    assert summary.status == "failed"
    assert summary.collected_signals == 0
    assert "creator center trend structure not found" in summary.error_summary
    assert FakeManager.signals == []
    assert FakeManager.records[0]["status"] == "failed"


def test_collect_skips_when_successful_run_already_exists(monkeypatch, tmp_path):
    FakeBrowserSession.opened = False
    FakeManager.success_exists = True
    FakeManager.records = []
    FakeManager.signals = []
    monkeypatch.setattr("trend_collector.coordinator.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("trend_collector.coordinator.XHSMemoryManager", FakeManager)

    summary = TrendCollectionCoordinator(_config(tmp_path)).collect()

    assert summary.status == "skipped"
    assert summary.collected_signals == 0
    assert FakeBrowserSession.opened is False
    assert FakeManager.signals == []


def test_collect_uses_configured_domain_scope(monkeypatch, tmp_path):
    FakeBrowserSession.html = """
    <main>
      <span class="trend-title">高温天通勤补水</span>
    </main>
    """
    FakeBrowserSession.opened = False
    FakeManager.success_exists = False
    FakeManager.records = []
    FakeManager.signals = []
    monkeypatch.setattr("trend_collector.coordinator.BrowserSession", FakeBrowserSession)
    monkeypatch.setattr("trend_collector.coordinator.XHSMemoryManager", FakeManager)

    summary = TrendCollectionCoordinator(
        _config(tmp_path, target_subdomain="hydration")
    ).collect()

    assert summary.status == "success"
    assert FakeManager.signals[0].domain == "healthy_lifestyle"
    assert FakeManager.signals[0].subdomain == "hydration"
    assert FakeManager.records[0]["status"] == "success"


def test_cli_treats_skipped_collection_as_success(monkeypatch):
    import trend_collector.__main__ as cli

    class SkippedCoordinator:
        def collect(self):
            return TrendCollectionSummary(status="skipped", collected_signals=0)

    monkeypatch.setattr(cli, "TrendCollectionCoordinator", SkippedCoordinator)

    assert cli.main(["collect"]) == 0
