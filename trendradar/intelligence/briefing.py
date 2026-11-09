"""Persist immutable daily reports separately from uncertain external delivery."""

from datetime import datetime
from html import escape
import json
import pytz


DIMENSIONS = dict(model='模型选型', architecture='应用架构', productivity='开发效率',
                  cost='运行成本', reliability='可靠性')


def render_html(day, items, issues=()):
    sections = []
    for item in items:
        source, analysis = item['source'], item['analysis']
        lines = [f'<h2>{escape(source["title"])}</h2>']
        for field, label in [('facts', '原始事实'), ('experience', '作者经验')]:
            lines.append(f'<h3>{label}</h3><ul>')
            for claim in analysis[field]:
                lines.append(f'<li>{escape(claim["text"])}<blockquote>{escape(claim["quote"])}</blockquote></li>')
            lines.append('</ul>')
        lines.extend([
            f'<p>工程影响：{escape("、".join(DIMENSIONS[d] for d in analysis["dimensions"]))}</p>',
            f'<p>关注理由：{escape(analysis["reason"])}</p>',
            f'<p>情报分析：{escape(analysis["analysis"])}</p>',
            f'<p>发布时间：{escape(source["published_at"] or "未知")}；发现时间：{escape(source["first_seen_at"])}</p>',
            f'<p>来源性质：{escape(source["source_kind"])}</p>',
            f'<a href="{escape(source["canonical_url"], quote=True)}">出处 #{source["id"]}</a>',
        ])
        if analysis['limited_information']:
            lines.append('<p>信息有限：分析仅使用正文节选。</p>')
        sections.append('<article>' + ''.join(lines) + '</article>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            f'<title>大模型每日简报 {escape(day)}</title><h1>{escape(day)} 每日简报</h1>'
            + (''.join(sections) or '<p>暂无有充分证据的新进展。</p>')
            + '<h2>资料与运行限制</h2>' + ''.join(f'<p>{escape(s)}</p>' for s in issues) + '</html>')


class BriefingService:
    def __init__(self, store):
        self.store = store

    def prepare(self, now: datetime, limit: int = 10, issues=()):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Explicit timezone required')
        if not 1 <= limit <= 10:
            raise ValueError('Briefing limit must be between 1 and 10')
        local = now.astimezone(pytz.timezone('Asia/Shanghai'))
        if local.hour < 9:
            return None
        day = local.date().isoformat()
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM briefings WHERE day=?', (day,)).fetchone()
            if existing:
                return dict(existing)
            # Per-version coverage avoids dropping unselected or late-arriving analyses.
            rows = db.execute('''SELECT a.* FROM analyses a WHERE a.version_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM briefing_items i JOIN briefings b ON b.id=i.briefing_id
                    WHERE i.version_id=a.version_id)
                ORDER BY a.id''').fetchall()
            # Rank validated engineering value first; keep deterministic ordering on ties.
            rows = sorted(rows, key=lambda row: (
                -json.loads(row['payload']).get('importance', 3), -row['id']))
            items, seen = [], set()
            for row in rows:
                if row['version_id'] in seen:
                    continue
                analysis = json.loads(row['payload'])
                source = db.execute('''SELECT s.* FROM source_documents s JOIN article_reads r
                    ON r.source_id=s.id WHERE r.id=?''', (row['read_id'],)).fetchone()
                items.append(dict(source=dict(source), analysis=analysis))
                seen.add(row['version_id'])
                if len(items) == limit:
                    break
            html = render_html(day, items, issues)
            key = db.execute('INSERT INTO briefings(day,payload,html) VALUES(?,?,?) RETURNING id',
                             (day, json.dumps(items, ensure_ascii=False), html)).fetchone()[0]
            for version in seen:
                db.execute('INSERT INTO briefing_items VALUES(?,?)', (key, version))
            return dict(db.execute('SELECT * FROM briefings WHERE id=?', (key,)).fetchone())

    def deliver(self, briefing_id, sender, *, retry_uncertain=False):
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM briefings WHERE id=?', (briefing_id,)).fetchone()
            if row is None:
                raise ValueError('Unknown briefing')
            if row['delivery'] == 'sent':
                return 'sent'
            if row['delivery'] == 'sending':
                return 'sending'
            if row['delivery'] == 'uncertain' and not retry_uncertain:
                return 'uncertain'
            db.execute("UPDATE briefings SET delivery='sending' WHERE id=?", (briefing_id,))
        try:
            result = sender(dict(row))
            status = 'sent' if result is True else 'uncertain'
        except Exception:
            status = 'uncertain'
        with self.store._connect() as db:
            db.execute('UPDATE briefings SET delivery=? WHERE id=?', (status, briefing_id))
        return status

    def recover_interrupted(self):
        """Call only on startup when no delivery worker is running."""
        with self.store._connect() as db:
            db.execute("UPDATE briefings SET delivery='uncertain' WHERE delivery='sending'")

    def covered_versions(self):
        with self.store._connect() as db:
            return [row[0] for row in db.execute('''SELECT i.version_id FROM briefing_items i
                JOIN briefings b ON b.id=i.briefing_id WHERE b.delivery='sent' ORDER BY i.version_id''')]
