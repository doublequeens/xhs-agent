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
                titles_by_scope = self._collect_titles(browser)
            if not titles_by_scope:
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
            signals = []
            for titles, metadata in titles_by_scope:
                signals.extend(
                    normalize_creator_trends(
                        titles,
                        domain=self.config.target_domain,
                        subdomain=self.config.target_subdomain,
                        collected_at=now,
                        metadata=metadata,
                    )
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

    def _collect_titles(self, browser) -> list[tuple[list[str], dict[str, object]]]:
        titles_by_scope: list[tuple[list[str], dict[str, object]]] = []
        browser.navigate(self.config.creator_center_url)
        browser.page.wait_for_timeout(5_000)
        for category in self.config.inspiration_categories:
            browser.page.get_by_text(category, exact=True).click(timeout=10_000)
            browser.page.wait_for_timeout(1_500)
            titles = extract_trend_titles_from_html(browser.page.content())[
                : self.config.max_items_per_block
            ]
            if titles:
                titles_by_scope.append(
                    (
                        titles,
                        {
                            "surface": "inspiration",
                            "category": category,
                        },
                    )
                )

        browser.navigate(self.config.events_center_url)
        browser.page.wait_for_timeout(5_000)
        event_titles = extract_trend_titles_from_html(browser.page.content())[
            : self.config.max_items_per_block
        ]
        if event_titles:
            titles_by_scope.append((event_titles, {"surface": "events"}))
        return titles_by_scope
