from __future__ import annotations

from datetime import datetime

from memory.memory_manager import XHSMemoryManager
from metrics_collector.browser import BrowserSession
from metrics_collector.config import CollectorConfig
from trend_collector.config import TrendCollectorConfig
from trend_collector.extractor import extract_trend_titles_from_html, normalize_creator_trends
from trend_collector.models import TrendCollectionSummary


class TrendCollectionCoordinator:
    def __init__(self, config: TrendCollectorConfig | None = None):
        self.config = config or TrendCollectorConfig.default()

    def collect(self) -> TrendCollectionSummary:
        manager = XHSMemoryManager(self.config.db_path)
        manager.init_db(self.config.schema_path)
        browser_config = CollectorConfig.default()
        now = datetime.now(self.config.timezone)
        try:
            with BrowserSession(browser_config) as browser:
                browser.navigate(self.config.creator_center_url)
                html = browser.page.content()
            titles = extract_trend_titles_from_html(html)[: self.config.max_items_per_block]
            signals = normalize_creator_trends(
                titles,
                domain="healthy_lifestyle",
                subdomain="daily_habits",
                collected_at=now,
            )
            manager.upsert_trend_signals(signals)
            return TrendCollectionSummary(
                status="success",
                collected_signals=len(signals),
            )
        except Exception as error:
            return TrendCollectionSummary(
                status="failed",
                error_summary=f"{type(error).__name__}: operation failed",
            )
