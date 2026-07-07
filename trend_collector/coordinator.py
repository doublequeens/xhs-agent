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
        collection_date = now.date().isoformat()
        if manager.has_successful_trend_collection(collection_date):
            return TrendCollectionSummary(status="skipped", collected_signals=0)
        try:
            with BrowserSession(browser_config) as browser:
                browser.navigate(self.config.creator_center_url)
                html = browser.page.content()
            titles = extract_trend_titles_from_html(html)[: self.config.max_items_per_block]
            if not titles:
                error_summary = "creator center trend structure not found"
                manager.record_trend_collection_run(
                    {
                        "collection_date": collection_date,
                        "status": "failed",
                        "started_at": now.isoformat(),
                        "completed_at": datetime.now(self.config.timezone).isoformat(),
                        "collected_signals": 0,
                        "error_summary": error_summary,
                    }
                )
                return TrendCollectionSummary(
                    status="failed",
                    collected_signals=0,
                    error_summary=error_summary,
                )
            signals = normalize_creator_trends(
                titles,
                domain=self.config.target_domain,
                subdomain=self.config.target_subdomain,
                collected_at=now,
            )
            manager.upsert_trend_signals(signals)
            manager.record_trend_collection_run(
                {
                    "collection_date": collection_date,
                    "status": "success",
                    "started_at": now.isoformat(),
                    "completed_at": datetime.now(self.config.timezone).isoformat(),
                    "collected_signals": len(signals),
                    "error_summary": None,
                }
            )
            return TrendCollectionSummary(
                status="success",
                collected_signals=len(signals),
            )
        except Exception as error:
            error_summary = f"{type(error).__name__}: {error}"
            manager.record_trend_collection_run(
                {
                    "collection_date": collection_date,
                    "status": "failed",
                    "started_at": now.isoformat(),
                    "completed_at": datetime.now(self.config.timezone).isoformat(),
                    "collected_signals": 0,
                    "error_summary": error_summary,
                }
            )
            return TrendCollectionSummary(
                status="failed",
                error_summary=error_summary,
            )
