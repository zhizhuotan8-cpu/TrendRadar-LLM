from datetime import datetime, timezone
import json
from unittest.mock import Mock, patch

from trendradar.intelligence.runtime import DailyRunner, feishu_sender


def test_daily_pipeline_offline_and_idempotent(tmp_path):
    config = dict(database=str(tmp_path / 'db'), reports=str(tmp_path / 'reports'),
                  feeds=[dict(id='test', url='https://example.com/feed')])
    response = Mock(text='<rss version="2.0"><channel><title>Feed</title><item>'
                         '<title>Release</title><link>https://example.com/a</link>'
                         '</item></channel></rss>')
    client = Mock(fallback_models=[])
    client.chat.return_value = json.dumps(dict(relevant=True, reason='选型', event_key='a/v1',
        change_key='release', confidence=0.95, facts=[dict(text='发布', quote='released')],
        experience=[], analysis='评估', dimensions=['model']))
    reader = Mock()
    reader.read_article.return_value = dict(success=True, data=dict(content='released'))
    runner = DailyRunner(config, client=client, reader=reader, get=Mock(return_value=response))
    now = datetime(2026, 11, 9, 1, tzinfo=timezone.utc)
    first, second = runner.run(now), runner.run(now)
    assert first['briefing_id'] == second['briefing_id']
    assert client.chat.call_count == 1
    assert (tmp_path / 'reports' / '2026-11-09.html').exists()
    assert first['unresolved'] == []


def test_feishu_adapter_uses_existing_sender():
    report = dict(day='2026-11-09', payload='[]')
    with patch('trendradar.notification.senders.send_to_feishu', return_value=True) as send:
        assert feishu_sender('https://example.com/webhook')(report)
        assert send.call_args.kwargs['split_content_func']() == ['暂无有充分证据的新进展。']


def test_collection_budget_stops_external_requests(tmp_path):
    config = dict(database=str(tmp_path / 'db'), reports=str(tmp_path / 'reports'),
                  feeds=[dict(id='test', url='https://example.com/feed')], daily_budget=dict(requests=0))
    get = Mock()
    result = DailyRunner(config, client=Mock(fallback_models=[]), get=get).run(
        datetime(2026, 11, 9, 1, tzinfo=timezone.utc))
    get.assert_not_called()
    assert result['unresolved'] == ['requests 预算已耗尽']
