import json
from unittest.mock import Mock

import pytest

from trendradar.intelligence.analysis import AnalysisService
from trendradar.intelligence.store import IntelligenceStore, SourceDocument


STAMP = '2026-11-09T00:00:00Z'


def decision(**changes):
    return dict(relevant=True, reason='与模型选型相关', event_key='model-a/v1',
                change_key='release', confidence=0.95,
                facts=[{'text': '发布模型', 'quote': 'Model A released'}],
                experience=[], analysis='可以评估选型', dimensions=['model'], **changes)


def setup(tmp_path):
    store = IntelligenceStore(tmp_path / 'domain.db')
    source = store.ingest(SourceDocument('https://example.com', 'Title', 'official', STAMP, STAMP))
    return store, source


def test_duplicate_reports_updates_and_distinct_releases(tmp_path):
    store, source = setup(tmp_path)
    client = Mock()
    service = AnalysisService(store, client)
    versions = []
    for event, change in [('model-a/v1', 'release'), ('model-a/v1', 'release'),
                          ('model-a/v1', 'cost-reduction'), ('model-a/v2', 'release')]:
        read = store.record_read(source, STAMP, content='Model A released')
        data = decision()
        data.update(event_key=event, change_key=change)
        client.chat.return_value = json.dumps(data)
        result = service.analyze(read)
        versions.append(result['version_id'])
        assert service.analyze(read) == result
    assert versions[0] == versions[1]
    assert len(set(versions)) == 3
    assert client.chat.call_count == 4
    assert client.chat.call_args.kwargs['num_retries'] == 0


@pytest.mark.parametrize('mutation', [
    {'facts': [{'text': 'Invented', 'quote': 'not in body'}]},
    {'confidence': 2}, {'dimensions': ['celebrity']}, {'relevant': 'true'},
])
def test_rejects_invalid_decisions_without_writes(tmp_path, mutation):
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, content='Model A released')
    data = decision()
    data.update(mutation)
    with pytest.raises(ValueError):
        AnalysisService(store, Mock(chat=Mock(return_value=json.dumps(data)))).analyze(read)
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM analyses').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM event_versions').fetchone()[0] == 0


def test_failed_read_never_calls_model(tmp_path):
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, error_code='TIMEOUT')
    client = Mock()
    with pytest.raises(ValueError):
        AnalysisService(store, client).analyze(read)
    client.chat.assert_not_called()


@pytest.mark.parametrize('relevant,confidence', [(False, 0.99), (True, 0.5)])
def test_irrelevant_and_uncertain_do_not_create_events(tmp_path, relevant, confidence):
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, content='Model A released')
    data = decision()
    data.update(relevant=relevant, confidence=confidence)
    result = AnalysisService(store, Mock(chat=Mock(return_value=json.dumps(data)))).analyze(read)
    assert result['version_id'] is None
    assert result['needs_review'] == relevant


def test_retries_truncated_response_with_same_evidence(tmp_path):
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, content='Model A released')
    client = Mock()
    client.chat.side_effect = ['{"relevant":true,"reason":"cut', json.dumps(decision())]
    result = AnalysisService(store, client).analyze(read)
    assert result['version_id'] is not None
    assert client.chat.call_count == 2
    assert client.chat.call_args_list[0].args[0][1] == client.chat.call_args_list[1].args[0][1]


def test_invalid_evidence_retry_still_cannot_write(tmp_path):
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, content='Model A released')
    data = decision()
    data['facts'][0]['quote'] = 'invented evidence'
    client = Mock(chat=Mock(return_value=json.dumps(data)))
    with pytest.raises(ValueError, match='evidence'):
        AnalysisService(store, client).analyze(read)
    assert client.chat.call_count == 2
    with store._connect() as db:
        assert db.execute('SELECT count(*) FROM analyses').fetchone()[0] == 0


def test_analysis_retry_obeys_shared_budget(tmp_path):
    from trendradar.intelligence.budget import Budget, BudgetedClient, BudgetExceeded
    store, source = setup(tmp_path)
    read = store.record_read(source, STAMP, content='Model A released')
    raw = Mock(chat=Mock(return_value='{"relevant":'))
    raw.fallback_models = []
    budget = Budget(model_calls=1)
    with pytest.raises(BudgetExceeded):
        AnalysisService(store, BudgetedClient(raw, budget)).analyze(read)
    assert raw.chat.call_count == 1
    assert budget.used['model_calls'] == 1
