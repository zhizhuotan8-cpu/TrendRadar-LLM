from datetime import datetime, timezone
import sqlite3
from unittest.mock import Mock, patch

import requests
import pytest

from trendradar.intelligence.article_reader import ArticleReader
from trendradar.intelligence.ingestion import IngestionService, source_from_item
from trendradar.intelligence.store import IntelligenceStore
from trendradar.storage.base import RSSItem, NewsItem
from mcp_server.tools.article_reader import ArticleReaderTools


NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


def test_collectors_and_failed_read_retry(tmp_path):
    store = IntelligenceStore(tmp_path / 'domain.db')
    reader = Mock()
    reader.read_article.side_effect = [
        {'success': False, 'error': {'code': 'TIMEOUT'}},
        {'success': True, 'data': {'content': 'Actual original text'}},
    ]
    service = IngestionService(store, reader)
    item = RSSItem('Release', 'feed', url='https://example.com/a', summary='Summary only')
    key = service.ingest(item, NOW)
    assert service.ingest(item, NOW) == key
    assert store.get_reads(key) == []
    service.read(key, timeout=2)
    service.read(key, timeout=3)
    reads = store.get_reads(key)
    assert [r['status'] for r in reads] == ['failed', 'read']
    assert reads[0]['content'] is None
    assert reads[1]['content'] == 'Actual original text'
    assert store.get_source(key)['summary'] == 'Summary only'
    assert reader.read_article.call_args.kwargs['timeout'] == 3


def test_hotlist_has_no_invented_publication_time():
    source = source_from_item(NewsItem('Title', 'platform', mobile_url='https://example.com'), NOW)
    assert source.published_at is None
    assert source.first_seen_at == NOW


@pytest.mark.parametrize('published', ['', 'invalid', '2026-01-01T12:00:00'])
def test_unknown_or_ambiguous_rss_publication(published):
    assert source_from_item(RSSItem('Title', 'feed', published_at=published), NOW).published_at is None


def test_v1_migration_preserves_sources(tmp_path):
    path = tmp_path / 'domain.db'
    store = IntelligenceStore(path)
    key = IngestionService(store).ingest(NewsItem('Title', 'p', url='https://example.com'), NOW)
    before = store.get_source(key)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE article_reads')
        db.execute('PRAGMA user_version=1')
    migrated = IntelligenceStore(path)
    assert migrated.get_source(key) == before
    assert migrated.get_reads(key) == []
    with pytest.raises(sqlite3.IntegrityError):
        migrated.record_read(999, NOW, content='orphan')


@pytest.mark.parametrize('reader_type', [ArticleReader, ArticleReaderTools])
def test_shared_reader_timeout_empty_response_and_success(reader_type):
    reader = reader_type()
    with patch.object(reader, '_throttle'), patch(
        'trendradar.intelligence.article_reader.requests.get'
    ) as get:
        get.side_effect = requests.Timeout()
        assert reader.read_article('https://example.com', 1)['error']['code'] == 'TIMEOUT'
        get.side_effect = None
        get.return_value = Mock(status_code=200, text=' ', reason='OK')
        assert not reader.read_article('https://example.com')['success']
        get.return_value.text = 'Original text'
        assert reader.read_article('https://example.com')['data']['content'] == 'Original text'
