import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import zipfile
from types import SimpleNamespace

import pytest
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
    assert result[-1]['progress'] == 0


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


def test_install_progress_counts_only_successes_and_reports_elapsed(capsys, monkeypatch):
    heartbeat_seen = threading.Event()
    original_report = module.report
    def observe(stage, detail, progress=None):
        original_report(stage, detail, progress)
        if 'elapsed' in detail and '0m 00s elapsed' not in detail:
            heartbeat_seen.set()
    monkeypatch.setattr(module, 'report', observe)
    def slow_install():
        assert heartbeat_seen.wait(5)
    def failed_install():
        raise RuntimeError('disk full')
    requirements = [SimpleNamespace(name='first', install=slow_install),
                    SimpleNamespace(name='second', install=failed_install)]
    def install_all(requirements):
        for requirement in requirements:
            requirement.install()
    with pytest.raises(RuntimeError, match='disk full'):
        module.install_with_progress(install_all, requirements, 'components')
    result = events(capsys.readouterr().out)
    assert heartbeat_seen.is_set()
    assert any('1 of 2 packages installed' in event['detail'] for event in result)
    assert result[-1]['progress'] == .5
    assert not any(event['progress'] == 1 for event in result)
    assert requirements[0].install is slow_install
    assert requirements[1].install is failed_install


@pytest.mark.parametrize('count', [1, 3])
def test_real_pip_install_reports_each_completed_package(tmp_path, count):
    wheels = []
    for i in range(count):
        name = f'progress_fixture_{i}'
        wheel = tmp_path / f'{name}-1.0-py3-none-any.whl'
        info = f'{name}-1.0.dist-info'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr(f'{name}/__init__.py', 'VALUE = 1\n')
            archive.writestr(f'{info}/METADATA', f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n')
            archive.writestr(f'{info}/WHEEL', 'Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
            archive.writestr(f'{info}/RECORD', '')
        wheels.append(str(wheel))
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/install-progress.py'),
        'test components', 'install', '--no-index', '--no-deps', '--target', str(tmp_path / 'installed'),
        *wheels], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    progress = events(result.stdout)
    for completed in range(count + 1):
        assert any(f'{completed} of {count} packages installed' in event['detail'] and
                   event['progress'] == completed / count for event in progress), result.stdout
    assert any('Installing progress' in event['detail'] for event in progress)
    assert progress[-1]['stage'] == 'Installed test components'
