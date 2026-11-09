import json
import re
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import Mock

import pytest

from trendradar.intelligence.web import make_server


def test_loopback_ui_csrf_and_chat(tmp_path):
    chat = Mock()
    chat.ask.return_value = dict(session='test', claims=[], unresolved=['资料不足'])
    server = make_server(dict(database=str(tmp_path / 'db'), port=0), chat)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base, timeout=5) as response:
            page = response.read().decode()
        token = re.search("'X-CSRF-Token':'([^']+)'", page)[1]
        body = json.dumps(dict(question='model')).encode()
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + '/chat', data=body), timeout=5)
        assert error.value.code == 403
        request = Request(base + '/chat', data=body, headers={'X-CSRF-Token': token})
        with urlopen(request, timeout=5) as response:
            assert json.loads(response.read())['unresolved'] == ['资料不足']
        chat.ask.assert_called_once_with('model', None)
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base, headers={'Host': 'evil.example'}), timeout=5)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
