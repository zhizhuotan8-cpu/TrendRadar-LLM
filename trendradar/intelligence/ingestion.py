"""Adapters for existing collectors; summaries are never treated as read bodies."""

from datetime import datetime, timezone

from trendradar.storage.base import NewsItem, RSSItem
from .article_reader import ArticleReader
from .store import IntelligenceStore, SourceDocument, timestamp


def source_from_item(item: RSSItem | NewsItem, observed_at: datetime,
                     source_kind: str = "unknown") -> SourceDocument:
    published = None
    if isinstance(item, RSSItem) and item.published_at:
        try:
            published = timestamp(item.published_at)
        except ValueError:
            # A missing offset or malformed date cannot establish publication time.
            pass
    return SourceDocument(
        original_url=item.url or (item.mobile_url if isinstance(item, NewsItem) else ""),
        title=item.title, source_kind=source_kind,
        first_seen_at=observed_at, fetched_at=observed_at, published_at=published,
        summary=item.summary if isinstance(item, RSSItem) else "",
    )


class IngestionService:
    def __init__(self, store: IntelligenceStore, reader: ArticleReader | None = None):
        self.store = store
        self.reader = reader or ArticleReader()

    def ingest(self, item: RSSItem | NewsItem, observed_at: datetime,
               source_kind: str = "unknown") -> int:
        return self.store.ingest(source_from_item(item, observed_at, source_kind))

    def read(self, source_id: int, timeout: float = 30) -> int:
        source = self.store.get_source(source_id)
        if source is None:
            raise ValueError("Unknown source ID")
        result = self.reader.read_article(source["canonical_url"], timeout=timeout)
        content = result.get("data", {}).get("content") if result.get("success") else None
        error = None if content and content.strip() else result.get("error", {}).get("code", "EMPTY_CONTENT")
        return self.store.record_read(source_id, datetime.now(timezone.utc),
                                      content if error is None else None, error)
