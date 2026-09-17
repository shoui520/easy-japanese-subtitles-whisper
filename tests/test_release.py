import os
from pathlib import Path
import subprocess
import sys
import time
import re
import urllib.request
import zipfile

import pytest

from app.runtime import ROOT


@pytest.mark.skipif(os.name != 'nt', reason='Windows launcher')
def test_portable_launcher_resolves_root_and_detects_moved_runtime(tmp_path):
    compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    output = tmp_path / 'layout.exe'
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/define:PORTABLE_RELEASE',
                    '/main:ReleaseLayoutSmoke', '/out:' + str(output),
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    '/reference:System.Web.Extensions.dll',
                    *[str(ROOT / 'launcher' / name) for name in ('Program.cs', 'SetupWindow.cs', 'ProcessJob.cs')],
                    str(ROOT / 'tests/ReleaseLayoutSmoke.cs')], check=True, capture_output=True)
    subprocess.run([str(output), str(tmp_path / "日本語 [portable] Queen's app")], check=True, timeout=20)


def test_moved_queue_uses_current_private_python(tmp_path, monkeypatch):
    import json
    import app.jobs as jobs
    old = tmp_path / 'old app' / '_internal'
    (tmp_path / 'queue.json').write_text(json.dumps({
        'app_root': str(old), 'settings': {'python': str(old / '.runtime/venv/Scripts/python.exe')},
        'items': [],
    }), encoding='utf-8')
    monkeypatch.setattr(jobs, 'default_python', lambda: 'current-private-python')
    queue = jobs.Queue(data_dir=tmp_path)
    assert queue.settings['python'] == 'current-private-python'


def test_built_zip_extracted_backend_with_clean_path(tmp_path):
    archives = list((ROOT / 'dist').glob('*-windows-x64.zip'))
    if not archives:
        pytest.skip('Build a release ZIP first')
    archive = max(archives, key=lambda path: path.stat().st_mtime)
    extraction = tmp_path / "日本語 [release] Queen's app"
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        assert 'Easy Japanese Subtitles.exe' in names
        assert 'Read me.txt' in names
        assert '_internal/app/ui/index.html' in names
        assert all(name.startswith('_internal/') or name in {'Easy Japanese Subtitles.exe', 'Read me.txt'} for name in names)
        assert not any(part in {'.runtime', '.app-data', '.git', 'tests', '__pycache__', '.venv'}
                       for name in names for part in Path(name).parts)
        assert not any(name.endswith('requirements-dev.txt') for name in names)
        package.extractall(extraction)
    internal = extraction / '_internal'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('PYTHON', 'EASY_SUBS'))}
    env.update(PATH=os.pathsep.join([str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot']]),
               PYTHONNOUSERSITE='1', PYTHONUTF8='1')
    # This checks packaged application files, not a fresh dependency installation.
    # Interpreter/packages are the existing private test runtime, explicitly named.
    with (extraction / 'smoke.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-s', '-m', 'app.main', '--headless'],
                                   cwd=internal, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            match = None
            while time.monotonic() < deadline:
                output = (extraction / 'smoke.log').read_text(encoding='utf-8')
                match = re.search(r'http://127\.0\.0\.1:\d+/#\S+', output)
                if match:
                    break
                assert process.poll() is None, output
                time.sleep(.1)
            assert match, output
            url, token = match.group().split('#')
            with urllib.request.urlopen(url, timeout=10) as response:
                assert 'CUDA · NVIDIA' in response.read().decode('utf-8')
            request = urllib.request.Request(url + 'api/state', headers={'X-App-Token': token})
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 200
            assert (internal / '.app-data').is_dir()
        finally:
            process.terminate()
            process.wait(timeout=15)
