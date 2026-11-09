from datetime import datetime, timezone
import json
from unittest.mock import Mock

from trendradar.intelligence.chat import ChatService
from trendradar.intelligence.search import BraveSearch
from trendradar.intelligence.budget import Budget
from trendradar.intelligence.store import IntelligenceStore, SourceDocument


def test_chat_citations_history_and_independent_budget(tmp_path):
    store = IntelligenceStore(tmp_path / 'db')
    now = datetime.now(timezone.utc)
    source = store.ingest(SourceDocument('https://example.com', 'model', 'official', now, now))
    read = store.record_read(source, now, content='model released')
    client = Mock(fallback_models=[])
    client.chat.return_value = json.dumps(dict(claims=[dict(text='模型已发布', kind='fact',
        source_id=source, read_id=read, quote='model released')], unresolved=[]))
    search = Mock()
    search.search.side_effect = ValueError('not configured')
    service = ChatService(store, {}, client=client, search=search)
    first = service.ask('model')
    second = service.ask('详细解释', first['session'])
    assert first['claims'][0]['url'] == 'https://example.com/'
    assert len(service.history(first['session'])) == 2
    assert first['usage']['reserved']['model_calls'] == second['usage']['reserved']['model_calls'] == 1
    client.chat.return_value = json.dumps(dict(claims=[dict(text='invented', kind='fact',
        source_id=999, read_id=read, quote='model released')], unresolved=[]))
    assert service.ask('model')['claims'] == []


def test_search_budget_and_normalization():
    response = Mock()
    response.json.return_value = {'web': {'results': [dict(url='https://EXAMPLE.com/a', title='A'),
                                                     dict(url='javascript:bad', title='Bad')]}}
    get = Mock(return_value=response)
    budget = Budget()
    results = BraveSearch('test-key', get).search('model', budget)
    assert results == [dict(url='https://example.com/a', title='A')]
    assert budget.used['searches'] == 1
    assert get.call_args.kwargs['headers']['X-Subscription-Token'] == 'test-key'


def test_no_evidence_returns_disclosure(tmp_path):
    store = IntelligenceStore(tmp_path / 'db')
    search = Mock()
    search.search.return_value = []
    client = Mock(fallback_models=[])
    result = ChatService(store, {}, client=client, search=search).ask('最新模型')
    assert result['claims'] == []
    assert result['unresolved']
    client.chat.assert_not_called()
