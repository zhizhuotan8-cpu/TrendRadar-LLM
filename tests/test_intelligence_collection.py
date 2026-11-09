from unittest.mock import Mock, patch

import pytest

from trendradar.intelligence.collection import collect
from trendradar.intelligence.budget import Budget, BudgetExceeded


def test_optional_hotlist_reuses_fetcher_without_hidden_retries():
    config = dict(hotlists=[dict(id='github', source_kind='community')])
    with patch('trendradar.intelligence.collection.DataFetcher') as factory:
        factory.return_value.fetch_data.return_value = ('{"items":[{"title":"Project","url":"https://github.com/a/b"}]}', 'github', 'github')
        rows = list(collect(config, Budget(seconds=3), Mock(), []))
        assert rows[0][0].url == 'https://github.com/a/b'
        assert rows[0][1] == 'community'
        assert factory.return_value.fetch_data.call_args.kwargs['max_retries'] == 0
        assert factory.return_value.fetch_data.call_args.kwargs['timeout'] <= 3


def test_hotlist_budget_prevents_call():
    with patch('trendradar.intelligence.collection.DataFetcher') as factory:
        with pytest.raises(BudgetExceeded):
            list(collect(dict(hotlists=[dict(id='github')]), Budget(requests=0), Mock(), []))
        factory.return_value.fetch_data.assert_not_called()
