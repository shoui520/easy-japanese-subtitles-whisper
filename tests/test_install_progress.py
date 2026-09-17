import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.runtime import ROOT

spec = importlib.util.spec_from_file_location('install_progress', ROOT / 'scripts/install-progress.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def events(output):
    return [json.loads(line[6:]) for line in output.splitlines() if line.startswith('SETUP ')]


def test_download_percentage_speed_eta_and_install_stage(capsys):
    clock = iter([0, 2, 4])
    progress = module.PipProgress('transcription engine', clock=lambda: next(clock))
    progress.feed('Downloading torch.whl (4 MB)')
    progress.feed('Progress 0 of 4194304')
    progress.feed('Progress 2097152 of 4194304')
    progress.feed('Progress 4194304 of 4194304')
    progress.feed('Installing collected packages: torch')
    result = events(capsys.readouterr().out)
    halfway = result[2]
    assert halfway['progress'] == .5
    assert '2.0 MB / 4.0 MB (50%)' in halfway['detail']
    assert '1.0 MB/s' in halfway['detail']
    assert '0m 02s left' in halfway['detail']
    assert result[-2]['progress'] == 1
    assert result[-1]['stage'] == 'Installing transcription engine'
    assert result[-1]['progress'] is None


def test_unknown_total_and_resumed_download(capsys):
    progress = module.PipProgress('engine')
    progress.feed('Resuming download https://example.com/torch.whl (1/4 MB)')
    progress.feed('Progress 1048576 of 0')
    event = events(capsys.readouterr().out)[-1]
    assert event['progress'] is None
    assert 'total size unavailable' in event['detail']
    assert 'torch.whl' in event['detail']


def test_real_pip_download_emits_live_progress_and_preserves_failure(tmp_path):
    # Real pip against a slow local server, not fabricated pip stdout. Invalid
    # wheel deliberately checks that a failed pip invocation remains a failure.
    payload = b'x' * (2 * 1024 * 1024)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            for offset in range(0, len(payload), 65536):
                self.wfile.write(payload[offset:offset + 65536])
                self.wfile.flush()
                time.sleep(.025)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install-progress.py'),
            'test engine', 'download', '--no-cache-dir', '--no-deps', '--dest', str(tmp_path),
            f'http://127.0.0.1:{server.server_port}/example-1.0-py3-none-any.whl'],
            capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
        progress = events(result.stdout)
        assert any(event['progress'] is not None and 0 < event['progress'] < 1 for event in progress), result.stdout + result.stderr
        assert any('MB/s' in event['detail'] for event in progress)
        assert any(event['progress'] == 1 for event in progress)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
