from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha1
from html.parser import HTMLParser

from src.schemas.topic_signal import TopicSignal


IGNORED_TITLES = {
    "创作服务平台",
    "发布笔记",
    "首页",
    "笔记管理",
    "数据看板",
    "活动中心",
    "笔记灵感",
    "创作学院",
    "创作百科",
}


class _TrendTitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.titles: list[str] = []
        self._capture = False
        self._capture_depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag, attrs):
        classes = set(dict(attrs).get("class", "").split())
        if "trend-title" in classes or "title" in classes:
            self._capture = True
            self._capture_depth = 1
            self._buffer = []
        elif self._capture:
            self._capture_depth += 1

    def handle_data(self, data):
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._capture:
            self._capture_depth -= 1
            if self._capture_depth > 0:
                return
            title = "".join(self._buffer).strip()
            if title:
                self.titles.append(title)
            self._capture = False
            self._capture_depth = 0
            self._buffer = []


def extract_trend_titles_from_html(html: str) -> list[str]:
    parser = _TrendTitleParser()
    parser.feed(html)
    unique: list[str] = []
    seen = set()
    for title in parser.titles:
        if title in IGNORED_TITLES:
            continue
        if title not in seen:
            seen.add(title)
            unique.append(title)
    return unique


def normalize_creator_trends(
    titles: list[str],
    *,
    domain: str,
    subdomain: str,
    collected_at: datetime,
    metadata: dict[str, object] | None = None,
) -> list[TopicSignal]:
    signals: list[TopicSignal] = []
    for title in titles:
        metadata_payload = dict(metadata or {})
        digest = sha1(
            f"{domain}:{subdomain}:{metadata_payload}:{title}".encode("utf-8")
        ).hexdigest()[:12]
        signals.append(
            TopicSignal(
                signal_id=f"creator_{digest}",
                source="creator_center",
                signal_type="creator_center",
                signal_name=title,
                normalized_signal=title,
                domain=domain,
                subdomain=subdomain,
                why_now="创作中心当前展示该灵感或活动方向。",
                domain_translation="将创作中心趋势转译为当前领域下的低风险生活场景。",
                risk_level="low",
                avoid_topics=["疾病诊断", "治疗建议", "药物建议", "事故灾害蹭热点"],
                confidence=0.78,
                active_from=collected_at.date(),
                expires_at=(collected_at + timedelta(days=7)).date(),
                collected_at=collected_at,
                raw_title=title,
                metadata=metadata_payload,
            )
        )
    return signals
