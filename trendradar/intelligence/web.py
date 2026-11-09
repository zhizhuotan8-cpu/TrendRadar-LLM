"""Loopback-only report viewer and conversation UI; no credentials reach the browser."""

from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
from urllib.parse import urlsplit

from .chat import ChatService
from .store import IntelligenceStore


PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>大模型情报</title>
<style>body{max-width:900px;margin:40px auto;font:17px/1.7 sans-serif;padding:0 20px}
textarea{width:100%;height:90px}article{border-top:1px solid #ccc;padding:15px}blockquote{color:#555}</style>
<h1>大模型情报</h1><a href="/reports">每日简报</a><h2>追问</h2>
<p>回答区分事实、作者经验和分析；资料不足会明确说明。</p>
<textarea id="question" maxlength="2000" placeholder="例如：最近的模型发布对应用架构有什么影响？"></textarea>
<button id="ask">发送</button><button id="new">新对话</button><div id="answers"></div>
<script>
let session=localStorage.getItem('intelligence-session');
const output=document.getElementById('answers');
function show(question,data){const a=document.createElement('article');
const h=document.createElement('h3');h.textContent=question;a.append(h);
for(const c of data.claims||[]){const p=document.createElement('p');
p.textContent=({fact:'原始事实',experience:'作者经验',analysis:'情报分析'}[c.kind])+': '+c.text;
const q=document.createElement('blockquote');q.textContent=c.quote;
const link=document.createElement('a');link.textContent='出处 #'+c.source_id;link.href=c.url;
link.target='_blank';link.rel='noopener noreferrer';a.append(p,q,link);}
for(const s of data.unresolved||[]){const p=document.createElement('p');p.textContent=s;a.append(p);}
const details=document.createElement('details');const summary=document.createElement('summary');
summary.textContent='本次预算使用';const pre=document.createElement('pre');pre.textContent=JSON.stringify(data.usage,null,2);
details.append(summary,pre);a.append(details);output.append(a);}
document.getElementById('new').onclick=()=>{session=null;localStorage.removeItem('intelligence-session');output.replaceChildren();};
document.getElementById('ask').onclick=async()=>{const button=document.getElementById('ask');button.disabled=true;
const question=document.getElementById('question').value;
try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'TOKEN'},
body:JSON.stringify({question,session})});const d=await r.json();if(!r.ok)throw Error(d.error);
session=d.session;localStorage.setItem('intelligence-session',session);show(question,d);
}catch(e){show(question,{unresolved:[e.message]});}finally{button.disabled=false;}};
if(session)fetch('/history?session='+encodeURIComponent(session)).then(r=>r.json()).then(rows=>{
for(const row of rows)show(row.question,row.answer);}).catch(()=>{});
</script></html>'''


def make_server(config, chat=None):
    store = IntelligenceStore(config['database'])
    chat = chat or ChatService(store, config)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, data, content_type='application/json; charset=utf-8'):
            body = data.encode('utf-8') if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}',
                                                f'localhost:{self.server.server_port}'}

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {'error': 'Invalid host'})
            path = urlsplit(self.path).path
            if path == '/':
                return self.reply(200, PAGE.replace('TOKEN', token), 'text/html; charset=utf-8')
            if path == '/history':
                from urllib.parse import parse_qs
                session = parse_qs(urlsplit(self.path).query).get('session', [''])[0]
                return self.reply(200, chat.history(session))
            if path == '/reports':
                with store._connect() as db:
                    rows = db.execute('SELECT id,day,delivery FROM briefings ORDER BY day DESC').fetchall()
                html = '<meta charset="utf-8"><h1>每日简报</h1><a href="/">追问</a><ul>'
                for row in rows:
                    html += f'<li><a href="/reports/{row[0]}">{escape(row[1])}</a> {escape(row[2])}</li>'
                return self.reply(200, html + '</ul>', 'text/html; charset=utf-8')
            if path.startswith('/reports/'):
                try:
                    key = int(path.rsplit('/', 1)[-1])
                except ValueError:
                    return self.reply(404, {'error': 'Not found'})
                with store._connect() as db:
                    row = db.execute('SELECT html FROM briefings WHERE id=?', (key,)).fetchone()
                if row:
                    return self.reply(200, row[0], 'text/html; charset=utf-8')
            return self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if not self.valid_host() or self.headers.get('X-CSRF-Token') != token:
                return self.reply(403, {'error': 'Invalid request token'})
            if self.path != '/chat':
                return self.reply(404, {'error': 'Not found'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16000:
                    return self.reply(413, {'error': 'Request too large'})
                data = json.loads(self.rfile.read(length))
                result = chat.ask(data.get('question'), data.get('session'))
                return self.reply(200, result)
            except (ValueError, AttributeError):
                return self.reply(400, {'error': '问题或会话格式无效'})
            except Exception:
                return self.reply(503, {'error': '服务暂时不可用，已保存资料不受影响'})

    return HTTPServer(('127.0.0.1', config.get('port', 8765)), Handler)


def serve(config):
    server = make_server(config)
    print(f'本机网页：http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
