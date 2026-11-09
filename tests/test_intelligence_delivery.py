from unittest.mock import Mock, patch

import pytest

from trendradar.intelligence.budget import Budget
from trendradar.intelligence.locking import worker_lock
from trendradar.intelligence.runtime import feishu_sender


def test_sender_budget_checked_before_request():
    budget = Budget(requests=0)
    with patch('trendradar.notification.senders.requests.post') as post:
        assert not feishu_sender('https://example.com/webhook', budget)(dict(day='2026-11-09', payload='[]'))
        post.assert_not_called()


def test_sender_success_uses_remaining_timeout():
    response = Mock(status_code=200)
    response.json.return_value = {'code': 0}
    with patch('trendradar.notification.senders.requests.post', return_value=response) as post:
        assert feishu_sender('https://example.com/webhook', Budget(seconds=5))(
            dict(day='2026-11-09', payload='[]'))
        assert 0 < post.call_args.kwargs['timeout'] <= 5


def test_worker_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / 'db'
    with worker_lock(path):
        with pytest.raises(OSError):
            with worker_lock(path):
                pass
    with worker_lock(path):
        pass
