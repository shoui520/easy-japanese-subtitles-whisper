import json
import os
from pathlib import Path
import subprocess

import pytest

from app.runtime import ROOT


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell 5.1 runtime profiles')
def test_profiles_in_windows_powershell():
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    code = ". ./scripts/runtime-profiles.ps1; @('cpu','cu128','xpu','rocm') | ForEach-Object { Get-RuntimeProfile $_ } | ConvertTo-Json -Depth 5"
    result = subprocess.run([str(powershell), '-NoProfile', '-Command', code], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    profiles = {p['Compute']: p for p in json.loads(result.stdout)}
    assert profiles['xpu']['TorchRequirement'] == 'torch==2.11.0+xpu'
    assert profiles['xpu']['Index'] == 'https://download.pytorch.org/whl/xpu'
    assert profiles['rocm']['Python'] == '3.12.10'
    assert len(profiles['rocm']['Sdk']) == 4
    assert 'cp312-cp312-win_amd64.whl' in profiles['rocm']['TorchRequirement']
    assert profiles['rocm']['Constraints'] == 'constraints-windows-py312.txt'
    assert profiles['cpu']['Device'] == 'cpu'
    assert profiles['cu128']['Device'] == 'cuda'


@pytest.mark.parametrize('profile', ['cpu', 'cu128', 'xpu', 'rocm'])
def test_active_profile_selects_its_python(tmp_path, monkeypatch, profile):
    import app.runtime as runtime
    monkeypatch.setattr(runtime, 'PRIVATE', tmp_path)
    python = tmp_path / 'profiles' / profile / 'venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    (tmp_path / 'ready.json').write_text(json.dumps({'profile': profile}), encoding='utf-8-sig')
    assert runtime.default_python() == str(python)


def test_switching_profile_updates_saved_private_python_and_device(tmp_path, monkeypatch):
    import app.jobs as jobs
    old = tmp_path / 'old app'
    (tmp_path / 'queue.json').write_text(json.dumps({
        'app_root': str(old), 'settings': {'python': str(old / '.runtime/profiles/xpu/venv/Scripts/python.exe'), 'device': 'xpu'},
        'items': [],
    }), encoding='utf-8')
    monkeypatch.setattr(jobs, 'default_python', lambda: 'new-amd-python')
    queue = jobs.Queue(data_dir=tmp_path)
    assert queue.settings['python'] == 'new-amd-python'
    assert queue.settings['device'] == 'auto'


def test_same_profile_preserves_manual_cpu_selection(tmp_path, monkeypatch):
    import app.jobs as jobs
    python = str(ROOT / '.runtime/profiles/xpu/venv/Scripts/python.exe')
    (tmp_path / 'queue.json').write_text(json.dumps({
        'app_root': str(ROOT), 'settings': {'python': python, 'device': 'cpu'}, 'items': [],
    }), encoding='utf-8')
    monkeypatch.setattr(jobs, 'default_python', lambda: python)
    assert jobs.Queue(data_dir=tmp_path).settings['device'] == 'cpu'


def test_missing_gpu_returns_actionable_setup_error(monkeypatch, capsys):
    import sys
    import types
    from app import setup_check, devices
    monkeypatch.setitem(sys.modules, 'torch', types.SimpleNamespace())
    monkeypatch.setattr(sys, 'argv', ['setup_check', 'xpu'])
    monkeypatch.setattr(devices, 'discover', lambda torch: [dict(id='cpu', available=True)])
    assert setup_check.main() == 1
    event = json.loads(capsys.readouterr().out.split('SETUP ')[-1])
    assert 'choose CPU' in event['error']
    assert event['stage'] == 'Device check failed'
