import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime import ROOT

spec = importlib.util.spec_from_file_location('native_setup_runtime', ROOT / 'scripts/setup-runtime.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.mark.parametrize('kind', ['cpu', 'cu128', 'xpu', 'rocm'])
def test_python_installer_matches_profiles(kind):
    selected = setup.profile(kind)
    assert selected['device'] == ('cuda' if kind == 'cu128' else kind)
    assert selected['python'] == ('3.12.10' if kind == 'rocm' else '3.14.3')
    assert bool(selected['sdk']) == (kind == 'rocm')


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended-length paths')
def test_temp_paths_are_extended_and_accept_more_than_260_characters(tmp_path):
    path = tmp_path / ('a' * 100) / ('b' * 100) / 'wheel.whl'
    extended = setup.extended_path(path)
    assert extended.startswith('\\\\?\\')
    assert len(extended) > 260
    target = Path(extended)
    target.parent.mkdir(parents=True)
    target.write_bytes(b'fixture')
    assert target.read_bytes() == b'fixture'


def test_download_fraction_is_not_rounded_to_integer(tmp_path, monkeypatch, capsys):
    import hashlib
    import io
    class Response(io.BytesIO):
        headers = {'Content-Length': str(1024 * 1024)}
    monkeypatch.setattr(setup.urllib.request, 'urlopen', lambda *a, **k: Response(b'x' * (1024 * 1024)))
    ticks = iter(range(20))
    monkeypatch.setattr(setup.time, 'monotonic', lambda: next(ticks))
    setup.download('https://example.test/file', tmp_path / 'download', hashlib.sha256(b'x' * (1024 * 1024)).hexdigest(), 'test')
    events = [json.loads(line[6:]) for line in capsys.readouterr().out.splitlines() if line.startswith('SETUP ')]
    assert any(event['progress'] == .25 for event in events)
    assert any(event['progress'] == .5 for event in events)
    assert any(event['progress'] == .75 for event in events)


def test_launcher_has_no_powershell_or_execution_policy():
    source = (ROOT / 'launcher/SetupWindow.cs').read_text()
    assert 'powershell' not in source.lower()
    assert 'ExecutionPolicy' not in source
    assert 'liveLog.ReadOnly=true' in source


def test_short_build_workspace_is_owned_and_cleaned(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    with setup.setup_temporary(ROOT) as directory:
        assert directory.parent == tmp_path / 'Temp/ejs'
        assert (directory / '.easy-subs-job').is_file()
        (directory / 'build-file').write_text('test')
    assert not directory.exists()
    with pytest.raises(RuntimeError):
        with setup.setup_temporary(ROOT) as failed:
            raise RuntimeError('installation failed')
    assert not failed.exists()


@pytest.mark.parametrize('supports_range', [True, False])
def test_download_resumes_or_safely_replaces_partial(tmp_path, monkeypatch, supports_range):
    import hashlib
    import io
    payload = b'completed download'
    target = tmp_path / 'archive.zip'
    target.with_suffix('.zip.partial').write_bytes(payload[:5])
    class Response(io.BytesIO):
        status = 206 if supports_range else 200
        headers = {'Content-Length': str(len(payload) - 5 if supports_range else len(payload)),
                   'Content-Range': f'bytes 5-{len(payload)-1}/{len(payload)}'}
    def open_request(request, **kwargs):
        assert request.get_header('Range') == 'bytes=5-'
        return Response(payload[5:] if supports_range else payload)
    monkeypatch.setattr(setup.urllib.request, 'urlopen', open_request)
    setup.download('https://example.test/archive', target, hashlib.sha256(payload).hexdigest(), 'fixture')
    assert target.read_bytes() == payload
    assert not target.with_suffix('.zip.partial').exists()


def test_interrupted_http_download_continues_from_saved_bytes(tmp_path):
    import hashlib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    payload = b'file contents' * 100000
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested = self.headers.get('Range')
            requests.append(requested)
            offset = int(requested[6:-1]) if requested else 0
            self.send_response(206 if requested else 200)
            self.send_header('Content-Length', str(len(payload) - offset))
            if requested:
                self.send_header('Content-Range', f'bytes {offset}-{len(payload)-1}/{len(payload)}')
            self.end_headers()
            self.wfile.write(payload[offset:] if requested else payload[:300000])
            self.wfile.flush()
            self.close_connection = True
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = tmp_path / 'download.zip'
    args = (f'http://127.0.0.1:{server.server_port}/download', target,
            hashlib.sha256(payload).hexdigest(), 'fixture')
    try:
        with pytest.raises(RuntimeError, match='interrupted'):
            setup.download(*args)
        assert target.with_suffix('.zip.partial').stat().st_size == 300000
        setup.download(*args)
        assert requests == [None, 'bytes=300000-']
        assert target.read_bytes() == payload
        setup.download(*args)
        assert len(requests) == 2  # No network for a verified complete file.
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('failed_step', ['app.setup_check', 'application components'])
def test_retry_skips_completed_phases_but_rechecks_device(tmp_path, monkeypatch, failed_step):
    monkeypatch.setenv('SystemRoot', 'C:\\Windows')
    runtime = tmp_path / '.runtime/profiles/cpu'
    python = runtime / 'venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.write_bytes(b'fixture')
    (runtime / 'venv/pyvenv.cfg').write_text('fixture')
    tools = tmp_path / '.runtime/ffmpeg/ffmpeg-9.0.1-essentials_build/bin'
    tools.mkdir(parents=True)
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        (tools / name).touch()
    (tmp_path / 'requirements.txt').write_text('fixture')
    (tmp_path / 'constraints-windows-py314.txt').write_text('fixture')
    monkeypatch.setattr(setup, 'download', lambda *args: None)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if failed_step in args:
            raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(setup.subprocess, 'run', run)
    for _ in range(2):
        with pytest.raises(subprocess.CalledProcessError):
            setup.install(tmp_path, 'cpu', tmp_path / 'scratch')
    installs = [c for c in calls if any('install-progress.py' in a for a in c)]
    assert len(installs) == (2 if failed_step == 'app.setup_check' else 3)
    assert all('--cache-dir' in c and '--no-cache-dir' not in c for c in installs)
    assert sum('app.setup_check' in c for c in calls) == (2 if failed_step == 'app.setup_check' else 0)
    assert not any('venv' in c for c in calls)
    assert not (tmp_path / '.runtime/ready.json').exists()
    # Changed requirements invalidate checkpoints instead of silently skipping updates.
    (tmp_path / 'requirements.txt').write_text('updated')
    with pytest.raises(subprocess.CalledProcessError):
        setup.install(tmp_path, 'cpu', tmp_path / 'scratch')
    assert len([c for c in calls if any('install-progress.py' in a for a in c)]) == len(installs) + 2
