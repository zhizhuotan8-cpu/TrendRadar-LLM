"""Reuse RSS parsing and optional NewsNow adapters under a shared request budget."""

from contextlib import redirect_stdout
import io
import json

from trendradar.crawler.fetcher import DataFetcher
from trendradar.crawler.rss.parser import RSSParser
from trendradar.storage.base import NewsItem, RSSItem
from .budget import BudgetExceeded


def collect(config, budget, get, issues):
    parser = RSSParser()
    limit = config.get('max_feed_items', 8)
    for feed in config.get('feeds', []):
        try:
            response = get(feed['url'], timeout=budget.reserve(requests=1))
            response.raise_for_status()
            entries = parser.parse(response.text, feed['url'])
        except BudgetExceeded:
            raise
        except Exception:
            issues.append(f"来源 {feed['id']} 采集失败")
            continue
        for entry in entries[:limit]:
            yield RSSItem(entry.title, feed['id'], url=entry.url,
                          published_at=entry.published_at or '', summary=entry.summary or ''), feed.get('source_kind', 'unknown')
    fetcher = DataFetcher(api_url=config.get('newsnow_url'))
    for platform in config.get('hotlists', []):
        timeout = budget.reserve(requests=1)
        with redirect_stdout(io.StringIO()):
            raw, _, _ = fetcher.fetch_data(platform['id'], max_retries=0, timeout=timeout)
        if not raw:
            issues.append(f"热榜 {platform['id']} 采集失败")
            continue
        try:
            rows = json.loads(raw).get('items', [])
            for row in rows[:limit]:
                yield NewsItem(row['title'], platform['id'], url=row.get('url', ''),
                               mobile_url=row.get('mobileUrl', '')), platform.get('source_kind', 'unknown')
        except (ValueError, KeyError, TypeError):
            issues.append(f"热榜 {platform['id']} 数据格式无效")
