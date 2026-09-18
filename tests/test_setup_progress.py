"""Run actual PowerShell 5.1 download functions against a local HTTP fixture."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import sys
import shutil

import pytest

from app.runtime import ROOT


@pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell 5.1')
@pytest.mark.parametrize('valid_hash', [True, False])
def test_powershell_download_reports_progress_and_verifies_hash(tmp_path, valid_hash):
    payload = b'local download fixture' * 150000
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            for start in range(0, len(payload), 262144):
                self.wfile.write(payload[start:start+262144])
                self.wfile.flush()
                time.sleep(.06)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    script = ROOT/'scripts/setup-private-runtime.ps1'
    target = tmp_path/'ffmpeg-test.zip'
    expected = hashlib.sha256(payload).hexdigest() if valid_hash else '0'*64
    env = dict(os.environ, SETUP_SOURCE=str(script), SETUP_TARGET=str(target),
               SETUP_URL=f'http://127.0.0.1:{server.server_port}/file', SETUP_HASH=expected)
    env['PATH'] = str(Path(os.environ['SystemRoot'])/'System32')
    # Import only the checked-in function definitions, never execute setup itself.
    command = '''$ErrorActionPreference='Stop'; $env:PSModulePath="$PSHOME\\Modules"; $tokens=$null; $errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile($env:SETUP_SOURCE,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Script parse failed'}
    $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]},$false) | ForEach-Object { Invoke-Expression $_.Extent.Text }
    Fetch-Verified $env:SETUP_URL $env:SETUP_TARGET $env:SETUP_HASH
    '''
    try:
        result = subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                                 '-NoProfile', '-Command', command], env=env, capture_output=True, text=True, timeout=30)
        events = [json.loads(line[6:]) for line in result.stdout.splitlines() if line.startswith('SETUP ')]
        assert any(event['stage'] == 'Downloading media tools' and 0 < event['progress'] <= 1 for event in events), result.stdout
        assert events[-1]['stage'] == 'Verifying download'
        if valid_hash:
            assert result.returncode == 0, result.stderr
            assert target.read_bytes() == payload
        else:
            assert result.returncode != 0
            assert not target.exists()
            assert 'checksum failed' in result.stderr
    finally:
        server.shutdown(); server.server_close(); thread.join()


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object')
def test_native_installer_job_kills_children(tmp_path):
    compiler = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.exists(): pytest.skip('Windows .NET Framework compiler unavailable')
    output = tmp_path/'job-smoke.exe'
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:'+str(output),
                    str(ROOT/'launcher/ProcessJob.cs'), str(ROOT/'tests/ProcessJobSmoke.cs')], check=True, capture_output=True)
    result = subprocess.run([str(output), sys.executable], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='WinForms setup dialog')
@pytest.mark.parametrize('fail', [False, True])
@pytest.mark.parametrize('profile', ['cu128', 'cpu', 'xpu', 'rocm'])
def test_native_setup_window_autocloses_only_on_success(tmp_path, fail, profile):
    compiler = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.exists(): pytest.skip('Windows .NET Framework compiler unavailable')
    script_dir = tmp_path/'scripts'; script_dir.mkdir()
    shutil.copyfile(ROOT/'tests/fixtures/setup-progress.ps1', script_dir/'setup-private-runtime.ps1')
    output = tmp_path/'setup-window-smoke.exe'
    subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:'+str(output),
        '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
        str(ROOT/'launcher/ProcessJob.cs'), str(ROOT/'launcher/SetupWindow.cs'),
        str(ROOT/'tests/SetupWindowSmoke.cs')], check=True, capture_output=True)
    result = subprocess.run([str(output), str(tmp_path), 'fail' if fail else 'success', profile],
        env=dict(os.environ, SETUP_TEST_FAIL='1' if fail else '0', SETUP_EXPECTED_PROFILE=profile),
        capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
