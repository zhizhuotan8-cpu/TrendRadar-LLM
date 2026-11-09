"""Daily orchestration. Credentials never enter the stored report payload."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path

import requests
import yaml

from trendradar.crawler.rss.parser import RSSParser
from trendradar.storage.base import RSSItem
from .analysis import AnalysisService
from .article_reader import ArticleReader
from .briefing import BriefingService
from .budget import Budget, BudgetExceeded, BudgetedClient, BudgetedReader
from .ingestion import IngestionService
from .store import IntelligenceStore


def load_settings(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Invalid intelligence configuration')
    return config


def model_client():
    from trendradar.ai.client import AIClient
    client = AIClient(dict(MODEL=os.environ.get('AI_MODEL', 'deepseek/deepseek-chat'),
                           API_KEY=os.environ.get('AI_API_KEY', ''),
                           API_BASE=os.environ.get('AI_API_BASE', ''), NUM_RETRIES=0,
                           MAX_TOKENS=2000, TIMEOUT=30))
    valid, reason = client.validate_config()
    if not valid:
        raise ValueError(reason)
    return client


def feishu_sender(webhook, budget=None):
    from trendradar.notification.senders import send_to_feishu
    def send(report):
        items = json.loads(report['payload'])
        # Plain text inside code blocks prevents source content creating mentions/links.
        batches = []
        for item in items:
            s, a = item['source'], item['analysis']
            text = '\n'.join([s['title'], '变化：' + '；'.join(c['text'] for c in a['facts']),
                              '作者经验：' + '；'.join(c['text'] for c in a['experience']),
                              '工程影响：' + a['analysis'], '关注理由：' + a['reason'],
                              '发布时间：' + (s['published_at'] or '未知'),
                              '出处：' + s['canonical_url']])
            text = text.replace('`', 'ˋ').replace('<', '＜').replace('>', '＞')
            # Leave space for the sender's batch headers.
            while text:
                chunk, text = text[:1800], text[1800:]
                batches.append('```\n' + chunk + '\n```')
        if not batches:
            batches = ['暂无有充分证据的新进展。']
        with redirect_stdout(io.StringIO()):
            return send_to_feishu(webhook, {}, report['day'] + ' 大模型每日简报',
                                  split_content_func=lambda *args, **kwargs: batches,
                                  timeout_provider=(lambda: budget.reserve(requests=1)) if budget else None)
    return send


class DailyRunner:
    def __init__(self, config, store=None, client=None, reader=None, get=requests.get):
        self.config = config
        self.store = store or IntelligenceStore(config['database'])
        self.client, self.reader, self.get = client, reader, get

    def run(self, now=None, *, send=False, retry_uncertain=False):
        now = now or datetime.now(timezone.utc)
        budget = Budget(**self.config.get('daily_budget', {}))
        issues = []
        client = self.client or model_client()
        analysis = AnalysisService(self.store, BudgetedClient(client, budget))
        ingest = IngestionService(self.store, BudgetedReader(
            self.reader or ArticleReader(jina_api_key=os.environ.get('JINA_API_KEY')), budget))
        parser = RSSParser()
        processed = set()
        for feed in self.config.get('feeds', []):
            try:
                response = self.get(feed['url'], timeout=budget.reserve(requests=1))
                response.raise_for_status()
                entries = parser.parse(response.text, feed['url'])
            except BudgetExceeded as error:
                issues.append(str(error))
                break
            except Exception:
                issues.append(f"来源 {feed['id']} 采集失败")
                continue
            for entry in entries[:self.config.get('max_feed_items', 8)]:
                try:
                    item = RSSItem(entry.title, feed['id'], url=entry.url,
                                   published_at=entry.published_at or '', summary=entry.summary or '')
                    key = ingest.ingest(item, now, feed.get('source_kind', 'unknown'))
                    if key in processed:
                        continue
                    processed.add(key)
                    read_id = ingest.read(key, timeout=budget.reserve())
                    reads = self.store.get_reads(key)
                    latest = next(r for r in reads if r['id'] == read_id)
                    if latest['status'] != 'read':
                        issues.append(f'出处 #{key} 正文读取失败，仅保留摘要')
                        continue
                    # Exact body reuse saves calls, without treating a hash as an event update.
                    with self.store._connect() as db:
                        previous = db.execute('''SELECT a.id FROM analyses a JOIN article_reads r
                            ON r.id=a.read_id WHERE r.source_id=? AND r.content=? LIMIT 1''',
                                              (key, latest['content'])).fetchone()
                    if previous is None:
                        analysis.analyze(read_id)
                except BudgetExceeded as error:
                    issues.append(str(error))
                    break
                except Exception:
                    issues.append('条目处理失败：来源或结构化证据无效')
            if budget.deadline <= budget.clock():
                break
        briefings = BriefingService(self.store)
        report = briefings.prepare(now, issues=issues)
        if report:
            directory = Path(self.config['reports'])
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (report['day'] + '.html')
            path.write_text(report['html'], encoding='utf-8')
        delivery = None
        if send:
            webhook = os.environ.get('FEISHU_WEBHOOK_URL', '')
            if not webhook:
                issues.append('未配置 FEISHU_WEBHOOK_URL；简报已保存')
            else:
                with self.store._connect() as db:
                    pending = db.execute("SELECT id FROM briefings WHERE delivery!='sent' ORDER BY id").fetchall()
                for row in pending:
                    delivery = briefings.deliver(row[0], feishu_sender(webhook, budget),
                                                 retry_uncertain=retry_uncertain)
        result = dict(briefing_id=report['id'] if report else None,
                      delivery=delivery, usage=budget.summary(), unresolved=issues)
        directory = Path(self.config['reports'])
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'last-run.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
