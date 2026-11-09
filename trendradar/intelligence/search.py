"""Brave web search adapter; snippets are discovery metadata, not read evidence."""

import requests

from .store import normalize_url


class BraveSearch:
    def __init__(self, api_key, get=requests.get):
        self.api_key, self.get = api_key, get

    def search(self, query, budget, limit=4):
        if not self.api_key:
            raise ValueError('未配置 BRAVE_SEARCH_API_KEY，联网搜索不可用')
        response = self.get('https://api.search.brave.com/res/v1/web/search',
                            params={'q': query[:600], 'count': min(limit, 20)},
                            headers={'X-Subscription-Token': self.api_key},
                            timeout=budget.reserve(searches=1, requests=1))
        response.raise_for_status()
        results = []
        for row in response.json().get('web', {}).get('results', [])[:limit]:
            try:
                url = normalize_url(row['url'])
            except (ValueError, KeyError):
                continue
            results.append(dict(url=url, title=row.get('title', url)))
        return results
