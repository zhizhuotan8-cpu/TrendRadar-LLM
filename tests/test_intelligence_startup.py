import os
import subprocess
import sys


def test_help_does_not_import_model_client_or_connect():
    script = '''
import sys
def guard(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'):
        raise AssertionError('Startup must not use network')
sys.addaudithook(guard)
from trendradar.intelligence.__main__ import main
assert 'litellm' not in sys.modules
sys.argv = ['intelligence', '--help']
main()
'''
    env = dict(os.environ)
    env.pop('LITELLM_LOCAL_MODEL_COST_MAP', None)
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, timeout=20, env=env)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
