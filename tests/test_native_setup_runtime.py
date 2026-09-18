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
