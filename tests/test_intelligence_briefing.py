from datetime import datetime, timezone
import json

from trendradar.intelligence.briefing import BriefingService, render_html
from trendradar.intelligence.store import IntelligenceStore, SourceDocument


def test_report_retry_and_coverage(tmp_path):
    store = IntelligenceStore(tmp_path / 'domain.db')
    stamp = '2026-11-09T00:00:00Z'
    source = store.ingest(SourceDocument('https://example.com', '<script>alert(1)</script>',
                                        'official', stamp, stamp))
    read = store.record_read(source, stamp, content='release')
    payload = dict(facts=[dict(text='发布', quote='release')], experience=[],
                   dimensions=['model'], reason='选型', analysis='测试', limited_information=False)
    with store._connect() as db:
        db.execute("INSERT INTO event_versions VALUES(1,'model/v1','release')")
        db.execute('INSERT INTO analyses(read_id,version_id,payload) VALUES(?,?,?)',
                   (read, 1, json.dumps(payload)))
    service = BriefingService(store)
    assert service.prepare(datetime(2026, 11, 9, 0, 59, tzinfo=timezone.utc)) is None
    now = datetime(2026, 11, 9, 1, tzinfo=timezone.utc)
    report = service.prepare(now)
    assert '<script>' not in report['html']
    assert '&lt;script&gt;' in report['html']
    assert service.prepare(now)['id'] == report['id']
    assert service.deliver(report['id'], lambda _: False) == 'uncertain'
    assert service.covered_versions() == []
    assert service.deliver(report['id'], lambda _: True) == 'uncertain'
    delivered = []
    def send(row):
        delivered.append(row['html'])
        return True
    assert service.deliver(report['id'], send, retry_uncertain=True) == 'sent'
    assert service.deliver(report['id'], send) == 'sent'
    assert delivered == [report['html']]
    assert service.covered_versions() == [1]
    following = service.prepare(datetime(2026, 11, 10, 1, tzinfo=timezone.utc))
    assert json.loads(following['payload']) == []


def test_crash_recovery_requires_explicit_retry(tmp_path):
    store = IntelligenceStore(tmp_path / 'domain.db')
    service = BriefingService(store)
    report = service.prepare(datetime(2026, 11, 9, 1, tzinfo=timezone.utc))
    with store._connect() as db:
        db.execute("UPDATE briefings SET delivery='sending'")
    assert service.deliver(report['id'], lambda _: True) == 'sending'
    service.recover_interrupted()
    assert service.deliver(report['id'], lambda _: True) == 'uncertain'


def test_empty_report():
    assert '暂无有充分证据' in render_html('2026-11-09', [])
    report = render_html('2026-11-09', [], ['正文失败 <script>'])
    assert '正文失败 &lt;script&gt;' in report
